"""wheeltec_03 解帧器：(meta, raw) → 帧对象。

纪律（仿 jdyw-hx 机型 `_decode.py`）：
- 只 import 族 `.._frames`、本包 `_frames`、stdlib——**禁止 import
  roslibpy / 本包 `_worker`**（ROS 依赖只许住 worker 侧）；
- 本函数不做话题名判断——话题名在 parser 侧已映射掉，这里只认本包
  自己的 kind 词汇表；
- 未知 kind → 每个 kind 告警一次（防刷屏）后返回 None 丢帧。
"""

from __future__ import annotations

import json
import logging

from .._frames import (CameraFrame, RobotDescriptionFrame, TelemetryFrame,
                       TfFrame)
from ._frames import JointStateFrame, LiftStateFrame

logger = logging.getLogger(__name__)

_seen_unknown: set = set()


def decode(robot_id: str, meta: dict, raw: bytes):
    """裸帧 → 帧类型；未知 kind → None（丢帧，有日志）。"""
    kind = meta.get("kind")
    if kind == "camera":
        return CameraFrame(
            robot_id=robot_id,
            channel=str(meta.get("channel", "")),
            encoding=str(meta.get("encoding", "jpeg")),
            data=bytes(raw),
            timestamp_ms=int(meta.get("ts_ms", 0)))
    if kind == "robot_description":
        return RobotDescriptionFrame(robot_id=robot_id,
                                     xml=raw.decode("utf-8"))
    if kind == "tf":
        pairs = tuple(
            (str(p[0]), str(p[1]), tuple(float(v) for v in p[2]),
             tuple(float(v) for v in p[3]))
            for p in json.loads(raw))
        return TfFrame(robot_id=robot_id, pairs=pairs,
                       is_static=bool(meta.get("static", False)))
    if kind == "telemetry":
        return TelemetryFrame(robot_id=robot_id,
                              fields=dict(meta.get("fields", {})),
                              timestamp_ms=int(meta.get("ts_ms", 0)))
    if kind == "lift_status":
        try:
            status = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("[%s] /lift/status 非 JSON（原样丢弃内容，"
                           "保留空状态）", robot_id)
            status = {}
        return LiftStateFrame(robot_id=robot_id, status=status)
    if kind == "joint_states":
        joints = {str(k): float(v) for k, v in json.loads(raw).items()}
        return JointStateFrame(robot_id=robot_id, joints=joints)
    if kind not in _seen_unknown:
        _seen_unknown.add(kind)
        logger.warning("wheeltec_03 decode: 未知 kind %r（丢帧）", kind)
    return None
