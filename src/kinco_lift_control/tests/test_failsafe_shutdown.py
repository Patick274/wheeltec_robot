"""2026-10-27事故回归:节点崩溃退出时驱动器残留mode3+60FF,机构无人上漂60mm.

崩溃路径不经过rospy.on_shutdown(signal_shutdown不运行),修复靠atexit兜底:
LiftNode.failsafe_shutdown -> LiftController.failsafe_halt,清零速度指令并关断驱动器.
复盘(2026-10-28)补充:纯只读未接管的会话退出不写驱动器;SDO会话失效时
降级为单向尽力发送;atexit覆盖不到SIGKILL/os._exit/断电,那些靠驱动器节点保护.
全部使用内存CAN及ROS桩,不连接硬件.
"""
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
import test_base_height as base
import test_keyboard as keyboard
import test_ros_wiring as wiring
from kinco_lift.canopen import CanError


class FailsafeKeyboardTests(unittest.TestCase):
    """速度模式(mode 3)崩溃现场:60FF非零,驱动器仍使能."""

    setUp = keyboard.KeyboardControllerTests.setUp
    tearDown = keyboard.KeyboardControllerTests.tearDown
    start = keyboard.KeyboardControllerTests.start

    def test_crash_exit_zeroes_velocity_and_shuts_down_drive(self):
        self.start()
        self.axis.keyboard_command(1)
        self.assertNotEqual(self.bus.od[(0x60FF, 0)][2], 0)
        self.assertTrue(self.bus.enabled)
        self.axis.failsafe_halt()
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], 0)
        self.assertEqual(self.bus.od[(0x6040, 0)][2], 6)
        self.assertFalse(self.bus.enabled)
        self.assertFalse(self.bus.moving)

    def test_readonly_exit_never_touches_drive(self):
        """纯只读未接管会话退出不写驱动器;遗留使能由显式接管/恢复流程处理,禁止自动续跑."""
        self.assertFalse(self.axis.took_control)
        self.axis.poll()
        sent = len(self.bus.sent)
        self.axis.failsafe_halt()
        self.assertEqual(len(self.bus.sent), sent)

    def test_failed_mid_enable_is_still_covered(self):
        """使能握手中途失败:armed尚未置位但已接管,崩溃退出仍要清零关断."""
        self.axis.confirm_keyboard_coordinates()
        original = self.axis.sdo.write
        def fail_at_accel(index, *args, **kwargs):
            if index == 0x6083:
                raise CanError('test mid-enable failure')
            return original(index, *args, **kwargs)
        with patch.object(self.axis.sdo, 'write', side_effect=fail_at_accel):
            with self.assertRaises(CanError):
                self.axis.enable(keyboard=True)
        self.assertFalse(self.axis.armed)
        self.assertTrue(self.axis.took_control)
        self.axis.failsafe_halt()
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], 0)
        self.assertEqual(self.bus.od[(0x6040, 0)][2], 6)

    def test_poisoned_session_still_emits_both_frames(self):
        """会话poisoned时普通SDO在发送前被拒绝;两帧必须经单向兜底真正发出."""
        self.start()
        self.axis.keyboard_command(1)
        self.bus.drop_replies = True
        self.axis.failsafe_halt()
        self.assertTrue(self.axis.sdo.poisoned)  # 兜底不清除失效标记.
        writes = [(data[1] | data[2] << 8, int.from_bytes(data[4:], 'little', signed=True))
                  for can_id, data, rtr in self.bus.sent
                  if not rtr and can_id == 0x601 and data[0] in (0x23, 0x2B)]
        self.assertIn((0x60FF, 0), writes)
        self.assertIn((0x6040, 6), writes)
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], 0)
        self.assertEqual(self.bus.od[(0x6040, 0)][2], 6)

    def test_failsafe_after_clean_close_is_silent(self):
        """正常退出close已获停机回执,兜底不得重复写或复活已关闭的传输."""
        self.start()
        self.axis.keyboard_command(1)
        self.axis.close()
        sent = len(self.bus.sent)
        self.axis.failsafe_halt()
        self.assertEqual(len(self.bus.sent), sent)

    def test_unconfirmed_close_still_gets_failsafe_attempt(self):
        """close的停机写入未获回执(poisoned)时,atexit仍经单向兜底补发清零/关断."""
        self.start()
        self.axis.keyboard_command(1)
        self.bus.drop_replies = True
        self.axis.close()
        self.assertFalse(self.axis.stop_confirmed)
        self.axis.failsafe_halt()
        writes = [(data[1] | data[2] << 8, int.from_bytes(data[4:], 'little', signed=True))
                  for can_id, data, rtr in self.bus.sent
                  if not rtr and can_id == 0x601 and data[0] in (0x23, 0x2B)]
        self.assertIn((0x60FF, 0), writes)
        self.assertIn((0x6040, 6), writes)

    def test_clean_close_disarms_guard_supervision(self):
        """干净退出撤防节点保护(100C=0),重启不再留下CAN中断故障;崩溃路径绝不撤防."""
        self.start()
        self.axis.keyboard_command(1)
        self.axis.close()
        self.assertEqual(self.bus.od[(0x100C, 0)][2], 0)
        self.bus.last_guard -= 10  # 干净退出后经过再久也不应触发看门狗故障.
        self.bus._step()
        self.assertFalse(self.bus.od[(0x2602, 0)][2] & 0x0002)


class FailsafePositionTests(unittest.TestCase):
    """位置模式(mode 1)崩溃现场:驱动器使能中,定位任务未完成."""

    setUp = base.HeightAndSpeedTests.setUp
    tearDown = base.HeightAndSpeedTests.tearDown
    start_position = base.HeightAndSpeedTests.start_position

    def test_position_move_crash_exit_disables_drive(self):
        self.start_position()
        self.axis.move_top_height(1.1)
        self.assertTrue(self.bus.moving)
        self.axis.failsafe_halt()
        self.assertEqual(self.bus.od[(0x60FF, 0)][2], 0)
        self.assertEqual(self.bus.od[(0x6040, 0)][2], 6)
        self.assertFalse(self.bus.enabled)
        self.assertFalse(self.bus.moving)


class NodeFailsafeTests(unittest.TestCase):
    setUp = wiring.NodeWiringTests.setUp
    tearDown = wiring.NodeWiringTests.tearDown

    def test_atexit_failsafe_is_registered_at_construction(self):
        with patch('atexit.register') as register:
            node = wiring.load_script('lift_node').LiftNode()
        try:
            self.assertTrue(any(call.args[0] == node.failsafe_shutdown
                                for call in register.call_args_list))
        finally:
            node.shutdown()

    def test_crash_bypassing_ros_shutdown_still_halts_drive(self):
        """测试中rospy.on_shutdown是Mock不会运行;直接调用atexit兜底模拟崩溃退出."""
        self.node.confirm_keyboard(None)
        self.node.enable_keyboard(wiring.Message(True))
        self.node.keyboard_cb(wiring.Message(0))
        self.node.keyboard_cb(wiring.Message(1))
        bus = self.node.axis.sdo.transport
        self.assertNotEqual(bus.od[(0x60FF, 0)][2], 0)
        self.node.failsafe_shutdown()
        self.assertEqual(bus.od[(0x60FF, 0)][2], 0)
        self.assertEqual(bus.od[(0x6040, 0)][2], 6)
        self.assertFalse(bus.enabled)


if __name__ == '__main__':
    unittest.main()
