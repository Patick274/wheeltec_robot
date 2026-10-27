#!/usr/bin/env python3
"""Linux/Jetson ROS1终端方向键,默认不使能,不设零,不复位故障."""
import json
import math
import os
import select
import sys
import time

import rospy
from std_msgs.msg import Int8, String
from std_srvs.srv import SetBool, Trigger
from kinco_lift.teleop import ArrowParser


class LiftKeyboard:
    def __init__(self):
        self.ns = rospy.get_param('~lift_namespace', '/lift').rstrip('/')
        self.release_timeout = float(rospy.get_param('~release_timeout_s', 0.25))
        if not math.isfinite(self.release_timeout) or not 0.1 <= self.release_timeout <= 0.3:
            raise ValueError('release_timeout_s must be 0.1..0.3 seconds.')
        self.status, self.status_time = {}, None
        self.direction, self.last_arrow, self.escape_time = 0, None, None
        self.parser = ArrowParser()
        self.pub = rospy.Publisher(self.ns + '/keyboard_command', Int8, queue_size=1)
        self.sub = rospy.Subscriber(self.ns + '/status', String, self.status_cb, queue_size=1)
        self.enable = rospy.ServiceProxy(self.ns + '/enable_keyboard', SetBool)
        self.confirm = rospy.ServiceProxy(self.ns + '/confirm_keyboard_coordinates', Trigger)
        self.halt = rospy.ServiceProxy(self.ns + '/keyboard_stop', Trigger)

    def status_cb(self, msg):
        try:
            state = json.loads(msg.data)
            if not isinstance(state, dict):
                return
            self.status, self.status_time = state, time.monotonic()
        except (ValueError, TypeError):
            pass

    def fresh(self):
        return self.status_time is not None and time.monotonic() - self.status_time <= 0.75

    def neutral(self):
        self.direction, self.last_arrow = 0, None
        self.pub.publish(Int8(data=0))

    def publish_current(self):
        if (not self.fresh() or self.last_arrow is None or
                time.monotonic() - self.last_arrow > self.release_timeout):
            self.direction = 0
        self.pub.publish(Int8(data=self.direction))

    def action(self, action):
        if action in ('up', 'down'):
            state = self.status
            if (not self.fresh() or not state.get('enabled') or
                    state.get('control_mode') != 3 or state.get('stop_latched')):
                self.neutral()
                rospy.logwarn_throttle(2, 'No fresh enabled keyboard session. Confirm coordinates, then press e.')
                return True
            self.direction = 1 if action == 'up' else -1
            self.last_arrow = time.monotonic()
        else:
            self.neutral()
            if action == 'quit':
                try:
                    self.halt()
                except rospy.ServiceException:
                    rospy.logwarn('Stop service unavailable. Use hardware stop if needed.')
                return False
            if action in ('enable', 'confirm'):
                if not self.fresh():
                    rospy.logwarn('No fresh /lift/status; no service request sent.')
                    return True
                if self.status.get('enabled'):
                    rospy.logwarn('Already enabled. c is only for stationary pre-enable confirmation.')
                    return True
                service = self.enable if action == 'enable' else self.confirm
                try:
                    result = service(True) if action == 'enable' else service()
                    rospy.loginfo('%s: %s', result.success, result.message)
                except rospy.ServiceException as exc:
                    rospy.logerr('Keyboard service failed: %s', exc)
            elif action == 'stop':
                try:
                    self.halt()
                except rospy.ServiceException:
                    rospy.logwarn('Stop service unavailable; backend deadman must stop motion. Use hardware stop if needed.')
        return True

    def run(self):
        if os.name != 'posix' or not sys.stdin.isatty():
            raise RuntimeError('Run rosrun lift_keyboard.py in a focused Linux TTY/SSH terminal, not roslaunch.')
        import termios
        import tty
        fd = sys.stdin.fileno()
        original = termios.tcgetattr(fd)
        print('c: confirm lower-limit coordinates (no homing) | e: explicitly enable keyboard mode')
        print('Hold UP/DOWN: lift up/down | SPACE/ESC: stop | q/Ctrl+C: stop and quit')
        print('Key release uses a 0.25s default timeout, NOT a real key-up event or hardware E-stop.')
        print('OS initial key-repeat delay may cause an initial pause. Reverse only after release and standstill.')
        running = True
        try:
            tty.setcbreak(fd)
            while running and not rospy.is_shutdown():
                readable, _, _ = select.select([fd], [], [], 0.05)
                actions = []
                if readable:
                    data = os.read(fd, 64)
                    if not data:
                        break
                    actions = self.parser.feed(data)
                    self.escape_time = time.monotonic() if self.parser.pending else None
                elif self.escape_time is not None and time.monotonic() - self.escape_time > 0.05:
                    actions = self.parser.expire_escape()
                    self.escape_time = None
                for action in actions:
                    if not self.action(action):
                        running = False
                        break
                self.publish_current()
        finally:
            try:
                self.neutral()
                if self.halt.resolved_name:
                    self.halt()
            except (rospy.ROSException, rospy.ServiceException):
                pass
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, original)


if __name__ == '__main__':
    rospy.init_node('lift_keyboard', anonymous=True)
    try:
        LiftKeyboard().run()
    except (KeyboardInterrupt, rospy.ROSInterruptException):
        pass
    except (ValueError, RuntimeError, OSError) as exc:
        rospy.logfatal('Keyboard controller failed: %s', exc)
        raise SystemExit(1)
