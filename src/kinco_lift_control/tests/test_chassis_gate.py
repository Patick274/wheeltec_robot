"""Compile/run the actual chassis C++ policy, not a Python reimplementation."""
import pathlib
import os
import shutil
import subprocess
import tempfile
import unittest

BASE = pathlib.Path(__file__).resolve().parents[2] / 'turn_on_wheeltec_robot'


class ChassisGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('g++')
        if not compiler or not (BASE / 'include/lift_motion_gate.h').exists():
            raise unittest.SkipTest('Needs g++ and the sibling turn_on_wheeltec_robot package.')
        cls.temp = tempfile.TemporaryDirectory(dir=os.environ.get('KINCO_TEST_TMPDIR'))
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binary = str(pathlib.Path(cls.temp.name) / 'lift_gate_test.exe')
        # MinGW on Windows cannot reliably open non-ASCII absolute source paths.
        result = subprocess.run([compiler, '-std=c++11', '-Wall', '-Wextra', '-Werror',
                                 '-I', '../include', 'lift_motion_gate_test.cpp', '-o', cls.binary],
                                cwd=BASE / 'test', capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def run_case(self, name):
        result = subprocess.run([self.binary, name], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wait_for_permit(self): self.run_case('wait_for_permit')
    def test_permit_timeout(self): self.run_case('permit_timeout')
    def test_command_timeout(self): self.run_case('command_timeout')
    def test_feedback_timeout(self): self.run_case('feedback_timeout')
    def test_zero_and_cooldown(self): self.run_case('zero_and_cooldown')
    def test_tiny_command(self): self.run_case('tiny_command')
    def test_invalid_command(self): self.run_case('invalid_command')
    def test_old_process(self): self.run_case('old_process')
    def test_uncommanded_motion(self): self.run_case('uncommanded_motion')

    def test_real_serial_entry_uses_gate_and_independent_queue(self):
        cpp = (BASE / 'src/wheeltec_robot.cpp').read_text(encoding='utf-8')
        callback = cpp.split('void turn_on_robot::Cmd_Vel_Callback', 1)[1].split('void turn_on_robot::Lift_Permit_Callback', 1)[0]
        self.assertIn('lift_gate.command', callback)
        self.assertNotIn('Stm32_Serial.write', callback)
        self.assertIn('lift_gate.output(now)', cpp)
        self.assertIn('new ros::AsyncSpinner(1, &lift_callback_queue)', cpp)
