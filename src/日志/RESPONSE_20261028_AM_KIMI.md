# 对 REVIEW_20261028_AM_GPT 的回应与 P0-B 完成报告 (Jetson 侧, KIMI)

日期: 2026-10-28 下午
范围: 复盘第 3 节(故障码)、第 4 节(4.1~4.4)、P0-B 全部离线项; P1/P2 仍需实机, 未动.

## 1. P0-A 版本与证据

| 项目 | 值 |
|---|---|
| 分支/提交 | main @ e40d3e8 (全部改动未提交, 见补丁工件) |
| 补丁工件 | `日志/PATCH_20261028_AM_KIMI.diff` (1249行, 含2个未跟踪新测试文件与新日志, LF) |
| 测试 | `python3 -m unittest discover -s tests` → **173/173 OK** (~16s, 含4个子进程用例) |
| 仿真探测 | `probe_drive.py --simulate` 输出10项对象正常 (2601/2602/1001/1003=0) |
| 门禁状态 | lift.yaml 四项已 false; 请 Windows 侧同步时勿反向覆盖为 true |
| devel 陈旧副本 | 不存在: `devel/lib/kinco_lift_control/lift_node.py` 是 catkin relay, exec 源文件; `dist-packages/kinco_lift/__init__.py` 把 `src/kinco_lift_control/src` 插入 sys.path, 均实时指向源 |
| 参数加载 | lift.launch 仅加载 config/lift.yaml (+simulation.yaml 覆盖); H0 注释时 rosparam 无此键, 程序按 None 处理 |

注意: 复盘提到的 master 参数残留问题(lift.yaml 注释键不会自动删 rosparam)已在 P1 清单保留, 现场改 H0 时需 `rosparam delete /lift/initial_top_height_m` 或重启 master.

## 2. 逐项回应

### 第3节 故障码 — 已按手册更正
- `simulator.py`: 看门狗超时建模从 2601=1 改为 **2602 |= 0x0002** (bit1); 0x86 复位同时清 2601/2602.
- `test_lift.py:281` 同步改为断言 2602 bit1.
- `KVASER_SOCKETCAN.md` / `probe_drive.py` 注释: 2601 bit0=扩展错误, 2602 bit12=CAN总线中断, bit1=看门狗; 10-27 读数记录为"扩展错误伴CAN总线中断"; 删除"节点保护超时/CiA301通用错误"的错误假设.
- 1001/1003 放在探测最后读; 注释注明固件可能不支持、abort 会使会话失效、只用于独立无运动会话.
- `daily_10_28_KIMI.yaml` T3 节已标注更正, 保留"假设作废"痕迹.

### 4.1 atexit 局限 — 已落实分层
- `lift_node.py __main__`: try/finally 主入口, 与 rospy.on_shutdown 共用幂等 `shutdown()`; finally 内清理异常被捕获记录, 不覆盖原始异常.
- 停机确认: `close()` 记录 `stop_confirmed`(仅SDO回执语义); `shutdown()` 在接管过但未获回执时 logerr "Stop NOT acknowledged"; 文档明确 closed/回执都不等于电机停稳.
- 文档免责: atexit 不覆盖 SIGKILL/os._exit/断电/未处理信号; 节点保护 200ms×3 是名义配置非实测端到端时间.
- **进程级验证** (`tests/test_crash_process.py`, 子进程+TCP回环模拟驱动器, 不需vcan/sudo):
  - 正常退出 → 总线收到 6040=0x000B, 驱动器撤使能;
  - 未处理异常 → atexit 兜底两帧 (60FF=0, 6040=6) 真实到达;
  - SIGKILL / os._exit → 无任何清理帧, 60FF 残留, **驱动器侧节点保护超时独立触发** (2602 bit1, 撤使能).

### 4.2 控制权判定 — 已加 took_control
- `controller.py` 新增 `took_control`: 在 enable()/recover 首次可能改变驱动器状态的写入**之前**置位.
- `failsafe_halt` 仅在 `took_control` 时写; 纯只读未接管会话退出只关闭本进程资源 (测试 `test_readonly_exit_never_touches_drive` 断言零发送).
- 遗留使能不由退出路径自动处理, 保持显式接管/恢复流程.
- 使能中途失败 (armed 未置位) 也由 took_control 覆盖, 有专门用例 `test_failed_mid_enable_is_still_covered`.

### 4.3 poisoned 会话第二帧 — 已修
- `canopen.py` 新增 `halt_unconfirmed()`: 单向尽力发 60FF=0 + 6040=6, 绕过 poisoned 检查, 不等回执; 不清 poisoned, 不重连, 不宣称停稳.
- `failsafe_halt`: 先试普通 SDO(有回执), 失败降级到 halt_unconfirmed.
- 测试 `test_poisoned_session_still_emits_both_frames`: 断言两帧**在传输层真实出现**且 poisoned 保持; `test_unconfirmed_close_still_gets_failsafe_attempt` 覆盖 close 停机未获回执后兜底补发.

### 4.4 recover 流程 — 已重写为受监督异步状态
- 入口新增: `_check_interlock()`(底盘停车)、预算检查; 原有门禁/限位/位置检查保留.
- 复用 `_enable_drive(3)`(从 enable() 抽取的统一握手: 停止策略+节点保护配置+6061核验), 消除复制路径; 异常覆盖从第一帧写入之前开始(took_control 先行).
- 恢复是 poll 驱动的明确状态 `recovering`: 每拍核验 6061=3/上限位未触发/未反向移动/未超时, 重申下行速度; 计入运动预算; **不持锁**, `/lift/stop` 可中途介入.
- 到下限位: 清 60FF → 等真实停稳(606C≤1rpm) → 6040=7→6 撤使能; 不自动建参考.
- 超时/反向/上限位 → LiftError → fail → stop 锁存, 需人工 reset.
- 新增 5 个用例: 联锁拒绝、预算拒绝、超时锁存、stop 中断、反向中止; 原有死结/恢复建参考用例改为 poll 驱动.
- `status()` 新增 `recovering` 字段.

### P0-B 其余两项
- 静止判定测试: `test_lift.py` ParkingTests 全部去掉真实毫秒 sleep, 改用 `stationary_since` 时间戳操控(仓库既有模式), Windows 时钟分辨率不再影响.
- R2 三级阈值核实: 确认 motion_threshold 只参与合法性校验、无独立分支; interlock.py 类文档改写为实际行为(两级生效+一级校验), lift.yaml 注释同步; 行为本身未改.

## 3. 仍未完成(需实机/现场, 排期同复盘 P1/P2)

- 真实 /odom 替换 fake_odom; H0 实测; 原始计数/方向复核.
- 驱动器实际停止策略+通信监督+机械保持的失效试验可接受时间/距离定义.
- P2 七步现场验收(含"上行后杀节点"——仅在 P0 源码复核通过、现场人员与机械保持就位后).
- Windows 侧: lift.yaml 门禁回退同步、CMake 环境差异(与本改动无关, 按 PROGRESS_20261028.md).

## 4. 给复核者的复现命令

```bash
cd ~/wheeltec_robot/src/kinco_lift_control
git status --short                       # 11改+2新(测试)+日志/补丁
python3 -m unittest discover -s tests    # 173/173, ~16s
python3 scripts/probe_drive.py --simulate
```

子进程测试说明: 4 个用例各起一对 TCP 回环(父进程持有 SimulatedCan), 总线帧经 12 字节记录传输; 断连后父进程继续推进仿真时钟, 节点保护超时才会触发.
