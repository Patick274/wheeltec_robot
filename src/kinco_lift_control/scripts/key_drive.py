#!/usr/bin/env python3
"""脚本化键盘心跳: 以10Hz向 /lift/keyboard_command 发布方向(-1/0/+1).

死 mans 开关由节点侧 0.4s 心跳超时保证: 本进程被杀/退出即停.
用法: key_drive.py _dir:=1 _secs:=40   (发布 +1 最长40秒)
"""
import rospy
from std_msgs.msg import Int8


def main():
    rospy.init_node('key_drive', anonymous=True)
    direction = int(rospy.get_param('~dir', 1))
    secs = float(rospy.get_param('~secs', 40))
    assert direction in (-1, 0, 1)
    pub = rospy.Publisher('/lift/keyboard_command', Int8, queue_size=1)
    rate = rospy.Rate(10)
    # enable后节点处于 neutral_required: 先发0.6s空挡解锁, 再发方向.
    t0 = rospy.Time.now()
    while not rospy.is_shutdown() and (rospy.Time.now() - t0).to_sec() < 0.6:
        pub.publish(Int8(0))
        rate.sleep()
    t0 = rospy.Time.now()
    while not rospy.is_shutdown() and (rospy.Time.now() - t0).to_sec() < secs:
        pub.publish(Int8(direction))
        rate.sleep()
    pub.publish(Int8(0))


if __name__ == '__main__':
    main()
