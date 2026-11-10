"""wheeltec_03 机型 parser（worker 侧）：ROS 消息 → (meta, raw)。

仿 jdyw-hx 机型 `_worker.py`：机型差异收敛为 _topics.py 映射表 + 本文件
的 parser 集；进程骨架/订阅闸门/补订/心跳全在族 `_worker.RobotLink`。

本软件是单进程 CLI（无 IPC），parser 与 decode 同进程顺序调用——但
(meta, raw) 两段式契约原样保留（见族 `_worker.py` 模块 docstring）。

roslibpy 回调给的是 dict（rosbridge JSON），jdyw-hx 的 parser 要兼容
rclpy 对象 + dict 双形态；本软件只有 roslibpy 腿，只处理 dict 形态，
`_field` 仍保留——将来接 rclpy 腿时不用重写。
"""

from __future__ import annotations

import json
import logging

from .._worker import as_bytes

logger = logging.getLogger(__name__)

_seen_unknown: set = set()
"""不支持/异常情形的已告警集合（每种只打一次，防刷屏——jdyw-hx 同款纪律）。"""


def _field(msg, name: str):
    """双形态取字段：roslibpy dict / （将来）rclpy 消息对象。"""
    if isinstance(msg, dict):
        return msg.get(name)
    return getattr(msg, name, None)


def parse_robot_description(cap: str, msg):
    """/robot_description（std_msgs/String）→ URDF XML 字节（原样透传）。"""
    data = _field(msg, "data")
    if data is None:
        return None
    return ({"kind": "robot_description"}, str(data).encode("utf-8"))


def parse_tf(cap: str, msg):
    """/tf 或 /tf_static（tf2_msgs/TFMessage）→ 扁平变换元组 JSON。

    归一为 ((parent, child, (x,y,z), (qx,qy,qz,qw)), …)——消费方不接触
    ROS 消息类型（jdyw-hx 同款扁平化，字段名与三维 set_pose 语义一致）。
    """
    transforms = _field(msg, "transforms") or []
    pairs = []
    for t in transforms:
        header = _field(t, "header") or {}
        parent = _field(header, "frame_id") or ""
        child = _field(t, "child_frame_id") or ""
        tf = _field(t, "transform") or {}
        tr = _field(tf, "translation") or {}
        ro = _field(tf, "rotation") or {}
        pairs.append([parent, child,
                      [float(tr.get("x", 0.0) if isinstance(tr, dict) else tr.x),
                       float(tr.get("y", 0.0) if isinstance(tr, dict) else tr.y),
                       float(tr.get("z", 0.0) if isinstance(tr, dict) else tr.z)],
                      [float(ro.get("x", 0.0) if isinstance(ro, dict) else ro.x),
                       float(ro.get("y", 0.0) if isinstance(ro, dict) else ro.y),
                       float(ro.get("z", 0.0) if isinstance(ro, dict) else ro.z),
                       float(ro.get("w", 1.0) if isinstance(ro, dict) else ro.w)]])
    if not pairs:
        return None
    return ({"kind": "tf", "static": cap == "tf_static"},
            json.dumps(pairs).encode("utf-8"))


def parse_power_voltage(cap: str, msg):
    """/PowerVoltage（std_msgs/Float32）→ 电压遥测帧。

    在线心跳的唯一来源（族 worker 按 6s 无帧判离线）——绝不丢帧、不做
    数值过滤：NaN/Inf 是机器人侧异常，照实上报（jdyw-hx 同款纪律）。
    """
    value = _field(msg, "data")
    if value is None:
        return None
    return {"kind": "telemetry", "fields": {"voltage": float(value)}}, b""


def parse_odom(cap: str, msg):
    """/odom（nav_msgs/Odometry）→ 速度遥测帧。

    只取 twist 的线速度 x 与角速度 z（差速底盘的两个自由度）；位姿权威
    是 TF，odom 的 pose 不走这条路（同一份数据走两条路会打架——jdyw-hx
    world_scene 口径，沿用）。
    """
    twist = _field(msg, "twist")
    inner = _field(twist, "twist") if twist is not None else None
    if inner is None:
        return None
    linear = _field(inner, "linear")
    angular = _field(inner, "angular")
    if linear is None or angular is None:
        return None
    get = (lambda o, k: o.get(k)) if isinstance(linear, dict) else getattr
    return {"kind": "telemetry",
            "fields": {"linear_x": float(get(linear, "x") or 0.0),
                       "angular_z": float(get(angular, "z") or 0.0)}}, b""


def parse_imu(cap: str, msg):
    """/imu（sensor_msgs/Imu）→ 姿态遥测帧（四元数原样，换算归消费方）。"""
    ori = _field(msg, "orientation")
    if ori is None:
        return None
    get = (lambda o, k: o.get(k)) if isinstance(ori, dict) else getattr
    return {"kind": "telemetry",
            "fields": {"orientation": [float(get(ori, k) or 0.0)
                                       for k in ("x", "y", "z", "w")]}}, b""


def parse_joint_states(cap: str, msg):
    """/joint_states（sensor_msgs/JointState）→ {关节名: 位置} JSON。"""
    names = _field(msg, "name") or []
    positions = _field(msg, "position") or []
    joints = {str(n): float(p) for n, p in zip(names, positions)}
    return ({"kind": "joint_states"},
            json.dumps(joints).encode("utf-8"))


def parse_lift_status(cap: str, msg):
    """/lift/status（std_msgs/String，latch JSON）→ 原样透传 JSON 字节。

    结构化解析归 decode（主进程侧）——worker 侧只做字节搬运，与
    robot_description 的"原样透传 XML"同一纪律。
    """
    data = _field(msg, "data")
    if data is None:
        return None
    return ({"kind": "lift_status"}, str(data).encode("utf-8"))


def parse_lift_scalar(cap: str, msg):
    """/lift/position_mm 与 /lift/top_height_m（std_msgs/Float64）→ 遥测字段。"""
    value = _field(msg, "data")
    if value is None:
        return None
    return {"kind": "telemetry", "fields": {cap: float(value)}}, b""


def parse_camera(cap: str, msg):
    """/image_raw/compressed（sensor_msgs/CompressedImage）→ JPEG 字节。

    只抽负载不解码（"不显示不解码"）；format 不是 jpeg 的丢帧+一次性告警
    （边界：出现真实 png 压缩话题时再扩）。
    """
    fmt = str(_field(msg, "format") or "").lower()
    if "jpeg" not in fmt and "jpg" not in fmt:
        if fmt not in _seen_unknown:
            _seen_unknown.add(fmt)
            logger.warning("parse_camera: 非 JPEG 格式 %r（丢帧）", fmt)
        return None
    raw = as_bytes(_field(msg, "data"))
    header = _field(msg, "header") or {}
    stamp = _field(header, "stamp") or {}
    sec = stamp.get("sec", 0) if isinstance(stamp, dict) else 0
    nsec = stamp.get("nanosec", stamp.get("nsec", 0)) \
        if isinstance(stamp, dict) else 0
    return ({"kind": "camera", "channel": cap, "encoding": "jpeg",
             "ts_ms": int(sec) * 1000 + int(nsec) // 1_000_000},
            raw)


_TELEMETRY_PARSERS = {
    "robot_description": parse_robot_description,
    "tf": parse_tf,
    "tf_static": parse_tf,
    "power_voltage": parse_power_voltage,
    "odom": parse_odom,
    "imu": parse_imu,
    "joint_states": parse_joint_states,
    "lift_status": parse_lift_status,
    "lift_position_mm": parse_lift_scalar,
    "lift_top_height_m": parse_lift_scalar,
}

_PIPE_PARSERS = {
    "image": parse_camera,
}


def parser_for(pipe: str, cap: str):
    """管道 × 能力词 → parser（telemetry 按能力词分派，数据管道按管道）。"""
    if pipe == "telemetry":
        return _TELEMETRY_PARSERS.get(cap)
    return _PIPE_PARSERS.get(pipe)
