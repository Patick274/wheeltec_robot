"""RobotCatalog —— 机器人注册表资源所有者（仿 jdyw-hx `_catalog.py`，简化版）。

机制口径与 jdyw-hx 一致：快照 + 订阅 + 进程内写后立即落盘广播。
简化点：不带文件系统 watch（jdyw-hx 用 os_platform 的 watch 感知进程外
编辑注册表；本 CLI 软件没有在线编辑注册表的入口，省去——将来加回时按
jdyw-hx 的 digest 判定纪律实现，绕过所有者直读会让 digest 基线漂移）。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ._config import _PROTOCOLS, RobotSpec, load_robots, save_robots

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RobotEntry:
    """一台机器人的快照条目（对外纯数据，与内部 RobotSpec 解耦）。"""

    robot_id: str
    model: str
    domain_id: int
    protocol: str
    endpoint: str


class _Listeners:
    """最小订阅器：subscribe(cb) -> 退订闭包（幂等）；emit() 逐个回调。"""

    def __init__(self) -> None:
        self._cbs: list[Callable[[], None]] = []

    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._cbs.append(cb)
        def _unsub() -> None:
            try:
                self._cbs.remove(cb)
            except ValueError:
                pass
        return _unsub

    def emit(self) -> None:
        for cb in tuple(self._cbs):
            try:
                cb()
            except Exception:                       # 回调异常不传染其他订阅者
                logger.exception("订阅回调异常")


class RobotCatalog:
    """机器人注册表资源所有者（快照 + 订阅 + 进程内写）。"""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._table: dict[str, RobotSpec] = load_robots(self._path)
        self._listeners = _Listeners()
        self._lock = threading.RLock()

    @property
    def table(self) -> dict[str, RobotSpec]:
        """注册表活字典（装配根注入消费方的通道）。调用方只读。"""
        return self._table

    def entries(self) -> tuple[RobotEntry, ...]:
        with self._lock:
            return tuple(RobotEntry(robot_id=r, model=s.model,
                                    domain_id=s.domain_id, protocol=s.protocol,
                                    endpoint=s.endpoint)
                         for r, s in sorted(self._table.items()))

    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]:
        return self._listeners.subscribe(cb)

    # -- 进程内写（完成后立即落盘 + 广播）----------------------------------------

    def set_endpoint(self, robot_id: str, endpoint: str) -> None:
        """改某台机器人的 rosbridge 地址（首次上机配置入口）。"""
        with self._lock:
            spec = self._table.get(robot_id)
            if spec is None:
                raise KeyError(f"未知机器人: {robot_id}")
            self._table[robot_id] = RobotSpec(
                model=spec.model, domain_id=spec.domain_id,
                protocol=spec.protocol, endpoint=endpoint, tls_ca=spec.tls_ca)
            save_robots(self._table, self._path)
        logger.info("机器人 %s endpoint → %s", robot_id, endpoint)
        self._listeners.emit()

    def set_protocol(self, robot_id: str, protocol: str) -> None:
        with self._lock:
            spec = self._table.get(robot_id)
            if spec is None:
                raise KeyError(f"未知机器人: {robot_id}")
            if protocol not in _PROTOCOLS:
                raise ValueError(f"非法协议: {protocol!r}（可选 {_PROTOCOLS}）")
            if spec.protocol == protocol:
                return
            self._table[robot_id] = RobotSpec(
                model=spec.model, domain_id=spec.domain_id,
                protocol=protocol, endpoint=spec.endpoint, tls_ca=spec.tls_ca)
            save_robots(self._table, self._path)
        self._listeners.emit()
