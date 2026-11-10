"""wheeltec_03 机型自报（仿 jdyw-hx 机型 `_service.py`）。

机型硬件参数与能力词表的全部出口——装配根经这些函数收齐注入消费方，
**通用代码不得知道"这台车是几串电芯/能跑多快/有哪些部件"**，换机型
只换本包。族父级禁 import 机型子级，装配根是唯一合法跨层编排者。

数值来源标注纪律：实测值注明出处，待核实的标 TODO（首次上机验证时
按 docs/onboarding.md 核实并回填）。
"""

from __future__ import annotations

PIPE_IMAGE = "image"
PIPE_TELEMETRY = "telemetry"


def camera_sources() -> tuple[str, ...]:
    """本机型相机能力词（新增相机 = `_topics.py` 加映射行）。"""
    from ._topics import TOPICS
    return tuple(TOPICS.get("image", {}))


def meta_caps() -> tuple[str, ...]:
    """本机型 telemetry 管道声明的能力词（订阅闸门的合法值域）。"""
    from ._topics import TOPICS
    return tuple(TOPICS.get(PIPE_TELEMETRY, {}))


def controllable_parts() -> tuple[str, ...]:
    """本机型可独立控制的部件（部件占用注册表的合法值域）。

    底盘 + 升降柱两条独立控制粒度（摇杆控底盘、升降面板控柱）并存。
    """
    return ("chassis", "lift")


def control_commands() -> dict:
    """本机型全部上行指令表（管道 → verb → 声明）——控制白名单全集。"""
    from ._topics import COMMANDS
    return COMMANDS


def velocity_channel() -> dict | None:
    """速度通道声明（话题/消息/QoS/安全值）；无该通道 → None。"""
    from ._topics import COMMANDS
    return COMMANDS.get(PIPE_TELEMETRY, {}).get("velocity")


# TODO(待真机核实): 底盘速度上限。机器人侧文档（kinco_lift_control
# README）提到"底盘运动 100rpm 上限"的升降联锁限速，轮径/减速比未定，
# m/s 换算待实测。先按 jdyw_02 的保守值填，上机后按实测调整。
VELOCITY_LINEAR_MAX = 0.3
VELOCITY_ANGULAR_MAX = 0.5


def velocity_limits() -> dict[str, float]:
    """底盘速度上限（摇杆归一值 → 物理量的换算上限）。"""
    return {"linear": VELOCITY_LINEAR_MAX, "angular": VELOCITY_ANGULAR_MAX}


# TODO(待真机核实): 电池量程。购物清单（AGV升降机构购物清单_CAN版.xlsx）
# 列的是 24V30Ah / 24V50Ah 电池；"24V" 锂电通常是 7S（标称 25.9V，
# 满 29.4V），先按 7S 填。上机后对照 /PowerVoltage 满充读数回填。
BATTERY_EMPTY_V = 21.0
BATTERY_FULL_V = 29.4


def voltage_range() -> tuple[float, float]:
    """本机型电池量程 (空电压, 满电压)，单位 V。"""
    return (BATTERY_EMPTY_V, BATTERY_FULL_V)


def supported_protocols() -> tuple[str, ...]:
    """本机型机器人端支持的通信腿。

    只有 roslibpy：本机型是 ROS1（Noetic）机器人，rclpy（ROS2/DDS）
    腿物理上连不上——这是机器人侧能力的声明，与上位机装没装 ROS2 无关。
    """
    return ("roslibpy",)


def demo_actions() -> tuple[dict, ...]:
    """本机型演示动作清单：无（显式声明，不是缺席）。"""
    return ()
