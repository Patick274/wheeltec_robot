#!/usr/bin/env python3
"""P2现场验收辅助:在隔离master下对真实升降做受控操作,全程打印带时间戳的状态时间轴.

直接运行,不经过catkin安装;lift_node 需已在实物模式运行.
用法:
  python3 scripts/field_p2.py watch            # 只读监控(故障指纹/位置/限位), Ctrl-C 结束
  python3 scripts/field_p2.py recover          # 回下限位并重建参考(含resetFault)
  python3 scripts/field_p2.py escape_upper     # 受监督释放上限位,停稳保留使能,不复位/建参考
  python3 scripts/field_p2.py move 50 3        # 位置模式到50mm, 速度3mm/s
  python3 scripts/field_p2.py halt             # 暂停(bit8, 保留使能)
  python3 scripts/field_p2.py stop             # 停机锁存
  python3 scripts/field_p2.py disable          # 停稳后撤使能
  python3 scripts/field_p2.py status           # 打印一次关键状态
经验(2026-10-28实机): 必须 -u 级别无缓冲输出; 不自动重试任何被拒请求.
"""
import json
import sys
import time


def connect():
    import rospy
    from std_msgs.msg import String
    rospy.init_node('field_p2', anonymous=True)
    return rospy, String


class StatusCache:
    """持久订阅 + 接收时间戳;latch话题上新建订阅可能拿到旧快照,wait_for_message 模式已在
    2026-10-28 实机验收中证明会误读 busy(陈旧快照导致提前下发第二个运动指令)."""

    def __init__(self, rospy, String):
        self.rospy = rospy
        self.latest = None
        self.stamp = None
        rospy.Subscriber('/lift/status', String, self._cb, queue_size=1)
        deadline = time.monotonic() + 8
        while self.latest is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.latest is None:
            raise RuntimeError('No /lift/status within 8s; is the lift node running?')

    def _cb(self, msg):
        self.latest = json.loads(msg.data)
        self.stamp = time.monotonic()

    def __call__(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.stamp is not None and time.monotonic() - self.stamp < 0.5:
                return self.latest
            time.sleep(0.05)
        raise RuntimeError('/lift/status went stale')


def fresh_status(rospy, String, cache=None):
    """兼容旧调用:优先用持久缓存,否则临时订阅(可能略旧)."""
    if cache is not None:
        return cache()
    rospy.wait_for_message('/lift/status', String, timeout=8)
    return json.loads(rospy.wait_for_message('/lift/status', String, timeout=5).data)


def show(tag, d):
    pos = d['position_mm']
    print('%s t=%6.1f en=%s busy=%s rec=%s latch=%s counts=%d pos=%s top=%s vel=%.1frpm '
          'sw=0x%04X err=%04X/%04X emcy=%04X budget=%.0fs msg=%.48r' % (
              tag, time.monotonic(), d['enabled'], d['busy'], d['recovering'], d['stop_latched'],
              d['position_counts'], ('%.2f' % pos) if pos is not None else 'None', d['top_height_m'],
              abs(d['velocity_raw']) * 1875 / 512 / 65536, d['statusword'],
              d['error_status'], d['error_status2'], d['emcy'],
              d['motion_budget_remaining_s'], d['message']))


def cmd_watch(rospy, String):
    print('只读监控中, Ctrl-C 结束. 异常位(故障/EMCY/限位变化)会逐行打印.')
    cache = StatusCache(rospy, String)
    last_sig = None
    while True:
        d = cache()
        sig = (d['error_status'], d['error_status2'], d['emcy'], d['statusword'] & 8,
               d['lower_limit'], d['upper_limit'], d['stop_latched'])
        if sig != last_sig:
            show('CHANGE' if last_sig is not None else 'INIT', d)
            last_sig = sig
        time.sleep(0.5)


def cmd_recover(rospy, String):
    from std_srvs.srv import Trigger
    cache = StatusCache(rospy, String)
    d = cache()
    show('start', d)
    if d['stop_latched'] or d['error_status'] or d['error_status2']:
        print('reset_fault ->', rospy.ServiceProxy('/lift/reset_fault', Trigger)().success)
    t0 = time.monotonic()
    r = rospy.ServiceProxy('/lift/recover_to_lower_limit', Trigger)()
    print('recover ->', r.success, '|', r.message)
    if not r.success:
        return 1
    while True:
        time.sleep(0.5)
        d = cache()
        if not d['recovering']:
            break
        if time.monotonic() - t0 > 15:
            print('恢复未确认完成(单次10s, 默认50rpm理论约18.75mm); 请检查状态, 不自动重试.')
            return 1
    show('recovered', d)
    if not d['lower_limit']:
        print('未到下限位, 预算分段设计; 再次运行本命令继续下行')
        return 1
    # 触发下限位后机构弹簧回弹约0.5mm/1s, 立即建参考会因未停稳被拒并锁存.
    print('等待回弹停稳...')
    t0 = time.monotonic()
    while time.monotonic() - t0 < 5:
        d = cache()
        if abs(d['velocity_raw']) * 1875 / 512 / 65536 < 0.5 and d['lower_limit']:
            break
        time.sleep(0.3)
    time.sleep(0.5)
    r = rospy.ServiceProxy('/lift/reference_here', Trigger)()
    print('reference_here ->', r.success, '|', r.message[:60])
    show('referenced', cache())
    return 0 if r.success else 1


def cmd_move(rospy, String, height, speed):
    from kinco_lift_control.srv import MoveLift
    cache = StatusCache(rospy, String)
    r = rospy.ServiceProxy('/lift/move', MoveLift)(height, speed)
    print('move(%s, %s) -> %s | %s' % (height, speed, r.accepted, r.message))
    if not r.accepted:
        return 1
    # 先确认运动真正开始(busy=True), 再等待完成;服务回执到状态发布有<=0.1s延迟.
    t0 = time.monotonic()
    while not cache()['busy']:
        if time.monotonic() - t0 > 2:
            print('busy 未置位, 运动未启动?')
            show('not-started', cache())
            return 1
        time.sleep(0.05)
    while True:
        time.sleep(1.0)
        d = cache()
        show('move', d)
        if not d['busy']:
            return 0
        if time.monotonic() - t0 > 130:
            print('超时未完成')
            return 1


def cmd_escape_upper(rospy, String):
    """只向正式节点申请受监督流程;不打开CAN,不自动复位、续跑或撤使能."""
    from std_srvs.srv import Trigger
    cache = StatusCache(rospy, String)
    r = rospy.ServiceProxy('/lift/escape_upper_limit', Trigger)()
    print('escape_upper ->', r.success, '|', r.message)
    if not r.success:
        return 1
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        d = cache()
        if d['stop_latched'] or d['error_status'] or d['error_status2']:
            show('escape-fault', d)
            return 1
        if d.get('upper_escape_phase') == 'holding':
            show('holding-enabled', d)
            return 0 if d.get('upper_escape_complete', False) else 1
        time.sleep(0.1)
    print('未确认完成; 请求stop, 继续查看节点反馈.')
    rospy.ServiceProxy('/lift/stop', Trigger)()
    return 1


def main(args=None):
    rospy, String = connect()
    args = sys.argv[1:] if args is None else args
    if not args or args[0] == 'status':
        show('status', fresh_status(rospy, String))
        return 0
    if args[0] == 'watch':
        cmd_watch(rospy, String)
        return 0
    if args[0] == 'recover':
        return cmd_recover(rospy, String)
    if args[0] == 'escape_upper':
        return cmd_escape_upper(rospy, String)
    if args[0] == 'move' and len(args) == 3:
        return cmd_move(rospy, String, float(args[1]), float(args[2]))
    if args[0] == 'halt':
        from std_srvs.srv import Trigger
        print('halt ->', rospy.ServiceProxy('/lift/keyboard_stop', Trigger)().success)
        show('halt', fresh_status(rospy, String))
        return 0
    if args[0] == 'stop':
        from std_srvs.srv import Trigger
        print('stop ->', rospy.ServiceProxy('/lift/stop', Trigger)().success)
        show('stop', fresh_status(rospy, String))
        return 0
    if args[0] == 'disable':
        from std_srvs.srv import SetBool
        print('disable ->', rospy.ServiceProxy('/lift/enable', SetBool)(False).success)
        show('disable', fresh_status(rospy, String))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
