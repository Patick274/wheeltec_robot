"""wheeltec-hx CLI 入口：监视链路 + 上行指令。

用法（项目根下）：
    python -m app.main list                          # 列出注册表机器人
    python -m app.main monitor [robot_id]            # 订阅全部遥测并打印
    python -m app.main endpoint <robot_id> <ws://…>  # 配置 rosbridge 地址
    python -m app.main cmd <robot_id> <verb> '<json-args>'   # 上行指令
    python -m app.main vel <robot_id> <linear> <angular>     # 速度（带看门狗）

运行方式见 scripts/run.sh / run.ps1（设置 PYTHONPATH=src 后调本模块）。
"""

from __future__ import annotations

import json
import logging
import sys
import time

from app.composition import AppComposition, model_pkgs
from core.features.robot import (CameraFrame, RobotDescriptionFrame,
                                 TelemetryFrame, TfFrame)

logger = logging.getLogger("wheeltec-hx")


def _fmt_frame(frame) -> str | None:
    """帧 → 一行打印文本（None = 不打印该帧，如高频相机）。"""
    from core.features.robot.wheeltec_03 import (JointStateFrame,
                                                 LiftStateFrame)
    if isinstance(frame, RobotDescriptionFrame):
        return (f"[{frame.robot_id}] URDF 装配描述到达：{len(frame.xml)} 字符"
                f"，片段: {frame.xml[:120]!r}…")
    if isinstance(frame, TfFrame):
        tag = "静态" if frame.is_static else "动态"
        lines = [f"[{frame.robot_id}] TF({tag}) ×{len(frame.pairs)}:"]
        for parent, child, xyz, quat in frame.pairs[:5]:
            lines.append(f"    {parent} → {child}  t={tuple(round(v, 3) for v in xyz)}"
                         f"  q={tuple(round(v, 3) for v in quat)}")
        if len(frame.pairs) > 5:
            lines.append(f"    …（其余 {len(frame.pairs) - 5} 条略）")
        return "\n".join(lines)
    if isinstance(frame, TelemetryFrame):
        return f"[{frame.robot_id}] 遥测 {frame.fields}"
    if isinstance(frame, LiftStateFrame):
        s = frame.status
        keys = ("busy", "position_mm", "top_height_m", "enabled",
                "at_lower_limit", "at_upper_limit", "fault")
        shown = {k: s[k] for k in keys if k in s}
        return f"[{frame.robot_id}] 升降柱状态 {shown or s}"
    if isinstance(frame, JointStateFrame):
        return f"[{frame.robot_id}] 关节 {frame.joints}"
    if isinstance(frame, CameraFrame):
        return None                                # 高频帧不刷屏
    return f"[{frame.robot_id}] ? {type(frame).__name__}"


def cmd_monitor(comp: AppComposition, robot_id: str) -> int:
    pkg = model_pkgs[comp.catalog.table[robot_id].model]
    link = comp.make_link(robot_id)
    link.set_on_frame(lambda rid, meta, raw: _print_frame(pkg, rid, meta, raw))
    link.set_on_online(lambda rid, on: print(f"== [{rid}] "
                                             f"{'在线' if on else '离线'} =="))
    print(f"连接 {comp.catalog.table[robot_id].endpoint} …（Ctrl+C 退出）")
    try:
        link.start()
    except ConnectionError as exc:
        print(f"连接失败：{exc}", file=sys.stderr)
        return 2
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        comp.stop_all()
    return 0


def _print_frame(pkg, robot_id: str, meta: dict, raw: bytes) -> None:
    frame = pkg.decode(robot_id, meta, raw)
    if frame is None:
        return
    text = _fmt_frame(frame)
    if text:
        print(text, flush=True)


def cmd_send(comp: AppComposition, robot_id: str, verb: str,
             args_json: str) -> int:
    pkg = model_pkgs[comp.catalog.table[robot_id].model]
    # 白名单提示：未声明的 verb 在 RobotLink 里会拒，这里先给出可选清单
    known = {v for pipe in pkg.COMMANDS.values() for v in pipe}
    if verb not in known:
        print(f"机型未声明指令 {verb!r}；已声明: {sorted(known)}",
              file=sys.stderr)
        return 2
    args = json.loads(args_json) if args_json else {}
    link = comp.make_link(robot_id)
    try:
        link.start(caps=())                       # 只发指令不需要订阅
    except ConnectionError as exc:
        print(f"连接失败：{exc}", file=sys.stderr)
        return 2
    try:
        result = link.send_command(verb, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    finally:
        comp.stop_all()


def main(argv: list[str]) -> int:
    # Windows 控制台默认非 UTF-8 代码页 → 中文输出先兜底（Git Bash/旧 cmd）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    comp = AppComposition()
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    op = argv[1]
    if op == "list":
        for e in comp.catalog.entries():
            print(f"{e.robot_id}\t机型={e.model}\t协议={e.protocol}"
                  f"\tendpoint={e.endpoint or '(未配置)'}")
        return 0
    if op == "endpoint" and len(argv) == 4:
        comp.catalog.set_endpoint(argv[2], argv[3])
        print(f"{argv[2]} endpoint → {argv[3]}（已落盘 robots.json）")
        return 0
    if op == "monitor":
        robot_id = argv[2] if len(argv) > 2 else "wheeltec_03"
        return cmd_monitor(comp, robot_id)
    if op == "cmd" and len(argv) >= 4:
        return cmd_send(comp, argv[2], argv[3],
                        argv[4] if len(argv) > 4 else "")
    if op == "vel" and len(argv) == 5:
        args = {"linear": {"x": float(argv[3])},
                "angular": {"z": float(argv[4])}, "ttl_ms": 500}
        return cmd_send(comp, argv[2], "velocity", json.dumps(args))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
