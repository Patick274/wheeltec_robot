"""前三项审查问题的回归;仅使用内存CAN及ROS桩,不连接硬件."""
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
import test_base_height as base
import test_ros_wiring as wiring
from kinco_lift.controller import LiftError
from kinco_lift.canopen import CanError


class ControllerP1Tests(unittest.TestCase):
    setUp = base.HeightAndSpeedTests.setUp
    tearDown = base.HeightAndSpeedTests.tearDown
    start_position = base.HeightAndSpeedTests.start_position

    def test_shifted_lower_frame_rejected_in_position_mode(self):
        self.bus.lower_counts = self.bus.position = 50000000
        with self.assertRaisesRegex(LiftError, 'raw frame'):
            self.axis.reference_here()
        self.assertIsNone(self.axis.reference)
        self.assertFalse(self.axis.frame_confirmed)
        self.assertFalse(self.bus.moving)

    def test_precision_mismatch_cannot_establish_position_reference(self):
        self.bus.od[(0x6410, 3)][2] = 131072
        with self.assertRaisesRegex(LiftError, 'precision'):
            self.axis.reference_here()
        self.assertIsNone(self.axis.reference)

    def test_jog_cannot_bypass_frame_confirmation(self):
        self.axis.enable()
        with self.assertRaisesRegex(LiftError, 'raw-coordinate frame'):
            self.axis.move(0.5, 1, jog=True)
        self.assertFalse(self.bus.moving)

    def test_position_mode_detects_encoder_jump(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.bus.position += 10000000
        with self.assertRaisesRegex(LiftError, 'jump'):
            self.axis.poll()
        self.assertFalse(self.axis.frame_confirmed)
        self.assertIsNone(self.axis.reference)

    def test_position_mode_detects_precision_change(self):
        self.start_position()
        self.bus.od[(0x6410, 3)][2] = 131072
        with self.assertRaisesRegex(LiftError, 'precision'):
            self.axis.poll()
        self.assertIsNone(self.axis.reference)

    def test_position_halt_stops_and_keeps_enabled(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.axis.operator_halt()
        self.assertTrue(self.axis.busy)
        self.assertTrue(self.axis.position_halted)
        self.assertFalse(self.bus.moving)
        self.assertTrue(self.bus.enabled)
        self.assertIsNone(self.axis.target)
        self.assertEqual(self.bus.od[(0x6040, 0)][2], 0x12F)
        self.assertEqual(self.bus.od[(0x605D, 0)][2], 2)
        self.axis.poll()
        self.assertFalse(self.axis.busy)
        self.assertTrue(self.axis.armed)
        self.axis.keyboard_command(0)
        self.assertTrue(self.axis.position_halted)
        self.assertFalse(self.bus.moving)

    def test_new_target_loaded_before_releasing_halt(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.axis.operator_halt()
        self.axis.poll()
        sent = len(self.bus.sent)
        self.axis.move_top_height(0.9)
        writes = [(int.from_bytes(data[1:3], 'little'), data[4:])
                  for can_id, data, rtr in self.bus.sent[sent:]
                  if not rtr and can_id == 0x601 and data[0] != 0x40]
        controls = [int.from_bytes(data[:2], 'little') for index, data in writes if index == 0x6040]
        self.assertEqual(controls, [0x12F, 0x3F])
        target_i = next(i for i, (index, data) in enumerate(writes) if index == 0x607A)
        resume_i = next(i for i, (index, data) in enumerate(writes)
                        if index == 0x6040 and int.from_bytes(data[:2], 'little') == 0x3F)
        self.assertLess(target_i, resume_i)
        self.assertTrue(self.bus.moving)
        self.assertAlmostEqual(self.axis.target_mm, 100, places=4)

    def test_halt_timeout_is_fault_not_false_idle(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.axis.operator_halt()
        self.axis.halt_started -= 3
        original = self.axis.sdo.read
        def read(index, *args, **kwargs):
            return self.cfg.velocity_raw(50) if index == 0x606C else original(index, *args, **kwargs)
        with patch.object(self.axis.sdo, 'read', side_effect=read):
            with self.assertRaisesRegex(LiftError, 'halt'):
                self.axis.poll()
        self.assertTrue(self.axis.busy)

    def test_halt_feedback_lag_keeps_busy_and_base_callback_works(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.axis.operator_halt()
        started = self.axis.halt_started
        self.axis.operator_halt()
        self.assertEqual(self.axis.halt_started, started)
        original = self.axis.sdo.read
        def read(index, *args, **kwargs):
            return self.cfg.velocity_raw(50) if index == 0x606C else original(index, *args, **kwargs)
        with patch.object(self.axis.sdo, 'read', side_effect=read):
            self.axis.poll()
            self.cap = 100
            self.axis.apply_speed_limits()
            self.assertTrue(self.axis.busy)
        self.axis.poll()
        self.assertFalse(self.axis.busy)

    def test_small_lower_reference_variation_is_accepted(self):
        self.bus.lower_counts += 6000
        self.bus.position = self.bus.lower_counts
        self.axis.reference_here()
        self.assertTrue(self.axis.frame_confirmed)
        self.assertEqual(self.axis.reference, self.bus.lower_counts)

    def test_disabled_session_also_invalidates_coordinate_jump(self):
        self.start_position()
        self.axis.disable()
        self.bus.position += 10000000
        with self.assertRaisesRegex(LiftError, 'jump'):
            self.axis.poll()
        self.assertFalse(self.axis.frame_confirmed)

    def test_position_mode_detects_6061_mode_change(self):
        """位置模式运行中驱动器6061被外部改动必须撤销任务并报错;键盘模式已有此保护."""
        self.start_position()
        self.axis.move_top_height(1.1)
        self.assertTrue(self.axis.busy)
        original = self.axis.sdo.read
        def read(index, *args, **kwargs):
            return 7 if index == 0x6061 else original(index, *args, **kwargs)
        with patch.object(self.axis.sdo, 'read', side_effect=read):
            with self.assertRaisesRegex(LiftError, 'mode'):
                self.axis.poll()

    def test_position_mode_6061_still_checked_during_halt(self):
        """位置暂停期间6061被改也要检测;不能只核验运动中的轮询."""
        self.start_position()
        self.axis.move_top_height(1.1)
        self.axis.operator_halt()
        original = self.axis.sdo.read
        def read(index, *args, **kwargs):
            return 7 if index == 0x6061 else original(index, *args, **kwargs)
        with patch.object(self.axis.sdo, 'read', side_effect=read):
            with self.assertRaisesRegex(LiftError, 'mode'):
                self.axis.poll()

    def test_lower_inset_recovery_deadlock(self):
        """正常内缩5mm停车后重启,下限位未触发;reference_here失败,jog向下被inset拦截,
        形成死结.需要独立的受控恢复流程,不能屏蔽硬限位或扩大普通行程."""
        inset_counts = round(5 * 65536 / 2.25)
        self.bus.position = 147599 + inset_counts
        self.axis.poll()
        lower, _ = self.axis._limits()
        self.assertFalse(lower)
        with self.assertRaisesRegex(LiftError, 'lower limit'):
            self.axis.reference_here()
        self.axis.enable()
        with self.assertRaisesRegex(LiftError, 'inset|frame'):
            self.axis.move(-1, 1, jog=True)
        self.axis.disable()

    def test_recover_to_lower_limit_enables_reference(self):
        """恢复流程应慢速下行至下限位触发,停稳后可正常建立参考."""
        inset_counts = round(5 * 65536 / 2.25)
        self.bus.position = 147599 + inset_counts
        self.axis.poll()
        self.axis.recover_to_lower_limit()
        lower, _ = self.axis._limits()
        self.assertTrue(lower)
        self.assertFalse(self.bus.moving)
        self.axis.reference_here()
        self.assertTrue(self.axis.frame_confirmed)
        self.assertIsNotNone(self.axis.reference)


class NodeP1Tests(unittest.TestCase):
    setUp = wiring.NodeWiringTests.setUp
    tearDown = wiring.NodeWiringTests.tearDown

    def stationary(self):
        self.node.parking.required = True
        self.node.parking.odometry(0, 0, 0)
        self.node.parking.stationary_since -= 2

    def test_keyboard_stop_reaches_position_task(self):
        self.node.cfg.travel = 4190
        self.node.cfg.initial_top_height = 0.8
        self.node.enable(wiring.Message(True))
        self.node.reference(None)
        self.node.move_top_height(types.SimpleNamespace(target_height_m=1.1))
        reply = self.node.keyboard_stop(None)
        self.assertTrue(reply.success)
        self.assertFalse(self.node.axis.sdo.transport.moving)
        self.assertTrue(self.node.axis.armed)
        self.assertIsNone(self.node.axis.target)

    def test_sequence_permit_waits_for_actual_slow_feedback(self):
        self.stationary()
        self.node.confirm_keyboard(None)
        self.node.enable_keyboard(wiring.Message(True))
        self.node.keyboard_cb(wiring.Message(0))
        self.node.keyboard_cb(wiring.Message(1))
        self.node.axis.velocity = self.node.cfg.velocity_raw(1000)
        self.node.base_request_cb(wiring.Message(123))
        self.assertEqual(self.node.axis.command_rpm, 100)
        self.assertEqual(self.node.base_permit_id(self.node.axis.status()), 0)
        self.node.axis.velocity = self.node.cfg.velocity_raw(100)
        self.assertEqual(self.node.base_permit_id(self.node.axis.status()), 123)
        self.node.base_request_time -= 1
        self.assertEqual(self.node.base_permit_id(self.node.axis.status()), 0)
        self.assertFalse(self.node.base_permission(self.node.axis.status()))
        self.assertEqual(self.node.current_speed_cap(), 100)

    def test_false_manual_request_cannot_release_auto_cap(self):
        self.stationary()
        self.node.base_request_cb(wiring.Message(123))
        self.node.request_base_motion(wiring.Message(False))
        self.assertEqual(self.node.current_speed_cap(), 100)
        self.node.base_request_cb(wiring.Message(0))
        self.assertFalse(self.node.base_auto_hold)
        self.assertEqual(self.node.current_speed_cap(), 1000)

    def test_release_while_moving_retains_cap_but_revokes_permit(self):
        self.stationary()
        self.node.base_request_cb(wiring.Message(123))
        self.node.parking.odometry(0.1, 0, 0)
        self.node.base_request_cb(wiring.Message(0))
        self.assertTrue(self.node.base_auto_hold)
        self.assertEqual(self.node.current_speed_cap(), 100)
        self.assertEqual(self.node.base_permit_id(self.node.axis.status()), 0)

    def test_fault_revokes_sequence_permit(self):
        self.stationary()
        self.node.base_request_cb(wiring.Message(123))
        self.node.axis.poll()
        self.assertEqual(self.node.base_permit_id(self.node.axis.status()), 123)
        self.node.axis.fail('test fault')
        self.assertEqual(self.node.base_permit_id(self.node.axis.status()), 0)

    def test_halt_write_failure_reported_and_fault_latched(self):
        self.node.cfg.travel = 4190
        self.node.enable(wiring.Message(True))
        with patch.object(self.node.axis, '_write', side_effect=CanError('test SDO failure')):
            self.assertFalse(self.node.keyboard_stop(None).success)
        self.assertTrue(self.node.axis.latched)
