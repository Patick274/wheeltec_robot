"""单轴升降控制层：单位换算、使能状态机、位置指令、限位及停止锁存。

本层不依赖ROS，既供真实节点调用，也供离线测试调用。
FD125实际位置读6063:00；不自动使能、寻零、清故障、重连或保存EEPROM。
"""
import math
import threading
import time

from .canopen import CanError


class LiftError(RuntimeError):
    pass


def finite(value, label):
    """拒绝NaN和无穷大，防止异常服务输入进入计数/速度计算。"""
    value = float(value)
    if not math.isfinite(value):
        raise LiftError(label + ' must be finite.')
    return value


class LiftConfig:
    """读取参数快照；未知标定值保持0，由validate_motion禁止运动。"""
    def __init__(self, params):
        self.motion_enabled = bool(params.get('motion_enabled', False))
        self.commissioned = bool(params.get('commissioning_confirmed', False))
        self.limits_verified = bool(params.get('drive_limits_verified', False))
        # counts是驱动器有效反馈精度，不一定等于编码器铭牌上的2^位数。
        self.counts = finite(params.get('encoder_counts_per_rev', 0), 'encoder counts')
        self.mm_rev = finite(params.get('mm_per_motor_rev', 0), 'mm per motor rev')
        self.direction = int(params.get('up_direction', 1))
        self.travel = finite(params.get('travel_mm', 0), 'travel')
        self.max_speed = finite(params.get('max_speed_mm_s', 5), 'max speed')
        self.max_rpm = finite(params.get('max_motor_rpm', 200), 'max motor rpm')
        self.accel = finite(params.get('acceleration_rps_s', 1), 'acceleration')
        self.quick_decel = finite(params.get('quick_stop_deceleration_rps_s', 2), 'quick deceleration')
        self.jog_max = finite(params.get('max_jog_mm', 1), 'max jog')
        self.timeout = finite(params.get('motion_timeout_s', 30), 'motion timeout')
        self.tolerance = finite(params.get('position_tolerance_mm', 0.2), 'position tolerance')
        if self.direction not in (-1, 1):
            raise LiftError('up_direction must be +1 or -1.')
        if min(self.max_speed, self.max_rpm, self.accel, self.quick_decel,
               self.jog_max, self.timeout, self.tolerance) <= 0:
            raise LiftError('Speed, acceleration, jog, timeout and tolerance must be positive.')

    def validate_motion(self):
        """同时确认运动许可、调试完成、驱动器限位和有效机械标定。"""
        if not self.motion_enabled or not self.commissioned or not self.limits_verified:
            raise LiftError('Motion locked: verify commissioning/drive limits and enable motion in YAML.')
        if self.counts <= 0 or self.mm_rev <= 0 or self.travel <= 0:
            raise LiftError('Confirm encoder_counts_per_rev, mm_per_motor_rev and travel_mm first.')
        if self.counts != int(self.counts):
            raise LiftError('encoder_counts_per_rev must be an integer.')

    def velocity_raw(self, rpm):
        """rpm -> 驱动器内部速度DEC；不能把rpm数值直接写入6081。"""
        return self._u32(round(finite(rpm, 'rpm') * 512 * self.counts / 1875))

    def acceleration_raw(self, rps_s):
        """电机转/秒² -> 驱动器内部加速度DEC，公式取自手册第7章。"""
        return self._u32(round(finite(rps_s, 'acceleration') * 65536 * self.counts / 4000000))

    @staticmethod
    def _u32(value):
        if not 1 <= value <= 0xFFFFFFFF:
            raise LiftError('Converted speed/acceleration is zero or outside uint32.')
        return value


class LiftController:
    """维护一个轴的会话状态；所有命令串行执行，不排队叠加运动。"""
    def __init__(self, sdo, config, interlock):
        self.sdo, self.cfg, self.interlock = sdo, config, interlock
        self.lock = threading.RLock()
        self.connected = self.armed = self.busy = False
        self.stopping = False  # 已请求停机、但尚未由反馈确认停稳。
        # reference仅存本进程内的下限位计数；重启或异常后不能沿用旧零点。
        self.reference = self.target = self.target_mm = None
        self.position = self.velocity = self.word = self.inputs = self.error_status = 0
        self.last_error = ''
        self.latched = self.guard_active = False
        self.guard_since = self.move_started = None
        self.session_boot = sdo.boot_count
        self.stop_event = threading.Event()
        self.guard_thread = threading.Thread(target=self._guard_loop, daemon=True)
        self.guard_thread.start()

    def _guard_loop(self):
        """每100ms询问节点保护；主控制事务卡住时不继续伪装为正常主站。"""
        while not self.stop_event.wait(0.1):
            if self.guard_active and time.monotonic() - self.sdo.last_io < 0.4:
                try:
                    self.sdo.guard()
                except (CanError, OSError):
                    self.guard_active = False
                    self.sdo.poisoned = True

    def _write(self, index, value, size=2, sub=0, signed=False):
        self.sdo.write(index, value, size=size, sub=sub, signed=signed)

    def _verified_write(self, index, value, size=2, sub=0, signed=False):
        """配置后立即回读；不把CAN发送成功误认为驱动器已采用该配置。"""
        self._write(index, value, size, sub, signed)
        if self.sdo.read(index, sub=sub, size=size, signed=signed) != value:
            raise LiftError('Parameter readback mismatch: {:04X}:{:02X}'.format(index, sub))

    def _wait_word(self, predicate, timeout=0.45):
        """等待状态字达到指定状态；有故障或超时就中止当前操作。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.word = self.sdo.read(0x6041, size=2)
            if self.word & 8:
                raise LiftError('Drive fault, statusword=0x{:04X}'.format(self.word))
            if predicate(self.word):
                return
            time.sleep(0.01)
        raise LiftError('Drive status/setpoint acknowledgement timed out.')

    def _check_interlock(self):
        """调用底盘停车检查器；非空字符串是当前不允许升降的原因。"""
        reason = self.interlock()
        if reason:
            raise LiftError(reason)

    def _height(self, counts):
        """原始计数 -> 相对会话零点的毫米高度；未建零点时返回None。"""
        if self.reference is None or self.cfg.counts <= 0 or self.cfg.mm_rev <= 0:
            return None
        return (counts - self.reference) * self.cfg.mm_rev / self.cfg.counts * self.cfg.direction

    def _limits(self):
        """60FD的bit0/bit1是负/正限位，按电机方向换成物理下/上限位。"""
        negative, positive = bool(self.inputs & 1), bool(self.inputs & 2)
        return (negative, positive) if self.cfg.direction == 1 else (positive, negative)

    def _tolerance_counts(self):
        return max(1, round(self.cfg.tolerance * self.cfg.counts / self.cfg.mm_rev))

    def poll(self):
        """主循环定期读取反馈，同时检查重启、故障、停车条件和定位完成。"""
        with self.lock:
            self.word = self.sdo.read(0x6041, size=2)
            self.position = self.sdo.read(0x6063, signed=True)
            self.inputs = self.sdo.read(0x60FD)
            self.velocity = self.sdo.read(0x606C, signed=True)
            self.error_status = self.sdo.read(0x2601, size=2)
            self.connected = True
            if self.sdo.boot_count != self.session_boot:
                self.reference = None
                raise LiftError('Drive reboot detected; restart and establish reference again.')
            if self.stopping and self.cfg.counts > 0:
                # 停机写入有回执后仍需等反馈；速度阈值约为电机1rpm。
                if not self.word & 4 and abs(self.velocity) <= self.cfg.velocity_raw(1):
                    self.stopping = False
            if self.word & 8 or self.error_status or self.sdo.emcy:
                raise LiftError('Drive fault: SW=0x{:04X}, error=0x{:04X}, EMCY=0x{:04X}'.format(
                    self.word, self.error_status, self.sdo.emcy))
            if self.armed:
                self._check_interlock()
                now = time.monotonic()
                if self.guard_active and now - self.guard_since > 0.5:
                    if self.sdo.guard_time is None or now - self.sdo.guard_time > 0.5:
                        raise LiftError('No fresh toggling node-guard response.')
                if not self.word & 4:
                    raise LiftError('Drive unexpectedly left operation-enabled state.')
            if self.busy:
                delta_up = (self.target - self.position) * self.cfg.direction
                lower, upper = self._limits()
                if (lower and delta_up < -self._tolerance_counts()) or (
                        upper and delta_up > self._tolerance_counts()):
                    raise LiftError('Directional travel limit is active.')
                height = self._height(self.position)
                if height is not None and not -self.cfg.tolerance <= height <= self.cfg.travel + self.cfg.tolerance:
                    raise LiftError('Feedback crossed software travel boundary.')
                if time.monotonic() - self.move_started > self.cfg.timeout:
                    raise LiftError('Motion timeout; no automatic retry.')
                # 到位需同时满足驱动器bit10、位置误差和低速反馈。
                if (self.word & 0x400 and abs(self.target - self.position) <= self._tolerance_counts()
                        and abs(self.velocity) <= self.cfg.velocity_raw(1)):
                    self.busy = False
                    self.target = None
                    self.last_error = ''
            return self.status()

    def enable(self):
        """显式使能：检查条件 -> 关断旧指令 -> 配置 -> 6/7/F状态握手。"""
        with self.lock:
            self.cfg.validate_motion()
            if self.armed:
                raise LiftError('Already enabled.')
            if self.stopping:
                raise LiftError('Stop has not yet been confirmed by feedback.')
            if self.latched or self.sdo.poisoned:
                raise LiftError('Stop/fault latch active; inspect cause and explicitly reset.')
            self._check_interlock()
            self.poll()
            # 先进入运行就绪，避免接管其他软件遗留的运动模式或目标。
            self._write(0x6040, 0x0006)
            self._wait_word(lambda w: w & 0x6F == 0x21)
            self._verified_write(0x6060, 1, size=1, signed=True)
            # 停止策略：快停用6085减速度；禁用/关机采用曲线停止。
            self._verified_write(0x605A, 2, signed=True)
            self._verified_write(0x605B, 1, signed=True)
            self._verified_write(0x605C, 1, signed=True)
            self._verified_write(0x605E, 2, signed=True)
            self._verified_write(0x6083, self.cfg.acceleration_raw(self.cfg.accel), size=4)
            self._verified_write(0x6084, self.cfg.acceleration_raw(self.cfg.accel), size=4)
            self._verified_write(0x6085, self.cfg.acceleration_raw(self.cfg.quick_decel), size=4)
            # 节点保护与heartbeat互斥；200ms*3是驱动器侧监督超时设置。
            self._verified_write(0x1017, 0)
            self._verified_write(0x100C, 200)
            self._verified_write(0x100D, 3, size=1)
            if self.sdo.read(0x100E, size=4) != 0x700 + self.sdo.node_id:
                raise LiftError('Unexpected node-guard COB-ID; restore it in KS3 first.')
            self._verified_write(0x6007, 1, signed=True)
            self.guard_active = True
            self.guard_since = time.monotonic()
            self.sdo.guard_time = self.sdo.guard_toggle = None
            self.sdo.nmt(0x01)
            self.sdo.guard()
            self._wait_word(lambda w: self.sdo.guard_time is not None)
            # 用当前反馈初始化目标，再使能；此处不触发bit4位置运动。
            self._write(0x607A, self.position, size=4, signed=True)
            self._write(0x6040, 0x0007)
            self._wait_word(lambda w: w & 0x6F == 0x23)
            self._check_interlock()
            self._write(0x6040, 0x000F)
            self._wait_word(lambda w: w & 0x6F == 0x27)
            self.armed = True
            self.last_error = ''

    def reference_here(self):
        """在静止下限位处记录0mm；不移动机构、不清编码器、不写原点参数。"""
        with self.lock:
            self.cfg.validate_motion()
            self._check_interlock()
            if self.busy or self.latched:
                raise LiftError('Reference requires a stationary, non-faulted axis.')
            self.poll()
            if not self._limits()[0]:
                raise LiftError('Lower limit must be physically active and configured in KS3.')
            if abs(self.velocity) > self.cfg.velocity_raw(1):
                raise LiftError('Axis is still moving.')
            self.reference = self.position
            self.target_mm = None

    def move(self, value_mm, speed_mm_s, jog=False):
        """开始有限位置运动；jog为相对毫米步长，否则为从零点算起的高度。"""
        with self.lock:
            self.cfg.validate_motion()
            if not self.armed or self.latched or self.busy or self.stopping:
                raise LiftError('Axis must be enabled, idle and free of stop/fault latches.')
            self._check_interlock()
            self.poll()
            value, speed = finite(value_mm, 'distance/height'), finite(speed_mm_s, 'speed')
            if not 0 < speed <= self.cfg.max_speed:
                raise LiftError('Speed outside configured range.')
            if jog:
                # 未记录零点也可做受限调试点动，此时只能依赖已验证的硬件限位。
                if not 0 < abs(value) <= self.cfg.jog_max:
                    raise LiftError('Jog exceeds max_jog_mm or is zero.')
                delta_mm = value
                target = self.position + round(value * self.cfg.counts / self.cfg.mm_rev) * self.cfg.direction
            else:
                # 绝对高度必须有有效会话零点，换算结果仍是电机原始inc。
                if self.reference is None:
                    raise LiftError('No lower reference. Call reference_here at lower limit first.')
                if not 0 <= value <= self.cfg.travel:
                    raise LiftError('Height outside configured travel.')
                delta_mm = value - self._height(self.position)
                target = self.reference + round(value * self.cfg.counts / self.cfg.mm_rev) * self.cfg.direction
            if not -0x80000000 <= target <= 0x7FFFFFFF:
                raise LiftError('Target overflows int32. Never wrap encoder counts.')
            if target == self.position:
                raise LiftError('Move rounds to zero encoder counts.')
            target_height = self._height(target)
            if target_height is not None and not 0 <= target_height <= self.cfg.travel:
                raise LiftError('Target crosses software travel boundary.')
            lower, upper = self._limits()
            if (delta_mm < 0 and lower) or (delta_mm > 0 and upper):
                raise LiftError('Requested direction blocked by active limit.')
            rpm = speed * 60 / self.cfg.mm_rev  # mm/s -> 电机rpm。
            if rpm > self.cfg.max_rpm:
                raise LiftError('Requested speed exceeds max_motor_rpm.')
            if abs(delta_mm) / speed + 2 > self.cfg.timeout:
                raise LiftError('Move exceeds timeout; use smaller steps or verify timeout.')
            # 绝对定位握手：先2F清激活位并等bit12清零，再写速度/目标，
            # 最后3F产生bit4上升沿，等bit12确认接收。此回执不是到位信号。
            self._write(0x6040, 0x002F)
            self._wait_word(lambda w: not w & 0x1000)
            self._write(0x6081, self.cfg.velocity_raw(rpm), size=4)
            self._write(0x607A, target, size=4, signed=True)
            self._check_interlock()
            self._write(0x6040, 0x003F)
            self._wait_word(lambda w: bool(w & 0x1000))
            self.target, self.target_mm = target, target_height
            self.busy = True
            self.move_started = time.monotonic()

    def stop(self, reason='Operator stop'):
        """锁住后续运动并下发000B；返回True只表示停机写入得到SDO回执。"""
        with self.lock:
            was_writing = self.armed or self.guard_active or self.busy
            self.stopping = self.stopping or was_writing
            self.busy = self.armed = False
            self.target = self.target_mm = None
            self.latched = True
            self.last_error = reason
            confirmed = False
            if was_writing:
                try:
                    self._write(0x6040, 0x000B)
                    confirmed = True
                except (CanError, OSError):
                    self.sdo.emergency_stop_unconfirmed()
                    self.guard_active = False
            return confirmed

    def disable(self):
        """确认定位结束/停稳后取消使能；取消后电机可能失去保持力。"""
        with self.lock:
            self.poll()
            if self.busy or self.stopping:
                raise LiftError('Stop first, then confirm stationary before disabling.')
            if self.armed or self.guard_active:
                self._write(0x6040, 0x0006)
                self._wait_word(lambda w: not w & 4)
            self.armed = False

    def reset(self):
        """人工故障复位；保持不使能，撤销旧参考，不恢复被中断的目标。"""
        with self.lock:
            self.cfg.validate_motion()
            self._check_interlock()
            if self.sdo.poisoned:
                raise LiftError('Invalid CAN session. Inspect connection and restart node.')
            if self.stopping:
                self.word = self.sdo.read(0x6041, size=2)
                self.velocity = self.sdo.read(0x606C, signed=True)
                if not self.word & 4 and abs(self.velocity) <= self.cfg.velocity_raw(1):
                    self.stopping = False
            if self.armed or self.busy or self.stopping:
                raise LiftError('Disable axis before resetting.')
            self._write(0x6040, 0x0086)
            self._write(0x6040, 0x0006)
            self.sdo.emcy = 0
            self.latched = False
            self.reference = None
            self.last_error = ''
            self.poll()

    def status(self):
        """供ROS发布的快照；busy也包含尚未确认停稳的stopping阶段。"""
        lower, upper = self._limits()
        return dict(connected=self.connected and not self.sdo.poisoned,
                    enabled=self.armed, busy=self.busy or self.stopping, stopping=self.stopping,
                    referenced=self.reference is not None,
                    position_counts=self.position, position_mm=self._height(self.position),
                    target_mm=self.target_mm, velocity_raw=self.velocity,
                    statusword=self.word, digital_inputs=self.inputs,
                    lower_limit=lower, upper_limit=upper, error_status=self.error_status,
                    emcy=self.sdo.emcy, stop_latched=self.latched, message=self.last_error)

    def fail(self, reason):
        """异常统一入口：撤销零点、记录原因，并尽力请求停机。"""
        self.connected = False
        self.reference = None
        return self.stop(reason)

    def close(self):
        """退出时请求停止、结束节点保护线程并关闭适配器，不自动再次连接。"""
        self.stop('Node shutdown')
        self.guard_active = False
        self.stop_event.set()
        self.guard_thread.join(timeout=0.5)
        self.sdo.transport.close()
