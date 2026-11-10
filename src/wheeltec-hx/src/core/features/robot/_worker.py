"""族 worker：roslibpy 链路（仿 jdyw-hx 族 `_worker.py` + `_source_roslibpy.py`）。

**与 jdyw-hx 的架构差异（有意为之，见 docs/architecture.md）**：
jdyw-hx 的 worker 是独立子进程、经 IPC 把 (meta, raw) 送回主进程解帧；
本软件是 CLI 工具，worker 与解帧同进程——但**两段式形状保留**：parser
（机型包 `_worker.py`）产出 (meta, raw)，decode（机型包 `_decode.py`）
转成帧对象，中间的契约一字不变。将来要搬回多进程，只加 IPC 不改解析。

本类收敛的横切纪律（全部来自 jdyw-hx 的真机实测教训，逐条注明出处）：

1. **类型名换算**：话题表用 rosidl 规范名 "pkg/msg/Type"，rosbridge 腿
   转 "pkg/Type"（jdyw-hx `_source_roslibpy.py` 同款）。
2. **latch 补订**：`qos: transient_local` 的话题走补订轮次（1.5s 一轮，
   先退后订、复用同一回调），连续 `rearm_dry_limit` 轮无新载荷指纹收手
   ——jdyw-hx 实测 rosbridge 对 ROS2 transient_local 回放**随机子集**，
   ROS1 latch 是一次全量回放，但补订无害且对两端口径一致。
3. **start_after**：声明了 `start_after: robot_description` 的话题，在
   URDF 首帧到达前挂起——"URDF 必须先装配完，TF 才开始接收"
   （2026-10-10 用户口径）。
4. **心跳**：power_voltage 是唯一的在线心跳源，6s 无帧判离线；
   该话题**绝不节流**（任何节流都在逼近心跳窗口，丢几帧就假离线）。
5. **速度看门狗**：velocity 指令带 ttl_ms，超时无新设定自动发 zero
   （死手），防"客户端卡住机器人继续跑"。
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Callable

from ._config import RobotSpec

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_S = 6.0
"""在线判定窗口（jdyw-hx 实测口径）：power_voltage 实测 ~1.7Hz，6s 余量充足。"""

_REARM_INTERVAL_S = 1.5
"""latch 补订轮次间隔（jdyw-hx `_worker._LatchRearm` 同款）。"""

_VELOCITY_VERB = "velocity"
"""看门狗盯防的指令词（COMMANDS 里带 zero 的那条）。"""


def to_rosbridge_type(rosidl_name: str) -> str:
    """"pkg/msg/Type" / "pkg/srv/Type" → rosbridge 线格式 "pkg/Type"。

    roslibpy 构造 Topic/Service 时要用后者；话题表统一存前者（rosidl
    规范名，与 jdyw-hx 机型表同构，将来若接 ROS2 机器人可直接共用）。
    """
    parts = rosidl_name.split("/")
    if len(parts) == 3:
        return f"{parts[0]}/{parts[2]}"
    return rosidl_name


class RobotLink:
    """一台机器人的 roslibpy 链路：订阅闸门 + 补订 + 心跳 + 上行指令。

    构造参数全部来自机型包自报（topics/commands/parser），本类不认识任何
    机型名——机型差异止步于机型包。
    """

    def __init__(self, robot_id: str, spec: RobotSpec, *,
                 topics: dict, commands: dict,
                 parser: Callable[[str, object], "tuple[dict, bytes] | None"],
                 heartbeat_cap: str = "power_voltage") -> None:
        self._robot_id = robot_id
        self._spec = spec
        self._topics = topics            # 能力词 → {topic, msg, qos, ...}
        self._commands = commands        # verb → {kind, topic/service, ...}
        self._parser = parser
        self._heartbeat_cap = heartbeat_cap

        self._ros = None                 # roslibpy.Ros（start 后）
        self._subs = {}                  # cap → roslibpy.Topic
        self._on_frame: list[Callable] = []
        self._on_online: list[Callable] = []
        self._online = False
        self._last_heartbeat = 0.0
        self._arrived: set[str] = set()  # 已首帧的能力词（start_after 闸门用）
        self._lock = threading.RLock()
        self._stop_evt = threading.Event()
        self._threads: list[threading.Thread] = []
        self._latch_fingerprints: dict[str, set] = {}
        self._velocity_deadline = 0.0

    # -- 事件订阅 ----------------------------------------------------------------

    def set_on_frame(self, cb: Callable) -> None:
        """帧回调：cb(robot_id, meta, raw)——解帧由装配根的 decode 完成。"""
        self._on_frame.append(cb)

    def set_on_online(self, cb: Callable[[str, bool], None]) -> None:
        self._on_online.append(cb)

    @property
    def online(self) -> bool:
        with self._lock:
            return self._online

    # -- 生命周期 ----------------------------------------------------------------

    def start(self, caps: "tuple[str, ...] | None" = None) -> None:
        """连接 rosbridge 并按能力词订阅。caps=None → 订阅机型表全集。"""
        import roslibpy

        want = tuple(caps) if caps is not None else tuple(self._topics)
        unknown = set(want) - set(self._topics)
        if unknown:
            raise ValueError(f"机型未声明能力词: {sorted(unknown)}（未知词不猜，"
                             f"见机型包 _topics.py）")

        url = self._spec.endpoint
        host, _, port_s = url.replace("ws://", "").replace("wss://", "").partition(":")
        port = int(port_s) if port_s else 9090
        self._ros = roslibpy.Ros(host=host, port=port)
        self._ros.on_ready(lambda: logger.info("[%s] rosbridge 已连接 %s",
                                               self._robot_id, url))
        # run() 阻塞 → 独立线程；回调在 roslibpy 自己的事件循环线程上触发。
        # 连接失败时 roslibpy 在线程里抛异常——吞掉（连接状态由
        # _wait_connected 统一判，裸 traceback 只会吓人）。
        def _run() -> None:
            try:
                self._ros.run()
            except Exception as exc:
                logger.debug("[%s] ros 事件循环退出: %s", self._robot_id, exc)

        t = threading.Thread(target=_run, name=f"ros-{self._robot_id}",
                             daemon=True)
        t.start()
        self._threads.append(t)
        if not self._wait_connected(10.0):
            self.stop()        # 连不上就收回 roslibpy 重试循环，不泄漏后台线程
            raise ConnectionError(f"连接 {url} 超时（10s）——检查机器人在线/"
                                  f"rosbridge 已启动/端口正确")
        # is_connected 只代表 TCP/WebSocket 层通了——再要一次服务列表确认
        # 对面真的是 rosbridge（实测：非 rosbridge 的 TCP 端点也能让
        # is_connected 变 True，然后静默没数据）
        try:
            self._ros.get_services()
        except Exception as exc:
            self.stop()
            raise ConnectionError(
                f"{url} TCP 已通但 rosbridge 无应答（{exc}）——"
                f"检查对端是否 rosbridge_server、端口是否被别的服务占用")

        for cap in want:
            gate = self._topics[cap].get("start_after")
            if gate is not None and gate not in self._arrived:
                continue                       # start_after 闸门：挂起
            self._subscribe(cap)

        # 心跳看门狗线程（6s 无 power_voltage → 离线）
        t = threading.Thread(target=self._heartbeat_loop,
                             name=f"hb-{self._robot_id}", daemon=True)
        t.start()
        self._threads.append(t)
        # 速度看门狗线程
        t = threading.Thread(target=self._velocity_watchdog_loop,
                             name=f"wd-{self._robot_id}", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop_evt.set()
        with self._lock:
            subs = list(self._subs.values())
            self._subs.clear()
        for sub in subs:
            try:
                if sub.is_subscribed:
                    sub.unsubscribe()
            except Exception:
                pass
        if self._ros is not None:
            try:
                self._ros.terminate()
            except Exception:
                pass
            self._ros = None
        self._set_online(False)

    def _wait_connected(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ros is not None and self._ros.is_connected:
                return True
            time.sleep(0.05)
        return False

    # -- 订阅（含补订与闸门）-------------------------------------------------------

    def _subscribe(self, cap: str) -> None:
        import roslibpy

        decl = self._topics[cap]
        opts = dict(decl.get("roslibpy", {}))     # 腿特定选项（节流/队长）
        topic = roslibpy.Topic(
            self._ros, decl["topic"], to_rosbridge_type(decl["msg"]),
            queue_size=int(opts.get("queue_length", 1)),
            throttle_rate=int(opts.get("throttle_rate", 0)))
        topic.subscribe(lambda msg, c=cap: self._on_message(c, msg))
        with self._lock:
            self._subs[cap] = topic
        logger.debug("[%s] 订阅 %s (%s)", self._robot_id,
                     decl["topic"], decl["msg"])
        # latch 话题 → 补订轮次（ROS1 latch 一次全量回放，补订是保险；
        # 对将来接 ROS2 机器人的 transient_local 随机子集回放是必需）
        if decl.get("qos") == "transient_local":
            dry_limit = int(decl.get("rearm_dry_limit", 2))
            t = threading.Thread(target=self._rearm_loop, args=(cap, dry_limit),
                                 name=f"rearm-{self._robot_id}-{cap}",
                                 daemon=True)
            t.start()
            self._threads.append(t)

    def _rearm_loop(self, cap: str, dry_limit: int) -> None:
        """先退后订、复用同一回调；连续 dry_limit 轮无新载荷指纹收手。"""
        dry = 0
        while not self._stop_evt.wait(_REARM_INTERVAL_S):
            with self._lock:
                topic = self._subs.get(cap)
            if topic is None:
                return
            seen = self._latch_fingerprints.setdefault(cap, set())
            before = len(seen)
            try:
                if topic.is_subscribed:
                    topic.unsubscribe()
                topic.subscribe(lambda msg, c=cap: self._on_message(c, msg))
            except Exception:
                logger.exception("[%s] %s 补订失败（下轮重试）",
                                 self._robot_id, cap)
                continue
            time.sleep(0.05)          # 让一轮回放到达后再判干燥
            dry = dry + 1 if len(seen) == before else 0
            if dry >= dry_limit:
                logger.debug("[%s] %s latch 补订收手（连续 %d 轮无新样本）",
                             self._robot_id, cap, dry)
                return

    def _on_message(self, cap: str, msg) -> None:
        """rosbridge 回调线程：parser → (meta, raw) → 广播给帧回调。"""
        try:
            out = self._parser(cap, msg)
        except Exception:
            logger.exception("[%s] %s 解析异常（丢帧）", self._robot_id, cap)
            return
        if out is None:
            return
        meta, raw = out
        # 载荷指纹（latch 补订的收手判定）：字节内容哈希
        self._latch_fingerprints.setdefault(cap, set()).add(
            hash(bytes(raw) if isinstance(raw, (bytes, bytearray))
                 else json.dumps(meta, sort_keys=True, default=str).encode()))
        if cap == self._heartbeat_cap:
            with self._lock:
                self._last_heartbeat = time.monotonic()
            self._set_online(True)
        if cap not in self._arrived:
            self._arrived.add(cap)
            # start_after 闸门释放：挂起的话题现在订阅
            for other, decl in self._topics.items():
                if decl.get("start_after") == cap and other not in self._subs:
                    try:
                        self._subscribe(other)
                    except Exception:
                        logger.exception("[%s] 释放闸门订阅 %s 失败",
                                         self._robot_id, other)
        for cb in tuple(self._on_frame):
            try:
                cb(self._robot_id, meta, raw)
            except Exception:
                logger.exception("[%s] 帧回调异常", self._robot_id)

    # -- 心跳 --------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        while not self._stop_evt.wait(1.0):
            with self._lock:
                last = self._last_heartbeat
            if last == 0.0:
                continue                      # 还没见过心跳帧，不判（启动宽限）
            if time.monotonic() - last > HEARTBEAT_TIMEOUT_S:
                self._set_online(False)

    def _set_online(self, online: bool) -> None:
        with self._lock:
            if self._online == online:
                return
            self._online = online
        logger.info("[%s] %s", self._robot_id, "在线" if online else "离线")
        for cb in tuple(self._on_online):
            try:
                cb(self._robot_id, online)
            except Exception:
                logger.exception("online 回调异常")

    # -- 上行指令 ------------------------------------------------------------------

    def send_command(self, verb: str, args: dict,
                     timeout: float = 10.0) -> dict:
        """按 COMMANDS 表的 kind 分派：topic → publish / service → call。

        未声明的 verb → ValueError（白名单纪律："未声明值一律拒绝，不猜"）。
        返回 {"ok": bool, "message": str, "response": dict|None}。
        """
        decl = self._commands.get(verb)
        if decl is None:
            raise ValueError(f"机型未声明指令 {verb!r}（已声明: "
                             f"{sorted(self._commands)}）")
        kind = decl.get("kind")
        if kind == "topic":
            payload = dict(args)
            ttl_ms = payload.pop("ttl_ms", None)   # ttl 是本侧看门狗语义，不下线
            self._publish(decl["topic"], decl["msg"], payload)
            if verb == _VELOCITY_VERB:
                ttl = float(ttl_ms if ttl_ms is not None else 500) / 1000.0
                self._velocity_deadline = time.monotonic() + ttl
            return {"ok": True, "message": "已发布", "response": None}
        if kind == "service":
            return self._call(decl["service"], decl["srv"], args,
                              timeout=float(decl.get("timeout", timeout)))
        raise NotImplementedError(
            f"指令 {verb!r} 的 kind={kind!r} 未实现——本机型（ROS1）无 action "
            f"服务端，COMMANDS 里不应出现；若真机发现了 action，先补本方法再声明")

    def _publish(self, topic_name: str, msg_type: str, payload: dict) -> None:
        import roslibpy

        if self._ros is None or not self._ros.is_connected:
            raise ConnectionError("链路未连接（绝不静默失败）")
        topic = roslibpy.Topic(self._ros, topic_name,
                               to_rosbridge_type(msg_type))
        try:
            topic.advertise()
            topic.publish(roslibpy.Message(dict(payload)))
        finally:
            topic.unadvertise()

    def _call(self, service_name: str, srv_type: str, args: dict,
              timeout: float) -> dict:
        import roslibpy

        if self._ros is None or not self._ros.is_connected:
            raise ConnectionError("链路未连接（绝不静默失败）")
        service = roslibpy.Service(self._ros, service_name,
                                   to_rosbridge_type(srv_type))
        done = threading.Event()
        box: dict = {}

        def _ok(resp):
            box["response"] = dict(resp or {})
            done.set()

        def _err(exc):
            box["error"] = str(exc)
            done.set()

        service.call(roslibpy.ServiceRequest(dict(args)), _ok, _err)
        if not done.wait(timeout):
            return {"ok": False, "message": f"服务 {service_name} 调用超时"
                    f"（{timeout}s）", "response": None}
        if "error" in box:
            return {"ok": False, "message": f"服务 {service_name} 失败: "
                    f"{box['error']}", "response": None}
        return {"ok": True, "message": "成功", "response": box["response"]}

    def set_velocity(self, linear_x: float, angular_z: float,
                     ttl_ms: float = 500.0) -> dict:
        """速度通道便捷入口（摇杆语义）：持续设定值 + ttl 看门狗。"""
        decl = self._commands.get(_VELOCITY_VERB)
        if decl is None:
            raise ValueError("本机型未声明 velocity 通道")
        return self.send_command(_VELOCITY_VERB,
                                 {"linear": {"x": float(linear_x)},
                                  "angular": {"z": float(angular_z)},
                                  "ttl_ms": ttl_ms})

    def _velocity_watchdog_loop(self) -> None:
        """死手：velocity 设定超时 → 发 zero（防客户端卡住机器人继续跑）。"""
        decl = self._commands.get(_VELOCITY_VERB)
        if decl is None:
            return                                # 本机型无速度通道
        zero = decl.get("zero")
        while not self._stop_evt.wait(0.1):
            if self._velocity_deadline == 0.0:
                continue
            if time.monotonic() > self._velocity_deadline:
                self._velocity_deadline = 0.0
                if zero is not None:
                    try:
                        self._publish(decl["topic"], decl["msg"], dict(zero))
                        logger.info("[%s] 速度看门狗超时 → 回零",
                                    self._robot_id)
                    except Exception:
                        logger.exception("[%s] 看门狗回零失败", self._robot_id)


def as_bytes(data) -> bytes:
    """rosbridge uint8[] 负载归一化：base64 串 / int 列表 / 已字节 → bytes。

    （jdyw-hx 机型 worker 同款纪律：rosbridge 把 uint8[] 编成 base64。）
    """
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        return base64.b64decode(data)
    return bytes(data or [])
