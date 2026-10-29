"""底盘反馈健康检查及停车/移动状态;移动可限速,反馈异常仍禁止升降.

这里只决定是否允许升降,不发布底盘速度,也不能阻止其他节点驱动车轮.
"""
import math
import threading
import time


class ParkingInterlock:
    """订阅回调更新状态,控制线程通过reason()获得禁止运动的原因.

    旧的单一阈值把测量噪声和真实微速混为一谈,现分两级使用:
    - 指令deadband: 任何超过此值的指令都视为"有意运动",立即阻止.
    - 实测噪声地板: 低于此值的实测认为是编码器/振动噪声,允许计入静止;
      达到或超过即重置静止时钟——包括噪声地板与运动阈值之间的可疑区间.
    - 明确运动阈值(motion_threshold): 当前只参与 cmd<=noise<=motion 合法性校验,
      没有独立判断分支;可疑区间与明确运动都按未停稳处理,行为等价.
      如需区分两级行为,须先实机采集噪声分布再实现,文档不得超前描述.
    """
    def __init__(self, required=True, odom_timeout=0.5, stationary_s=1.0,
                 linear_threshold=0.005, angular_threshold=0.01,
                 cmd_deadband_linear=0.001, cmd_deadband_angular=0.002,
                 motion_threshold_linear=0.02, motion_threshold_angular=0.05):
        self.required = required
        self.timeout = float(odom_timeout)
        self.dwell = float(stationary_s)
        # 旧参数保留名字,但语义重定义为实测噪声地板.
        self.noise_linear = float(linear_threshold)
        self.noise_angular = float(angular_threshold)
        self.cmd_linear = float(cmd_deadband_linear)
        self.cmd_angular = float(cmd_deadband_angular)
        self.motion_linear = float(motion_threshold_linear)
        self.motion_angular = float(motion_threshold_angular)
        thresholds = (self.timeout, self.dwell,
                      self.noise_linear, self.noise_angular,
                      self.cmd_linear, self.cmd_angular,
                      self.motion_linear, self.motion_angular)
        if not all(math.isfinite(v) and v > 0 for v in thresholds):
            raise ValueError('Parking interlock thresholds/times must be positive.')
        if not (self.cmd_linear <= self.noise_linear <= self.motion_linear
                and self.cmd_angular <= self.noise_angular <= self.motion_angular):
            raise ValueError('Command deadband <= noise floor <= motion threshold required.')
        self.lock = threading.Lock()
        self.odom_time = None
        self.stationary_since = None
        self.command_moving = False
        self.invalid_command = False
        self.invalid_odometry = False

    def _exceeds(self, vx, vy, wz, linear, angular):
        """返回True/False;NaN等非法值返回None,按不安全状态处理."""
        values = (vx, vy, wz)
        if not all(math.isfinite(v) for v in values):
            return None
        return math.hypot(vx, vy) > linear or abs(wz) > angular

    def odometry(self, vx, vy, wz):
        """更新实测速度;中断后恢复的里程计需要重新累计静止时间.

        实测低于噪声地板才算静止候选;高于运动阈值或在噪声地板与阈值之间
        都重置静止时钟——后者是"不确定"区间,不能当作已停稳.
        """
        now = time.monotonic()
        below_noise = self._exceeds(vx, vy, wz, self.noise_linear, self.noise_angular)
        with self.lock:
            if self.odom_time is None or now - self.odom_time > self.timeout:
                self.stationary_since = None
            self.odom_time = now
            self.invalid_odometry = below_noise is None
            if below_noise is False:
                if self.stationary_since is None:
                    self.stationary_since = now
            else:
                self.stationary_since = None

    def command(self, vx, vy, wz):
        """任何超过deadband的指令立即撤销静止确认;零速度不代替实测反馈."""
        moving = self._exceeds(vx, vy, wz, self.cmd_linear, self.cmd_angular)
        with self.lock:
            self.command_moving = moving is True
            self.invalid_command = moving is None
            if moving is not False:
                self.stationary_since = None

    def reason(self):
        """空字符串表示允许;其余字符串可直接显示给操作者."""
        if not self.required:
            return ''
        now = time.monotonic()
        with self.lock:
            if self.odom_time is None or now - self.odom_time > self.timeout:
                return 'Chassis odometry missing/stale; park chassis and start its odometry node.'
            if self.invalid_odometry:
                return 'Chassis odometry is non-finite/invalid.'
            if self.invalid_command or self.command_moving:
                return 'Chassis velocity command is nonzero/invalid.'
            if self.stationary_since is None or now - self.stationary_since < self.dwell:
                return 'Chassis has not remained stationary long enough.'
        return ''

    def health_reason(self):
        """允许边走边低速升降时,仅反馈健康异常是禁止条件."""
        if not self.required:
            return ''
        with self.lock:
            if self.odom_time is None or time.monotonic() - self.odom_time > self.timeout:
                return 'Chassis odometry missing/stale; lift motion prohibited.'
            if self.invalid_odometry or self.invalid_command:
                return 'Chassis odometry/command is non-finite/invalid.'
        return ''

    def speed_limit_rpm(self, stationary_rpm, moving_rpm):
        """实测运动,非零底盘命令或停车尚未稳定,均采用移动限速."""
        if not self.required:
            return stationary_rpm  # 只用于明确的内存模拟.
        now = time.monotonic()
        with self.lock:
            stable = (self.odom_time is not None and now - self.odom_time <= self.timeout
                      and not self.invalid_odometry and not self.invalid_command
                      and not self.command_moving and self.stationary_since is not None
                      and now - self.stationary_since >= self.dwell)
        return stationary_rpm if stable else moving_rpm
