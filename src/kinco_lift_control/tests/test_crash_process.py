"""进程级退出测试:控制逻辑跑在子进程,模拟驱动器留在父进程,跨进程观察总线结果.

对应复盘P0-B:不依赖vcan/sudo;覆盖正常退出/未处理异常/SIGKILL/os._exit.
SIGKILL与os._exit没有任何Python清理机会,验收的是驱动器侧节点保护超时
(仿真600ms)独立兜底,不是atexit.
"""
import os
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
import atexit, os, signal, socket, struct, sys, time
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
elif scenario == 'wait':
    time.sleep(60)  # 由父进程terminate;不执行正常close或解释器退出钩子.
'''


class DriveServer:
    """父进程持有的模拟驱动器;连接断开后继续推进时间,节点保护超时才会触发."""

    def __init__(self):
        self.sim = SimulatedCan(travel_mm=(122303105 - 147599) * 2.25 / 65536,
                                lower_counts=147599)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.settimeout(0.05)
        self.port = self.listener.getsockname()[1]
        self.stopped = False
        self.connection = None
        self.child_paths = []
        self.children = []
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _tick_until_stop(self):
        while not self.stopped:
            self.sim._step()
            time.sleep(0.02)

    def _serve(self):
        while not self.stopped:
            try:
                conn, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.stopped:  # Windows关闭listener会唤醒accept并报10038.
                    return
                raise
            break
        else:
            return
        self.connection = conn
        conn.settimeout(0.05)
        pending = b''
        try:
            while not self.stopped:
                try:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    pending += chunk
                    while len(pending) >= FRAME.size:
                        record, pending = pending[:FRAME.size], pending[FRAME.size:]
                        can_id, remote, dlc, data = FRAME.unpack(record)
                        self.sim.send(can_id, data[:dlc], bool(remote))
                        while True:
                            reply = self.sim.recv(0)
                            if reply is None:
                                break
                            rid, rdata = reply
                            conn.sendall(FRAME.pack(rid, 0, len(rdata), rdata.ljust(8, b'\0')))
                except socket.timeout:
                    self.sim._step()
                except OSError:
                    # 强杀可产生EOF或连接重置;两者都表示主站不再发送流量.
                    break
        finally:
            conn.close()
        # 子进程退出/被杀后模拟驱动器仍独立走表,监督超时才会停车.
        self._tick_until_stop()

    def run_child(self, scenario):
        # 源码含中文项目路径;Windows默认ANSI编码不能保存它.先关文件再启动子进程.
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False,
                                         encoding='utf-8', newline='\n') as f:
            f.write(CHILD.format(src=str(ROOT / 'src')))
            path = f.name
        self.child_paths.append(path)
        proc = subprocess.Popen([sys.executable, '-B', path, scenario, str(self.port)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=dict(os.environ, PYTHONIOENCODING='utf-8',
                                         PYTHONDONTWRITEBYTECODE='1'))
        self.children.append(proc)
        return proc

    def close(self):
        for proc in self.children:
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=3)
        self.stopped = True
        if self.connection is not None:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.listener.close()
        self.thread.join(timeout=2)
        for path in self.child_paths:
            pathlib.Path(path).unlink()
        if self.thread.is_alive():
            raise RuntimeError('DriveServer thread did not stop.')


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
            stdout, stderr = proc.communicate(timeout=3)
            self.fail('Child process hung: ' + stderr.decode('utf-8', 'replace'))
        return stdout, stderr

    def test_normal_exit_quick_stops_drive(self):
        proc = self.server.run_child('normal')
        stdout, stderr = self.wait_child(proc)
        self.assertEqual(proc.returncode, 0, stderr.decode('utf-8', 'replace'))
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
        """无Python清理的退出保留60FF,仅独立驱动器监督可以停车."""
        proc = self.server.run_child('wait' if scenario == 'terminate' else scenario)
        if scenario == 'terminate':
            deadline = time.monotonic() + 5
            while self.server.sim.od[(0x60FF, 0)][2] == 0:
                if proc.poll() is not None:
                    self.fail('Child exited before reaching the velocity command.')
                if time.monotonic() > deadline:
                    self.fail('Child never reached the velocity command.')
                time.sleep(0.005)
            # POSIX默认SIGTERM和WindowsTerminateProcess都不执行Python清理钩子.
            proc.terminate()
        self.wait_child(proc)
        sim = self.server.sim
        self.assertNotEqual(sim.od[(0x60FF, 0)][2], 0)  # 残留正是10-27事故形态.
        self.assertEqual(sim.od[(0x6040, 0)][2], 0x000F)  # 没有收到任何停机/关断帧.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if sim.od[(0x2602, 0)][2] & 0x1000:
                break
            time.sleep(0.02)
        # 手册表10-2:节点保护超时是2602 bit12(CAN总线中断0x8100);驱动器撤使能,运动停止.
        self.assertTrue(sim.od[(0x2602, 0)][2] & 0x1000)
        self.assertFalse(sim.enabled)
        self.assertFalse(sim.moving)

    @unittest.skipUnless(os.name == 'posix', 'SIGKILL is a POSIX-specific exit path.')
    def test_sigkill_relies_on_drive_supervision(self):
        self.check_supervision_only_backstop('sigkill')

    def test_forced_termination_relies_on_drive_supervision(self):
        self.check_supervision_only_backstop('terminate')

    def test_os_exit_relies_on_drive_supervision(self):
        self.check_supervision_only_backstop('os_exit')


if __name__ == '__main__':
    unittest.main()
