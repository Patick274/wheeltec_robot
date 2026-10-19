"""不依赖ROS的回归测试：在包目录执行python3 -m unittest discover -s tests -v。

覆盖报文字节、数据类型、换算、运动许可、停车、限位、故障及停止状态。
测试使用内存模拟器，不向实物设备发送任何消息。
"""
import math
import pathlib
import struct
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from kinco_lift.canopen import CanError, SdoAbort, SdoClient
from kinco_lift.controller import LiftConfig, LiftController, LiftError
from kinco_lift.interlock import ParkingInterlock
from kinco_lift.simulator import SimulatedCan


def calibrated(**updates):
    p = dict(motion_enabled=True, commissioning_confirmed=True,
             drive_limits_verified=True, encoder_counts_per_rev=65536,
             mm_per_motor_rev=2.25, travel_mm=200)
    p.update(updates)
    return LiftConfig(p)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.bus = SimulatedCan()
        self.sdo = SdoClient(self.bus, timeout=0.02)

    def tearDown(self):
        self.bus.close()

    def test_exact_manual_position_write(self):
        self.sdo.write(0x607A, 100000, signed=True)
        self.assertEqual(self.bus.sent[-1], (0x601, bytes.fromhex('237A6000A0860100'), False))

    def test_signed_roundtrip(self):
        self.sdo.write(0x607A, -123456, signed=True)
        self.assertEqual(self.sdo.read(0x607A, signed=True), -123456)

    def test_explicit_sdo_sizes(self):
        self.sdo.write(0x6060, -3, size=1, signed=True)
        self.assertEqual(self.sdo.read(0x6060, size=1, signed=True), -3)
        self.sdo.write(0x6040, 6, size=2)
        self.assertEqual(self.sdo.read(0x6040, size=2), 6)

    def test_abort_invalidates_session(self):
        with self.assertRaises(SdoAbort):
            self.sdo.read(0xFFFF)
        self.assertTrue(self.sdo.poisoned)

    def test_timeout_no_retry(self):
        self.bus.drop_replies = True
        with self.assertRaises(CanError):
            self.sdo.read(0x6041, size=2)
        sent = len(self.bus.sent)
        self.bus.drop_replies = False
        with self.assertRaises(CanError):
            self.sdo.write(0x6040, 15, size=2)
        self.assertEqual(len(self.bus.sent), sent)

    def test_wrong_reply_object_is_rejected(self):
        original = self.bus.send
        def corrupt(*args, **kwargs):
            original(*args, **kwargs)
            if self.bus.queue:
                can_id, data = self.bus.queue.pop()
                self.bus.queue.append((can_id, data[:1] + b'\x42\x60' + data[3:]))
        self.bus.send = corrupt
        with self.assertRaises(CanError):
            self.sdo.read(0x6041, size=2)
        self.assertTrue(self.sdo.poisoned)

    def test_guard_toggle(self):
        self.sdo.guard()
        self.sdo.read(0x6041, size=2)
        first = self.sdo.guard_toggle
        self.sdo.guard()
        self.sdo.read(0x6041, size=2)
        self.assertNotEqual(first, self.sdo.guard_toggle)

    def test_manual_scaling_examples(self):
        cfg = calibrated()
        self.assertEqual(cfg.velocity_raw(200), 0x00369D03)
        self.assertEqual(cfg.acceleration_raw(100), 0x0001A36E)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.bus = SimulatedCan()
        self.sdo = SdoClient(self.bus, timeout=0.02)
        self.reason = ''
        self.axis = LiftController(self.sdo, calibrated(), lambda: self.reason)

    def tearDown(self):
        self.axis.close()

    def test_startup_and_poll_have_no_writes(self):
        self.axis.poll()
        self.assertFalse(self.axis.armed)
        self.assertTrue(all(data[0] == 0x40 for can_id, data, rtr in self.bus.sent))
        self.axis.close()
        self.assertTrue(all(data[0] == 0x40 for can_id, data, rtr in self.bus.sent))

    def test_readonly_defaults_deny_enable(self):
        self.axis.cfg = LiftConfig({})
        with self.assertRaises(LiftError):
            self.axis.enable()
        self.assertFalse(self.bus.sent)

    def test_unknown_calibration_denies_enable(self):
        self.axis.cfg = calibrated(encoder_counts_per_rev=0)
        with self.assertRaises(LiftError):
            self.axis.enable()

    def test_missing_limit_confirmation_denies_enable(self):
        self.axis.cfg = calibrated(drive_limits_verified=False)
        with self.assertRaises(LiftError):
            self.axis.enable()

    def test_enable_guard_configuration_and_no_motion(self):
        self.axis.enable()
        self.assertTrue(self.axis.armed)
        self.assertFalse(self.bus.moving)
        self.assertEqual(self.bus.od[(0x6007, 0)][2], 1)
        self.assertEqual(self.bus.od[(0x100C, 0)][2], 200)
        self.assertEqual(self.bus.od[(0x100D, 0)][2], 3)
        self.assertEqual(self.bus.od[(0x1017, 0)][2], 0)

    def test_absolute_motion_needs_reference(self):
        self.axis.enable()
        with self.assertRaises(LiftError):
            self.axis.move(1, 1)

    def test_reference_at_lower_and_profile_position(self):
        self.axis.enable()
        self.axis.reference_here()
        self.axis.move(1, 5)
        self.assertTrue(self.axis.busy)
        self.assertEqual(self.bus.target, round(65536 / 2.25))
        deadline = time.monotonic() + 2
        while self.axis.busy and time.monotonic() < deadline:
            time.sleep(0.02)
            self.axis.poll()
        self.assertFalse(self.axis.busy)
        self.assertAlmostEqual(self.axis.status()['position_mm'], 1, places=3)

    def test_reference_denied_away_from_lower(self):
        self.bus.position = 10000
        with self.assertRaises(LiftError):
            self.axis.reference_here()

    def test_lower_limit_blocks_down_but_allows_up(self):
        self.axis.enable()
        with self.assertRaises(LiftError):
            self.axis.move(-1, 1, jog=True)
        self.axis.move(1, 1, jog=True)
        self.assertTrue(self.axis.busy)

    def test_oversized_jog_nan_and_speed_rejected(self):
        self.axis.enable()
        for value, speed in [(2, 1), (math.nan, 1), (1, 0), (1, math.inf), (1, 6)]:
            with self.assertRaises(LiftError):
                self.axis.move(value, speed, jog=True)
        self.assertFalse(self.bus.moving)

    def test_absolute_soft_limit(self):
        self.axis.enable()
        self.axis.reference_here()
        with self.assertRaises(LiftError):
            self.axis.move(201, 5)

    def test_signed_direction_and_int32_overflow(self):
        self.axis.enable()
        self.axis.cfg.direction = -1
        self.bus.direction = -1
        self.bus.position = -10000
        self.axis.poll()
        self.axis.move(0.1, 1, jog=True)
        self.assertLess(self.bus.target, -10000)
        self.axis.stop()
        self.axis.poll()
        self.axis.reset()
        self.axis.enable()
        self.bus.position = -2147483640
        with self.assertRaises(LiftError):
            self.axis.move(1, 1, jog=True)

    def test_stop_latches_and_does_not_resume(self):
        self.axis.enable()
        self.axis.move(1, 1, jog=True)
        self.assertTrue(self.axis.stop())
        self.assertFalse(self.bus.moving)
        self.assertFalse(self.axis.armed)
        with self.assertRaises(LiftError):
            self.axis.enable()
        self.axis.poll()
        self.axis.reset()
        self.assertIsNone(self.axis.reference)
        self.axis.enable()

    def test_moving_base_denies_enable_and_monitor(self):
        self.reason = 'base moving'
        with self.assertRaisesRegex(LiftError, 'base moving'):
            self.axis.enable()
        self.reason = ''
        self.axis.enable()
        self.reason = 'base moving'
        with self.assertRaisesRegex(LiftError, 'base moving'):
            self.axis.poll()
        self.axis.fail('base moving')
        self.assertFalse(self.axis.armed)

    def test_drive_reboot_clears_reference(self):
        self.axis.enable()
        self.axis.reference_here()
        self.bus.queue.append((0x701, b'\0'))
        with self.assertRaisesRegex(LiftError, 'reboot'):
            self.axis.poll()
        self.assertIsNone(self.axis.reference)

    def test_link_loss_latches_and_clears_reference(self):
        self.axis.enable()
        self.axis.reference_here()
        self.bus.drop_replies = True
        with self.assertRaises(CanError):
            self.axis.poll()
        self.axis.fail('CAN link lost')
        self.assertFalse(self.axis.armed)
        self.assertFalse(self.axis.guard_active)
        self.assertTrue(self.axis.latched)
        self.assertIsNone(self.axis.reference)

    def test_motion_timeout(self):
        self.axis.enable()
        self.axis.move(1, 1, jog=True)
        self.axis.move_started -= 31
        with self.assertRaisesRegex(LiftError, 'timeout'):
            self.axis.poll()

    def test_fault_can_be_reset_after_confirmed_stop(self):
        self.axis.enable()
        self.axis.reference_here()
        self.axis.move(1, 1, jog=True)
        self.bus.od[(0x2601, 0)][2] = 1
        self.bus.od[(0x6041, 0)][2] = 0x38
        with self.assertRaises(LiftError):
            self.axis.poll()
        self.axis.fail('drive fault')
        self.axis.reset()
        self.assertFalse(self.axis.latched)
        self.assertFalse(self.axis.armed)
        self.assertIsNone(self.axis.reference)

    def test_stop_does_not_report_idle_before_feedback(self):
        self.axis.enable()
        self.axis.move(1, 1, jog=True)
        self.axis.stop()
        self.assertTrue(self.axis.status()['busy'])
        self.assertTrue(self.axis.status()['stopping'])
        self.axis.poll()
        self.assertFalse(self.axis.status()['busy'])

    def test_guard_configuration_must_be_acknowledged(self):
        self.bus.od[(0x100E, 0)][2] = 0x777
        with self.assertRaisesRegex(LiftError, 'COB-ID'):
            self.axis.enable()
        self.assertFalse(self.bus.enabled)

    def test_node_guard_loss_causes_drive_fault(self):
        self.axis.enable()
        self.axis.move(1, 1, jog=True)
        self.axis.guard_active = False
        self.bus.last_guard = time.monotonic() - 1
        with self.assertRaises(LiftError):
            self.axis.poll()
        self.assertFalse(self.bus.moving)
        self.assertTrue(self.bus.od[(0x2601, 0)][2])


class ParkingTests(unittest.TestCase):
    def test_missing_stale_and_stationary(self):
        p = ParkingInterlock(odom_timeout=0.1, stationary_s=0.01)
        self.assertIn('missing', p.reason())
        p.odometry(0, 0, 0)
        self.assertIn('long enough', p.reason())
        time.sleep(0.02)
        self.assertEqual(p.reason(), '')
        p.odom_time -= 1
        self.assertIn('stale', p.reason())
        p.odometry(0, 0, 0)
        self.assertIn('long enough', p.reason())

    def test_command_invalid_or_nonzero(self):
        p = ParkingInterlock(stationary_s=0.001)
        p.odometry(0, 0, 0)
        p.command(0.1, 0, 0)
        self.assertIn('command', p.reason())
        p.command(math.nan, 0, 0)
        self.assertIn('command', p.reason())


if __name__ == '__main__':
    unittest.main()
