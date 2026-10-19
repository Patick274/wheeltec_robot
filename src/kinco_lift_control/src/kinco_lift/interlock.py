"""底盘停车软件检查：要求里程计新鲜、速度接近零并持续达到指定时间。

这里只决定是否允许升降，不发布底盘速度，也不能阻止其他节点驱动车轮。
"""
import math
import threading
import time


class ParkingInterlock:
    """订阅回调更新状态，控制线程通过reason()获得禁止运动的原因。"""
    def __init__(self, required=True, odom_timeout=0.5, stationary_s=1.0,
                 linear_threshold=0.01, angular_threshold=0.02):
        self.required = required
        self.timeout = float(odom_timeout)
        self.dwell = float(stationary_s)
        self.linear = float(linear_threshold)
        self.angular = float(angular_threshold)
        if min(self.timeout, self.dwell, self.linear, self.angular) <= 0:
            raise ValueError('Parking interlock thresholds/times must be positive.')
        self.lock = threading.Lock()
        self.odom_time = None
        self.stationary_since = None
        self.command_moving = False
        self.invalid_command = False

    def _moving(self, vx, vy, wz):
        """返回True/False；NaN等非法反馈返回None，按不安全状态处理。"""
        values = (vx, vy, wz)
        if not all(math.isfinite(v) for v in values):
            return None
        return math.hypot(vx, vy) > self.linear or abs(wz) > self.angular

    def odometry(self, vx, vy, wz):
        """更新实测速度；中断后恢复的里程计需要重新累计静止时间。"""
        now = time.monotonic()
        moving = self._moving(vx, vy, wz)
        with self.lock:
            if self.odom_time is None or now - self.odom_time > self.timeout:
                self.stationary_since = None
            self.odom_time = now
            if moving is False:
                if self.stationary_since is None:
                    self.stationary_since = now
            else:
                self.stationary_since = None

    def command(self, vx, vy, wz):
        """非零或非法速度指令立即撤销静止确认；零速度不代替实测反馈。"""
        moving = self._moving(vx, vy, wz)
        with self.lock:
            self.command_moving = moving is True
            self.invalid_command = moving is None
            if moving is not False:
                self.stationary_since = None

    def reason(self):
        """空字符串表示允许；其余字符串可直接显示给操作者。"""
        if not self.required:
            return ''
        now = time.monotonic()
        with self.lock:
            if self.odom_time is None or now - self.odom_time > self.timeout:
                return 'Chassis odometry missing/stale; park chassis and start its odometry node.'
            if self.invalid_command or self.command_moving:
                return 'Chassis velocity command is nonzero/invalid.'
            if self.stationary_since is None or now - self.stationary_since < self.dwell:
                return 'Chassis has not remained stationary long enough.'
        return ''
