"""装配根：唯一跨层编排者（仿 jdyw-hx `app/composition.py`）。

**机型登记点**：`model_pkgs`——新增机型 = 机型包放
`core/features/robot/<机型id>/` + 这里加一行 + robots.json 加实例条目。
族层（core/features/robot/）禁 import 机型子级；本模块是唯一合法的
"族 × 机型"编排点。

jdyw-hx 的装配根还编排 UI 桥/生命周期租约/进程池/MCP——本软件是 CLI
工具，那些层不存在；保留的是机型接入的最小完整链：注册表 → 机型包
→ 链路 → 解帧 → 帧回调。
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.features.robot import RobotCatalog, RobotLink
from core.features.robot import wheeltec_03

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ROBOTS_JSON = _PROJECT_ROOT / "robots.json"
"""注册表路径（项目根；jdyw-hx 放用户 appdata，本 CLI 工具放项目内，
便于随项目分发与版本管理）。"""

model_pkgs = {"wheeltec_03": wheeltec_03}
"""机型 → 机型包（**唯一的跨模型登记点**：新增机型只改这一行）。
机型包自报 parser/解帧器/词表/电池量程/控制声明——装配根不判断内容。"""


class AppComposition:
    """装配根：持有注册表与全部机器人链路。"""

    def __init__(self, robots_path: Path = ROBOTS_JSON) -> None:
        self.catalog = RobotCatalog(robots_path)
        # 注册表里出现未登记的机型 → 显形告警，不让"漏登记"变成静默没数据
        # （jdyw-hx 同款纪律）。
        _unknown = {s.model for s in self.catalog.table.values()} \
            - set(model_pkgs)
        if _unknown:
            logger.error("机型 %s 未在装配根登记（model_pkgs 缺行）——"
                         "该机型的数据链路不可用", ", ".join(sorted(_unknown)))
        self._links: dict[str, RobotLink] = {}

    def make_link(self, robot_id: str) -> RobotLink:
        """为某台机器人建链路（未 start；订阅哪些能力词由 start(caps=…)
        决定，None = 机型表全集）。"""
        spec = self.catalog.table.get(robot_id)
        if spec is None:
            raise KeyError(f"未知机器人: {robot_id}（注册表: "
                           f"{sorted(self.catalog.table)}）")
        pkg = model_pkgs.get(spec.model)
        if pkg is None:
            raise KeyError(f"机型 {spec.model!r} 未在装配根登记")
        topics = {cap: decl
                  for pipe in pkg.TOPICS.values() for cap, decl in pipe.items()}
        commands = {verb: decl
                    for pipe in pkg.COMMANDS.values()
                    for verb, decl in pipe.items()}

        def _parse(cap: str, msg):
            # 能力词 → 管道反查：TOPICS 是两级的（pipe → cap → decl）
            for pipe, pipe_caps in pkg.TOPICS.items():
                if cap in pipe_caps:
                    parser = pkg.parser_for(pipe, cap)
                    return parser(cap, msg) if parser is not None else None
            return None

        link = RobotLink(robot_id, spec, topics=topics, commands=commands,
                         parser=_parse)
        self._links[robot_id] = link
        return link

    def stop_all(self) -> None:
        for link in tuple(self._links.values()):
            try:
                link.stop()
            except Exception:
                logger.exception("链路停止异常")
        self._links.clear()
