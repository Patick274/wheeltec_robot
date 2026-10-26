# 底盘运动限速和顶端高度指令（2026-10-26补充）

只修改本地源码；未连接/部署Jetson，未使能实物。以下内容更新旧的“必须停车才能升降”策略。
默认motion_enabled、commissioning_confirmed、drive_limits_verified、keyboard_control_enabled仍为false。

## 1. 底盘运动期间升降不超过100rpm的控制策略

- 实测底盘线速度/角速度超出静止阈值，或收到非零/cmd_vel，立即将升降目标上限限制为100rpm。
- 底盘刚停止、尚未达到base_stationary_s静止确认时间，也按100rpm限制。
- 稳定停车后可使用原有1000rpm中段、100rpm端部规则。
- 限速覆盖键盘、原move/jog和新move_top_height；不是仅在任务开始时判断。
- 定位运行中保持控制字bit5=1，更新6081梯形速度上限，不重发/替换原位置目标。
- 同一轮按键或同一定位任务只降不升。底盘停下后，不突然从100恢复1000；新一轮指令再重新计算。
- /odom丢失、过期或数据非法，/cmd_vel为NaN/Inf，仍停机锁存，不以低速继续盲走。
- 原有方向限位、端点内缩、会话参考、运行预算、CAN监督等继续有效。

配置：

```yaml
require_base_feedback: true
allow_lift_while_base_moving: true
base_moving_max_rpm: 100.0
```

100rpm按当前传动约3.75mm/s。配置的移动限速不允许超过100rpm；可以进一步降低。
allow_lift_while_base_moving=false可恢复旧的严格停车策略。
实物禁止require_base_feedback=false；该绕过仅用于明确的内存模拟。

### 底盘已接入低速握手（审查修复）

电机从1000减到100rpm需要物理时间。若底盘突然自行起步，本节点只能马上请求减速，
不能宣称实际转速瞬间就小于等于100。接入流程应是：

1. 底盘尚未起步，调用/lift/request_base_motion，data=true。
2. 本节点锁住100rpm上限，并重新读取真实速度。
3. 服务success=true才表示已具备本节点定义的低速条件；false时不能起步，可稍后重试。
   false可能仅表示尚在减速，也可能是反馈异常/故障；须同时看message和/lift/status。
4. 获准后保持请求为true，再允许底盘驱动。请求保持期间，即使出现新的升降指令也只能低速。
5. 底盘停止后再请求data=false；底盘实际/命令运动状态及停车稳定时间仍继续限制速度。

/lift/base_motion_permitted发布非锁存Bool，/lift/status也带同名字段。
底盘必须处理许可丢失及消息过期，不能在节点退出后沿用旧许可；请求服务的success与普通
“接受任务”不同，它在data=true时表示本次回读的低速条件已经满足。
以上SetBool仍供人工/其他集成使用。现有底盘已在实际串口速度入口接入自动联锁：

- `/lift/base_motion_request`：底盘20Hz发布UInt64，本轮非零请求序号；停稳后为0。
- `/lift/base_motion_permit`：升降仅在实际/目标速度均不超过100rpm时回送本轮序号，否则为0。
- 底盘只接受相同序号且未超过0.3秒的许可；速度指令超过0.3秒、实测底盘反馈超过0.5秒也输出零速。
- 请求失联时撤销许可，但保留升降100rpm限制；不会因底盘减速/掉线而突然恢复1000rpm。
- 底盘连续实际零速1秒后才释放请求。底盘安全回调独立运行，不随串口读等待或ROS仿真时钟暂停。
- 同步编译turn_on_wheeltec_robot及kinco_lift_control。未启动健康lift节点时，底盘将保持停车。

底盘导航/twist_mux输出仍进原cmd_vel；串口报文格式不变，联锁对平滑器后的最终速度入口同样有效。
100rpm限制不等于高位行车稳定性验收；重心、负载、路面及底盘允许速度需另行确认。

## 2. 目标顶端高度（米）

在config/lift.yaml中，后续测量并填写：

```yaml
initial_top_height_m: null
```

初始高度H0应是：升降柱在用于建立会话零点的下限位静止位置时，
从地面到机器人目标顶端测量点的总高度，包含底盘、缩回升降柱和顶部附件。
不是单独的底盘高度，不要把图纸1800mm未经测量直接填入，也不要用0代替未知值。
此处是平地高度换算，不是地图/world坐标或坡地姿态补偿。

新服务/lift/move_top_height的参数：

```text
float64 target_height_m
```

换算关系：目标伸长量mm = (target_height_m - initial_top_height_m) * 1000。
例：假设实际测得H0=0.8m，要到1.1m，则伸长目标为0.3m，而不是再上升1.1m。
该服务使用位置模式1，让驱动器闭环到目标；中途继续应用方向速度区和底盘限速。

修改初始高度配置后需重启节点。以下仅是填写正确标定并具备运行许可后的接口示例，
不是当前实物已经可以运行的声明：

```bash
# Jetson源码同步后必须重新catkin_make，生成新增的MoveTopHeight服务，再source工作区。
# 停稳，在真实下限位记录ROS会话零点；不是驱动器清零。
rosservice call /lift/enable "data: true"
rosservice call /lift/reference_here "{}"

# 仅示例，前提是初始高度已经测得并填为0.8m：
rosservice call /lift/move_top_height "{target_height_m: 1.1}"
rostopic echo /lift/top_height_m
rostopic echo /lift/status
```

原reference_here在下限位记相对零点；键盘会话确认也只记本地参考，不改驱动器6063。
两者现共用下限位、反馈精度及原始坐标核验；启用固定速度区时，未核验也不能用jog绕过。
坐标跳变或运行中反馈精度改变会撤销参考并停机，不自动平移旧阈值。
如果当前已通过e处于键盘速度模式，先停车、停稳后取消使能，再显式使用/lift/enable
选择位置模式；程序不会为高度请求自动切换运行模式或自动使能。

初始高度未填、会话零点不存在、目标非有限数、低于H0、超过行程或端点内缩边界，都会拒绝。
实测4190mm已填为候选travel_mm，但正常目标同时受原始坐标两端5mm内缩约束。
例如目标恰等于H0会进入下端保护区，不能用它反复顶下限位；实际允许范围以标定/验收为准。
定位accepted=true只表示已接受/下发，观察busy、target_mm、target_top_height_m及实际位置确认到位。
空格/Esc/q现在也能停止位置任务：605D=2、6040 bit8暂停，保留使能；2秒未停稳进入故障停车。
暂停后不会恢复旧目标，新任务在暂停保持期间装入新目标，最后才解除暂停。
预算/超时/限位中断不会自动续跑。全行程或底盘运动时的长距离低速运动可能超工作制，
不能通过增大超时或重启程序绕过110秒累计预算和现场冷却要求。

## 3. 状态与接口

| 接口/字段 | 说明 |
|---|---|
| /lift/move_top_height | MoveTopHeight，目标总高度m；响应accepted/message |
| /lift/top_height_m | Float64，初始高度和会话参考都有效时才发布 |
| /lift/request_base_motion | SetBool；true请求并回读低速许可，false释放请求 |
| /lift/base_motion_permitted | 非锁存Bool，底盘侧需核对新鲜度并实际接入 |
| /lift/base_motion_request / base_motion_permit | UInt64，底盘已接入的带请求序号许可，非锁存 |
| status.top_height_m | 当前总高度m；未知时null |
| status.target_top_height_m | 当前/最近目标总高度m；未知时null |
| status.base_speed_limit_rpm | 当前底盘状态对应的升降转速上限 |
| status.base_speed_violation | 底盘已运动/请求运动而实际升降速度仍超上限，需关注减速及互锁 |

新增服务无需新的ROS依赖，但必须重新生成服务类型。
模拟默认不要求真实底盘里程计，可通过request_base_motion=true测试100rpm上限；
真实运动反馈、减速瞬态及底盘拒绝起步的联动必须在Jetson实机另行验证。

驱动器实现依据：FD1X5手册第57页控制字bit5、位置模式的6081速度/607A目标。
Windows环境只运行标准库单测、内存CAN和ROS接口桩，不等同真实catkin或ROS集成测试。
前三项审查修复后142项离线测试通过（含实际C++联锁策略编译执行），Python/XML语法检查通过；
尚未部署Jetson、完成完整catkin构建或实机验收。
