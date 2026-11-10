# wheeltec-hx 架构说明（仿制 jdyw-hx 的精简实现）

**定位**：轮式升降机器人（机型 `wheeltec_03`）的上位机客户端。
架构仿制 `jdyw-hx`（多机器人管理桌面应用）的**机型包模式**，范围收敛为
可独立运行的 CLI 工具——保留"新机型可导入"的完整接缝，去掉与本目标
无关的重层（自定义 UI 框架 / 三维世界引擎 / 多进程+IPC / MCP）。

## 一、分层与依赖方向

```
scripts/（入口脚本：run / test / 两个验证脚本）
   │
app/（装配根，唯一跨层编排者）
   │  composition.py：model_pkgs 机型登记点 + 链路装配
   │  main.py：CLI 入口（list / monitor / endpoint / cmd / vel）
   ▼
core/features/robot/（robot 族层——机型无关）
   │  _config.py    RobotSpec + robots.json 读写
   │  _catalog.py   RobotCatalog 注册表（快照+订阅+进程内写）
   │  _frames.py    族帧类型（所有机型都可能有的帧）
   │  _worker.py    RobotLink：roslibpy 链路（订阅闸门/latch 补订/
   │                心跳看门狗/速度看门狗/上行指令分派）
   ▼
core/features/robot/wheeltec_03/（机型包——机型差异的全部收敛点）
      _topics.py   TOPICS（订阅表）+ COMMANDS（上行指令表）
      _worker.py   parser 集：ROS 消息 → (meta, raw)
      _decode.py   解帧器：(meta, raw) → 帧对象
      _frames.py   机型私有帧（LiftStateFrame / JointStateFrame）
      _service.py  机型自报（词表/电池量程/速度上限/部件/通信腿）
```

依赖方向单向：`app → core族层`，机型包被装配根 import；**族层禁
import 机型子级**（jdyw-hx core-development-guide §六，沿用）。

## 二、与 jdyw-hx 的关键差异（有意为之）

| 维度 | jdyw-hx | wheeltec-hx |
|---|---|---|
| 进程模型 | worker 独立子进程 + IPC 送 (meta,raw) 回主进程解帧 | 单进程：parser 与 decode 同进程顺序调用，**两段式契约原样保留** |
| 通信腿 | rclpy（ROS2）+ roslibpy 双腿动态切换 | 仅 roslibpy——本机型是 ROS1（Noetic）机器人，rclpy 物理连不上 |
| UI | 自研控件框架 + 三维世界 | 无；CLI 打印。将来接 UI 时帧对象就是数据出口 |
| 生命周期 | lifecycle 租约 + process 进程拓扑 | 无；CLI 启停即链路启停 |
| 注册表 | 用户 appdata robots.json + fs watch | 项目内 robots.json（便于分发与版本管理） |

## 三、机型包契约（新增机型要满足什么）

由 `test/test_model_contract.py` 机械守住，要点：

1. **出口面**：`TOPICS` / `COMMANDS` / `parser_for` / `decode` /
   一组自报函数（见机型包 `__init__.py`）。
2. **TOPICS** 是订阅闸门词汇表，**COMMANDS** 是上行指令白名单——
   两张表平行、不能合并；未声明的能力词/指令一律拒绝（不猜）。
3. **消息类型写 rosidl 规范名** `pkg/msg/Type`；roslibpy 腿内部转
   `pkg/Type`（族 `_worker.to_rosbridge_type`）。
4. **机型间互不参照**：同名话题在不同机型上可以是完全不同的数据
   （/joint_states：这边是轮子，jdyw_01 那边是 6 轴臂）——各机型包
   各自一份表，"改一处要改两处"是正常成本。
5. **数值来源标注**：实测值注明出处，待核实的标 TODO + 回填路径
   （docs/onboarding.md）。

## 四、沿用 jdyw-hx 的真机实测纪律（逐条注明出处）

- `/robot_description` 必须 transient_local/latch 语义订阅，否则 0 字符
  （jdyw-hx 实测 0 vs 21297 字符）；
- `/tf_static` latch 回放可能是随机子集 → 补订轮次（1.5s/轮，连续
  N 轮无新样本收手）；
- TF 等 URDF：`start_after: robot_description` 闸门；
- `/PowerVoltage` 是心跳唯一来源，6s 无帧判离线，**绝不节流**；
- 速度指令带 ttl_ms 看门狗，超时回零（死手）；
- 高频话题（图像/odom）roslibpy 侧 `queue_length=1` + 节流；
- rosbridge 把 `uint8[]` 编成 base64，parser 必须还原。
