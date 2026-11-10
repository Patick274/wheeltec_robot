"""wheeltec_03 parser / decode 的纯数据测试（不需要 ROS/真机）。

样本消息按 rosbridge 的 JSON 形态构造（dict）；字段结构来自机器人侧
源码的离线阅读（PHM/src，2026-11-10），真机核实后如有出入改样本。
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.features.robot import (RobotDescriptionFrame, TelemetryFrame,
                                 TfFrame)
from core.features.robot.wheeltec_03 import (JointStateFrame, LiftStateFrame,
                                             TOPICS, decode, parser_for)


def _parse(pipe, cap, msg):
    return parser_for(pipe, cap)(cap, msg)


def _roundtrip(pipe, cap, msg, robot_id="wheeltec_03"):
    """parser → (meta, raw) → decode → 帧（两段式契约的完整走查）。"""
    out = _parse(pipe, cap, msg)
    assert out is not None, f"{pipe}/{cap} parser 丢帧"
    meta, raw = out
    return decode(robot_id, meta, raw)


def test_robot_description_roundtrip():
    frame = _roundtrip("telemetry", "robot_description",
                       {"data": "<robot name='wheeltec'/>"})
    assert isinstance(frame, RobotDescriptionFrame)
    assert frame.xml == "<robot name='wheeltec'/>"


def test_tf_roundtrip():
    msg = {"transforms": [{
        "header": {"frame_id": "odom_combined"},
        "child_frame_id": "base_footprint",
        "transform": {"translation": {"x": 1.0, "y": 2.0, "z": 0.0},
                      "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}]}
    frame = _roundtrip("telemetry", "tf", msg)
    assert isinstance(frame, TfFrame) and not frame.is_static
    parent, child, xyz, quat = frame.pairs[0]
    assert (parent, child) == ("odom_combined", "base_footprint")
    assert xyz == (1.0, 2.0, 0.0) and quat == (0.0, 0.0, 0.0, 1.0)

    static_frame = _roundtrip("telemetry", "tf_static", msg)
    assert static_frame.is_static


def test_tf_empty_transforms_dropped():
    assert _parse("telemetry", "tf", {"transforms": []}) is None


def test_power_voltage_never_filtered():
    """心跳源绝不丢帧、不过滤数值（NaN 照实上报）。"""
    frame = _roundtrip("telemetry", "power_voltage", {"data": 25.9})
    assert isinstance(frame, TelemetryFrame)
    assert frame.fields == {"voltage": 25.9}
    nan_frame = _roundtrip("telemetry", "power_voltage",
                           {"data": float("nan")})
    assert nan_frame is not None  # NaN 也出帧——异常照实上报，不伪装成缺失


def test_odom_twist_only():
    """odom 只取 twist（位姿权威是 TF，不走第二条路）。"""
    msg = {"pose": {"pose": {"position": {"x": 9.9}}},
           "twist": {"twist": {"linear": {"x": 0.21},
                               "angular": {"z": -0.1}}}}
    frame = _roundtrip("telemetry", "odom", msg)
    assert frame.fields == {"linear_x": 0.21, "angular_z": -0.1}


def test_lift_status_roundtrip():
    payload = {"busy": False, "position_mm": 0.0, "enabled": False}
    frame = _roundtrip("telemetry", "lift_status",
                       {"data": json.dumps(payload)})
    assert isinstance(frame, LiftStateFrame)
    assert frame.status == payload


def test_lift_status_non_json_degrades():
    frame = _roundtrip("telemetry", "lift_status", {"data": "not-json"})
    assert isinstance(frame, LiftStateFrame) and frame.status == {}


def test_lift_scalars():
    f1 = _roundtrip("telemetry", "lift_position_mm", {"data": 123.0})
    assert f1.fields == {"lift_position_mm": 123.0}
    f2 = _roundtrip("telemetry", "lift_top_height_m", {"data": 2.05})
    assert f2.fields == {"lift_top_height_m": 2.05}


def test_joint_states_roundtrip():
    msg = {"name": ["left_wheel_joint", "right_wheel_joint"],
           "position": [0.0, 0.0]}
    frame = _roundtrip("telemetry", "joint_states", msg)
    assert isinstance(frame, JointStateFrame)
    assert frame.joints == {"left_wheel_joint": 0.0, "right_wheel_joint": 0.0}


def test_camera_base64():
    """rosbridge 把 uint8[] 编成 base64——parser 必须还原。"""
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
    msg = {"format": "jpeg", "header": {"stamp": {"sec": 1, "nsec": 500}},
           "data": base64.b64encode(jpeg).decode()}
    out = _parse("image", "color", msg)
    meta, raw = out
    assert raw == jpeg and meta["encoding"] == "jpeg"


def test_every_topic_cap_decodes():
    """TOPICS 每个能力词的 parser 都能在最小样本上走通到 decode。"""
    samples = {
        "robot_description": {"data": "<robot/>"},
        "tf": {"transforms": [{"header": {"frame_id": "a"},
                               "child_frame_id": "b",
                               "transform": {"translation": {},
                                             "rotation": {}}}]},
        "tf_static": {"transforms": [{"header": {"frame_id": "a"},
                                      "child_frame_id": "b",
                                      "transform": {"translation": {},
                                                    "rotation": {}}}]},
        "power_voltage": {"data": 24.0},
        "odom": {"twist": {"twist": {"linear": {"x": 0.0},
                                     "angular": {"z": 0.0}}}},
        "imu": {"orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}},
        "joint_states": {"name": [], "position": []},
        "lift_status": {"data": "{}"},
        "lift_position_mm": {"data": 0.0},
        "lift_top_height_m": {"data": 0.0},
    }
    for pipe, caps in TOPICS.items():
        for cap in caps:
            sample = samples.get(cap)
            if pipe == "image":
                sample = {"format": "jpeg", "header": {},
                          "data": base64.b64encode(b"x").decode()}
            assert sample is not None, f"缺样本: {pipe}/{cap}"
            assert _roundtrip(pipe, cap, sample) is not None, \
                f"{pipe}/{cap} 全链路丢帧"


def test_decode_unknown_kind_once():
    assert decode("wheeltec_03", {"kind": "nope"}, b"") is None
