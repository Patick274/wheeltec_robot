"""上端开关在正常行程外、参考丢失时的受监督释放;无ROS/硬件."""
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from kinco_lift.canopen import CanError, SdoClient
from kinco_lift.controller import LiftConfig, LiftController, LiftError, LiftReject
from kinco_lift.simulator import SimulatedCan
import test_ros_wiring as wiring


class UpperEscapeTests(unittest.TestCase):
    def setUp(self):
        self.cfg = LiftConfig(dict(
            motion_enabled=True, commissioning_confirmed=True, drive_limits_verified=True,
            speed_zones_enabled=True, keyboard_control_enabled=True,
            encoder_counts_per_rev=65536, mm_per_motor_rev=2.25,
            max_motor_rpm=1000, max_speed_mm_s=37.5, travel_mm=4190,
            keyboard_lower_position_counts=-447240, keyboard_upper_position_counts=121681191,
            keyboard_down_slow_counts=2465161, keyboard_up_slow_counts=118795161))
        span = (self.cfg.zones.upper - self.cfg.zones.lower) * 2.25 / 65536
        self.bus = SimulatedCan(travel_mm=span, lower_counts=self.cfg.zones.lower)
        self.bus.position = self.cfg.zones.upper
        self.health = self.parking = ''
        self.cap = 1000
        self.axis = LiftController(SdoClient(self.bus, timeout=0.02), self.cfg,
                                   lambda: self.health, lambda: self.cap,
                                   recovery_interlock=lambda: self.parking)
        self.addCleanup(self.axis.close)

    def position(self, counts):
        self.bus.position = counts
        self.bus.last_time = time.monotonic()
        # 注入与该位移相容的采样间隔,跳变失效另有独立用例.
        self.axis.feedback_time = time.monotonic() - 0.3

    def hold(self):
        self.axis.escape_upper_limit()
        self.position(self.axis.upper_escape_target - 1000)
        self.axis.poll()
        self.assertEqual(self.axis.upper_escape_phase, 'halting')
        self.axis.poll()
        self.assertEqual(self.axis.upper_escape_phase, 'holding')

    def test_escape_outside_software_travel_without_reference_then_holds(self):
        self.assertGreater((self.bus.position - self.cfg.zones.lower) * 2.25 / 65536, 4190)
        self.hold()
        self.assertIsNone(self.axis.reference)
        self.assertFalse(self.axis.keyboard_confirmed)
        self.assertTrue(self.axis.armed)
        self.assertTrue(self.axis.guard_active)
        self.assertTrue(self.bus.enabled)
        self.assertFalse(self.axis.busy)
        self.assertFalse(self.axis.status()['upper_limit'])
        self.assertTrue(self.axis.status()['upper_escape_complete'])
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], 0)
        for unused in range(3):
            self.axis.poll()
            self.axis.apply_speed_limits()
        self.assertEqual(self.axis.upper_escape_phase, 'holding')
        self.assertFalse(self.axis.latched)
        self.assertEqual(self.cfg.travel, 4190)

    def test_explicit_disable_then_frame_reference_and_position_mode(self):
        self.hold()
        self.axis.disable()
        self.assertEqual(self.axis.upper_escape_phase, '')
        self.axis.reference_from_frame()
        self.axis.enable()
        self.assertEqual(self.axis.control_mode, 1)
        with self.assertRaises(LiftReject):
            self.axis.move(4191, 1)
        self.axis.move(4180, 3)
        self.assertTrue(self.axis.busy)

    def test_requires_only_upper_limit_and_stationary_healthy_base(self):
        for reason in ('Chassis moving', 'Chassis odometry missing/stale'):
            self.parking = reason
            with self.assertRaises(LiftError):
                self.axis.escape_upper_limit()
            self.assertFalse(self.axis.took_control)
        self.parking = ''
        for limits in ((False, False), (True, True), (True, False)):
            with patch.object(self.axis, '_limits', return_value=limits):
                with self.assertRaises(LiftReject):
                    self.axis.escape_upper_limit()
            self.assertFalse(self.bus.enabled)

    def test_permissions_budget_and_invalid_arguments_never_enable(self):
        self.cfg.motion_enabled = False
        with self.assertRaises(LiftReject):
            self.axis.escape_upper_limit()
        self.cfg.motion_enabled = True
        self.axis.budget.used = self.axis.budget.limit
        with self.assertRaises(LiftReject):
            self.axis.escape_upper_limit()
        self.axis.budget.used = 0
        for args in ((float('nan'), 10), (50, float('inf')), (101, 10), (50, 11), (0, 1)):
            with self.assertRaises(LiftReject):
                self.axis.escape_upper_limit(*args)
        self.assertFalse(self.axis.took_control)
        self.assertFalse(self.bus.enabled)

    def test_wrong_precision_or_raw_frame_cannot_start(self):
        self.bus.od[(0x6410, 3)][2] = 131072
        with self.assertRaisesRegex(LiftError, 'precision'):
            self.axis.escape_upper_limit()
        self.bus.od[(0x6410, 3)][2] = 65536
        self.position(self.cfg.zones.upper - round(10 * 65536 / 2.25))
        with patch.object(self.axis, '_limits', return_value=(False, True)):
            with self.assertRaisesRegex(LiftReject, 'raw frame'):
                self.axis.escape_upper_limit()
        self.assertFalse(self.axis.took_control)

    def test_switch_hysteresis_and_no_stop_before_normal_interior(self):
        # 模拟开关向下移动2mm后才释放;不能像默认模拟器一样一离开顶部就释放.
        threshold = self.cfg.zones.upper - round(2 * 65536 / 2.25)
        with patch.object(self.axis, '_limits',
                          side_effect=lambda: (False, self.bus.position > threshold)):
            self.axis.escape_upper_limit()
            self.position(threshold + 1000)
            self.axis.poll()
            self.assertFalse(self.axis.upper_escape_released)
            self.position(threshold - 1000)
            self.axis.poll()
            self.assertTrue(self.axis.upper_escape_released)
            self.assertEqual(self.axis.upper_escape_phase, 'descending')
            self.position(self.axis.upper_escape_target - 1000)
            self.axis.poll()
            self.axis.poll()
            self.assertEqual(self.axis.upper_escape_phase, 'holding')

    def test_stuck_switch_times_out_and_retrigger_is_fault(self):
        self.axis.escape_upper_limit()
        self.axis.upper_escape_deadline = time.monotonic() - 1
        with self.assertRaisesRegex(LiftError, 'timeout'):
            self.axis.poll()
        self.axis.fail('timeout')
        self.assertTrue(self.axis.latched)
        self.assertFalse(self.bus.enabled)

    def test_released_switch_must_not_retrigger(self):
        self.axis.escape_upper_limit()
        self.position(self.cfg.zones.upper - 10000)
        self.axis.poll()
        self.assertTrue(self.axis.upper_escape_released)
        with patch.object(self.axis, '_limits', return_value=(False, True)):
            with self.assertRaisesRegex(LiftError, 'limit'):
                self.axis.poll()

    def test_distance_limit_and_wrong_direction(self):
        self.axis.escape_upper_limit()
        self.position(self.cfg.zones.upper - round(21 * 65536 / 2.25))
        with self.assertRaisesRegex(LiftError, 'distance'):
            self.axis.poll()
        self.position(self.cfg.zones.upper)
        self.axis.upper_escape_start = self.cfg.zones.upper - round(0.5 * 65536 / 2.25)
        with self.assertRaisesRegex(LiftError, 'direction|reversed'):
            self.axis.poll()

    def test_mode_precision_and_feedback_jump_remain_supervised(self):
        self.axis.escape_upper_limit()
        original = self.axis.sdo.read
        for index, value in ((0x6061, 1), (0x6410, 131072)):
            with patch.object(self.axis.sdo, 'read',
                              side_effect=lambda i, *a, **k: value if i == index else original(i, *a, **k)):
                with self.assertRaises(LiftError):
                    self.axis.poll()
        self.bus.position -= round(10 * 65536 / 2.25)
        self.axis.feedback_position = self.cfg.zones.upper
        self.axis.feedback_time = time.monotonic()
        with self.assertRaisesRegex(LiftError, 'jump'):
            self.axis.poll()

    def test_chassis_loss_budget_exhaustion_and_guard_timeout(self):
        self.axis.escape_upper_limit()
        self.parking = 'Chassis odometry missing/stale'
        with self.assertRaisesRegex(LiftError, 'stale'):
            self.axis.poll()
        self.parking = ''
        self.axis.budget.used = self.axis.budget.limit
        with self.assertRaisesRegex(LiftError, 'budget'):
            self.axis.poll()
        self.axis.budget.used = 0
        self.axis.guard_since = time.monotonic() - 1
        self.axis.sdo.guard_time = None
        # 后台guard线程每100ms按last_io门控刷新guard_time;把last_io置陈旧,
        # 阻止它在断言前抢刷,消除"guard响应确实不再到达"场景的时序竞争.
        self.axis.sdo.last_io = time.monotonic() - 1
        with self.assertRaisesRegex(LiftError, 'guard'):
            self.axis.poll()

    def test_operator_halt_neutral_and_global_stop_never_resume(self):
        self.axis.escape_upper_limit()
        with self.assertRaises(LiftReject):
            self.axis.keyboard_command(-1)
        self.axis.keyboard_command(0)
        self.axis.poll()
        for unused in range(3):
            self.axis.poll()
        self.assertEqual(self.axis.upper_escape_phase, 'holding')
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], 0)
        self.assertFalse(self.axis.status()['upper_escape_complete'])
        self.axis.stop()
        self.axis.poll()
        self.assertEqual(self.axis.upper_escape_phase, '')
        self.assertTrue(self.axis.latched)
        self.assertFalse(self.bus.enabled)

    def test_startup_failure_after_enable_stops_and_latches(self):
        original = self.axis._enable_drive
        def broken(mode):
            original(mode)
            raise LiftError('injected post-enable failure')
        with patch.object(self.axis, '_enable_drive', side_effect=broken):
            with self.assertRaisesRegex(LiftError, 'injected'):
                self.axis.escape_upper_limit()
        self.assertFalse(self.bus.enabled)
        self.assertTrue(self.axis.latched)
        self.assertEqual(self.axis.upper_escape_phase, '')

    def test_chassis_movement_during_enable_prevents_first_velocity(self):
        original = self.axis._enable_drive
        def changed(mode):
            original(mode)
            self.parking = 'Chassis moved during enable'
        with patch.object(self.axis, '_enable_drive', side_effect=changed):
            with self.assertRaisesRegex(LiftError, 'Chassis'):
                self.axis.escape_upper_limit()
        velocity_writes = [int.from_bytes(data[4:8], 'little', signed=True)
                           for can_id, data, remote in self.bus.sent
                           if len(data) == 8 and data[:4] == b'\x23\xff\x60\x00']
        self.assertFalse(any(value < 0 for value in velocity_writes))
        self.assertFalse(self.bus.enabled)

    def test_reverse_after_descent_and_slow_holding_drift_are_faults(self):
        self.axis.escape_upper_limit()
        self.position(self.cfg.zones.upper - round(2 * 65536 / 2.25))
        self.axis.poll()
        self.position(self.bus.position + round(0.5 * 65536 / 2.25))
        with self.assertRaisesRegex(LiftError, 'reversed'):
            self.axis.poll()

    def test_holding_position_drift_below_velocity_threshold_is_fault(self):
        self.hold()
        self.position(self.axis.upper_escape_hold_position - round(0.3 * 65536 / 2.25))
        with self.assertRaisesRegex(LiftError, 'holding'):
            self.axis.poll()

    def test_feedback_reverse_or_over_100rpm_is_fault(self):
        self.axis.escape_upper_limit()
        original = self.axis.sdo.read
        for rpm in (10, -101):
            raw = self.cfg.velocity_raw(abs(rpm)) * (1 if rpm > 0 else -1)
            with patch.object(self.axis.sdo, 'read',
                              side_effect=lambda i, *a, **k: raw if i == 0x606C else original(i, *a, **k)):
                with self.assertRaises(LiftError):
                    self.axis.poll()

    def test_halting_waits_for_feedback_then_times_out(self):
        self.axis.escape_upper_limit()
        self.position(self.axis.upper_escape_target - 1000)
        original = self.axis.sdo.read
        with patch.object(self.axis.sdo, 'read',
                          side_effect=lambda i, *a, **k: -self.cfg.velocity_raw(10)
                          if i == 0x606C else original(i, *a, **k)):
            self.axis.poll()
            self.assertEqual(self.axis.upper_escape_phase, 'halting')
            self.assertTrue(self.axis.busy)
            self.axis.upper_escape_halt_deadline = time.monotonic() - 1
            with self.assertRaisesRegex(LiftError, 'standstill'):
                self.axis.poll()

    def test_poisoned_can_startup_requests_raw_stop(self):
        original = self.axis._write
        def fail_on_velocity(index, value, *a, **k):
            if index == 0x60FF and value < 0:
                self.axis.sdo.poisoned = True
                raise CanError('injected lost reply')
            return original(index, value, *a, **k)
        with patch.object(self.axis, '_write', side_effect=fail_on_velocity):
            with self.assertRaises(CanError):
                self.axis.escape_upper_limit()
        self.assertTrue(self.axis.latched)
        self.assertFalse(self.bus.enabled)

    def test_lower_recovery_operator_halt_cancels_future_velocity(self):
        self.position(self.cfg.zones.lower + round(5 * 65536 / 2.25))
        self.axis.recover_to_lower_limit()
        self.axis.operator_halt()
        self.axis.poll()
        self.assertFalse(self.axis.recovering)
        self.assertFalse(self.bus.enabled)
        self.assertTrue(self.axis.latched)

    def test_reference_rejection_preserves_existing_reference(self):
        self.position(self.cfg.zones.lower)
        self.axis.reference_here()
        reference = self.axis.reference
        self.position(self.cfg.zones.lower + round(20 * 65536 / 2.25))
        self.axis.feedback_time = None
        with self.assertRaises(LiftReject):
            self.axis.reference_here()
        self.assertEqual(self.axis.reference, reference)
        self.assertTrue(self.axis.frame_confirmed)


class UpperEscapeNodeTests(unittest.TestCase):
    def test_service_uses_stationary_interlock_and_blocks_base_permit(self):
        params = dict(simulate=True, require_base_feedback=True,
                      motion_enabled=True, commissioning_confirmed=True,
                      drive_limits_verified=True, speed_zones_enabled=True,
                      encoder_counts_per_rev=65536, mm_per_motor_rev=2.25,
                      travel_mm=4190, max_motor_rpm=1000, max_speed_mm_s=37.5)
        modules, ros, unused = wiring.ros_stubs(params)
        with patch.dict(sys.modules, modules):
            node = wiring.load_script('lift_node').LiftNode()
            try:
                callbacks = {call.args[0]: call.args[2] for call in ros.Service.call_args_list}
                self.assertIn('~escape_upper_limit', callbacks)
                node.parking.odometry(0.1, 0, 0)
                node.axis.sdo.transport.position = node.cfg.zones.upper
                result = callbacks['~escape_upper_limit'](None)
                self.assertFalse(result.success)
                self.assertFalse(node.axis.took_control)
                node.axis.upper_escape_phase = 'holding'
                node.base_motion_requested = True
                self.assertFalse(node.base_permission(node.axis.status()))
            finally:
                node.shutdown()


if __name__ == '__main__':
    unittest.main()
