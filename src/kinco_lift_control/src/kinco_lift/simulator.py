"""内存驱动器模拟:让真实SDO客户端在无ROS,无电机条件下做协议测试.

此类不会打开can0,也不模拟惯量,负载,真实加减速,电源或电磁干扰.
它仅实现本包用到的对象,使能/目标握手及简化位置变化.
"""
import collections
import struct
import threading
import time

from .canopen import CanError


class SimulatedCan:
    """与SocketCan具有相同send/recv/close接口,可替换传输层进行测试."""
    def __init__(self, node_id=1, counts=65536, mm_rev=2.25, travel_mm=200, direction=1,
                 lower_counts=0):
        self.node_id = node_id
        self.counts = counts
        self.mm_rev = mm_rev
        self.direction = direction
        self.maximum = travel_mm * counts / mm_rev
        self.lower_counts = lower_counts
        self.position = float(lower_counts)
        self.target = 0
        self.moving = False
        self.enabled = False
        self.last_time = time.monotonic()
        self.last_guard = None
        self.toggle = 0
        self.queue = collections.deque()
        self.lock = threading.RLock()
        self.closed = False
        self.sent = []
        self.drop_replies = False
        # 简化对象字典:(索引, 子索引) -> [字节数, 是否有符号, 当前值].
        self.od = {
            (0x6040, 0): [2, False, 6], (0x6041, 0): [2, False, 0x31],
            (0x6060, 0): [1, True, 1], (0x6063, 0): [4, True, 0],
            (0x6061, 0): [1, True, 0], (0x60FF, 0): [4, True, 0],
            (0x606C, 0): [4, True, 0], (0x60FD, 0): [4, False, 1],
            (0x2601, 0): [2, False, 0], (0x607A, 0): [4, True, 0],
            (0x2602, 0): [2, False, 0],
            (0x6081, 0): [4, False, 1],
            (0x6083, 0): [4, False, 1], (0x6084, 0): [4, False, 1],
            (0x6085, 0): [4, False, 1], (0x605A, 0): [2, True, 0],
            (0x605B, 0): [2, True, 0], (0x605C, 0): [2, True, 0],
            (0x605E, 0): [2, True, 0], (0x1017, 0): [2, False, 0],
            (0x605D, 0): [2, True, 0],
            (0x100C, 0): [2, False, 1000], (0x100D, 0): [1, False, 3],
            (0x100E, 0): [4, False, 0x700 + node_id],
            (0x6007, 0): [2, True, 0],
            (0x6410, 3): [4, False, counts],
        }

    def _step(self):
        """按墙钟推进位置,并模拟节点保护超时;没有真实机械动力学."""
        now = time.monotonic()
        dt, self.last_time = now - self.last_time, now
        if self.last_guard is not None and self.od[(0x6007, 0)][2] == 1:
            timeout = self.od[(0x100C, 0)][2] * self.od[(0x100D, 0)][2] / 1000.0
            if now - self.last_guard > timeout:
                self.moving = self.enabled = False
                self.od[(0x6041, 0)][2] = 0x38
                self.od[(0x2601, 0)][2] = 1
        speed_raw = self.od[(0x6081, 0)][2]
        counts_s = speed_raw * 1875 / 512 / 60
        velocity = 0
        mode = self.od[(0x6060, 0)][2]
        if self.enabled and mode == 3:
            requested = self.od[(0x60FF, 0)][2]
            low, high = sorted((self.lower_counts, self.lower_counts + self.maximum * self.direction))
            step = requested * 1875 / 512 / 60 * dt
            self.position = max(low, min(high, self.position + step))
            velocity = requested if low < self.position < high else 0
            self.moving = velocity != 0
        elif self.moving:
            delta = self.target - self.position
            step = min(abs(delta), counts_s * dt)
            velocity = speed_raw if delta >= 0 else -speed_raw
            self.position += step if delta >= 0 else -step
            if abs(self.target - self.position) < 0.5:
                self.position = float(self.target)
                self.moving = False
                self.od[(0x6041, 0)][2] |= 0x400
                velocity = 0
        self.od[(0x6063, 0)][2] = round(self.position)
        self.od[(0x606C, 0)][2] = velocity
        lower = (self.position - self.lower_counts) * self.direction <= 0.5
        upper = (self.position - self.lower_counts) * self.direction >= self.maximum
        self.od[(0x6061, 0)][2] = mode if self.enabled else 0
        self.od[(0x60FD, 0)][2] = (int(lower) | (int(upper) << 1) if self.direction == 1
                                 else int(upper) | (int(lower) << 1))

    def _control(self, value, previous):
        """模拟6040控制字,6041状态字及bit4位置目标触发."""
        if value == 0x86:
            self.enabled = self.moving = False
            self.od[(0x2601, 0)][2] = 0
            self.od[(0x6041, 0)][2] = 0x31
            self.last_guard = time.monotonic() if self.last_guard is not None else None
        elif value in (0x0B, 0x02):
            self.enabled = self.moving = False
            self.od[(0x6041, 0)][2] = 0x50
        elif value in (0, 6, 7):
            self.enabled = self.moving = False
            self.od[(0x6041, 0)][2] = {0: 0x70, 6: 0x31, 7: 0x33}[value]
        elif value & 0x0F == 0x0F:
            self.enabled = True
            self.od[(0x6041, 0)][2] = (self.od[(0x6041, 0)][2] & 0x1400) | 0x37
            if value & 0x100:
                self.moving = False
                self.od[(0x6041, 0)][2] &= ~0x1000
                return
            if value & 0x10 and self.od[(0x6060, 0)][2] == 1:
                self.od[(0x6041, 0)][2] |= 0x1000
                if not previous & 0x10:
                    self.target = self.od[(0x607A, 0)][2]
                    self.moving = True
                    self.od[(0x6041, 0)][2] &= ~0x400
            else:
                self.od[(0x6041, 0)][2] &= ~0x1000

    def send(self, can_id, data=b'', remote=False):
        """解释主站帧,将SDO应答或节点保护应答加入内存队列."""
        with self.lock:
            if self.closed:
                raise CanError('Simulator closed.')
            self._step()
            self.sent.append((can_id, bytes(data), remote))
            if remote and can_id == 0x700 + self.node_id:
                self.last_guard = time.monotonic()
                if not self.drop_replies:
                    self.queue.append((can_id, bytes([5 | self.toggle << 7])))
                    self.toggle ^= 1
                return
            if can_id == 0:
                return
            if can_id != 0x600 + self.node_id or len(data) != 8:
                return
            command, index, sub = struct.unpack_from('<BHB', data)
            key = (index, sub)
            if key not in self.od:
                reply = struct.pack('<BHBI', 0x80, index, sub, 0x06020000)
            else:
                width, signed, value = self.od[key]
                if command == 0x40:
                    reply = struct.pack('<BHB', {1: 0x4F, 2: 0x4B, 4: 0x43}[width], index, sub)
                    reply += int(value).to_bytes(width, 'little', signed=signed).ljust(4, b'\0')
                elif command == {1: 0x2F, 2: 0x2B, 4: 0x23}[width]:
                    new = int.from_bytes(data[4:4 + width], 'little', signed=signed)
                    self.od[key][2] = new
                    if index == 0x6040:
                        self._control(new, value)
                    reply = struct.pack('<BHB4x', 0x60, index, sub)
                else:
                    reply = struct.pack('<BHBI', 0x80, index, sub, 0x06070010)
            if not self.drop_replies:
                self.queue.append((0x580 + self.node_id, reply))

    def recv(self, timeout):
        """读取一条模拟应答;无数据时短暂等待,不访问任何USB/CAN设备."""
        with self.lock:
            self._step()
            if self.queue:
                return self.queue.popleft()
        time.sleep(min(max(timeout, 0), 0.002))
        return None

    def close(self):
        with self.lock:
            self.closed = True
