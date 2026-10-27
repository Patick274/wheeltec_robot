"""方向键/速度模式/分区/看门狗测试,全程内存模拟,不打开CAN或ROS."""
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from kinco_lift.canopen import CanError, SdoClient
from kinco_lift.controller import LiftConfig, LiftController, LiftError
from kinco_lift.simulator import SimulatedCan
from kinco_lift.teleop import ArrowParser, MotionBudget, SpeedZones


def config(**changes):
    params = dict(motion_enabled=True, commissioning_confirmed=True,
                  drive_limits_verified=True, encoder_counts_per_rev=65536,
                  mm_per_motor_rev=2.25, travel_mm=0,
                  keyboard_control_enabled=True, max_motor_rpm=1000,
                  max_speed_mm_s=37.5, acceleration_rps_s=100,
                  quick_stop_deceleration_rps_s=610)
    params.update(changes)
    return LiftConfig(params)


class ZoneTests(unittest.TestCase):
    def setUp(self):
        self.z = config().zones

    def test_exact_switch_boundaries_both_directions(self):
        self.assertEqual(self.z.rpm(3060001, -1), -1000)
        self.assertEqual(self.z.rpm(3060000, -1), -100)
        self.assertEqual(self.z.rpm(119389999, 1), 1000)
        self.assertEqual(self.z.rpm(119390000, 1), 100)

    def test_directional_not_spatial_slowdown(self):
        self.assertEqual(self.z.rpm(1000000, 1), 1000)
        self.assertEqual(self.z.rpm(120000000, -1), -1000)

    def test_limit_blocks_only_outward_direction(self):
        self.assertEqual(self.z.rpm(self.z.lower, -1, lower_limit=True), 0)
        self.assertEqual(self.z.rpm(self.z.lower, 1, lower_limit=True), 1000)
        self.assertEqual(self.z.rpm(self.z.upper, 1, upper_limit=True), 0)
        self.assertEqual(self.z.rpm(self.z.upper, -1, upper_limit=True), -1000)

    def test_software_endpoint_inset(self):
        self.assertEqual(self.z.rpm(self.z.lower_stop, -1), 0)
        self.assertEqual(self.z.rpm(self.z.upper_stop, 1), 0)
        self.assertEqual(self.z.rpm(self.z.lower_stop + 1, -1), -100)

    def test_bad_calibration_zones_and_speed_rejected(self):
        for values in (dict(up_direction=-1), dict(encoder_counts_per_rev=0),
                       dict(keyboard_down_slow_counts=0), dict(keyboard_approach_rpm=1001),
                       dict(keyboard_stop_margin_mm=200), dict(keyboard_up_slow_counts=float('nan')),
                       dict(keyboard_down_slow_counts=3060000.5), dict(max_motor_rpm=200),
                       dict(keyboard_command_timeout_s=2)):
            with self.subTest(values=values), self.assertRaises((ValueError, LiftError)):
                config(**values)

    def test_slow_zone_is_about_100mm(self):
        self.assertAlmostEqual((self.z.down_switch - self.z.lower) * 2.25 / 65536, 100, delta=0.02)
        self.assertAlmostEqual((self.z.upper - self.z.up_switch) * 2.25 / 65536, 100, delta=0.02)


class ParserTests(unittest.TestCase):
    def test_arrow_sequences(self):
        self.assertEqual(ArrowParser().feed(b'\x1b[A\x1b[B\x1bOA\x1bOB'), ['up', 'down', 'up', 'down'])

    def test_split_escape(self):
        p = ArrowParser()
        self.assertEqual(p.feed(b'\x1b'), [])
        self.assertEqual(p.feed(b'['), [])
        self.assertEqual(p.feed(b'A'), ['up'])

    def test_other_keys_stop_and_explicit_controls(self):
        self.assertEqual(ArrowParser().feed(b'ce q'), ['confirm', 'enable', 'stop', 'quit'])
        self.assertEqual(ArrowParser().feed(b'\x1b[C'), ['stop'])

    def test_lone_escape_stops(self):
        p = ArrowParser()
        p.feed(b'\x1b')
        self.assertEqual(p.expire_escape(), ['stop'])
        self.assertEqual(p.expire_escape(), [])


class BudgetTests(unittest.TestCase):
    def test_short_stops_do_not_reset_budget(self):
        b = MotionBudget(110, 1080)
        b.update(True, 0)
        b.update(True, 60)
        b.update(False, 60)
        b.update(False, 70)
        b.update(True, 70)
        b.update(True, 120)
        self.assertEqual(b.remaining, 0)

    def test_only_full_rest_restores_budget(self):
        b = MotionBudget(110, 1080)
        b.update(True, 0)
        b.update(False, 110)
        b.update(False, 111)
        b.update(False, 1190)
        self.assertEqual(b.remaining, 0)
        b.update(False, 1191)
        self.assertEqual(b.remaining, 110)

    def test_invalid_limits(self):
        for limit, rest in ((0, 1080), (110, -1), (float('nan'), 1)):
            with self.assertRaises(ValueError):
                MotionBudget(limit, rest)


class KeyboardControllerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.bus = SimulatedCan(travel_mm=(122303105 - 147599) * 2.25 / 65536,
                                lower_counts=147599)
        self.sdo = SdoClient(self.bus, timeout=0.02)
        self.reason = ''
        self.axis = LiftController(self.sdo, self.cfg, lambda: self.reason)

    def tearDown(self):
        self.axis.close()

    def start(self):
        self.axis.confirm_keyboard_coordinates()
        self.axis.enable(keyboard=True)
        self.axis.keyboard_command(0)

    def place(self, position):
        # 测试夹具模拟已经过的行程,不把测试瞬移当作真实反馈.
        self.bus.position = position
        self.axis.feedback_position = position
        self.axis.feedback_time = time.monotonic()

    def test_startup_neutral_and_coordinate_confirmation_are_readonly(self):
        self.axis.keyboard_command(0)
        self.axis.confirm_keyboard_coordinates()
        self.assertTrue(all(data[0] == 0x40 for can_id, data, rtr in self.bus.sent))

    def test_keyboard_needs_explicit_session_confirmation(self):
        with self.assertRaisesRegex(LiftError, 'confirmation'):
            self.axis.enable(keyboard=True)

    def test_confirmation_requires_real_lower_stationary_coordinate(self):
        self.bus.position = 1000000
        with self.assertRaisesRegex(LiftError, 'lower limit'):
            self.axis.confirm_keyboard_coordinates()
        self.bus.lower_counts = self.bus.position = 0
        with self.assertRaisesRegex(LiftError, 'raw frame'):
            self.axis.confirm_keyboard_coordinates()

    def test_keyboard_enable_clears_stale_signed_target_and_never_moves(self):
        self.bus.od[(0x60FF, 0)][2] = -1234567
        self.start()
        self.assertEqual(self.bus.od[(0x6060, 0)][2], 3)
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], 0)
        self.assertFalse(self.bus.moving)
        self.assertEqual(self.bus.od[(0x6085, 0)][2], self.cfg.acceleration_raw(610))

    def test_up_leaves_lower_and_sends_correct_signed_velocity(self):
        self.start()
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 1000)
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], self.cfg.velocity_raw(1000))

    def test_down_blocked_at_lower_needs_neutral_before_exit(self):
        self.start()
        self.axis.keyboard_command(-1)
        self.assertEqual(self.axis.command_rpm, 0)
        self.assertTrue(self.axis.neutral_required)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 0)
        self.axis.keyboard_command(0)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 1000)

    def test_down_velocity_is_negative_and_slow_at_threshold(self):
        self.start()
        self.place(1000000)
        self.axis.keyboard_command(-1)
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], -self.cfg.velocity_raw(100))

    def test_up_slows_and_never_chatters_back_to_fast(self):
        self.start()
        self.place(119390010)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 100)
        self.place(119389900)
        self.axis.key_time = time.monotonic()
        self.axis.poll()
        self.assertEqual(self.axis.command_rpm, 100)

    def test_poll_changes_running_cruise_to_approach(self):
        self.start()
        self.place(10000000)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 1000)
        self.place(119400000)
        self.axis.key_time = time.monotonic()
        self.axis.poll()
        self.assertEqual(self.axis.command_rpm, 100)

    def test_running_downward_uses_negative_cruise_and_approach(self):
        self.start()
        self.place(10000000)
        self.axis.keyboard_command(-1)
        self.assertEqual(self.axis.command_rpm, -1000)
        self.place(3000000)
        self.axis.key_time = time.monotonic()
        self.axis.poll()
        self.assertEqual(self.axis.command_rpm, -100)

    def test_new_enable_requires_neutral(self):
        self.axis.confirm_keyboard_coordinates()
        self.axis.enable(keyboard=True)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 0)
        self.axis.keyboard_command(0)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 1000)

    def test_enabled_drive_mode_change_is_rejected(self):
        self.start()
        self.bus.od[(0x6060, 0)][2] = 1
        with self.assertRaisesRegex(LiftError, 'velocity mode'):
            self.axis.poll()

    def test_both_limits_rejected_without_masking_either(self):
        self.start()
        with patch.object(self.axis, '_limits', return_value=(True, True)):
            with self.assertRaisesRegex(LiftError, 'Both travel'):
                self.axis.poll()

    def test_wrong_feedback_precision_rejected(self):
        self.bus.od[(0x6410, 3)][2] = 10000
        with self.assertRaisesRegex(LiftError, 'precision'):
            self.axis.confirm_keyboard_coordinates()

    def test_motion_permission_gate_still_required_for_keyboard(self):
        self.axis.confirm_keyboard_coordinates()
        self.axis.cfg.motion_enabled = False
        with self.assertRaisesRegex(LiftError, 'Motion locked'):
            self.axis.enable(keyboard=True)
        self.assertFalse(self.bus.enabled)

    def test_neutral_does_not_erase_fault_message(self):
        self.start()
        self.axis.fail('CAN failure')
        self.axis.keyboard_command(0)
        self.assertEqual(self.axis.last_error, 'CAN failure')

    def test_can_loss_does_not_reuse_coordinate_confirmation(self):
        self.start()
        self.bus.drop_replies = True
        with self.assertRaises(CanError):
            self.axis.poll()
        self.axis.fail('CAN lost')
        self.assertFalse(self.axis.keyboard_confirmed)
        self.assertTrue(self.axis.latched)

    def test_reboot_invalidates_keyboard_confirmation(self):
        self.start()
        self.bus.queue.append((0x701, b'\0'))
        with self.assertRaisesRegex(LiftError, 'reboot'):
            self.axis.poll()
        self.assertFalse(self.axis.keyboard_confirmed)

    def test_release_zeroes_velocity_without_disabling(self):
        self.start()
        self.axis.keyboard_command(1)
        self.axis.keyboard_command(0)
        self.axis.poll()
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], 0)
        self.assertTrue(self.axis.armed)
        self.assertTrue(self.bus.enabled)
        self.assertFalse(self.axis.busy)

    def test_key_timeout_stops_and_does_not_resume_from_held_key(self):
        self.start()
        self.axis.keyboard_command(1)
        self.axis.key_time -= 1
        self.axis.poll()
        self.assertEqual(self.axis.command_rpm, 0)
        self.assertTrue(self.axis.neutral_required)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 0)

    def test_reverse_while_moving_requires_release(self):
        self.start()
        self.place(10000000)
        self.axis.keyboard_command(1)
        self.axis.keyboard_command(-1)
        self.assertEqual(self.axis.command_rpm, 0)
        self.assertTrue(self.axis.neutral_required)
        self.axis.keyboard_command(0)
        self.axis.keyboard_command(-1)
        self.assertEqual(self.axis.command_rpm, -1000)

    def test_software_endpoint_stops_even_if_hardware_limit_not_yet_active(self):
        self.start()
        self.place(self.cfg.zones.upper_stop)
        self.axis.keyboard_command(1)
        self.assertEqual(self.axis.command_rpm, 0)
        self.assertFalse(self.axis._limits()[1])
        self.assertTrue(self.axis.neutral_required)

    def test_no_position_services_in_velocity_mode(self):
        self.start()
        self.axis.cfg.travel = 4190
        with self.assertRaisesRegex(LiftError, 'Position services'):
            self.axis.move(0.1, 1, jog=True)

    def test_coordinate_jump_invalidates_session(self):
        self.start()
        self.bus.position = 50000000
        with self.assertRaisesRegex(LiftError, 'coordinate jump'):
            self.axis.poll()
        self.assertFalse(self.axis.keyboard_confirmed)

    def test_error_word_two_not_ignored(self):
        self.start()
        self.bus.od[(0x2602, 0)][2] = 1
        with self.assertRaisesRegex(LiftError, 'fault'):
            self.axis.poll()

    def test_budget_exhaustion_denies_motion_and_survives_reset(self):
        self.start()
        self.axis.budget.used = self.axis.budget.limit
        with self.assertRaisesRegex(LiftError, 'budget'):
            self.axis.poll()
        self.axis.fail('budget exhausted')
        self.axis.poll()
        self.axis.reset()
        self.assertEqual(self.axis.budget.remaining, 0)
        self.assertFalse(self.axis.keyboard_confirmed)

    def test_parking_interlock_and_link_loss_invalidate_keyboard_session(self):
        self.start()
        self.axis.keyboard_command(1)
        self.reason = 'base moving'
        with self.assertRaisesRegex(LiftError, 'base moving'):
            self.axis.poll()
        self.axis.fail('base moving')
        self.assertFalse(self.axis.keyboard_confirmed)
        self.assertFalse(self.axis.armed)


if __name__ == '__main__':
    unittest.main()
