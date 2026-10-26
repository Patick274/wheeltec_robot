# 方向键与端部配速（2026-10-26）

本次补充底盘运动100rpm限速、顶端米制高度接口，优先参见[底盘限速与高度控制](BASE_HEIGHT_CONTROL.md)。
审查修复后，空格/Esc/q的停车覆盖位置任务；底盘已接入自动许可，部署必须同时更新两个包。

本次只修改本地代码，未连接、同步Jetson，未发送真实CAN命令。
原包已备份到Codex工作目录的backups/kinco_lift_control-before-keyboard-20261026。
新增的是ROS1终端遥控，不是驱动器内部位置表；硬限位仍由FD125独立处理。

## 配速与停止

| 指令 | 正常速度 | 降速条件 | 接近速度 |
|---|---:|---|---:|
| ↑ 上升 | +1000 rpm | 6063 >= 119390000 inc | +100 rpm |
| ↓ 下降 | -1000 rpm | 6063 <= 3060000 inc | -100 rpm |

只接近本方向的端部才降速；从下端上升、从上端下降不因另一端限位被禁止。
进入低速区后，本次按压只保持低速，不因边界抖动重新加速。
按65536 inc/转、2.25mm/转，两个接近区均约100mm。

原始参考停车点：下147599、上122303105 inc。这些不是通用固定坐标。
驱动器重新设零、编码器复位、计数跳变或更换传动后，不得继续沿用。
每个ROS会话需在真实下限位停稳后显式确认，且下端读数应在配置值约±1mm内。
会话确认只记录ROS位置偏移，不写原点、不清编码器，不依赖此前失败的方式35。
确认后position_mm是本会话相对高度；驱动器6063仍显示原始计数。

正常终点暂向已测两端内部缩5mm（keyboard_stop_margin_mm，可配置，仍待实机验收），
到达后给速度0并保留使能；不会每次主动顶到硬限位。
硬限位输入有效时，相应方向立即撤销命令；保留反向退出能力。
端点、超时或换向停车后，必须先输入中立0、反馈停稳，再接受新的方向。
不修改607E旋转方向，不模拟、屏蔽或重新映射限位，不写EEPROM。

## 键盘使用（先用模拟）

在Jetson实际工作区完成catkin编译并source devel/setup.bash后：

```bash
# 终端1：内存模拟，绝不打开can0
roslaunch kinco_lift_control lift.launch simulate:=true

# 终端2：必须是有焦点的Linux终端或SSH TTY，不用roslaunch启动键盘脚本
rosrun kinco_lift_control lift_keyboard.py

# 终端3：查看状态
rostopic echo /lift/status
```

| 按键 | 功能 |
|---|---|
| c | 未使能时，在真实下限位静止处确认本会话原始坐标；不触发回零 |
| e | 显式使能键盘速度模式3；本身不启动运动 |
| ↑ / ↓ | 按住上升/下降，只有方向心跳持续更新才维持运动 |
| 空格 / Esc | 速度模式写0；位置模式bit8暂停，保留使能；不是物理急停 |
| q / Ctrl+C | 请求停车并退出键盘程序，恢复终端设置 |

模拟器初始就在下限位，可依次按c、e，等待新状态，再试↑；先松开停稳，再试↓。
不用方向键代替底盘遥控；键盘脚本不发布/cmd_vel。底盘的最终串口入口另有升降低速许可联锁。

普通终端没有可靠的key-up事件。键盘端最后一个箭头字节后默认0.25秒发送0，
后端超过0.4秒没有新方向命令也发送0；实际停车还包含ROS/SDO调度、反馈轮询和机械减速。
操作系统首次按键重复有延迟，长按初期可能先停一下再继续。不要加长超时来掩盖此现象。
TCP/ROS缓冲、进程卡死和CAN断线的停止保证仍依赖驱动器监督及现场硬件保护，
不能把终端控制当作安全认证的保持运行按钮。

## 实机仍默认锁住

config/lift.yaml中以下四项仍为false：

```yaml
motion_enabled: false
commissioning_confirmed: false
drive_limits_verified: false
keyboard_control_enabled: false
```

这不是缺功能，而是尚未在Jetson完成只读CAN探测、实际输入/反馈核对、停车联锁、
键盘丢失/断CAN/进程退出等受限测试。不能只把四项改true就当作验收完成。
实机require_base_feedback必须true，/odom应持续新鲜；非零底盘命令/实测运动时上限100rpm，
无效或过期反馈仍停机。严格限制实际转速需底盘接入request_base_motion握手。
enable_keyboard使能时会在RAM回读确认工作模式、停止策略、加减速和节点保护，
包括6083/6084=100rps/s、6085=610rps/s；应先在实物核对适用性，不保存EEPROM。
使能前先清60FF旧目标速度，避免接管Windows遗留的负速度指令。
travel_mm已按实测填入4190mm候选值，正常位置目标还受端点内缩保护。
新增顶端高度服务需另填initial_top_height_m；未知时不能执行。
已有move/jog与键盘速度模式互斥，不能同时下发；模式切换需停稳并显式重新使能。

普通松键/端点停车写60FF=0，保留使能。全局/lift/stop、严重异常、通信保护及断电
可能使电机失去保持力；可靠机械保持/支撑和物理急停必须独立存在。

## 工作制限制

交接资料记录2分钟运行、18分钟停止。按1000rpm中段、末端100mm为100rpm，
约4190mm单程约136秒，不能直接连续完整往返。
默认进程内累计运动预算110秒，短暂停顿、松键、使能/复位不恢复预算；
连续静止1080秒后才恢复。预算耗尽会停机锁存，冷却完成也不会自动重新使能。
这不是电机温升模型。计时不跨进程持久化，重启不能证明已冷却；
启动前操作者必须确认此前的运行/冷却历史，不能重启程序绕过工作制。
现场工作制、24V供电下能力及负载/断电保持仍需厂家或整机验收确认。

## 新增ROS接口

| 接口 | 类型 | 说明 |
|---|---|---|
| /lift/keyboard_command | std_msgs/Int8 | +1上升、-1下降、0中立；非零需持续更新 |
| /lift/confirm_keyboard_coordinates | std_srvs/Trigger | 静止真实下限位确认原始坐标，仅本会话有效 |
| /lift/enable_keyboard | std_srvs/SetBool | true显式使能速度模式；false仅停稳后取消使能 |
| /lift/keyboard_stop | std_srvs/Trigger | 正常速度0停车，不取消使能 |

status新增control_mode、commanded_rpm、keyboard_confirmed、keyboard_neutral_required、
error_status2、motion_budget_remaining_s和cooldown_remaining_s。
Windows停止点精度、驱动器原点/软限位有效性没有因新增ROS代码而被认定验收通过。

## 离线验证

```bash
python3 -m unittest discover -s tests -v
python3 scripts/probe_drive.py --simulate
```

测试使用内存传输，不安装ROS、不打开CAN。它验证策略/报文，不模拟真实惯量、
负载、减速度、热过程或物理制动距离；catkin和真机测试需之后在Jetson单独进行。

前三项审查修复后的本地结果：142项离线测试通过（包含C++策略编译执行）、Python/XML语法检查通过、
模拟probe只读探测通过。ROS服务/键盘入口使用桩对象验证，不能称为真实ROS集成测试。
