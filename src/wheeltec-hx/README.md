# wheeltec-hx

轮式升降机器人（机型 `wheeltec_03`：wheeltec 差速底盘 + kinco FD125
升降柱 + lslidar + usb_cam，ROS1 Noetic）的上位机客户端——**仿制
[jdyw-hx](../../jdyw-hx) 机型包架构**的精简实现：无 ROS 环境的电脑经
roslibpy + rosbridge 连接机器人，订阅遥测/模型描述/坐标变换/升降柱
状态，下发速度与升降指令。

## 快速开始

```bash
pip install roslibpy          # 唯一运行时依赖（开发加 pytest）

# 1. 配置机器人 rosbridge 地址（首次）
scripts/run.sh endpoint wheeltec_03 ws://<机器人IP>:9090

# 2. 监视链路（URDF / TF / 电压 / 里程计 / 升降柱状态实时打印）
scripts/run.sh monitor wheeltec_03

# 3. 上行指令（白名单见机型包 _topics.py 的 COMMANDS 表）
scripts/run.sh vel wheeltec_03 0.1 0.0                    # 速度（带看门狗）
scripts/run.sh cmd wheeltec_03 lift_enable '{"data": true}'
scripts/run.sh cmd wheeltec_03 lift_jog '{"distance_mm": 50, "speed_mm_s": 10}'
```

Windows 用 `scripts/run.ps1`（参数同）。真机验证流程见
[docs/onboarding.md](docs/onboarding.md)；架构与仿制差异见
[docs/architecture.md](docs/architecture.md)。

## 目录

```
├── docs/            架构说明 + 接入/验证流程
├── resource/model/wheeltec_03/   STL 网格 + URDF（复制自机器人侧 wheeltec_robot 包）
├── scripts/         run / test / 验证脚本（示例5a 通用自省探测、5b 实机对账）
├── src/app/         装配根（model_pkgs 机型登记点）+ CLI
├── src/core/features/robot/      robot 族层（注册表/帧/roslibpy 链路）
│   └── wheeltec_03/              机型包（话题表/parser/解帧/私有帧/自报）
├── test/            机型契约机械校验 + parser/decode 纯数据测试
└── robots.json      机器人注册表（实例 → 机型/协议/endpoint）
```

## 测试

```bash
scripts/test.sh     # 不需要 ROS/真机
```
