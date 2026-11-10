"""机器人注册表配置：RobotSpec + robots.json 读写（仿 jdyw-hx `_config.py`）。

注册表是"机器人实例 → 机型/连接方式"的唯一权威：
- robot_id（如 "wheeltec_03"）是实例名，一台实物机器人一行；
- model 指向机型包（装配根 model_pkgs 的键）；
- protocol 是连接腿（本软件只有 roslibpy 腿——本机型是 ROS1 机器人，
  rclpy 腿（ROS2/DDS）连不上；保留字段是为与 jdyw-hx 注册表同构）；
- endpoint 是 rosbridge 的 ws:// 地址（roslibpy 腿使用）。

与 jdyw-hx 的差异：jdyw-hx 的 endpoint 还有云端隧道等形态，本软件
只认 ws://host:port。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_PROTOCOLS = ("auto", "roslibpy")
"""合法协议值。auto = 按机型自报 supported_protocols 自动选（当前恒落到
roslibpy——唯一实现腿）。rclpy 不在列：本软件面向 ROS1 机器人。"""

DEFAULT_ENDPOINT = "ws://192.168.1.100:9090"
"""占位 endpoint——真机 IP 以现场为准，首次上机验证时改 robots.json。"""


@dataclass(frozen=True, slots=True)
class RobotSpec:
    """一台机器人的注册配置（纯数据）。"""

    model: str          # 机型包名（model_pkgs 的键，如 "wheeltec_03"）
    domain_id: int      # ROS2 域隔离概念，ROS1/roslibpy 腿不用，占位保同构
    protocol: str       # auto / roslibpy
    endpoint: str       # ws://host:port（rosbridge 监听地址）
    tls_ca: str = ""    # 预留（wss 场景）


DEFAULT_ROBOTS: dict[str, RobotSpec] = {
    "wheeltec_03": RobotSpec(model="wheeltec_03", domain_id=0,
                             protocol="roslibpy", endpoint=DEFAULT_ENDPOINT),
}


def load_robots(path: Path) -> dict[str, RobotSpec]:
    """读注册表；文件不存在 → 落一份默认表并返回（首次运行即见占位条目）。"""
    path = Path(path)
    if not path.exists():
        save_robots(DEFAULT_ROBOTS, path)
        return dict(DEFAULT_ROBOTS)
    raw = json.loads(path.read_text(encoding="utf-8"))
    table: dict[str, RobotSpec] = {}
    for robot_id, item in raw.items():
        protocol = str(item.get("protocol", "auto"))
        if protocol not in _PROTOCOLS:
            raise ValueError(f"{robot_id}: 非法协议 {protocol!r}（可选 {_PROTOCOLS}）")
        table[str(robot_id)] = RobotSpec(
            model=str(item["model"]),
            domain_id=int(item.get("domain_id", 0)),
            protocol=protocol,
            endpoint=str(item.get("endpoint", "")),
            tls_ca=str(item.get("tls_ca", "")))
    return table


def save_robots(table: dict[str, RobotSpec], path: Path) -> None:
    """原子写注册表（先写临时文件再替换，防半截文件）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = {rid: {"model": s.model, "domain_id": s.domain_id,
                 "protocol": s.protocol, "endpoint": s.endpoint,
                 "tls_ca": s.tls_ca}
           for rid, s in sorted(table.items())}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
