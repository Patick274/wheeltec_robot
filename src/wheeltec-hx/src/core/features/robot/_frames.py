"""族层帧类型：worker 解析 → 解帧后的纯数据帧（仿 jdyw-hx `_frames.py`）。

帧是**主进程侧的通用货币**：ROS 消息类型止步于机型包的 parser/解帧器，
消费方（CLI/状态存储/将来的 UI）只见这些 frozen dataclass。

族层只放**所有机型都可能有的帧**；机型私有帧（如轮式升降机的升降柱
状态帧）住机型包 `_frames.py`——族层不认识它们，路由按类型分发即可。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RobotDescriptionFrame:
    """装配描述（URDF XML 全文）。"""

    robot_id: str
    xml: str


@dataclass(frozen=True, slots=True)
class TfFrame:
    """坐标系变换批：((parent, child, (x,y,z), (qx,qy,qz,qw)), …)。

    is_static=True 来自 /tf_static（latch，装配关系）；
    False 来自 /tf（动态，定位链/升降柱等）。
    """

    robot_id: str
    pairs: tuple
    is_static: bool = False


@dataclass(frozen=True, slots=True)
class TelemetryFrame:
    """轻量遥测：fields 词典（voltage / linear_x / angular_z …，见机型表）。

    兼作在线心跳源：power_voltage 是必配项，消费方按 6s 无帧判离线
    （jdyw-hx 实测口径，沿用）。
    """

    robot_id: str
    fields: dict = field(default_factory=dict)
    timestamp_ms: int = 0


@dataclass(frozen=True, slots=True)
class CameraFrame:
    """相机帧（JPEG 字节；不解码——"不显示不解码"）。"""

    robot_id: str
    channel: str
    encoding: str
    data: bytes
    width: int = 0
    height: int = 0
    timestamp_ms: int = 0
