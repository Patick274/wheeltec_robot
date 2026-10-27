"""ROS适配层桩测试:验证接口连接,不代表真实ROS/catkin测试通过."""
import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


class Message:
    def __init__(self, data=None):
        self.data = data


class Response:
    def __init__(self, success=True, message='ok'):
        self.success, self.message = success, message
        self.accepted = success


def ros_stubs(params):
    rospy = types.ModuleType('rospy')
    rospy.get_param = lambda name, default=None: params if name == '~' else params.get(name[1:], default)
    for name in ('Publisher', 'Subscriber', 'Service', 'on_shutdown', 'logwarn', 'loginfo',
                 'logwarn_throttle', 'logerr', 'logfatal', 'logerr_throttle'):
        setattr(rospy, name, Mock())
    rospy.Publisher.side_effect = lambda *args, **kwargs: Mock()
    rospy.ServiceException = rospy.ROSException = RuntimeError
    proxies = {}
    def proxy(name, service):
        proxies[name] = Mock(return_value=Response())
        return proxies[name]
    rospy.ServiceProxy = proxy
    modules = {'rospy': rospy}
    groups = {
        'geometry_msgs.msg': ['Twist'], 'nav_msgs.msg': ['Odometry'],
        'std_msgs.msg': ['Bool', 'Float64', 'Int8', 'String', 'UInt64'],
        'std_srvs.srv': ['SetBool', 'SetBoolResponse', 'Trigger', 'TriggerResponse'],
        'kinco_lift_control.srv': ['MoveLift', 'MoveLiftResponse', 'JogLift', 'JogLiftResponse',
                                 'MoveTopHeight', 'MoveTopHeightResponse'],
    }
    for module_name, names in groups.items():
        parent_name = module_name.split('.')[0]
        modules.setdefault(parent_name, types.ModuleType(parent_name))
        module = types.ModuleType(module_name)
        for name in names:
            setattr(module, name, Response if name.endswith('Response') else Message)
        modules[module_name] = module
    return modules, rospy, proxies


def load_script(name):
    spec = importlib.util.spec_from_file_location('test_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NodeWiringTests(unittest.TestCase):
    def setUp(self):
        params = dict(simulate=True, require_base_stationary=False, motion_enabled=True,
                      commissioning_confirmed=True, drive_limits_verified=True,
                      keyboard_control_enabled=True, encoder_counts_per_rev=65536,
                      mm_per_motor_rev=2.25, travel_mm=0, max_motor_rpm=1000,
                      max_speed_mm_s=37.5)
        modules, self.ros, _ = ros_stubs(params)
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.node = load_script('lift_node').LiftNode()

    def tearDown(self):
        self.node.shutdown()
        self.module_patch.stop()

    def test_new_interfaces_registered(self):
        names = [call.args[0] for call in self.ros.Service.call_args_list]
        self.assertIn('~enable_keyboard', names)
        self.assertIn('~confirm_keyboard_coordinates', names)
        self.assertIn('~keyboard_stop', names)
        self.assertIn('~recover_to_lower_limit', names)
        topics = [call.args[0] for call in self.ros.Subscriber.call_args_list]
        self.assertIn('~keyboard_command', topics)

    def test_ros_service_and_topic_to_controller(self):
        self.assertTrue(self.node.confirm_keyboard(None).success)
        self.assertTrue(self.node.enable_keyboard(Message(True)).success)
        self.node.keyboard_cb(Message(0))
        self.node.keyboard_cb(Message(1))
        self.assertEqual(self.node.axis.command_rpm, 1000)
        self.assertTrue(self.node.keyboard_stop(None).success)
        self.assertEqual(self.node.axis.command_rpm, 0)
        self.assertTrue(self.node.axis.armed)

    def test_status_contains_keyboard_and_duty_fields(self):
        self.node.axis.poll()
        self.node.publish()
        payload = self.node.status_pub.publish.call_args.args[0].data
        state = json.loads(payload)
        self.assertTrue(state['simulate'])
        self.assertIn('commanded_rpm', state)
        self.assertIn('motion_budget_remaining_s', state)

    def test_top_height_service_registered_and_converts_metres(self):
        names = [call.args[0] for call in self.ros.Service.call_args_list]
        self.assertIn('~move_top_height', names)
        self.node.cfg.initial_top_height = 0.8
        self.node.cfg.travel = 4190
        self.assertTrue(self.node.enable(Message(True)).success)
        self.assertTrue(self.node.reference(None).success)
        response = self.node.move_top_height(types.SimpleNamespace(target_height_m=1.1))
        self.assertTrue(response.accepted)
        self.assertAlmostEqual(self.node.axis.target_mm, 300, places=4)

    def test_top_height_missing_is_explicitly_rejected(self):
        response = self.node.move_top_height(types.SimpleNamespace(target_height_m=1.1))
        self.assertFalse(response.accepted)
        self.assertIn('initial_top_height_m', response.message)

    def test_nonzero_base_command_caps_keyboard_before_actual_odometry_moves(self):
        self.node.parking.required = True
        self.node.parking.odometry(0, 0, 0)
        self.node.parking.stationary_since -= 2
        self.node.confirm_keyboard(None)
        self.node.enable_keyboard(Message(True))
        self.node.keyboard_cb(Message(0))
        self.node.keyboard_cb(Message(1))
        self.assertEqual(self.node.axis.command_rpm, 1000)
        command = types.SimpleNamespace(linear=types.SimpleNamespace(x=0.1, y=0),
                                        angular=types.SimpleNamespace(z=0))
        self.node.cmd_cb(command)
        self.assertEqual(self.node.axis.command_rpm, 100)
        self.assertTrue(self.node.axis.armed)

    def test_base_request_waits_for_measured_speed_and_does_not_clear_cap(self):
        self.node.confirm_keyboard(None)
        self.node.enable_keyboard(Message(True))
        self.node.keyboard_cb(Message(0))
        self.node.keyboard_cb(Message(1))
        self.node.axis.velocity = self.node.cfg.velocity_raw(1000)
        with patch.object(self.node.axis, 'poll', side_effect=self.node.axis.status):
            response = self.node.request_base_motion(Message(True))
            self.assertFalse(response.success)
            self.assertTrue(self.node.base_motion_requested)
            self.assertEqual(self.node.axis.command_rpm, 100)
            self.node.axis.velocity = self.node.cfg.velocity_raw(100)
            self.assertTrue(self.node.request_base_motion(Message(True)).success)
        self.node.publish()
        self.assertTrue(self.node.base_permission_pub.publish.call_args.args[0].data)

    def test_new_top_height_topic_is_not_published_until_configured(self):
        self.node.axis.poll()
        self.node.publish()
        self.node.top_height_pub.publish.assert_not_called()
        self.node.cfg.initial_top_height = 0.8
        self.node.confirm_keyboard(None)
        self.node.publish()
        self.assertAlmostEqual(self.node.top_height_pub.publish.call_args.args[0].data, 0.8)

    def test_unhealthy_base_still_fault_latches(self):
        self.node.parking.required = True
        self.node.parking.odometry(0, 0, 0)
        self.node.parking.stationary_since -= 2
        self.node.confirm_keyboard(None)
        self.node.enable_keyboard(Message(True))
        self.node.parking.odom_time -= 10
        self.node._run(self.node.axis.apply_speed_limits)
        self.assertTrue(self.node.axis.latched)
        self.assertFalse(self.node.axis.armed)

    def test_invalid_direction_stops_enabled_axis(self):
        self.node.confirm_keyboard(None)
        self.node.enable_keyboard(Message(True))
        self.node.keyboard_cb(Message(2))
        self.assertTrue(self.node.axis.latched)
        self.assertFalse(self.node.axis.armed)


class KeyboardClientTests(unittest.TestCase):
    def setUp(self):
        modules, self.ros, self.proxies = ros_stubs({})
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.client = load_script('lift_keyboard').LiftKeyboard()

    def tearDown(self):
        self.module_patch.stop()

    def status(self, **updates):
        data = dict(enabled=True, control_mode=3, stop_latched=False)
        data.update(updates)
        self.client.status_cb(Message(json.dumps(data)))

    def test_startup_never_enables(self):
        self.assertFalse(self.proxies['/lift/enable_keyboard'].called)
        self.assertFalse(self.proxies['/lift/confirm_keyboard_coordinates'].called)

    def test_arrows_require_fresh_enabled_mode(self):
        self.client.action('up')
        self.assertEqual(self.client.direction, 0)
        self.status()
        self.client.action('up')
        self.assertEqual(self.client.direction, 1)
        self.client.action('down')
        self.assertEqual(self.client.direction, -1)
        self.client.status_time -= 1
        self.client.action('up')
        self.assertEqual(self.client.direction, 0)

    def test_enable_and_confirmation_are_explicit(self):
        self.status(enabled=False)
        self.client.action('confirm')
        self.proxies['/lift/confirm_keyboard_coordinates'].assert_called_once_with()
        self.client.action('enable')
        self.proxies['/lift/enable_keyboard'].assert_called_once_with(True)

    def test_space_and_quit_send_neutral(self):
        self.status()
        self.client.action('up')
        self.client.action('stop')
        self.assertEqual(self.client.direction, 0)
        self.proxies['/lift/keyboard_stop'].assert_called_once_with()
        self.assertFalse(self.client.action('quit'))
        self.assertEqual(self.client.pub.publish.call_args.args[0].data, 0)

    def test_stale_or_faulted_status_cannot_drive(self):
        self.status(stop_latched=True)
        self.client.action('up')
        self.assertEqual(self.client.direction, 0)
        self.status(control_mode=1)
        self.client.action('down')
        self.assertEqual(self.client.direction, 0)

    def test_release_timeout_publishes_zero_without_real_keyup(self):
        self.status()
        self.client.action('up')
        self.client.publish_current()
        self.assertEqual(self.client.pub.publish.call_args.args[0].data, 1)
        self.client.last_arrow -= 1
        self.client.publish_current()
        self.assertEqual(self.client.pub.publish.call_args.args[0].data, 0)

    def test_status_loss_sends_zero_and_fresh_status_alone_does_not_resume(self):
        self.status()
        self.client.action('up')
        self.client.status_time -= 1
        self.client.publish_current()
        self.assertEqual(self.client.direction, 0)
        self.status()
        self.client.publish_current()
        self.assertEqual(self.client.pub.publish.call_args.args[0].data, 0)


if __name__ == '__main__':
    unittest.main()
