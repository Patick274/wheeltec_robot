# 机型接入与真机验证流程（onboarding）

本文档回答两件事：**(1) 新机型怎么导入本软件**（仿制 jdyw-hx 的接入
模式）；**(2) wheeltec_03 的离线推导话题表怎么在真机上核实**（提示
词.txt"无文档动态对接"方法论在本项目的落地）。

## 一、新机型导入五步法

以已完成的 `wheeltec_03` 为样板：

1. **机型包**：新建 `src/core/features/robot/<机型id>/`，五个文件
   （`_topics.py` 话题/指令表、`_worker.py` parser 集、`_decode.py`
   解帧、`_frames.py` 私有帧、`_service.py` 自报）+ `__init__.py`
   出口面。契约由 `test/test_model_contract.py` 机械守住——新机型加
   进来自动被它遍历校验。
2. **模型资源**：STL/URDF 放 `resource/model/<机型id>/`
   （wheeltec_03 的来自机器人侧 `wheeltec_robot` 包，2026-11-10 复制）。
3. **装配根登记**：`src/app/composition.py` 的 `model_pkgs` 加一行
   （**唯一的跨机型登记点**）。
4. **注册表加实例**：`robots.json` 加一行（robot_id / model /
   endpoint）。
5. **跑测试**：`scripts/test.sh`——契约测试 + 机型 parser/decode 测试
   全绿才算接入完成。

## 二、wheeltec_03 话题表的真机核实（待办）

当前 `_topics.py` 的话题名/类型来自**离线阅读机器人侧源码**
（PHM/src，2026-11-10），标注了"待真机核实"。核实步骤：

### 前置（机器人侧，一次性）

1. 机器人开机，确认 ROS1 环境正常（`rostopic list` 能出清单）；
2. 确认 rosbridge 在跑：`roslaunch rosbridge_server rosbridge_websocket.launch`
   （默认 9090 端口；`netstat -tlnp | grep 9090` 确认监听）；
3. 确认客户端电脑与机器人同局域网、能 ping 通。

### 核实（客户端侧，无 ROS 环境也能跑）

```bash
# 1. 配置注册表里的机器人地址
scripts/run.ps1 endpoint wheeltec_03 ws://<机器人IP>:9090

# 2. 通用自省探测（示例5a）：纯自省链路发现话题/服务/类型/字段树
python scripts/introspection_probe.py --host <机器人IP> --scan
python scripts/introspection_probe.py --host <机器人IP> --topic /robot_description
python scripts/introspection_probe.py --host <机器人IP> --service /lift/jog

# 3. 实机对账（示例5b）：离线期望表 × 在线自省，逐条 ✓/✗
python scripts/verify_wheeltec_03.py --host <机器人IP>

# 4. 全链路监视：走一遍真实的 parser→decode→帧 链
scripts/run.ps1 monitor wheeltec_03
```

### 核实后的回填清单

- [ ] `_topics.py` 头部"待真机核实"段：逐条对账后删除；
- [ ] `_service.py` 的 `VELOCITY_LINEAR_MAX/ANGULAR_MAX`（TODO：按
      实测车速回填；注意机器人侧 100rpm 升降联锁限速）；
- [ ] `_service.py` 的 `BATTERY_EMPTY_V/FULL_V`（TODO：对照
      /PowerVoltage 满充/放空读数回填；"24V" 电池按 7S 暂填 21.0–29.4）；
- [ ] 若真机发现了 action 服务端（自省 `--scan` 可见）：族
      `_worker.RobotLink.send_command` 补 `action` kind，再进 COMMANDS。

## 三、注意事项（离线阅读阶段已观察到的）

1. **升降-底盘联锁**：底盘节点在升降未给许可时强制零速
   （`wheeltec_robot.cpp` 的 /lift/base_motion_request/permit 机制）——
   上位机发速度底盘不动时，先查 /lift/status，这是安全特性不是故障。
2. **/cmd_vel 经过 twist_mux 仲裁**（手柄优先级高于本链路）——摇杆
   在用时上位机速度指令可能被压制。
3. **/lift/status 是 latch 的 JSON 串**（std_msgs/String 承载），
   字段集以 lift_node.py 的 publish() 为准，本侧 dict 透传不逐字段建模。
4. **启动默认只读**：升降柱要先 /lift/enable 才能动（机器人侧安全
   设计，README 明确）。
