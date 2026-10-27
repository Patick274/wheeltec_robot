"""FD1X5 expedited SDO and node guarding, manual 2025-11 sections 9.3/9.4.

Classical 11-bit CAN only. A timeout invalidates the session; never retry
a motion transaction with ambiguous outcome. KS3 must not control this axis
concurrently.
"""
import socket
import struct
import threading
import time

EFF, RTR, ERR = 0x80000000, 0x40000000, 0x20000000
FRAME = struct.Struct('=IB3x8s')


class CanError(RuntimeError):
    pass


class SdoAbort(CanError):
    def __init__(self, index, sub, code):
        self.code = code
        super().__init__('SDO abort {:04X}:{:02X}: 0x{:08X}'.format(index, sub, code))


class SocketCan:
    """通用SocketCAN接口,不绑定Kvaser,candleLight等品牌/固件.

    先在Linux生成并配置can0等接口;Windows或厂商CANlib API不能替代此接口.
    驱动问题先运行scripts/diagnose_can.py,不由运动程序自动加载驱动或改网卡.
    """
    def __init__(self, interface):
        if not hasattr(socket, 'AF_CAN'):
            raise CanError('SocketCAN requires Linux, not Windows.')
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.send_lock = threading.Lock()
        try:
            self.sock.setsockopt(socket.SOL_CAN_RAW, 2, struct.pack('=I', 0x1FFFFFFF))
            self.sock.bind((interface,))
            self.sock.settimeout(0.15)
        except OSError as exc:
            self.sock.close()
            raise CanError('Cannot open SocketCAN interface {}: {}. '
                           'Run diagnose_can.py --interface {} on Jetson first.'.format(
                               interface, exc, interface)) from exc

    def send(self, can_id, data=b'', remote=False):
        if not 0 <= can_id <= 0x7FF or len(data) > 8:
            raise ValueError('Only classical 11-bit CAN, up to 8 bytes.')
        packet = FRAME.pack(can_id | (RTR if remote else 0), len(data), data.ljust(8, b'\0'))
        with self.send_lock:
            if self.sock.send(packet) != FRAME.size:
                raise CanError('Incomplete CAN write.')

    def recv(self, timeout):
        self.sock.settimeout(max(0.001, timeout))
        try:
            raw = self.sock.recv(FRAME.size)
        except socket.timeout:
            return None
        if len(raw) != FRAME.size:
            raise CanError('Unexpected CAN frame length.')
        can_id, dlc, data = FRAME.unpack(raw)
        if can_id & ERR:
            raise CanError('SocketCAN error frame: 0x{:08X}'.format(can_id))
        if dlc > 8:
            raise CanError('CAN FD is not supported by this implementation.')
        return can_id, data[:dlc]

    def close(self):
        self.sock.close()


class SdoClient:
    def __init__(self, transport, node_id=1, timeout=0.15):
        if not 1 <= node_id <= 127 or not 0.02 <= timeout <= 0.3:
            raise ValueError('Invalid node ID or SDO timeout.')
        self.transport, self.node_id, self.timeout = transport, node_id, timeout
        self.lock = threading.RLock()
        self.poisoned = False
        self.last_io = time.monotonic()
        self.guard_time = None
        self.guard_toggle = None
        self.boot_count = 0
        self.emcy = 0

    def _event(self, can_id, data):
        if can_id & (EFF | RTR):
            return
        if can_id == 0x700 + self.node_id and len(data) == 1:
            if data[0] == 0:
                self.boot_count += 1
                self.guard_time = None
            else:
                toggle = data[0] >> 7
                if toggle != self.guard_toggle:
                    self.guard_time = time.monotonic()
                    self.guard_toggle = toggle
        elif can_id == 0x80 + self.node_id and len(data) >= 2:
            self.emcy = int.from_bytes(data[:2], 'little')

    def _exchange(self, request, index, sub):
        with self.lock:
            if self.poisoned:
                raise CanError('CAN session invalid; inspect hardware and restart node.')
            try:
                # Consume old traffic before a request; no blind retry after timeout.
                for unused in range(128):
                    event = self.transport.recv(0.001)
                    if event is None:
                        break
                    self._event(*event)
                self.transport.send(0x600 + self.node_id, request)
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    reply = self.transport.recv(deadline - time.monotonic())
                    if reply is None:
                        continue
                    can_id, data = reply
                    self._event(can_id, data)
                    if can_id != 0x580 + self.node_id:
                        continue
                    if len(data) != 8:
                        raise CanError('SDO response must contain 8 bytes.')
                    if int.from_bytes(data[1:3], 'little') != index or data[3] != sub:
                        raise CanError('Mismatched SDO response: another master may be active.')
                    if data[0] == 0x80:
                        raise SdoAbort(index, sub, int.from_bytes(data[4:8], 'little'))
                    self.last_io = time.monotonic()
                    return data
                raise CanError('SDO timeout {:04X}:{:02X}; command outcome unknown.'.format(index, sub))
            except (OSError, CanError):
                self.poisoned = True
                raise

    def read(self, index, sub=0, size=4, signed=False):
        data = self._exchange(struct.pack('<BHB4x', 0x40, index, sub), index, sub)
        if data[0] != {1: 0x4F, 2: 0x4B, 4: 0x43}[size]:
            self.poisoned = True
            raise CanError('Unexpected SDO data type/size at {:04X}:{:02X}.'.format(index, sub))
        return int.from_bytes(data[4:4 + size], 'little', signed=signed)

    def write(self, index, value, sub=0, size=4, signed=False):
        payload = int(value).to_bytes(size, 'little', signed=signed)
        request = struct.pack('<BHB', {1: 0x2F, 2: 0x2B, 4: 0x23}[size], index, sub)
        data = self._exchange(request + payload.ljust(4, b'\0'), index, sub)
        if data[0] != 0x60:
            self.poisoned = True
            raise CanError('Invalid write acknowledgement.')

    def nmt(self, command):
        self.transport.send(0, bytes([command, self.node_id]))

    def guard(self):
        self.transport.send(0x700 + self.node_id, remote=True)

    def emergency_stop_unconfirmed(self):
        try:
            self.transport.send(0x600 + self.node_id,
                                struct.pack('<BHBH2x', 0x2B, 0x6040, 0, 0x000B))
        except (OSError, CanError):
            pass
