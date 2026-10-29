# Kvaser兼容转换器接入Jetson（2026-10-19）

当前程序使用通用SocketCAN，不能仅凭商品写Kvaser就推断使用Windows DLL，
也不需要为了商品名字改写FD125的CANopen运动报文。

## 已在当前Windows电脑读到的事实

- USB设备报告名称：Kvaser Leaf Light v2。
- VID/PID：0BFD:0120。
- Windows问题码：28。
- DriverInfPath和Service为空：未安装匹配的Windows驱动。
- 第三方AP311板可以报告兼容设备的名字；上述结果不证明它是原厂设备，
  也不证明其固件完整实现Linux驱动需要的协议。
- 当前不需要为了Jetson使用而在Windows装驱动或刷机。

## 1. 先只接USB，在Jetson读取身份

先把本包最新改动同步到Jetson。假设工作区是~/PHM，以下命令在Jetson终端执行：

```bash
uname -r
lsusb -d 0bfd:0120
ip -details link show
python3 ~/PHM/src/kinco_lift_control/scripts/diagnose_can.py --interface can0
```

diagnose_can.py无需ROS和第三方Python库，只读采集USB/驱动/接口状态。
它不打开CAN套接字、不发送CAN帧、不加载模块或修改网络。
--json输出完整可复制报告；USB序列号不采集。

- USB能列出但没有CAN接口：进入第2步。
- 已有can0：先确认它属于这个USB适配器，进入第3步。
- 只有can1：可以使用can1，不强制改名；后续命令和启动参数保持一致。
- USB都没有：检查连接和线缆，再看dmesg；不是修改运动代码能解决的问题。
- 只有ttyUSB或厂商CANlib通道，不等于已具备SocketCAN。

## 2. 没有CAN接口时，检查候选内核驱动

对于报告Kvaser USB身份的设备，先检查当前内核的kvaser_usb支持；
第三方固件能否真正兼容，需要以绑定结果和后续通信实测为准。

```bash
modinfo kvaser_usb
sudo modprobe can_raw
sudo modprobe kvaser_usb
ip -details link show
sudo dmesg | tail -n 60
```

加载模块不会替你设置波特率或驱动电机。
USB驱动通常能够自动加载，已有接口时不必重复操作。

- Module not found：当前Jetson内核可能没有该模块，或支持为内建；
  先结合接口/dmesg判断，缺少支持时需要与uname -r一致的内核配置/模块。
- 模块可加载但没有接口：检查dmesg、USB VID/PID和绑定结果。
  不要用“加载成功”代替兼容验证。
- 出现can0：说明形成了SocketCAN接口，仍需配置和读取FD125。
- 明确的固件协议错误/USB超时：把诊断报告交给卖家，要求给出
  在Linux ARM64、对应Jetson内核上验证过的接入方法和固件版本。

不要给Kvaser兼容固件照抄sudo modprobe gs_usb；
gs_usb对应另一类协议，包括此前讨论的candleLight。
也不要未经确认把厂商CANlib驱动、内核SocketCAN驱动和多个程序同时用于同一设备。

## 3. 确认接口后配置500kbit/s

以下只适用于已经确认属于升降转换器的can0。操作前关闭KS3和其他控制程序。
若底盘也使用CAN，应先区分两个适配器，不能按编号猜测。

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000 restart-ms 0
sudo ip link set can0 up
ip -details -statistics link show can0
python3 ~/PHM/src/kinco_lift_control/scripts/diagnose_can.py --interface can0
```

FD125站号和波特率在KS3/拨码中按手册设置，本程序不替你修改。
不要为排障随意改成CAN FD。程序使用经典CAN的11位标识符。

诊断ready只代表接口已启用、状态可用、波特率一致，不代表电机控制成功。
没有接总线时也可能显示ERROR-ACTIVE；真正通信要看下一步SDO应答。
BUS-OFF/ERROR-PASSIVE时检查总线、终端和位速率，不自动反复重启。

## 4. 接驱动器，先只读

按已核对接线连接CAN_H/L/GND与FD125 X1A，核对两端120Ω终端，
确认驱动器供电、站号1和500kbit/s正确，保持motion_enabled=false。

```bash
cd ~/PHM
python3 src/kinco_lift_control/scripts/probe_drive.py --interface can0 --node-id 1
```

若接口名为can1或实际站号不是1，修改参数。
这个工具只发送SDO读取，不使能、不写参数、不执行升降。
读到6041、6063、606C、60FD、2601、2602、1001、6060才说明本包与驱动器建立了对应通信。
2601/2602是FD1X5手册7.12节(印刷页108-109)的Unsigned16错误状态位掩码:
2601 bit0(0x0001)是扩展错误,2602 bit12(0x1000)是CAN总线中断,2602 bit1(0x0002)才是看门狗。
2026-10-27实机读数2601=0x0001+2602=0x1000应记录为"扩展错误伴CAN总线中断",
不能单凭数值区分适配器/线缆/供电、bus-off、主站退出或通信监督触发;复位可清除不代表原因已消除。
1001/1003是补充只读诊断,须先核对固件支持;对象不支持会SDO中止并使会话失效,
只在probe这类独立无运动会话中使用,不能混入活动控制循环。
如超时，先检查供电、接线、波特率、站号和其他主站。

## 5. 再启动ROS只读节点

新增诊断脚本后，在Jetson重新编译，以更新catkin安装入口：

```bash
source /opt/ros/noetic/setup.bash
cd ~/PHM
catkin_make -DPYTHON_EXECUTABLE=/usr/bin/python3
source devel/setup.bash
roslaunch kinco_lift_control lift.launch can_interface:=can0 node_id:=1
```

运行方式与之前相同。真实运动还需要标定、方向与上下限位验证，
不能因适配器识别成功就开放motion_enabled。

## 本次代码调整

- 保留SocketCAN及全部运动门禁，不改成Kvaser厂商API。
- 新增scripts/diagnose_can.py及src/kinco_lift/diagnostics.py。
- 接口打开失败时给出诊断脚本提示。
- 更新README和explain.yaml中的当前固件、驱动及操作步骤。
- docs中的旧PDF未重导出；其中candleLight专用驱动步骤由本指南替代。

## 需要反馈的最少信息

```bash
uname -r
python3 ~/PHM/src/kinco_lift_control/scripts/diagnose_can.py --interface can0 --json
sudo dmesg | tail -n 60
```

不需要提供密码，也不需要为了采集USB身份给电机通电。
