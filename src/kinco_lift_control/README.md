# kinco_lift_control：FD125升降控制包

完整中文操作流程、逐文件解析、参数解释和排障入口见同目录explain.yaml。
explain.yaml是阅读用的说明文档；运行参数仍在config/lift.yaml中。

适配当前PHM的ROS1/catkin工程，目标环境为Ubuntu 20.04 + ROS Noetic + Python3，
CPU可以是Jetson ARM64或x86。你本次说“Xavier TX”，此前说“Xavier NX”；
板卡具体型号不影响本包的SocketCAN接口，仍需确认板上实际ROS/Python环境。

## 已实现

- Linux原生SocketCAN，不限制适配器品牌；当前购买的是Kvaser兼容固件，
  需在Jetson上验证内核驱动是否生成可用的can0。candleLight也是可选接入方式。
- FD125经典CAN、默认500kbit/s（系统配置）、默认节点1（YAML可改）。
- 启动默认只读，不使能、不回零、不自动复位故障、不自动重新连接。
- 读状态字、实际位置、实际速度原始值、限位状态、报警状态。
- 显式使能/禁止、限速的小距离点动、下限位处记录会话零点、绝对高度定位。
- 底盘停车检查：同时检查/odom反馈及/cmd_vel指令；丢失里程计也禁止运动。
- 停止锁存、目标范围/整数溢出检查、定位超时、CAN掉线停止请求。
- 驱动器侧节点保护；过程卡住或被杀死后，不再持续发送监督报文。
- 同一控制器的内存模拟、无ROS单元测试及独立只读通信探测工具。

本包不改已有底盘串口协议、导航启动文件、URDF，也不自动控制底盘停车。
停车检查是软件联锁，不会阻止其他节点向底盘下发运动命令。
升降过程中一旦发现底盘运动，本包请求升降停止。若要主动禁止底盘运动，
需要后续将/lift/busy接入现有twist_mux锁或任务调度。

## 接线与初次调试

Jetson USB -> 隔离USB-CAN（当前为Kvaser兼容固件） -> FD125 X1A：
CAN_H接1脚，CAN_L接2脚，CAN侧GND接3脚。
RJ45接口不是以太网口，禁止接入电脑网口或24V电源。
总线两端各120欧；已内置启用的不重复添加。
FD125 SW4按手册启用；单驱动器末端、适配器另一端。
必接动力电源在X5 DC+/DC-。手册第15页明确逻辑24V电源“可不接”；
X3 8脚24V+/1脚24V-仅在需要外部逻辑供电时使用，不是必接第二路。
不要把X3的24V输入端当成传感器电源输出，外接供电需满足厂家范围。
电机动力在X5 U/V/W/PE，编码器在X4。CAN接口不需要外部24V供电。

先用KS3通过X2 USB隔离调试连接完成电机匹配、反馈参数、输入功能及极性、
正负限位、使能行为、停止方式、制动电阻参数和低压运行配置。
SMK60S-0040-30QAK-5DSA的电机参数按实物和厂家配置，不由本包自动写入。
KS3的CAN控制会与本包争用，运行本包前关闭KS3通信及其他CAN主站。

当前只确认有下限位，上限位尚未确定，因此默认drive_limits_verified=false；
不能仅修改开关为true就当作已安装、验证。必须完成实际硬件行程保护。
不执行自动寻底，不把首次读到的位置当作机械零点。
驱动器、电机断电、编码器位置复位或本节点重启后，应重新建立会话零点。

## 安装和编译（在Jetson执行，不在Windows执行）

把此包放入Jetson实际catkin工作区的src中。假设工作区是 ~/PHM：
以下命令中的路径按实际工作区修改。

```bash
source /opt/ros/noetic/setup.bash
sudo apt update
sudo apt install can-utils python3-setuptools python3-catkin-pkg
cd ~/PHM
catkin_make -DPYTHON_EXECUTABLE=/usr/bin/python3
source devel/setup.bash
```

包的ROS依赖：rospy、std_msgs、std_srvs、geometry_msgs、nav_msgs、
message_generation、message_runtime。缺依赖时可在工作区用rosdep安装。
如果自定义服务尚未生成，不能直接运行lift_node.py；先编译。
独立probe_drive.py无需ROS，运行时会定位同包src/kinco_lift。
Windows复制可能丢失可执行位，可在Jetson运行：
```bash
chmod +x ~/PHM/src/kinco_lift_control/scripts/*.py
```

## 配置CAN（Jetson执行）

2026-10-19在Windows实际读到USB名称Kvaser Leaf Light v2，VID/PID为0BFD:0120；
设备问题码28且没有绑定驱动，表示Windows未安装匹配驱动，不等同于硬件损坏。
这是第三方板报告的兼容身份，不能由此证明原厂硬件或Linux协议完全兼容。
详细分步操作见docs/KVASER_SOCKETCAN.md。

先只读诊断，不需要ROS或sudo：

```bash
cd ~/PHM
python3 src/kinco_lift_control/scripts/diagnose_can.py --interface can0
lsusb -d 0bfd:0120
ip -details link show
```

如果USB已识别但没有CAN接口，检查并尝试加载当前内核的候选驱动：

```bash
modinfo kvaser_usb
sudo modprobe can_raw
sudo modprobe kvaser_usb
ip -details link show
```

若已有can0且能识别，通常无需手工加载驱动。candleLight设备对应gs_usb；
不要因为本包旧说明写了gs_usb，就给Kvaser固件照抄这一驱动步骤。
modprobe失败时保留原始错误，不能仅靠安装Python库修复。
加载模块成功但没有接口，也不能认定已适配，继续检查dmesg和USB绑定信息。

确定can0确实属于升降转换器且未被其他节点占用后，再执行：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000 restart-ms 0
sudo ip link set can0 up
ip -details -statistics link show can0
```

若kvaser_usb缺失，需要匹配Jetson当前uname -r的内核驱动；不要盲目安装x86或不同内核驱动。
不自动重启bus-off，总线异常排查后人工恢复。
此程序不运行sudo，不修改网络接口，不修改电机库和CAN站号/波特率。
接口名称和站号必须与实物相符。

接口就绪后再运行probe_drive.py读取FD125。出现can0不等于SDO通信成功，
控制代码无需改成厂商CANlib API；本包仍通过SocketCAN传输。

## 先运行离线测试/模拟

在包目录执行，无需ROS、CAN适配器、电机：
```bash
python3 -m unittest discover -s tests -v
python3 scripts/probe_drive.py --simulate
```

ROS模拟：
```bash
roslaunch kinco_lift_control lift.launch simulate:=true
```
模拟使用config/simulation.yaml中的人工参数，永远不打开物理CAN。
启动时也不自动使能。另一个终端source工作区后：
```bash
rosservice call /lift/enable "data: true"
rosservice call /lift/reference_here "{}"
rosservice call /lift/move "{height_mm: 10.0, speed_mm_s: 2.0}"
rostopic echo /lift/status
rosservice call /lift/stop "{}"
```

## 硬件先只读

默认config/lift.yaml禁止任何使能和运动，不需要知道反馈精度即可读取：
```bash
python3 scripts/probe_drive.py --interface can0 --node-id 1
roslaunch kinco_lift_control lift.launch
rostopic echo /lift/status
```
不要同时运行两个控制节点或KS3。探测完成退出后，再启动控制节点。
读取超时/SDO中止后会锁住会话，不自动重试运动或重连；查明原因后重启节点。

## 运动前必须填写的参数

编辑config/lift.yaml：
- encoder_counts_per_rev：KS3的有效反馈精度inc/电机转，不直接使用23bit编码器标称值。
  手册示例是65536，但本设备尚未确认，默认0。
- mm_per_motor_rev：电机每转实际伸长毫米数。附图标16:1、导程36mm，
  理论候选值36/16=2.25mm/电机转；多级传动/伸缩结构的倍率必须实测确认，默认0。
- up_direction：6063计数增大对应上升则+1，反之-1。
  正负限位名称是电机计数方向，本包按up_direction映射为下/上限位。
- travel_mm：实际允许伸出量，保留机械余量。图纸4200mm不能直接当软件安全边界，默认0。
- commissioning_confirmed：完成电机匹配、方向、停止、机械保持验证后才能true。
- drive_limits_verified：物理上下限位、IO功能/极性及驱动器保护实测通过后才能true。
- motion_enabled：以上就绪后显式改true。不提供命令行绕过开关。
- 速度、加速度、单步长度和超时按机械能力设置。默认点动不超过1mm、最高5mm/s。
  要验证电池总20A的功率预算；本包不把电池电流当作电机相电流，
  不自行修改6073电流限制。
- /odom与/cmd_vel若实际有命名空间/重映射，修改对应话题。

修改YAML需重启节点；配置不会在线静默改变。
启动后仍需显式调用enable。
默认motion_timeout_s=30，长行程请分段，或经确认后调整；不会自动延长超时。

## 硬件操作顺序

1. 正确启动底盘里程计、停车，确保/odom持续更新，并向/cmd_vel发送零速度。
2. 完成上述配置，启动lift.launch，查看status。所有运动命令默认不排队。
3. 显式使能：rosservice call /lift/enable "data: true"。
4. 在已验证的保护范围内以1mm以下点动检查方向：
   rosservice call /lift/jog "{distance_mm: 0.5, speed_mm_s: 0.5}"。
   正数上升、负数下降；下限位激活时不允许继续下降。
   未建立零点的点动没有绝对高度软件边界，只能用于受监护的短距离调试，
   必须已有经过测试的驱动器硬件限位。
5. 机构实际停在下限位且60FD对应位有效时调用：
   rosservice call /lift/reference_here "{}"。
   这只是记录当前会话位置偏移，不写编码器、不改变机械零点、不触发运动。
   禁止把任意悬空位置记为0mm。
6. 短程定位：
   rosservice call /lift/move "{height_mm: 10.0, speed_mm_s: 1.0}"。
   accepted=true仅表示已接受并下发，必须持续看/lift/status；
   busy=false、无故障、目标/实际位置匹配才表示本次正常完成。
7. 停止：rosservice call /lift/stop "{}"。
   本包下发控制字0x000B，锁住后续运动。SDO回执仅表示写入收到，
   不等于已物理停稳。CAN断线时通信停止命令可能送不到，使用硬件急停。
8. 查明原因后显式reset_fault；会清除本包参考零点，不自动恢复任务。
   rosservice call /lift/reset_fault "{}"
   然后重新使能、下限位确认和记录零点。
9. 停稳后取消使能：rosservice call /lift/enable "data: false"。
   电机失去保持力，是否安全由实际丝杆/抱闸/负载结构决定。

## ROS接口

| 接口 | 类型 | 含义 |
|---|---|---|
| /lift/enable | std_srvs/SetBool | true显式使能，false取消使能 |
| /lift/stop | std_srvs/Trigger | 停止并锁存，不自动恢复 |
| /lift/reset_fault | std_srvs/Trigger | 人工复位，清除会话参考 |
| /lift/reference_here | std_srvs/Trigger | 在静止下限位处建立0mm |
| /lift/jog | kinco_lift_control/JogLift | 有限长度相对点动 |
| /lift/move | kinco_lift_control/MoveLift | 相对本会话零点的绝对高度 |
| /lift/status | std_msgs/String | JSON状态；position_mm未知时为null |
| /lift/position_mm | std_msgs/Float64 | 仅有有效参考后发布 |
| /lift/busy | std_msgs/Bool | 未完成定位或尚未确认停稳；停止回执后不会立即解锁 |

本包不发布joint_states，因为现有URDF的arm_joint仍是fixed，
尚未定义实际升降prismatic关节。后续需要按机械结构修改URDF并对接。

## 手册实现依据与边界

依据本次提供的《Kinco FD1X5驱动器使用手册 20251110》：
- 第5章控制字/状态字：6 -> 7 -> F使能；2F -> 3F绝对定位。
- 第7章实际位置6063:00、限位60FD:00、故障2601:00。
- 607A:00 int32 inc；6081:00 uint32；6083/6084/6085:00 uint32。
- 速度原始值=round(rpm*512*反馈精度/1875)。
- 加速度原始值=round((rps/s)*65536*反馈精度/4000000)。
- 第9章SDO请求600+ID，应答580+ID，字节低位在前。
- 停止605A=2、605B=1、605C=1、605E=2，按已验证的加减速设置。
- 通信保护使用节点保护，不同时使用heartbeat：
  1017=0、100C=200ms、100D=3、6007=1，核对100E的节点保护ID；主站每100ms发送700+ID的RTR，
  接收带交替toggle位的回复。所有设置回读确认，不保存EEPROM。
  本程序长时间无成功SDO事务时暂停监督发送；断线/进程死亡时依赖驱动器保护停机。
  约600ms是从最后一次有效节点保护询问起的设定值，不是整机急停响应保证；
  实物必须做断USB/CAN、停止进程等试验，并核对驱动器报错停止方式。

SDO轮询10Hz适用于单轴低频梯形定位；不是1kHz同步插补或多轴实时控制器。
不自动设置IO功能、极性、原点模式、电机库、制动电阻、电池阈值、持久软限位，
也不自动修改底盘启动流程。机械安全、驱动器限位和硬件急停不能由本包替代。

接线指南见docs目录中的PDF。电源保护、滤波器直流适用性和实际限位型号
尚未全部确认时，可完成软件模拟及经核查后的只读联调，不解锁实物运动。

附图HTL4与FD125手册分别用于核对机构信息与驱动协议。附图中其他通用裸线/
直流电机接线示例不适用于已确定的伺服动力/编码器连接，代码不使用这些示例协议。

## 已验证与尚未验证

已提供无硬件单元测试覆盖：手册报文、正负整数、速度/加速度换算、
默认只读、标定/限位门禁、使能状态机、目标握手、零点、限位、超程、
点动、停止锁存、反馈超时、底盘停车、重启丢参考、CAN失联等。
内存模拟不等同FD125真机；当前Windows环境未运行catkin/ROS，也未接电机。
需要在Jetson上实际编译并逐步只读联调，再进行受限的实机运动验证。

外部依据：
- Linux SocketCAN：https://docs.kernel.org/networking/can.html
- catkin Python安装：https://docs.ros.org/en/kinetic/api/catkin/html/howto/format1/installing_python.html
