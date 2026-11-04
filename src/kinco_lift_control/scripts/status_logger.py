#!/usr/bin/env python3
"""订阅 /lift/status, 带纪元时间戳落 CSV. 只读, 无CAN交互."""
import json
import time

import rospy
from std_msgs.msg import String

FIELDS = ('position_counts', 'position_mm', 'profile_rpm', 'commanded_rpm',
          'velocity_raw', 'lower_limit', 'upper_limit', 'enabled', 'busy',
          'stop_latched', 'error_status', 'error_status2', 'emcy',
          'motion_budget_remaining_s', 'control_mode', 'keyboard_confirmed',
          'frame_confirmed', 'message')


def main():
    rospy.init_node('status_logger', anonymous=True)
    out_path = rospy.get_param('~out', '/tmp/lift_status.csv')
    out = open(out_path, 'a', buffering=1)
    out.write('epoch,mono,' + ','.join(FIELDS) + '\n')

    def cb(msg):
        try:
            data = json.loads(msg.data)
        except ValueError:
            return
        row = ['{:.3f}'.format(time.time()), '{:.3f}'.format(time.monotonic())]
        for f in FIELDS:
            v = data.get(f)
            row.append('' if v is None else str(v))
        out.write(','.join(row) + '\n')

    rospy.Subscriber('/lift/status', String, cb, queue_size=50, tcp_nodelay=True)
    rospy.spin()


if __name__ == '__main__':
    main()
