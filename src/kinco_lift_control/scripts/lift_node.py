#!/usr/bin/env python3
"""ROS1入口：读取配置、订阅底盘状态、提供升降服务并定期发布反馈。

roslaunch kinco_lift_control lift.launch：实物默认只读。
roslaunch kinco_lift_control lift.launch simulate:=true：内存模拟，不打开CAN。
详细步骤和文件关系见包根目录explain.yaml。
"""
import json
import math
import threading
import time

import rospy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from std_msgs.msg import Bool, Float64, String
from std_srvs.srv import SetBool, SetBoolResponse, Trigger, TriggerResponse
from kinco_lift_control.srv import MoveLift, MoveLiftResponse, JogLift, JogLiftResponse
from kinco_lift.canopen import CanError, SdoClient, SocketCan
from kinco_lift.controller import LiftConfig, LiftController, LiftError
from kinco_lift.interlock import ParkingInterlock
from kinco_lift.simulator import SimulatedCan


class LiftNode:
    """ROS适配层；运动决策委托LiftController，协议收发委托SdoClient。"""
    def __init__(self):
        params = rospy.get_param('~', {})
        self.simulate = bool(params.get('simulate', False))
        self.cfg = LiftConfig(params)
        if not self.simulate and not params.get('require_base_stationary', True):
            raise LiftError('Physical operation requires require_base_stationary=true.')
        self.parking = ParkingInterlock(
            required=bool(params.get('require_base_stationary', True)),
            odom_timeout=params.get('odom_timeout_s', 0.5),
            stationary_s=params.get('base_stationary_s', 1),
            linear_threshold=params.get('base_linear_threshold_m_s', 0.01),
            angular_threshold=params.get('base_angular_threshold_rad_s', 0.02))
        node_id = int(params.get('node_id', 1))
        # simulate是明确的传输层选择；真实模式不会用模拟标定值填补未知参数。
        transport = (SimulatedCan(node_id, self.cfg.counts or 65536,
                                  self.cfg.mm_rev or 2.25, self.cfg.travel or 200, self.cfg.direction)
                     if self.simulate else SocketCan(params.get('can_interface', 'can0')))
        sdo = SdoClient(transport, node_id, float(params.get('sdo_timeout_s', 0.15)))
        self.axis = LiftController(sdo, self.cfg, self.parking.reason)
        self.action_lock = threading.RLock()  # ROS服务线程与轮询线程共享同一控制轴。
        self.closing = False
        self.status_pub = rospy.Publisher('~status', String, queue_size=1, latch=True)
        self.height_pub = rospy.Publisher('~position_mm', Float64, queue_size=1)
        self.busy_pub = rospy.Publisher('~busy', Bool, queue_size=1, latch=True)
        self.odom_sub = rospy.Subscriber(params.get('base_odom_topic', '/odom'),
                                         Odometry, self.odom_cb, queue_size=1)
        self.cmd_sub = rospy.Subscriber(params.get('base_command_topic', '/cmd_vel'),
                                        Twist, self.cmd_cb, queue_size=1)
        # 私有名称~会随launch中的节点名lift展开为/lift/enable等。
        self.services = [
            rospy.Service('~enable', SetBool, self.enable),
            rospy.Service('~stop', Trigger, self.stop),
            rospy.Service('~reset_fault', Trigger, self.reset),
            rospy.Service('~reference_here', Trigger, self.reference),
            rospy.Service('~move', MoveLift, self.move),
            rospy.Service('~jog', JogLift, self.jog)]
        self.poll_hz = float(params.get('poll_hz', 10))
        if not math.isfinite(self.poll_hz) or not 5 <= self.poll_hz <= 20:
            raise LiftError('poll_hz must be between 5 and 20.')
        rospy.on_shutdown(self.shutdown)
        rospy.logwarn('SIMULATION: no physical CAN access.' if self.simulate else
                      'FD125 started disabled. No automatic enable, homing or reconnect.')
        if not self.cfg.motion_enabled:
            rospy.logwarn('READ ONLY: calibrate YAML and verify drive limits before enabling.')

    def odom_cb(self, msg):
        """底盘实测速度回调；默认订阅现有底盘发布的/odom。"""
        t = msg.twist.twist
        self.parking.odometry(t.linear.x, t.linear.y, t.angular.z)

    def cmd_cb(self, msg):
        """底盘速度命令回调；发现非零命令，不等待车轮真正转动才禁止升降。"""
        self.parking.command(msg.linear.x, msg.linear.y, msg.angular.z)

    def _run(self, operation):
        """统一串行服务入口；请求失败时返回原因，已使能轴会进入停机锁定。"""
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
        """SetBool：true显式使能，false在停稳后取消使能。"""
        return SetBoolResponse(*self._run(self.axis.enable if req.data else self.axis.disable))

    def reset(self, req):
        """Trigger：人工复位故障和停止锁存，同时撤销会话零点。"""
        return TriggerResponse(*self._run(self.axis.reset))

    def reference(self, req):
        """Trigger：静止下限位处记零；不是自动找下限位。"""
        return TriggerResponse(*self._run(self.axis.reference_here))

    def move(self, req):
        """MoveLift：height_mm是绝对伸出高度，speed_mm_s是正的线速度。"""
        return MoveLiftResponse(*self._run(lambda: self.axis.move(req.height_mm, req.speed_mm_s)))

    def jog(self, req):
        """JogLift：distance_mm正数上升、负数下降，一次只执行有限步长。"""
        return JogLiftResponse(*self._run(lambda: self.axis.move(req.distance_mm, req.speed_mm_s, jog=True)))

    def stop(self, req):
        """停机回执只说明通信写入结果，实际停稳继续看status/busy。"""
        with self.action_lock:
            confirmed = self.axis.stop()
        message = ('Stop write acknowledged; confirm actual standstill in feedback.'
                   if confirmed else 'Stop not acknowledged (or axis already disabled). Use hardware emergency stop if moving.')
        return TriggerResponse(confirmed, message)

    def publish(self):
        """JSON包含计数、参考、故障与限位；未知毫米高度为null，暂不发布高度话题。"""
        status = self.axis.status()
        status.update(simulate=self.simulate, motion_allowed=self.cfg.motion_enabled,
                      parking_interlock=self.parking.reason())
        self.status_pub.publish(String(data=json.dumps(status, allow_nan=False)))
        self.busy_pub.publish(Bool(data=status['busy']))
        if status['position_mm'] is not None:
            self.height_pub.publish(Float64(data=status['position_mm']))

    def run(self):
        # 用单调墙钟，不依赖ROS /clock；仿真时钟暂停不能让通信监督虚假续期。
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
        """防止ROS重复调用退出回调；退出前请求停机并释放CAN资源。"""
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
