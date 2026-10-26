"""无ROS的方向键解析、方向相关速度区和运行时间预算。"""
import math


class SpeedZones:
    def __init__(self, params, counts, mm_rev, up_direction=1):
        def integer(name, default):
            value = params.get(name, default)
            if isinstance(value, bool) or int(value) != value:
                raise ValueError(name + ' must be an integer count.')
            return int(value)
        self.lower = integer('keyboard_lower_position_counts', 147599)
        self.upper = integer('keyboard_upper_position_counts', 122303105)
        self.down_switch = integer('keyboard_down_slow_counts', 3060000)
        self.up_switch = integer('keyboard_up_slow_counts', 119390000)
        self.fast = float(params.get('keyboard_cruise_rpm', 1000))
        self.slow = float(params.get('keyboard_approach_rpm', 100))
        self.margin_mm = float(params.get('keyboard_stop_margin_mm', 5))
        if not all(math.isfinite(v) for v in (counts, mm_rev, self.fast, self.slow, self.margin_mm)):
            raise ValueError('Keyboard calibration/speeds must be finite.')
        if counts <= 0 or mm_rev <= 0 or up_direction != 1:
            raise ValueError('Fixed count zones require calibrated positive-up feedback.')
        if not 0 < self.slow <= self.fast or self.margin_mm <= 0:
            raise ValueError('Keyboard speeds and endpoint inset must be positive.')
        margin = math.ceil(self.margin_mm * counts / mm_rev)
        self.lower_stop, self.upper_stop = self.lower + margin, self.upper - margin
        if not (-0x80000000 <= self.lower < self.lower_stop < self.down_switch
                < self.up_switch < self.upper_stop < self.upper <= 0x7fffffff):
            raise ValueError('Invalid keyboard positions, slow zones or endpoint inset.')

    def rpm(self, position, direction, lower_limit=False, upper_limit=False):
        """只在接近本次运动方向的端部时降速，另一端限位不阻止退出。"""
        if direction == 1:
            return (0 if upper_limit or position >= self.upper_stop else
                    self.slow if position >= self.up_switch else self.fast)
        if direction == -1:
            return (0 if lower_limit or position <= self.lower_stop else
                    -self.slow if position <= self.down_switch else -self.fast)
        if direction == 0:
            return 0
        raise ValueError('Keyboard direction must be -1, 0 or +1.')


class MotionBudget:
    """进程内累计预算；松键/复位/短暂停顿不恢复，仅完整静止冷却恢复。

    重启不证明冷却完成。本类不是热模型，不替代厂家工作制或硬件保护。
    """
    def __init__(self, limit_s=110, rest_s=1080):
        self.limit, self.rest = float(limit_s), float(rest_s)
        if not all(math.isfinite(v) and v > 0 for v in (self.limit, self.rest)):
            raise ValueError('Motion budget/cooldown must be positive and finite.')
        self.used = 0.0
        self.last = self.rest_since = None
        self.was_active = False

    def update(self, active, now):
        if self.last is None:
            self.last = now
        elapsed = max(0.0, now - self.last)
        if active or self.was_active:
            self.used = min(self.limit, self.used + elapsed)
            self.rest_since = None
        else:
            if self.rest_since is None:
                self.rest_since = now
            if now - self.rest_since >= self.rest:
                self.used = 0.0
        self.last, self.was_active = now, bool(active)

    @property
    def remaining(self):
        return max(0.0, self.limit - self.used)

    def cooldown_remaining(self, now):
        if self.used == 0:
            return 0.0
        return self.rest if self.rest_since is None else max(0.0, self.rest - (now - self.rest_since))


class ArrowParser:
    """解析CSI/SS3方向键及分包；终端不能提供真实key-up，须配合超时。"""
    def __init__(self):
        self.pending = b''

    def feed(self, data):
        self.pending += data
        actions = []
        arrows = {b'\x1b[A': 'up', b'\x1b[B': 'down', b'\x1bOA': 'up', b'\x1bOB': 'down'}
        while self.pending:
            if self.pending[:1] == b'\x1b':
                match = next((key for key in arrows if self.pending.startswith(key)), None)
                if match:
                    actions.append(arrows[match])
                    self.pending = self.pending[len(match):]
                elif any(key.startswith(self.pending) for key in arrows):
                    break
                else:
                    actions.append('stop')
                    self.pending = b''
            else:
                key, self.pending = self.pending[:1], self.pending[1:]
                actions.append({b'e': 'enable', b'c': 'confirm', b'q': 'quit',
                                b'\x03': 'quit', b' ': 'stop'}.get(key, 'stop'))
        return actions

    def expire_escape(self):
        if not self.pending:
            return []
        self.pending = b''
        return ['stop']
