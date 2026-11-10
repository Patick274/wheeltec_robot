"""wheeltec_03 机型私有帧（族层不认识的帧类型住这里）。

判据（仿 jdyw-hx 机型包契约）：不是所有机型都可能有的帧 = 机型私有。
升降柱状态、轮关节状态是本机型特有——别的机型可能有臂关节帧
（jdyw_01 的 JointStateFrame 是同名词不同物），互不参照。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LiftStateFrame:
    """升降柱状态全貌（/lift/status 的 JSON 解析结果）。

    字段集以机器人侧 `kinco_lift_control/scripts/lift_node.py` 的
    publish() 为准（busy/position_mm/top_height_m/限位/报警/会话零点等），
    本帧不逐字段建模——机器人侧加字段本侧自动可见（dict 透传），
    消费方按名取，缺字段显示"—"（缺数据是正常态，不是错误）。
    """

    robot_id: str
    status: dict = field(default_factory=dict)
    timestamp_ms: int = 0


@dataclass(frozen=True, slots=True)
class JointStateFrame:
    """关节状态（本机型 = 左右轮 continuous 关节的零位发布）。

    名字与 jdyw_01 的机型私有帧同名是巧合——那边是 6 轴臂+夹爪，这边是
    两个轮子；同名话题不同数据正是"机型包各自一份、互不参照"的理由。
    """

    robot_id: str
    joints: dict = field(default_factory=dict)   # name → position(rad)
    timestamp_ms: int = 0
