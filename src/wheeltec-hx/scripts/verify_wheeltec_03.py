#!/usr/bin/env python3
"""**示例 5b：wheeltec_03 实机读取脚本**（只依赖 roslibpy，可在无 ROS
环境的客户端运行）。

定位：已经知道要读"机器人模型描述 + 坐标系变换 + 升降柱状态"这三个
目标时，直接拿来用的可运行脚本；同时把 wheeltec_03 机型包的离线图
（话题名/类型，来源见下）与真机自省结果逐条对账——**这就是机型表
"待真机核实"标注的清除工具**：全部对上后，去
`src/core/features/robot/wheeltec_03/_topics.py` 把"待核实"段删掉。

**下列话题名/类型的来源声明**（提示词.txt 纪律：不许凭空假设）：
- 取自机器人侧 catkin 工作空间源码的**离线阅读**（PHM/src，
  2026-11-10）：`turn_on_wheeltec_robot`（/robot_description 经
  robot_state_publisher、/tf、/tf_static、/PowerVoltage、/odom）、
  `kinco_lift_control`（/lift/status 等）。
- 本脚本运行时还会经 rosbridge 自省服务**在线复核**每个话题的存在性
  与类型，打印对账表——对不上的行标 ✗ 并给出真机实际值。

用法：python verify_wheeltec_03.py --host 192.168.1.100 [--port 9090]
"""

from __future__ import annotations

import argparse
import json
import sys
import threading

# -- 离线读取得出、待本脚本在线复核的期望值（来源见模块 docstring）-------------
EXPECTED = {
    "/robot_description": "std_msgs/String",
    "/tf": "tf2_msgs/TFMessage",
    "/tf_static": "tf2_msgs/TFMessage",
    "/PowerVoltage": "std_msgs/Float32",
    "/odom": "nav_msgs/Odometry",
    "/joint_states": "sensor_msgs/JointState",
    "/lift/status": "std_msgs/String",
    "/lift/position_mm": "std_msgs/Float64",
    "/lift/top_height_m": "std_msgs/Float64",
}


def _norm(t: str) -> str:
    parts = (t or "").split("/")
    return f"{parts[0]}/{parts[-1]}" if len(parts) >= 2 else (t or "")


def reconcile(ros) -> bool:
    """离线期望表 × 在线自省结果 → 对账表。返回是否全部对上。"""
    topics = sorted(ros.get_topics())
    ok = True
    print("\n══ 话题对账（离线期望 × 在线自省）══")
    for topic, want in EXPECTED.items():
        if topic not in topics:
            print(f"  ✗ {topic}: 不在线（期望 {want}）")
            ok = False
            continue
        got = ros.get_topic_type(topic)
        mark = "✓" if _norm(got) == _norm(want) else "✗"
        if mark == "✗":
            ok = False
        print(f"  {mark} {topic}: {got}"
              + ("" if mark == "✓" else f"（期望 {want}）"))
    extra = [t for t in topics if t not in EXPECTED
             and not t.startswith("/ros")]
    if extra:
        print(f"  ＋ 真机上还有未登记话题 {len(extra)} 个（按需扩机型表）: "
              f"{extra[:10]}{'…' if len(extra) > 10 else ''}")
    return ok


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):      # Windows 控制台中文兜底
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=9090)
    ap.add_argument("--duration", type=float, default=8.0,
                    help="订阅观察时长（秒）")
    args = ap.parse_args(argv[1:])

    import roslibpy
    ros = roslibpy.Ros(host=args.host, port=args.port)
    ros.run()
    if not ros.is_connected:
        print(f"连不上 {args.host}:{args.port}", file=sys.stderr)
        return 2

    done = threading.Event()
    state: dict = {"urdf": None, "tf": [], "tf_static": [], "lift": None,
                   "voltage": None, "odom": None}

    def on_urdf(msg):
        if state["urdf"] is None:
            state["urdf"] = msg.get("data", "")
            print(f"\n[目标A] robot_description 到达: {len(state['urdf'])} 字符")
            print(f"  片段: {state['urdf'][:200]!r}")

    def on_tf(msg):
        state["tf"].append(msg)

    def on_tf_static(msg):
        state["tf_static"].append(msg)

    def on_lift(msg):
        try:
            state["lift"] = json.loads(msg.get("data", "{}"))
        except ValueError:
            state["lift"] = {"_raw": msg.get("data", "")[:200]}

    def on_voltage(msg):
        state["voltage"] = msg.get("data")

    def on_odom(msg):
        tw = (msg.get("twist") or {}).get("twist") or {}
        state["odom"] = ((tw.get("linear") or {}).get("x"),
                         (tw.get("angular") or {}).get("z"))

    subs = [
        roslibpy.Topic(ros, "/robot_description", "std_msgs/String"),
        roslibpy.Topic(ros, "/tf", "tf2_msgs/TFMessage", queue_size=10),
        roslibpy.Topic(ros, "/tf_static", "tf2_msgs/TFMessage"),
        roslibpy.Topic(ros, "/lift/status", "std_msgs/String"),
        roslibpy.Topic(ros, "/PowerVoltage", "std_msgs/Float32"),
        roslibpy.Topic(ros, "/odom", "nav_msgs/Odometry", queue_size=1,
                       throttle_rate=200),
    ]
    cbs = [on_urdf, on_tf, on_tf_static, on_lift, on_voltage, on_odom]
    try:
        for sub, cb in zip(subs, cbs):
            sub.subscribe(cb)
        print(f"已连接 {args.host}:{args.port}，观察 {args.duration}s …")
        reconcile(ros)
        done.wait(args.duration)

        print("\n══ 目标 B：坐标系变换 ══")
        for tag, key in (("动态 /tf", "tf"), ("静态 /tf_static", "tf_static")):
            msgs = state[key]
            print(f"{tag}: 收到 {len(msgs)} 帧")
            if msgs:
                transforms = msgs[-1].get("transforms", [])
                print(f"  最新帧变换数: {len(transforms)}")
                for t in transforms[:3]:
                    parent = (t.get("header") or {}).get("frame_id", "?")
                    child = t.get("child_frame_id", "?")
                    tr = (t.get("transform") or {}).get("translation") or {}
                    ro = (t.get("transform") or {}).get("rotation") or {}
                    print(f"  {parent} → {child}  t=({tr.get('x', 0):.3f}, "
                          f"{tr.get('y', 0):.3f}, {tr.get('z', 0):.3f})  "
                          f"q=({ro.get('x', 0):.3f}, {ro.get('y', 0):.3f}, "
                          f"{ro.get('z', 0):.3f}, {ro.get('w', 1):.3f})")
        if not state["tf_static"]:
            print("  （静态变换为 latch 话题：若一帧未到，检查机器人侧 "
                  "static_transform_publisher / robot_state_publisher 在跑）")

        print("\n══ 升降柱与遥测 ══")
        print(f"  /lift/status: {json.dumps(state['lift'], ensure_ascii=False)}"
              if state["lift"] else "  /lift/status: 未收到（lift 节点在跑？）")
        print(f"  /PowerVoltage: {state['voltage']}"
              f"  /odom twist: {state['odom']}")
    finally:
        for sub in subs:
            try:
                sub.unsubscribe()
            except Exception:
                pass
        ros.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
