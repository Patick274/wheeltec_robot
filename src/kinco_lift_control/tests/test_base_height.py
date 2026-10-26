"""底盘运动限速、顶端米制高度及在线定位降速；全部使用内存传输。"""
import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from kinco_lift.canopen import SdoClient
from kinco_lift.controller import LiftConfig, LiftController, LiftError
from kinco_lift.interlock import ParkingInterlock
from kinco_lift.simulator import SimulatedCan


class MovingChassisTests(unittest.TestCase):
    def setUp(self):
        self.p = ParkingInterlock(stationary_s=0.001)
        self.p.odometry(0, 0, 0)
        self.p.stationary_since -= 1

    def test_stationary_can_cruise_and_command_immediately_reduces_cap(self):
        self.assertEqual(self.p.speed_limit_rpm(1000, 100), 1000)
        self.p.command(0.2, 0, 0)
        self.assertEqual(self.p.speed_limit_rpm(1000, 100), 100)
        self.assertEqual(self.p.health_reason(), '')
        self.assertTrue(self.p.reason())  # 旧严格停车策略仍可选。

    def test_actual_linear_and_angular_movement_reduce_cap(self):
        for vx, vy, wz in ((0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)):
            self.p.odometry(vx, vy, wz)
            self.assertEqual(self.p.speed_limit_rpm(1000, 100), 100)
            self.assertEqual(self.p.health_reason(), '')

    def test_stale_or_invalid_is_not_merely_slow(self):
        self.p.odom_time -= 10
        self.assertIn('stale', self.p.health_reason())
        self.p.odometry(float('nan'), 0, 0)
        self.assertIn('invalid', self.p.health_reason())
        self.p.odometry(0, 0, 0)
        self.p.command(0, float('inf'), 0)
        self.assertIn('invalid', self.p.health_reason())

    def test_dwell_after_motion_is_also_slow(self):
        self.p.command(0.1, 0, 0)
        self.p.command(0, 0, 0)
        self.p.odometry(0, 0, 0)
        self.p.dwell = 1
        self.assertEqual(self.p.speed_limit_rpm(1000, 100), 100)
        self.p.stationary_since -= 2
        self.assertEqual(self.p.speed_limit_rpm(1000, 100), 1000)


class HeightAndSpeedTests(unittest.TestCase):
    def setUp(self):
        self.params = dict(motion_enabled=True, commissioning_confirmed=True,
                           drive_limits_verified=True, keyboard_control_enabled=True,
                           speed_zones_enabled=True, encoder_counts_per_rev=65536,
                           mm_per_motor_rev=2.25, travel_mm=4190, max_motor_rpm=1000,
                           max_speed_mm_s=37.5, initial_top_height_m=0.8,
                           motion_timeout_s=110)
        self.cfg = LiftConfig(self.params)
        self.bus = SimulatedCan(travel_mm=(122303105 - 147599) * 2.25 / 65536,
                                lower_counts=147599)
        self.cap, self.reason = 1000, ''
        self.axis = LiftController(SdoClient(self.bus, timeout=0.02), self.cfg,
                                   lambda: self.reason, lambda: self.cap)

    def tearDown(self):
        self.axis.close()

    def start_position(self):
        self.axis.enable()
        self.axis.reference_here()

    def test_absolute_top_height_is_initial_plus_extension_not_increment(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.assertEqual(self.bus.target, 147599 + round(300 * 65536 / 2.25))
        self.assertAlmostEqual(self.axis.target_mm, 300, places=4)
        self.assertAlmostEqual(self.axis.status()['target_top_height_m'], 1.1)
        self.assertAlmostEqual(self.axis.status()['top_height_m'], 0.8, places=2)

    def test_unmeasured_initial_height_disables_only_top_height_service(self):
        self.axis.cfg.initial_top_height = None
        self.start_position()
        with self.assertRaisesRegex(LiftError, 'initial_top_height_m'):
            self.axis.move_top_height(1.1)
        self.axis.move(10, 1)
        self.assertTrue(self.axis.busy)
        self.assertIsNone(self.axis.status()['top_height_m'])

    def test_height_requires_reference_and_rejects_below_base_nan_or_overtravel(self):
        self.axis.enable()
        with self.assertRaisesRegex(LiftError, 'reference'):
            self.axis.move_top_height(1.1)
        self.axis.reference_here()
        for value in (0.7, float('nan'), float('inf'), 100, 0.8):
            with self.subTest(value=value), self.assertRaises(LiftError):
                self.axis.move_top_height(value)
        self.assertFalse(self.bus.moving)

    def test_moving_base_caps_height_move_before_trigger(self):
        self.cap = 100
        self.start_position()
        self.axis.move_top_height(1.1)
        self.assertEqual(self.axis.position_rpm, 100)
        self.assertEqual(self.bus.od[(0x6081, 0)][2], self.cfg.velocity_raw(100))

    def test_base_starts_during_move_and_stop_does_not_restore_fast_speed(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.assertEqual(self.axis.position_rpm, 1000)
        target = self.bus.target
        self.cap = 100
        self.axis.apply_speed_limits()
        self.assertEqual(self.axis.position_rpm, 100)
        self.assertEqual(self.bus.target, target)
        self.cap = 1000
        self.axis.poll()
        self.assertEqual(self.axis.position_rpm, 100)

    def test_legacy_jog_and_move_also_obey_chassis_cap(self):
        self.cap = 100
        self.start_position()
        self.axis.move(0.5, 37.5, jog=True)
        self.assertEqual(self.axis.position_rpm, 100)

    def test_keyboard_also_caps_when_chassis_starts(self):
        self.axis.confirm_keyboard_coordinates()
        self.axis.enable(keyboard=True)
        self.axis.keyboard_command(0)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 1000)
        self.cap = 100
        self.axis.apply_speed_limits()
        self.assertEqual(self.axis.command_rpm, 100)
        self.cap = 1000
        self.axis.poll()
        self.assertEqual(self.axis.command_rpm, 100)

    def test_feedback_loss_still_stops_not_permission_to_move_slowly(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.reason = 'Chassis odometry missing/stale'
        with self.assertRaisesRegex(LiftError, 'stale'):
            self.axis.apply_speed_limits()

    def test_position_mode_also_slows_at_upper_zone(self):
        # 扩大人工仿真预算只用于策略单测，不是实机工作制设置。
        self.axis.cfg.timeout = 300
        self.axis.budget.limit = 300
        self.start_position()
        self.axis.move_top_height(0.8 + 4.15)
        self.bus.position = 119400000
        self.axis.feedback_time = None  # 人工放置，分区测试；坐标跳变另有专门用例。
        self.axis.poll()
        self.assertEqual(self.axis.position_rpm, 100)

    def test_profile_speed_clears_after_arrival_for_base_permission(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.bus.position = self.bus.target
        self.axis.feedback_time = None  # 人工模拟到位，不代表真实运动跳变可放行。
        self.bus.moving = False
        self.bus.od[(0x6041, 0)][2] |= 0x400
        self.axis.poll()
        self.assertFalse(self.axis.busy)
        self.assertEqual(self.axis.position_rpm, 0)

    def test_configuration_rejects_bad_initial_height_or_cap(self):
        for key, value in (('initial_top_height_m', 0), ('initial_top_height_m', -1),
                           ('initial_top_height_m', float('nan')), ('base_moving_max_rpm', 101)):
            with self.subTest(key=key, value=value), self.assertRaises(LiftError):
                LiftConfig(dict(self.params, **{key: value}))


if __name__ == '__main__':
    unittest.main()
