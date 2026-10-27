#!/usr/bin/env python3
"""ROS1入口:读取配置,订阅底盘状态,提供升降服务并定期发布反馈.

roslaunch kinco_lift_control lift.launch:实物默认只读.
roslaunch kinco_lift_control lift.launch simulate:=true:内存模拟,不打开CAN.
详细步骤和文件关系见包根目录explain.yaml.
"""
import json
import math
import threading
import time

import rospy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from std_msgs.msg import Bool, Float64, Int8, String, UInt64
from std_srvs.srv import SetBool, SetBoolResponse, Trigger, TriggerResponse
from kinco_lift_control.srv import MoveLift, MoveLiftResponse, JogLift, JogLiftResponse
from kinco_lift_control.srv import MoveTopHeight, MoveTopHeightResponse
from kinco_lift.canopen import CanError, SdoClient, SocketCan
from kinco_lift.controller import LiftConfig, LiftController, LiftError
from kinco_lift.interlock import ParkingInterlock
from kinco_lift.simulator import SimulatedCan


class LiftNode:
    """ROS适配层;运动决策委托LiftController,协议收发委托SdoClient."""
    def __init__(self):
        params = rospy.get_param('~', {})
        self.simulate = bool(params.get('simulate', False))
        self.cfg = LiftConfig(params)
        require_feedback = bool(params.get('require_base_feedback', params.get('require_base_stationary', True)))
        if not self.simulate and not require_feedback:
            raise LiftError('Physical operation requires fresh chassis feedback.')
        self.allow_moving = bool(params.get('allow_lift_while_base_moving', True))
        self.base_motion_requested = False
        # 自动底盘请求与人工服务分开;心跳丢失撤销许可,但不释放100rpm限制.
        self.base_auto_hold = False
        self.base_request_id = 0
        self.base_request_time = None
        self.parking = ParkingInterlock(
            required=require_feedback,
            odom_timeout=params.get('odom_timeout_s', 0.5),
            stationary_s=params.get('base_stationary_s', 1),
            linear_threshold=params.get('base_linear_noise_m_s', 0.005),
            angular_threshold=params.get('base_angular_noise_rad_s', 0.01),
            cmd_deadband_linear=params.get('base_linear_cmd_deadband_m_s', 0.001),
            cmd_deadband_angular=params.get('base_angular_cmd_deadband_rad_s', 0.002),
            motion_threshold_linear=params.get('base_linear_motion_m_s', 0.02),
            motion_threshold_angular=params.get('base_angular_motion_rad_s', 0.05))
        node_id = int(params.get('node_id', 1))
        # simulate是明确的传输层选择;真实模式不会用模拟标定值填补未知参数.
        transport = (SimulatedCan(node_id, self.cfg.counts or 65536,
                                  self.cfg.mm_rev or 2.25,
                                  ((self.cfg.zones.upper - self.cfg.zones.lower) * self.cfg.mm_rev / self.cfg.counts
                                   if self.cfg.zones else self.cfg.travel or 200), self.cfg.direction,
                                  self.cfg.zones.lower if self.cfg.zones else 0)
                     if self.simulate else SocketCan(params.get('can_interface', 'can0')))
        sdo = SdoClient(transport, node_id, float(params.get('sdo_timeout_s', 0.15)))
        self.axis = LiftController(sdo, self.cfg,
                                   self.parking.health_reason if self.allow_moving else self.parking.reason,
                                   self.current_speed_cap)
        self.action_lock = threading.RLock()  # ROS服务线程与轮询线程共享同一控制轴.
        self.closing = False
        self.status_pub = rospy.Publisher('~status', String, queue_size=1, latch=True)
        self.height_pub = rospy.Publisher('~position_mm', Float64, queue_size=1)
        self.top_height_pub = rospy.Publisher('~top_height_m', Float64, queue_size=1)
        # 不锁存;底盘必须同时检查消息新鲜度,节点退出不能沿用旧许可.
        self.base_permission_pub = rospy.Publisher('~base_motion_permitted', Bool, queue_size=1)
        self.base_permit_pub = rospy.Publisher('~base_motion_permit', UInt64, queue_size=1)
        self.busy_pub = rospy.Publisher('~busy', Bool, queue_size=1, latch=True)
        self.odom_sub = rospy.Subscriber(params.get('base_odom_topic', '/odom'),
                                         Odometry, self.odom_cb, queue_size=1)
        self.cmd_sub = rospy.Subscriber(params.get('base_command_topic', '/cmd_vel'),
                                        Twist, self.cmd_cb, queue_size=1)
        self.base_request_sub = rospy.Subscriber('~base_motion_request', UInt64,
                                                 self.base_request_cb, queue_size=1, tcp_nodelay=True)
        self.keyboard_sub = rospy.Subscriber('~keyboard_command', Int8,
                                             self.keyboard_cb, queue_size=1, tcp_nodelay=True)
        # 私有名称~会随launch中的节点名lift展开为/lift/enable等.
        self.services = [
            rospy.Service('~enable', SetBool, self.enable),
            rospy.Service('~stop', Trigger, self.stop),
            rospy.Service('~reset_fault', Trigger, self.reset),
            rospy.Service('~reference_here', Trigger, self.reference),
            rospy.Service('~recover_to_lower_limit', Trigger, self.recover_to_lower_limit),
            rospy.Service('~move', MoveLift, self.move),
            rospy.Service('~jog', JogLift, self.jog),
            rospy.Service('~enable_keyboard', SetBool, self.enable_keyboard),
            rospy.Service('~confirm_keyboard_coordinates', Trigger, self.confirm_keyboard),
            rospy.Service('~keyboard_stop', Trigger, self.keyboard_stop)]
        self.services.extend([
            rospy.Service('~move_top_height', MoveTopHeight, self.move_top_height),
            rospy.Service('~request_base_motion', SetBool, self.request_base_motion)])
        self.poll_hz = float(params.get('poll_hz', 10))
        if not math.isfinite(self.poll_hz) or not 5 <= self.poll_hz <= 20:
            raise LiftError('poll_hz must be between 5 and 20.')
        rospy.on_shutdown(self.shutdown)
        rospy.logwarn('SIMULATION: no physical CAN access.' if self.simulate else
                      'FD125 started disabled. No automatic enable, homing or reconnect.')
        if not self.cfg.motion_enabled:
            rospy.logwarn('READ ONLY: calibrate YAML and verify drive limits before enabling.')

    def odom_cb(self, msg):
        """底盘实测速度回调;默认订阅现有底盘发布的/odom."""
        t = msg.twist.twist
        self.parking.odometry(t.linear.x, t.linear.y, t.angular.z)
        self._run(self.axis.apply_speed_limits)

    def cmd_cb(self, msg):
        """非零底盘命令立即请求100rpm上限,不等车轮已经开始转动."""
        self.parking.command(msg.linear.x, msg.linear.y, msg.angular.z)
        self._run(self.axis.apply_speed_limits)

    def current_speed_cap(self):
        if self.base_motion_requested or self.base_auto_hold:
            return min(self.cfg.max_rpm, self.cfg.moving_max_rpm)
        return self.parking.speed_limit_rpm(self.cfg.max_rpm, self.cfg.moving_max_rpm)

    def base_request_cb(self, msg):
        """非零序号持续申请低速许可;0只有在底盘确认停稳后才释放自动限速."""
        def request():
            self.base_request_id = int(msg.data)
            self.base_request_time = time.monotonic()
            if self.base_request_id:
                self.base_auto_hold = True
            elif not self.parking.reason():
                self.base_auto_hold = False
            self.axis.apply_speed_limits()
        self._run(request)

    def base_permit_id(self, status):
        if (not self.base_request_id or self.base_request_time is None or
                time.monotonic() - self.base_request_time > 0.3):
            return 0
        return self.base_request_id if self.base_permission(status) else 0

    def request_base_motion(self, req):
        def request():
            self.base_motion_requested = bool(req.data)
            self.axis.apply_speed_limits()
            self.axis.poll()  # 返回许可前必须重新读取实际速度,不能沿用旧的静止读数.
        with self.action_lock:
            accepted, message = self._run(request)
            if accepted and req.data:
                ready = self.base_permission(self.axis.status())
                return SetBoolResponse(ready, 'Base motion permitted under retained 100rpm cap.' if ready else
                                       '100rpm cap requested, but actual speed/health is not ready; do not drive, retry later.')
            return SetBoolResponse(accepted, message)

    def base_permission(self, status):
        if self.cfg.counts <= 0:
            return False
        auto_fresh = (self.base_auto_hold and self.base_request_id and self.base_request_time is not None
                      and time.monotonic() - self.base_request_time <= 0.3)
        requested_rpm = abs(status['commanded_rpm']) if self.axis.control_mode == 3 else status['profile_rpm']
        return bool((self.base_motion_requested or auto_fresh) and status['connected'] and not status['error_status']
                    and not status['error_status2'] and not status['stop_latched']
                    and not self.parking.health_reason()
                    and abs(status['velocity_raw']) <= self.cfg.velocity_raw(self.cfg.moving_max_rpm)
                    and requested_rpm <= self.cfg.moving_max_rpm
                    and (self.allow_moving or not status['enabled']))

    def _run(self, operation):
        """统一串行服务入口;请求失败时返回原因,已使能轴会进入停机锁定."""
        with self.action_lock:
            if self.closing:
                return False, 'Node shutting down.'
            try:
                operation()
                return True, 'Accepted. Inspect /lift/status for completion and faults.'
            except (CanError, OSError, LiftError, ValueError, OverflowError) as exc:
                if self.axis.armed or self.axis.guard_active or self.axis.sdo.poisoned:
                    self.axis.fail(str(exc))
                rospy.logwarn('Lift request rejected: %s', exc)
                return False, str(exc)

    def enable(self, req):
        """SetBool:true显式使能,false在停稳后取消使能."""
        return SetBoolResponse(*self._run(self.axis.enable if req.data else self.axis.disable))

    def reset(self, req):
        """Trigger:人工复位故障和停止锁存,同时撤销会话零点."""
        return TriggerResponse(*self._run(self.axis.reset))

    def enable_keyboard(self, req):
        return SetBoolResponse(*self._run(
            (lambda: self.axis.enable(keyboard=True)) if req.data else self.axis.disable))

    def confirm_keyboard(self, req):
        return TriggerResponse(*self._run(self.axis.confirm_keyboard_coordinates))

    def keyboard_stop(self, req):
        ok, message = self._run(self.axis.operator_halt)
        return TriggerResponse(ok, 'Halt requested; confirm actual standstill in /lift/status.' if ok else message)

    def keyboard_cb(self, msg):
        self._run(lambda: self.axis.keyboard_command(msg.data))

    def reference(self, req):
        """Trigger:静止下限位处记零;不是自动找下限位."""
        return TriggerResponse(*self._run(self.axis.reference_here))

    def recover_to_lower_limit(self, req):
        """Trigger:独立受控恢复;下限位未触发且位置高于参考时,慢速下行至触发."""
        return TriggerResponse(*self._run(self.axis.recover_to_lower_limit))

    def move(self, req):
        """MoveLift:height_mm是绝对伸出高度,speed_mm_s是正的线速度."""
        return MoveLiftResponse(*self._run(lambda: self.axis.move(req.height_mm, req.speed_mm_s)))

    def jog(self, req):
        """JogLift:distance_mm正数上升,负数下降,一次只执行有限步长."""
        return JogLiftResponse(*self._run(lambda: self.axis.move(req.distance_mm, req.speed_mm_s, jog=True)))

    def move_top_height(self, req):
        return MoveTopHeightResponse(*self._run(lambda: self.axis.move_top_height(req.target_height_m)))

    def stop(self, req):
        """停机回执只说明通信写入结果,实际停稳继续看status/busy."""
        with self.action_lock:
            confirmed = self.axis.stop()
        message = ('Stop write acknowledged; confirm actual standstill in feedback.'
                   if confirmed else 'Stop not acknowledged (or axis already disabled). Use hardware emergency stop if moving.')
        return TriggerResponse(confirmed, message)

    def publish(self):
        """JSON包含计数,参考,故障与限位;未知毫米高度为null,暂不发布高度话题."""
        status = self.axis.status()
        actual_limit = (self.cfg.velocity_raw(self.cfg.moving_max_rpm) if self.cfg.counts > 0 else None)
        base_permitted = self.base_permission(status)
        status.update(simulate=self.simulate, motion_allowed=self.cfg.motion_enabled,
                      parking_interlock=(self.parking.health_reason() if self.allow_moving else self.parking.reason()),
                      base_speed_limit_rpm=self.current_speed_cap(),
                      base_motion_requested=self.base_motion_requested,
                      base_auto_hold=self.base_auto_hold,
                      base_request_id=self.base_request_id,
                      base_motion_permitted=base_permitted,
                      base_speed_violation=bool(actual_limit is not None
                                                and self.current_speed_cap() <= self.cfg.moving_max_rpm
                                                and abs(status['velocity_raw']) > actual_limit))
        self.status_pub.publish(String(data=json.dumps(status, allow_nan=False)))
        self.busy_pub.publish(Bool(data=status['busy']))
        self.base_permission_pub.publish(Bool(data=base_permitted))
        self.base_permit_pub.publish(UInt64(data=self.base_permit_id(status)))
        if status['base_speed_violation']:
            rospy.logwarn_throttle(1.0, 'Chassis moving/requested while lift is decelerating above 100rpm. Base must honor permission.')
        if status['position_mm'] is not None:
            self.height_pub.publish(Float64(data=status['position_mm']))
        if status['top_height_m'] is not None:
            self.top_height_pub.publish(Float64(data=status['top_height_m']))

    def run(self):
        # 用单调墙钟,不依赖ROS /clock;仿真时钟暂停不能让通信监督虚假续期.
        while not rospy.is_shutdown():
            started = time.monotonic()
            with self.action_lock:
                try:
                    self.axis.poll()
                except (CanError, OSError, LiftError) as exc:
                    self.axis.fail(str(exc))
                    rospy.logerr_throttle(2.0, 'Lift stopped/locked: %s', exc)
                self.publish()
            time.sleep(max(0, 1 / self.poll_hz - (time.monotonic() - started)))

    def shutdown(self):
        """防止ROS重复调用退出回调;退出前请求停机并释放CAN资源."""
        with self.action_lock:
            if not self.closing:
                self.closing = True
                self.axis.close()


if __name__ == '__main__':
    rospy.init_node('lift')
    try:
        LiftNode().run()
    except (CanError, OSError, LiftError, ValueError) as exc:
        rospy.logfatal('Lift startup failed: %s', exc)
        raise SystemExit(1)
