"""机型包契约的机械校验（仿 jdyw-hx test/core/features/robot/test_model_contract.py）。

把"新增机型要满足什么"从文档变成跑得了的断言：出口面齐全、话题表/
指令表形状合法、parser 覆盖每个订阅能力词、自报函数之间一致。
新增机型时本测试自动覆盖它（遍历装配根的 model_pkgs）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from app.composition import model_pkgs
from core.features.robot._worker import to_rosbridge_type

MODEL_IDS = sorted(model_pkgs)


def _pkg(model):
    return model_pkgs[model]


def test_registry_nonempty():
    assert MODEL_IDS, "装配根 model_pkgs 为空——一台机型都没登记"


@pytest.mark.parametrize("model", MODEL_IDS)
def test_export_surface(model):
    """机型包出口面（装配根与消费方按这些名字消费）。"""
    pkg = _pkg(model)
    for name in ("TOPICS", "COMMANDS", "parser_for", "decode",
                 "camera_sources", "meta_caps", "voltage_range",
                 "velocity_channel", "velocity_limits", "controllable_parts",
                 "control_commands", "demo_actions", "supported_protocols"):
        assert hasattr(pkg, name), f"{model} 缺出口 {name}"


@pytest.mark.parametrize("model", MODEL_IDS)
def test_topics_shape(model):
    """TOPICS：pipe → cap → {topic, msg, qos}；msg 是 rosidl 三段名；
    qos 合法；start_after 指向同表能力词。"""
    for pipe, caps in _pkg(model).TOPICS.items():
        assert isinstance(pipe, str) and pipe
        for cap, decl in caps.items():
            assert decl["topic"].startswith("/"), f"{model}.{cap} 话题名"
            parts = decl["msg"].split("/")
            assert len(parts) == 3 and parts[1] == "msg", \
                f"{model}.{cap} 消息类型应为 pkg/msg/Type: {decl['msg']}"
            assert decl["qos"] in ("default", "sensor_data",
                                   "transient_local")
            gate = decl.get("start_after")
            if gate is not None:
                assert any(gate in p2 for p2 in _pkg(model).TOPICS.values()), \
                    f"{model}.{cap} start_after={gate!r} 不在本机型话题表"


@pytest.mark.parametrize("model", MODEL_IDS)
def test_commands_shape(model):
    """COMMANDS：kind 合法；topic 行有 msg+zero；service 行有 srv。"""
    for pipe, verbs in _pkg(model).COMMANDS.items():
        for verb, decl in verbs.items():
            kind = decl.get("kind")
            assert kind in ("topic", "service", "action", "action_cancel"), \
                f"{model}.{verb} kind={kind!r}"
            if kind == "topic":
                assert decl["topic"].startswith("/")
                assert len(decl["msg"].split("/")) == 3
                if "zero" in decl:
                    assert isinstance(decl["zero"], dict)
            if kind == "service":
                assert decl["service"].startswith("/")
                assert decl["srv"].split("/")[1] == "srv"


@pytest.mark.parametrize("model", MODEL_IDS)
def test_parser_covers_every_cap(model):
    """每个订阅能力词都有 parser（漏了就是静默没数据）。"""
    pkg = _pkg(model)
    for pipe, caps in pkg.TOPICS.items():
        for cap in caps:
            assert pkg.parser_for(pipe, cap) is not None, \
                f"{model}: {pipe}/{cap} 无 parser"


@pytest.mark.parametrize("model", MODEL_IDS)
def test_self_report_consistency(model):
    """自报函数一致：meta_caps == telemetry 词表；velocity_channel 指回
    COMMANDS；电池量程空<满；supported_protocols 非空。"""
    pkg = _pkg(model)
    assert set(pkg.meta_caps()) == set(pkg.TOPICS.get("telemetry", {}))
    vc = pkg.velocity_channel()
    if vc is not None:
        assert vc is pkg.COMMANDS["telemetry"]["velocity"]
    lo, hi = pkg.voltage_range()
    assert 0 < lo < hi, f"{model} 电池量程异常: {lo}/{hi}"
    assert pkg.supported_protocols(), f"{model} 未声明任何通信腿"
    assert set(pkg.camera_sources()) == set(pkg.TOPICS.get("image", {}))
    # 可控部件与 COMMANDS 的 parts 值域一致
    parts = set(pkg.controllable_parts())
    for pipe in pkg.COMMANDS.values():
        for decl in pipe.values():
            assert set(decl.get("parts", [])) <= parts


def test_type_name_conversion():
    assert to_rosbridge_type("std_msgs/msg/String") == "std_msgs/String"
    assert to_rosbridge_type("tf2_msgs/msg/TFMessage") == "tf2_msgs/TFMessage"
    assert to_rosbridge_type("kinco_lift_control/srv/JogLift") == \
        "kinco_lift_control/JogLift"
    assert to_rosbridge_type("std_msgs/String") == "std_msgs/String"  # 幂等
