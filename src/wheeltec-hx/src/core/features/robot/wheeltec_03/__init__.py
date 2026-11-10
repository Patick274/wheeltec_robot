"""wheeltec_03 机型包 —— 轮式升降机器人（wheeltec 差速底盘 + kinco FD125
升降柱 + lslidar + usb_cam，ROS1 Noetic）业务的全部实现。

一条数据链路的完整形状在本包内闭环：话题表（_topics）→ 解析（_worker
的 parser 集）→ 解帧（_decode）→ 帧对象（族 _frames + 本包 _frames）。
族层不认识 meta["kind"]，也不认识任何机型私有帧——改话题名/剔字段/
换消息类型都只动本包。

对外面（装配根与测试按此消费，仿 jdyw-hx 机型包出口面）：
`TOPICS` / `COMMANDS` / `parser_for` / `decode` / `camera_sources` /
`meta_caps` / `voltage_range` / `velocity_channel` / `velocity_limits` /
`controllable_parts` / `control_commands` / `demo_actions` /
`supported_protocols`。
"""

from ._decode import decode
from ._frames import JointStateFrame, LiftStateFrame
from ._service import (camera_sources, controllable_parts, control_commands,
                       demo_actions, meta_caps, supported_protocols,
                       velocity_channel, velocity_limits, voltage_range)
from ._topics import COMMANDS, TOPICS
from ._worker import parser_for

__all__ = ["TOPICS", "COMMANDS", "parser_for", "decode",
           "LiftStateFrame", "JointStateFrame",
           "camera_sources", "meta_caps", "voltage_range",
           "velocity_channel", "velocity_limits", "controllable_parts",
           "control_commands", "demo_actions", "supported_protocols"]
