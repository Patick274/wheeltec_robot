"""单轴升降控制层:单位换算,使能状态机,位置指令,限位及停止锁存.

本层不依赖ROS,既供真实节点调用,也供离线测试调用.
FD125实际位置读6063:00;不自动使能,寻零,清故障,重连或保存EEPROM.
"""
import math
import threading
import time

from .canopen import CanError
from .teleop import MotionBudget, SpeedZones


class LiftError(RuntimeError):
    pass


def finite(value, label):
    """拒绝NaN和无穷大,防止异常服务输入进入计数/速度计算."""
    value = float(value)
    if not math.isfinite(value):
        raise LiftError(label + ' must be finite.')
    return value


class LiftConfig:
    """读取参数快照;未知标定值保持0,由validate_motion禁止运动."""
    def __init__(self, params):
        self.motion_enabled = bool(params.get('motion_enabled', False))
        self.commissioned = bool(params.get('commissioning_confirmed', False))
        self.limits_verified = bool(params.get('drive_limits_verified', False))
        # counts是驱动器有效反馈精度,不一定等于编码器铭牌上的2^位数.
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
        self.keyboard_enabled = bool(params.get('keyboard_control_enabled', False))
        self.keyboard_timeout = finite(params.get('keyboard_command_timeout_s', 0.4), 'keyboard timeout')
        self.coordinate_tolerance = finite(params.get('keyboard_reference_tolerance_mm', 1), 'reference tolerance')
        self.budget_seconds = finite(params.get('motion_budget_s', 110), 'motion budget')
        self.cooldown_seconds = finite(params.get('motion_cooldown_s', 1080), 'cooldown')
        self.moving_max_rpm = finite(params.get('base_moving_max_rpm', 100), 'moving-base cap')
        initial_height = params.get('initial_top_height_m')
        self.initial_top_height = (None if initial_height is None else
                                   finite(initial_height, 'initial top height'))
        if self.initial_top_height is not None and self.initial_top_height <= 0:
            raise LiftError('initial_top_height_m must be positive, or null until measured.')
        if not 0 < self.moving_max_rpm <= 100:
            raise LiftError('base_moving_max_rpm must be positive and cannot exceed 100 rpm.')
        self.zones = (SpeedZones(params, self.counts, self.mm_rev, self.direction)
                      if self.keyboard_enabled or params.get('speed_zones_enabled', False) else None)
        if self.direction not in (-1, 1):
            raise LiftError('up_direction must be +1 or -1.')
        if min(self.max_speed, self.max_rpm, self.accel, self.quick_decel,
               self.jog_max, self.timeout, self.tolerance) <= 0:
            raise LiftError('Speed, acceleration, jog, timeout and tolerance must be positive.')
        if not 0.1 <= self.keyboard_timeout <= 0.5 or self.coordinate_tolerance <= 0:
            raise LiftError('Keyboard timeout must be 0.1..0.5s and reference tolerance positive.')
        if self.zones and (self.zones.fast > self.max_rpm
                           or self.zones.fast * self.mm_rev / 60 > self.max_speed):
            raise LiftError('Keyboard cruise speed exceeds configured speed cap.')

    def validate_motion(self, require_travel=True):
        """同时确认运动许可,调试完成,驱动器限位和有效机械标定."""
        if not self.motion_enabled or not self.commissioned or not self.limits_verified:
            raise LiftError('Motion locked: verify commissioning/drive limits and enable motion in YAML.')
        if self.counts <= 0 or self.mm_rev <= 0 or (require_travel and self.travel <= 0):
            raise LiftError('Confirm encoder_counts_per_rev, mm_per_motor_rev and travel_mm first.')
        if self.counts != int(self.counts):
            raise LiftError('encoder_counts_per_rev must be an integer.')

    def velocity_raw(self, rpm):
        """rpm -> 驱动器内部速度DEC;不能把rpm数值直接写入6081."""
        return self._u32(round(finite(rpm, 'rpm') * 512 * self.counts / 1875))

    def acceleration_raw(self, rps_s):
        """电机转/秒² -> 驱动器内部加速度DEC,公式取自手册第7章."""
        return self._u32(round(finite(rps_s, 'acceleration') * 65536 * self.counts / 4000000))

    @staticmethod
    def _u32(value):
        if not 1 <= value <= 0xFFFFFFFF:
            raise LiftError('Converted speed/acceleration is zero or outside uint32.')
        return value


class LiftController:
    """维护一个轴的会话状态;所有命令串行执行,不排队叠加运动."""
    def __init__(self, sdo, config, interlock, speed_limit=None):
        self.sdo, self.cfg, self.interlock = sdo, config, interlock
        self.speed_limit = speed_limit or (lambda: self.cfg.max_rpm)
        self.lock = threading.RLock()
        self.connected = self.armed = self.busy = False
        self.stopping = False  # 已请求停机,但尚未由反馈确认停稳.
        # reference仅存本进程内的下限位计数;重启或异常后不能沿用旧零点.
        self.reference = self.target = self.target_mm = None
        self.position = self.velocity = self.word = self.inputs = self.error_status = 0
        self.last_error = ''
        self.latched = self.guard_active = False
        self.guard_since = self.move_started = None
        self.session_boot = sdo.boot_count
        self.control_mode = 1
        self.error_status2 = 0
        self.keyboard_confirmed = False
        self.frame_confirmed = False
        self.position_halting = self.position_halted = False
        self.halt_started = None
        self.key_direction = 0
        self.key_time = None
        self.neutral_required = True
        self.slow_latched = False
        self.command_rpm = 0
        self.position_rpm = 0
        # 回下限位恢复是poll监督的明确状态,不是持锁的同步循环.
        self.recovering = False
        self.recover_deadline = self.recover_start = None
        self.recover_velocity = 0
        self.budget = MotionBudget(config.budget_seconds, config.cooldown_seconds)
        self.feedback_position = self.feedback_time = None
        self.stop_event = threading.Event()
        self.closed = False
        # 接管标志:本会话首次试图改变驱动器状态之前置位;纯只读会话退出不得写驱动器.
        self.took_control = False
        # 只记录close路径的停机回执,不代表电机已停稳;停稳只能由反馈确认.
        self.stop_confirmed = False
        self.guard_thread = threading.Thread(target=self._guard_loop, daemon=True)
        self.guard_thread.start()

    def _guard_loop(self):
        """每100ms询问节点保护;主控制事务卡住时不继续伪装为正常主站."""
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
        """配置后立即回读;不把CAN发送成功误认为驱动器已采用该配置."""
        self._write(index, value, size, sub, signed)
        if self.sdo.read(index, sub=sub, size=size, signed=signed) != value:
            raise LiftError('Parameter readback mismatch: {:04X}:{:02X}'.format(index, sub))

    def _wait_word(self, predicate, timeout=0.45):
        """等待状态字达到指定状态;有故障或超时就中止当前操作."""
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
        """调用底盘停车检查器;非空字符串是当前不允许升降的原因."""
        reason = self.interlock()
        if reason:
            raise LiftError(reason)

    def _speed_cap(self):
        cap = finite(self.speed_limit(), 'base speed limit')
        if cap <= 0:
            raise LiftError('Chassis policy prohibits lift motion.')
        return min(cap, self.cfg.max_rpm)

    def _profile_rpm(self, requested_rpm, delta_up):
        rpm = min(requested_rpm, self._speed_cap())
        if self.cfg.zones:
            lower, upper = self._limits()
            directional = self.cfg.zones.rpm(self.position, 1 if delta_up > 0 else -1,
                                              lower, upper)
            if directional == 0:
                raise LiftError('Directional software endpoint/limit is active.')
            rpm = min(rpm, abs(directional))
        return rpm

    def _refresh_position_speed(self):
        """控制字3F的bit5保持1,6081在线修改立即生效,不重发位置目标."""
        if self.position_halting or self.target is None:
            return
        delta = (self.target - self.position) * self.cfg.direction
        if abs(self.target - self.position) <= self._tolerance_counts():
            return
        rpm = self._profile_rpm(self.position_rpm, delta)
        if rpm < self.position_rpm:
            self._write(0x6081, self.cfg.velocity_raw(rpm), size=4)
            self.position_rpm = rpm  # 同一任务只降不升,底盘停下不会突然加速.

    def apply_speed_limits(self):
        """底盘回调立刻请求降速,不能代替底盘侧的运动许可互锁."""
        with self.lock:
            if not self.armed:
                return
            self._check_interlock()
            if self.control_mode == 3 and not self.recovering:
                self._keyboard_poll()
            elif self.busy and not self.recovering:
                self._refresh_position_speed()

    def _height(self, counts):
        """原始计数 -> 相对会话零点的毫米高度;未建零点时返回None."""
        if self.reference is None or self.cfg.counts <= 0 or self.cfg.mm_rev <= 0:
            return None
        return (counts - self.reference) * self.cfg.mm_rev / self.cfg.counts * self.cfg.direction

    def _limits(self):
        """60FD的bit0/bit1是负/正限位,按电机方向换成物理下/上限位."""
        negative, positive = bool(self.inputs & 1), bool(self.inputs & 2)
        return (negative, positive) if self.cfg.direction == 1 else (positive, negative)

    def _tolerance_counts(self):
        return max(1, round(self.cfg.tolerance * self.cfg.counts / self.cfg.mm_rev))

    def poll(self):
        """主循环定期读取反馈,同时检查重启,故障,停车条件和定位完成."""
        with self.lock:
            self.word = self.sdo.read(0x6041, size=2)
            self.position = self.sdo.read(0x6063, signed=True)
            feedback_now = time.monotonic()
            if (self.cfg.zones and self.frame_confirmed and self.feedback_time is not None):
                elapsed = max(0.0, feedback_now - self.feedback_time)
                allowed_mm = self.cfg.max_speed * elapsed * 2 + self.cfg.coordinate_tolerance
                if abs(self.position - self.feedback_position) * self.cfg.mm_rev / self.cfg.counts > allowed_mm:
                    self.keyboard_confirmed = False
                    self.frame_confirmed = False
                    self.reference = None
                    raise LiftError('Encoder coordinate jump detected; stop and confirm frame again.')
            self.feedback_position, self.feedback_time = self.position, feedback_now
            self.inputs = self.sdo.read(0x60FD)
            self.velocity = self.sdo.read(0x606C, signed=True)
            self.error_status = self.sdo.read(0x2601, size=2)
            self.error_status2 = self.sdo.read(0x2602, size=2)
            moving = (self.busy or self.stopping or
                      (self.cfg.counts > 0 and abs(self.velocity) > self.cfg.velocity_raw(1)))
            self.budget.update(moving, time.monotonic())
            self.connected = True
            if self.sdo.boot_count != self.session_boot:
                self.reference = None
                self.keyboard_confirmed = False
                self.frame_confirmed = False
                raise LiftError('Drive reboot detected; restart and establish reference again.')
            if self.stopping and self.cfg.counts > 0:
                # 停机写入有回执后仍需等反馈;速度阈值约为电机1rpm.
                if not self.word & 4 and abs(self.velocity) <= self.cfg.velocity_raw(1):
                    self.stopping = False
            if self.word & 8 or self.error_status or self.error_status2 or self.sdo.emcy:
                raise LiftError('Drive fault: SW=0x{:04X}, error=0x{:04X}, error2=0x{:04X}, EMCY=0x{:04X}'.format(
                    self.word, self.error_status, self.error_status2, self.sdo.emcy))
            if self.armed:
                self._check_interlock()
                if self.cfg.zones and self.frame_confirmed:
                    tolerance = self.cfg.coordinate_tolerance * self.cfg.counts / self.cfg.mm_rev
                    if (self.sdo.read(0x6410, sub=3) != self.cfg.counts or
                            not self.cfg.zones.lower - tolerance <= self.position <= self.cfg.zones.upper + tolerance):
                        self.reference = None
                        self.frame_confirmed = self.keyboard_confirmed = False
                        raise LiftError('Confirmed encoder frame/precision/limits changed; stop and verify calibration.')
                    if all(self._limits()):
                        self.reference = None
                        self.frame_confirmed = self.keyboard_confirmed = False
                        raise LiftError('Both travel limits active; inspect wiring/IO configuration.')
                if self.budget.remaining <= 0:
                    raise LiftError('Motion duty budget exhausted; full stationary cooldown required.')
                now = time.monotonic()
                if self.guard_active and now - self.guard_since > 0.5:
                    if self.sdo.guard_time is None or now - self.sdo.guard_time > 0.5:
                        raise LiftError('No fresh toggling node-guard response.')
                if not self.word & 4:
                    raise LiftError('Drive unexpectedly left operation-enabled state.')
            if self.armed and self.recovering:
                self._recover_poll()
            elif self.armed and self.control_mode == 3:
                if self.sdo.read(0x6061, size=1, signed=True) != 3:
                    raise LiftError('Keyboard operation lost profile velocity mode.')
                self._keyboard_poll()
            elif self.position_halting:
                if self.armed and self.control_mode == 1 and \
                        self.sdo.read(0x6061, size=1, signed=True) != 1:
                    raise LiftError('Position halt lost profile position mode.')
                if abs(self.velocity) <= self.cfg.velocity_raw(1):
                    self.position_halting = self.busy = False
                elif time.monotonic() - self.halt_started > 2:
                    raise LiftError('Position halt did not reach standstill within 2 seconds.')
            elif self.busy:
                if self.armed and self.control_mode == 1 and \
                        self.sdo.read(0x6061, size=1, signed=True) != 1:
                    raise LiftError('Position operation lost profile position mode.')
                self._refresh_position_speed()
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
                # 到位需同时满足驱动器bit10,位置误差和低速反馈.
                if (self.word & 0x400 and abs(self.target - self.position) <= self._tolerance_counts()
                        and abs(self.velocity) <= self.cfg.velocity_raw(1)):
                    self.busy = False
                    self.target = None
                    self.position_rpm = 0
                    self.last_error = ''
            return self.status()

    def _enable_drive(self, mode):
        """6/7/F使能握手+停止策略+节点保护配置;调用方须先完成许可检查并置took_control.

        使能中途失败时驱动器状态不确定:took_control已置位,进程退出由failsafe覆盖,
        运行中由节点_run在guard_active/poisoned时转fail处理.
        """
        self.control_mode = mode
        # 先进入运行就绪,避免接管其他软件遗留的运动模式或目标.
        self._write(0x6040, 0x0006)
        self._wait_word(lambda w: w & 0x6F == 0x21)
        self._verified_write(0x60FF, 0, size=4, signed=True)
        self._verified_write(0x6060, mode, size=1, signed=True)
        # 停止策略:快停用6085减速度;禁用/关机采用曲线停止.
        self._verified_write(0x605A, 2, signed=True)
        self._verified_write(0x605B, 1, signed=True)
        self._verified_write(0x605C, 1, signed=True)
        self._verified_write(0x605D, 2, signed=True)  # bit8暂停:按6085减速,保留使能.
        self._verified_write(0x605E, 2, signed=True)
        self._verified_write(0x6083, self.cfg.acceleration_raw(self.cfg.accel), size=4)
        self._verified_write(0x6084, self.cfg.acceleration_raw(self.cfg.accel), size=4)
        self._verified_write(0x6085, self.cfg.acceleration_raw(self.cfg.quick_decel), size=4)
        # 节点保护与heartbeat互斥;200ms*3是驱动器侧监督超时设置.
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
        # 用当前反馈初始化目标,再使能;此处不触发bit4位置运动.
        self._write(0x607A, self.position, size=4, signed=True)
        self._write(0x6040, 0x0007)
        self._wait_word(lambda w: w & 0x6F == 0x23)
        self._check_interlock()
        self._write(0x6040, 0x000F)
        self._wait_word(lambda w: w & 0x6F == 0x27)
        if self.sdo.read(0x6061, size=1, signed=True) != mode:
            raise LiftError('Effective operating mode differs from requested mode.')

    def enable(self, keyboard=False):
        """显式使能:检查条件 -> 关断旧指令 -> 配置 -> 6/7/F状态握手."""
        with self.lock:
            self.cfg.validate_motion(require_travel=not keyboard)
            if keyboard and (not self.cfg.keyboard_enabled or not self.keyboard_confirmed):
                raise LiftError('Keyboard needs enabled configuration and session coordinate confirmation.')
            if self.armed:
                raise LiftError('Already enabled.')
            if self.stopping:
                raise LiftError('Stop has not yet been confirmed by feedback.')
            if self.latched or self.sdo.poisoned:
                raise LiftError('Stop/fault latch active; inspect cause and explicitly reset.')
            self._check_interlock()
            self.poll()
            if self.budget.remaining <= 0:
                raise LiftError('Motion duty budget exhausted; full stationary cooldown required.')
            self.took_control = True
            self._enable_drive(3 if keyboard else 1)
            self.armed = True
            self.key_direction = 0
            self.key_time = None
            self.neutral_required = True
            self.command_rpm = 0
            self.position_rpm = 0
            self.last_error = ''
            self.position_halting = self.position_halted = False
            self.halt_started = None

    def reference_here(self):
        """在静止下限位处记录0mm;不移动机构,不清编码器,不写原点参数."""
        with self.lock:
            self.cfg.validate_motion()
            self._check_interlock()
            if self.busy or self.stopping or self.latched:
                raise LiftError('Reference requires a stationary, non-faulted axis.')
            self.poll()
            self._record_checked_reference()
            self.target_mm = None

    def recover_to_lower_limit(self, rpm=50, timeout_s=10):
        """启动受监督的回下限位恢复:未使能/空闲/无故障时慢速下行至下限位触发.

        与正常运动同等待遇(复盘4.4):入口检查底盘联锁/工作制预算/限位/位置,
        使能握手与节点保护统一复用_enable_drive,运行期由poll持续监督故障/模式/
        方向/预算,不全程独占控制锁,/lift/stop可中断.
        服务返回只代表已启动;完成情况与故障看status/busy.完成后机构静止在下限位
        且未使能,需显式reference_here建立会话参考.
        不屏蔽硬限位,不清编码器,不扩大普通行程,不自动续跑旧目标.
        """
        with self.lock:
            self.cfg.validate_motion(require_travel=False)
            if self.armed or self.busy or self.stopping or self.latched or self.recovering:
                raise LiftError('Recovery requires a disabled, idle, non-faulted axis.')
            if not self.cfg.zones:
                raise LiftError('Recovery requires configured raw zones.')
            if not 1 <= rpm <= 100:
                raise LiftError('Recovery speed must be within 1..100 rpm.')
            self._check_interlock()
            self.poll()
            if self.budget.remaining <= 0:
                raise LiftError('Motion duty budget exhausted; full stationary cooldown required.')
            lower, upper = self._limits()
            if lower:
                raise LiftError('Lower limit already active; call reference_here directly.')
            if upper:
                raise LiftError('Upper limit active; manual inspection required.')
            tolerance = self.cfg.coordinate_tolerance * self.cfg.counts / self.cfg.mm_rev
            if self.position <= self.cfg.zones.lower + tolerance:
                raise LiftError('Position already at/below lower reference; check wiring/sensor.')
            self.took_control = True
            self._enable_drive(3)
            down_raw = self.cfg.velocity_raw(rpm)
            self.recover_velocity = -down_raw if self.cfg.direction == 1 else down_raw
            self._write(0x60FF, self.recover_velocity, size=4, signed=True)
            self.recover_start = self.position
            self.recover_deadline = time.monotonic() + timeout_s
            self.armed = self.recovering = self.busy = True
            self.last_error = 'Recovery descending; confirm lower limit and standstill in /lift/status.'

    def _recover_poll(self):
        """恢复下行的周期监督:到限位后清零速度,确认停稳再撤使能.

        超时,反向,上限位触发,模式丢失都按故障处理;每拍重申下行速度,
        外部清零(如keyboard_stop)不能悄悄冻结恢复,彻底停止用/lift/stop.
        """
        if self.sdo.read(0x6061, size=1, signed=True) != 3:
            raise LiftError('Recovery lost profile velocity mode.')
        lower, upper = self._limits()
        if upper:
            raise LiftError('Upper limit active during recovery descent; inspect wiring/sensor.')
        if ((self.position - self.recover_start) * self.cfg.direction
                > self._tolerance_counts()):
            raise LiftError('Recovery moved away from the lower limit; aborting.')
        if not lower:
            if time.monotonic() > self.recover_deadline:
                raise LiftError('Lower limit not reached within recovery timeout.')
            self._write(0x60FF, self.recover_velocity, size=4, signed=True)
            return
        self._write(0x60FF, 0, size=4, signed=True)
        if abs(self.velocity) > self.cfg.velocity_raw(1):
            if time.monotonic() > self.recover_deadline + 2:
                raise LiftError('Recovery stop did not reach standstill within 2 seconds.')
            return
        self._write(0x6040, 0x0007)
        self._wait_word(lambda w: w & 0x6F == 0x23)
        self._write(0x6040, 0x0006)
        self._wait_word(lambda w: w & 0x6F == 0x21)
        # 进程存活期间guard帧继续流动;撤防100C会让重新使能后的运动被判通信中断.
        self.armed = False
        self.recovering = self.busy = False
        self.recover_velocity = 0
        self.last_error = 'Recovery complete at lower limit; call reference_here to establish reference.'

    def _record_checked_reference(self):
        """位置/键盘共用核验,不能把新零点套入旧的绝对计数速度区."""
        self.reference = None
        self.frame_confirmed = self.keyboard_confirmed = False
        lower, upper = self._limits()
        if not lower or upper:
            raise LiftError('Reference requires the real lower limit only.')
        if self.sdo.read(0x6410, sub=3) != self.cfg.counts:
            raise LiftError('Drive feedback precision differs from configured counts per revolution.')
        if abs(self.velocity) > self.cfg.velocity_raw(1):
            raise LiftError('Axis must be stationary before confirming coordinates.')
        if self.cfg.zones:
            tolerance = self.cfg.coordinate_tolerance * self.cfg.counts / self.cfg.mm_rev
            if abs(self.position - self.cfg.zones.lower) > tolerance:
                raise LiftError('Lower position does not match configured raw frame; do not reuse old thresholds.')
        self.reference = self.position
        self.frame_confirmed = True

    def move(self, value_mm, speed_mm_s, jog=False):
        """开始有限位置运动;jog为相对毫米步长,否则为从零点算起的高度."""
        with self.lock:
            self.cfg.validate_motion()
            if self.cfg.zones and not self.frame_confirmed:
                raise LiftError('Confirm the lower raw-coordinate frame before any position move or jog.')
            if self.control_mode != 1:
                raise LiftError('Position services require position mode; stop and explicitly re-enable first.')
            if not self.armed or self.latched or self.busy or self.stopping:
                raise LiftError('Axis must be enabled, idle and free of stop/fault latches.')
            self._check_interlock()
            self.poll()
            value, speed = finite(value_mm, 'distance/height'), finite(speed_mm_s, 'speed')
            if not 0 < speed <= self.cfg.max_speed:
                raise LiftError('Speed outside configured range.')
            if jog:
                # 未记录零点也可做受限调试点动,此时只能依赖已验证的硬件限位.
                if not 0 < abs(value) <= self.cfg.jog_max:
                    raise LiftError('Jog exceeds max_jog_mm or is zero.')
                delta_mm = value
                target = self.position + round(value * self.cfg.counts / self.cfg.mm_rev) * self.cfg.direction
            else:
                # 绝对高度必须有有效会话零点,换算结果仍是电机原始inc.
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
            if self.cfg.zones:
                zones = self.cfg.zones
                frame_tolerance = self.cfg.coordinate_tolerance * self.cfg.counts / self.cfg.mm_rev
                if not zones.lower - frame_tolerance <= self.position <= zones.upper + frame_tolerance:
                    raise LiftError('Position outside configured raw-coordinate frame.')
                if not min(self.position, zones.lower_stop) <= target <= max(self.position, zones.upper_stop):
                    raise LiftError('Position target crosses inset normal endpoints.')
            target_height = self._height(target)
            if target_height is not None and not 0 <= target_height <= self.cfg.travel:
                raise LiftError('Target crosses software travel boundary.')
            lower, upper = self._limits()
            if (delta_mm < 0 and lower) or (delta_mm > 0 and upper):
                raise LiftError('Requested direction blocked by active limit.')
            rpm = speed * 60 / self.cfg.mm_rev  # mm/s -> 电机rpm.
            if rpm > self.cfg.max_rpm:
                raise LiftError('Requested speed exceeds max_motor_rpm.')
            rpm = self._profile_rpm(rpm, delta_mm)
            effective_speed = rpm * self.cfg.mm_rev / 60
            if abs(delta_mm) / effective_speed + 2 > min(self.cfg.timeout, self.budget.remaining):
                raise LiftError('Move exceeds timeout; use smaller steps or verify timeout.')
            # 绝对定位握手:先2F清激活位并等bit12清零,再写速度/目标,
            # 最后3F产生bit4上升沿,等bit12确认接收.此回执不是到位信号.
            # 暂停后保持bit8清bit4,装入新目标,最后3F才解除暂停,不能恢复旧任务.
            self._write(0x6040, 0x012F if self.position_halted else 0x002F)
            self._wait_word(lambda w: not w & 0x1000)
            self._write(0x6081, self.cfg.velocity_raw(rpm), size=4)
            self._write(0x607A, target, size=4, signed=True)
            self._check_interlock()
            current_rpm = self._profile_rpm(rpm, delta_mm)
            if current_rpm < rpm:
                rpm = current_rpm
                self._write(0x6081, self.cfg.velocity_raw(rpm), size=4)
            self._write(0x6040, 0x003F)
            self._wait_word(lambda w: bool(w & 0x1000))
            self.target, self.target_mm = target, target_height
            self.position_rpm = rpm
            self.busy = True
            self.move_started = time.monotonic()
            self.position_halted = False

    def move_top_height(self, height_m):
        """目标是顶端总高度(米),不是本次增量,也不是直接编码器坐标."""
        with self.lock:
            if self.cfg.initial_top_height is None:
                raise LiftError('Measure and fill initial_top_height_m before requesting top height.')
            height = finite(height_m, 'target top height')
            extension_mm = finite((height - self.cfg.initial_top_height) * 1000, 'extension')
            if extension_mm < 0:
                raise LiftError('Target top height is below initial_top_height_m.')
            if self.reference is None:
                raise LiftError('No lower reference; establish stationary lower-limit session reference first.')
            if self.cfg.zones:
                raw_target = self.reference + round(extension_mm * self.cfg.counts / self.cfg.mm_rev) * self.cfg.direction
                if not self.cfg.zones.lower_stop <= raw_target <= self.cfg.zones.upper_stop:
                    raise LiftError('Top-height target is outside inset normal travel.')
            self.move(extension_mm, self.cfg.max_rpm * self.cfg.mm_rev / 60)

    def confirm_keyboard_coordinates(self):
        """人工确认本会话计数框架:必须静止在真实下限位且读数匹配.

        不清零,不回原,不写2010/607D,也不把固定计数当作掉电有效参考.
        """
        with self.lock:
            if not self.cfg.zones:
                raise LiftError('Keyboard configuration is disabled.')
            if self.armed or self.busy or self.stopping or self.latched:
                raise LiftError('Confirm coordinates before enabling, while stationary and unlatched.')
            self._check_interlock()
            self.poll()
            self._record_checked_reference()
            self.keyboard_confirmed = True

    def operator_halt(self):
        """跨模式普通停车;位置模式用bit8暂停,不取消使能,也不恢复旧任务."""
        with self.lock:
            if self.armed and self.control_mode == 1:
                if not self.position_halted:
                    self._write(0x6040, 0x012F)
                    self.halt_started = time.monotonic()
                    self.position_halting = self.position_halted = True
                    self.target = self.target_mm = None
                    self.position_rpm = 0
                    self.busy = True  # 下一次真实反馈确认停稳前保持busy.
                self.last_error = 'Position halt requested; confirm standstill in feedback.'
            else:
                self.keyboard_halt()

    def _set_keyboard_rpm(self, rpm):
        if rpm != self.command_rpm:
            raw = 0 if rpm == 0 else self.cfg.velocity_raw(abs(rpm)) * (1 if rpm > 0 else -1)
            if not -0x80000000 <= raw <= 0x7fffffff:
                raise LiftError('Signed velocity target overflows int32.')
            self._write(0x60FF, raw, size=4, signed=True)
            self.command_rpm = rpm

    def keyboard_halt(self, reason='Keyboard stop', require_neutral=True):
        """正常松键/端点停止:带减速度写速度0,保留使能保持力.

        与全局stop的故障锁存不同;不取消使能,不自动复位故障.
        """
        with self.lock:
            if self.armed and self.control_mode == 3:
                self._set_keyboard_rpm(0)
            self.key_direction = 0
            self.key_time = None
            self.neutral_required = require_neutral
            self.slow_latched = False
            if self.control_mode == 3:
                self.busy = abs(self.velocity) > self.cfg.velocity_raw(1) if self.cfg.counts else False
            if not self.latched:
                self.last_error = reason

    def keyboard_command(self, direction):
        """方向心跳(-1/0/+1),无队列,无自动使能,换向先停稳并松键."""
        with self.lock:
            if isinstance(direction, bool) or direction not in (-1, 0, 1):
                raise LiftError('Keyboard direction must be -1, 0 or +1.')
            if direction == 0:
                if self.armed and self.control_mode == 3:
                    self.poll()
                stationary = not self.cfg.counts or abs(self.velocity) <= self.cfg.velocity_raw(1)
                self.keyboard_halt('Keyboard neutral', require_neutral=not stationary)
                return
            self.cfg.validate_motion(require_travel=False)
            if not self.cfg.keyboard_enabled or not self.keyboard_confirmed:
                raise LiftError('Keyboard configuration/session is not confirmed.')
            if not self.armed or self.control_mode != 3 or self.latched or self.stopping:
                raise LiftError('Explicitly enable keyboard mode first.')
            self.poll()
            if self.neutral_required:
                return  # 长按到限位后不会因为传感器抖动而恢复运动.
            if self.key_direction and direction != self.key_direction:
                self.keyboard_halt('Release arrows and stop before reversing.')
                return
            if self.key_direction == 0:
                if abs(self.velocity) > self.cfg.velocity_raw(1):
                    self.keyboard_halt('Axis must stop before accepting a new direction.')
                    return
                self.slow_latched = False
            self.key_direction, self.key_time = direction, time.monotonic()
            self._keyboard_poll()

    def _keyboard_poll(self):
        if not self.keyboard_confirmed:
            raise LiftError('Keyboard coordinate confirmation lost.')
        zones = self.cfg.zones
        tolerance = self.cfg.coordinate_tolerance * self.cfg.counts / self.cfg.mm_rev
        if not zones.lower - tolerance <= self.position <= zones.upper + tolerance:
            raise LiftError('Feedback outside confirmed raw-coordinate frame.')
        lower, upper = self._limits()
        if lower and upper:
            raise LiftError('Both travel limits active; inspect wiring/IO configuration.')
        if self.key_direction and (self.key_time is None or
                time.monotonic() - self.key_time > self.cfg.keyboard_timeout):
            self.keyboard_halt('Keyboard heartbeat expired; release arrows before resuming.')
        if self.key_direction and not self.neutral_required:
            rpm = zones.rpm(self.position, self.key_direction, lower, upper)
            if rpm == 0:
                self.keyboard_halt('Directional endpoint/limit reached; release arrows.')
            else:
                rpm = min(abs(rpm), self._speed_cap()) * self.key_direction
                self.slow_latched = self.slow_latched or abs(rpm) <= zones.slow
                if self.slow_latched:
                    rpm = min(abs(rpm), zones.slow) * self.key_direction
                self._set_keyboard_rpm(rpm)
        self.busy = self.command_rpm != 0 or abs(self.velocity) > self.cfg.velocity_raw(1)

    def stop(self, reason='Operator stop'):
        """锁住后续运动并下发000B;返回True只表示停机写入得到SDO回执."""
        with self.lock:
            was_writing = self.armed or self.guard_active or self.busy
            self.stopping = self.stopping or was_writing
            self.busy = self.armed = False
            self.target = self.target_mm = None
            self.latched = True
            self.last_error = reason
            self.key_direction = 0
            self.key_time = None
            self.neutral_required = True
            self.command_rpm = 0
            self.position_rpm = 0
            self.recovering = False
            self.recover_velocity = 0
            confirmed = False
            self.position_halting = self.position_halted = False
            self.halt_started = None
            if was_writing:
                try:
                    self._write(0x6040, 0x000B)
                    confirmed = True
                except (CanError, OSError):
                    self.sdo.emergency_stop_unconfirmed()
                    self.guard_active = False
            return confirmed

    def disable(self):
        """确认定位结束/停稳后取消使能;取消后电机可能失去保持力.

        进程存活期间guard帧继续流动(不撤防):实机验证disable时撤防100C
        会让下次重新使能后的运动被驱动器判"CAN总线中断"(EMCY 0x8100, 2026-10-28).
        """
        with self.lock:
            self.poll()
            if self.busy or self.stopping:
                raise LiftError('Stop first, then confirm stationary before disabling.')
            if self.armed or self.guard_active:
                self._write(0x6040, 0x0006)
                self._wait_word(lambda w: not w & 4)
            self.armed = False

    def reset(self):
        """人工故障复位;保持不使能,撤销旧参考,不恢复被中断的目标."""
        with self.lock:
            self.cfg.validate_motion(require_travel=False)
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
            self.keyboard_confirmed = False
            self.frame_confirmed = False
            self.last_error = ''
            self.poll()

    def status(self):
        """供ROS发布的快照;busy也包含尚未确认停稳的stopping阶段."""
        lower, upper = self._limits()
        height_mm = self._height(self.position)
        initial = self.cfg.initial_top_height
        return dict(connected=self.connected and not self.sdo.poisoned,
                    enabled=self.armed, busy=self.busy or self.stopping, stopping=self.stopping,
                    referenced=self.reference is not None,
                    position_counts=self.position, position_mm=self._height(self.position),
                    target_mm=self.target_mm, velocity_raw=self.velocity,
                    statusword=self.word, digital_inputs=self.inputs,
                    lower_limit=lower, upper_limit=upper, error_status=self.error_status,
                    emcy=self.sdo.emcy, stop_latched=self.latched, message=self.last_error,
                    error_status2=self.error_status2, control_mode=self.control_mode,
                    keyboard_confirmed=self.keyboard_confirmed,
                    frame_confirmed=self.frame_confirmed,
                    position_halting=self.position_halting, position_halted=self.position_halted,
                    keyboard_neutral_required=self.neutral_required,
                    commanded_rpm=self.command_rpm,
                    profile_rpm=self.position_rpm,
                    recovering=self.recovering,
                    initial_top_height_m=initial,
                    top_height_m=(initial + height_mm / 1000 if initial is not None and height_mm is not None else None),
                    target_top_height_m=(initial + self.target_mm / 1000
                                         if initial is not None and self.target_mm is not None else None),
                    motion_budget_remaining_s=self.budget.remaining,
                    cooldown_remaining_s=self.budget.cooldown_remaining(time.monotonic()))

    def fail(self, reason):
        """异常统一入口:撤销零点,记录原因,并尽力请求停机."""
        self.connected = False
        self.reference = None
        self.keyboard_confirmed = False
        self.frame_confirmed = False
        return self.stop(reason)

    def failsafe_halt(self):
        """进程崩溃退出的兜底:本会话接管过驱动器才尽力清零速度指令并关断.

        2026-10-27事故:节点异常退出没走close,驱动器残留mode3+60FF,机构上漂60mm.
        纯只读且未接管的会话退出时不写——另一会话可能正在控制该轴(复盘4.2).
        SDO会话已失效时降级为单向尽力发送;发送成功不代表驱动器已停稳.
        覆盖不到SIGKILL/os._exit/断电/致命信号,那些路径只能靠驱动器自身
        节点保护(名义200ms x 3,未经实测)与独立机械保持.
        """
        if not self.took_control or (self.closed and self.stop_confirmed):
            return
        try:
            with self.lock:
                try:
                    self._write(0x60FF, 0, size=4, signed=True)
                    self._write(0x6040, 0x0006)
                except (CanError, OSError):
                    self.sdo.halt_unconfirmed()
        except Exception:
            pass  # 解释器退出阶段任何异常都不能阻碍进程结束.

    def close(self):
        """退出时请求停止,结束节点保护线程并关闭适配器,不自动再次连接.

        停机得到回执后撤防节点保护(100C=0):干净退出不应在驱动器侧留下
        "CAN总线中断"故障(2026-10-27/28两次重启均复现2602=0x1000);
        停机未确认或崩溃路径绝不撤防,监督超时是它们唯一的驱动器侧兜底.
        """
        self.stop_confirmed = self.stop('Node shutdown')
        if self.stop_confirmed:
            try:
                self._write(0x100C, 0)
            except (CanError, OSError):
                pass
        self.guard_active = False
        self.stop_event.set()
        self.guard_thread.join(timeout=0.5)
        self.sdo.transport.close()
        self.closed = True
