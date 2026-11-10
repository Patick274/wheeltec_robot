# CHANGELOG

## 0.1.0（2026-11-10）

- 初始搭建：仿制 jdyw-hx 机型包架构的精简 CLI 客户端，落地于
  `PHM/src/wheeltec-hx/`。
- 机型包 `wheeltec_03`（轮式升降机器人）接入：话题表/指令表/parser/
  解帧/机型自报全套；模型资源（7×STL + URDF）复制自机器人侧
  `wheeltec_robot` 包。
- 话题/指令表来源：机器人侧 catkin 工作空间离线阅读（PHM/src，
  `turn_on_wheeltec_robot` + `kinco_lift_control` + `usb_cam`），
  **待真机自省核实**（docs/onboarding.md §二）。
- 交付提示词.txt 方法论的两份示例脚本：`scripts/introspection_probe.py`
  （5a 通用无资料探测）、`scripts/verify_wheeltec_03.py`（5b 实机对账）。
- 测试：机型契约机械校验 + parser/decode 纯数据测试（无需 ROS/真机）。
