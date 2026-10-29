"""进程级退出测试:控制逻辑跑在子进程,模拟驱动器留在父进程,跨进程观察总线结果.

对应复盘P0-B:不依赖vcan/sudo;覆盖正常退出/未处理异常/SIGKILL/os._exit.
SIGKILL与os._exit没有任何Python清理机会,验收的是驱动器侧节点保护超时
(仿真600ms)独立兜底,不是atexit.
"""
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kinco_lift.simulator import SimulatedCan

FRAME = struct.Struct('=HBB8s')  # can_id, remote, dlc, data

CHILD = '''
import atexit, os, signal, socket, struct, sys
sys.path.insert(0, {src!r})
from kinco_lift.canopen import SdoClient
from kinco_lift.controller import LiftConfig, LiftController

FRAME = struct.Struct('=HBB8s')

class TcpCan:
    def __init__(self, port):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=3)
        self.buf = b''
    def send(self, can_id, data=b'', remote=False):
        self.sock.sendall(FRAME.pack(can_id, int(remote), len(data), data.ljust(8, b'\\0')))
    def recv(self, timeout):
        self.sock.settimeout(max(timeout, 0.001))
        try:
            while len(self.buf) < FRAME.size:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return None
                self.buf += chunk
        except socket.timeout:
            return None
        record, self.buf = self.buf[:FRAME.size], self.buf[FRAME.size:]
        can_id, remote, dlc, data = FRAME.unpack(record)
        return can_id, data[:dlc]
    def close(self):
        self.sock.close()

scenario, port = sys.argv[1], int(sys.argv[2])
cfg = LiftConfig(dict(motion_enabled=True, commissioning_confirmed=True,
                      drive_limits_verified=True, keyboard_control_enabled=True,
                      encoder_counts_per_rev=65536, mm_per_motor_rev=2.25,
                      travel_mm=0, max_motor_rpm=1000, max_speed_mm_s=37.5))
axis = LiftController(SdoClient(TcpCan(port), timeout=0.15), cfg, lambda: '')
# 与lift_node一致:atexit兜底在构造后立即注册.
atexit.register(axis.failsafe_halt)
axis.confirm_keyboard_coordinates()
axis.enable(keyboard=True)
axis.keyboard_command(0)
axis.keyboard_command(1)
if scenario == 'normal':
    axis.close()
elif scenario == 'crash':
    raise RuntimeError('simulated crash with pending velocity command')
elif scenario == 'sigkill':
    os.kill(os.getpid(), signal.SIGKILL)
elif scenario == 'os_exit':
    os._exit(1)
'''


class DriveServer:
    """父进程持有的模拟驱动器;连接断开后继续推进时间,节点保护超时才会触发."""

    def __init__(self):
        self.sim = SimulatedCan(travel_mm=(122303105 - 147599) * 2.25 / 65536,
                                lower_counts=147599)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.stopped = False
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _tick_until_stop(self):
        while not self.stopped:
            self.sim._step()
            time.sleep(0.02)

    def _serve(self):
        conn, _ = self.listener.accept()
        conn.settimeout(0.05)
        while not self.stopped:
            try:
                record = self._read(conn, FRAME.size)
            except socket.timeout:
                self.sim._step()
                continue
            if record is None:  # 子进程退出/被杀:没有流量也要继续走表.
                self._tick_until_stop()
                return
            can_id, remote, dlc, data = FRAME.unpack(record)
            self.sim.send(can_id, data[:dlc], bool(remote))
            while True:
                reply = self.sim.recv(0)
                if reply is None:
                    break
                rid, rdata = reply
                conn.sendall(FRAME.pack(rid, 0, len(rdata), rdata.ljust(8, b'\0')))

    @staticmethod
    def _read(conn, size):
        data = b''
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def run_child(self, scenario):
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
            f.write(CHILD.format(src=str(ROOT / 'src')))
            path = f.name
        return subprocess.Popen([sys.executable, path, scenario, str(self.port)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def close(self):
        self.stopped = True
        self.thread.join(timeout=2)
        self.listener.close()


class CrashProcessTests(unittest.TestCase):
    def setUp(self):
        self.server = DriveServer()
        self.server.thread.start()

    def tearDown(self):
        self.server.close()

    def wait_child(self, proc, timeout=8):
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail('Child process hung: ' + proc.stderr.read().decode('utf-8', 'replace'))
        return stdout, stderr

    def test_normal_exit_quick_stops_drive(self):
        proc = self.server.run_child('normal')
        self.wait_child(proc)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.server.sim.od[(0x6040, 0)][2], 0x000B)
        self.assertFalse(self.server.sim.enabled)
        self.assertFalse(self.server.sim.moving)

    def test_unhandled_exception_runs_atexit_failsafe(self):
        proc = self.server.run_child('crash')
        self.wait_child(proc)
        self.assertNotEqual(proc.returncode, 0)
        # atexit兜底:60FF清零+6040=6两帧真正到达总线.
        self.assertEqual(self.server.sim.od[(0x60FF, 0)][2], 0)
        self.assertEqual(self.server.sim.od[(0x6040, 0)][2], 6)
        self.assertFalse(self.server.sim.enabled)

    def check_supervision_only_backstop(self, scenario):
        """SIGKILL/os._exit:无Python清理,60FF残留,但驱动器节点保护超时独立停车."""
        proc = self.server.run_child(scenario)
        self.wait_child(proc)
        sim = self.server.sim
        self.assertNotEqual(sim.od[(0x60FF, 0)][2], 0)  # 残留正是10-27事故形态.
        self.assertEqual(sim.od[(0x6040, 0)][2], 0x000F)  # 没有收到任何停机/关断帧.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if sim.od[(0x2602, 0)][2] & 0x0002:
                break
            time.sleep(0.02)
        # 手册7.12节:看门狗是2602 bit1;驱动器撤使能,运动停止.
        self.assertTrue(sim.od[(0x2602, 0)][2] & 0x0002)
        self.assertFalse(sim.enabled)
        self.assertFalse(sim.moving)

    def test_sigkill_relies_on_drive_supervision(self):
        self.check_supervision_only_backstop('sigkill')
        self.assertEqual(self.server and True, True)

    def test_os_exit_relies_on_drive_supervision(self):
        self.check_supervision_only_backstop('os_exit')


if __name__ == '__main__':
    unittest.main()
