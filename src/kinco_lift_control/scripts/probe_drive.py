#!/usr/bin/env python3
"""只读通信探测工具,不需要启动ROS或编译自定义服务.

在本包目录执行:
  python3 scripts/probe_drive.py --simulate
  python3 scripts/probe_drive.py --interface can0 --node-id 1
只读对象,不使能,不写参数;探测退出后再启动正式控制节点.
"""
import argparse
import json
import os
import sys

# 直接从源码运行时补充模块路径;catkin安装后使用安装环境中的Python模块.
source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if os.path.isdir(source):
    sys.path.insert(0, source)
from kinco_lift.canopen import CanError, SdoClient, SocketCan
from kinco_lift.simulator import SimulatedCan


def main():
    """选择真实/模拟传输,读取状态/错误对象,输出JSON;退出时始终关闭连接."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', default='can0')
    parser.add_argument('--node-id', type=int, default=1)
    parser.add_argument('--simulate', action='store_true')
    args = parser.parse_args()
    transport = None
    try:
        transport = SimulatedCan(args.node_id) if args.simulate else SocketCan(args.interface)
        sdo = SdoClient(transport, args.node_id)
        # 2601/2602是FD1X5手册7.12节的错误状态位掩码(如2602 bit12=CAN总线中断,bit1=看门狗);
        # 1001错误寄存器与1003错误记录是CiA301标准对象,本驱动器固件可能不支持,
        # 不支持时SDO中止会使会话失效,因此放在最后读取,仅用于独立无运动会话.
        result = {
            'simulate': args.simulate,
            'statusword': '0x{:04X}'.format(sdo.read(0x6041, size=2)),
            'actual_position_6063': sdo.read(0x6063, signed=True),
            'actual_velocity_raw_606C': sdo.read(0x606C, signed=True),
            'digital_inputs_60FD': '0x{:08X}'.format(sdo.read(0x60FD)),
            'error_status_2601': '0x{:04X}'.format(sdo.read(0x2601, size=2)),
            'error_status2_2602': '0x{:04X}'.format(sdo.read(0x2602, size=2)),
            'mode': sdo.read(0x6060, size=1, signed=True),
        }
        result['error_register_1001'] = '0x{:02X}'.format(sdo.read(0x1001, size=1))
        error_count = sdo.read(0x1003, size=1)
        result['error_field_entries_1003'] = error_count
        if error_count:  # 无记录时读sub1会被驱动器中止;只在有记录时读最近一条.
            result['error_field_latest_1003_1'] = '0x{:08X}'.format(sdo.read(0x1003, sub=1))
        print(json.dumps(result, indent=2))
        return 0
    except (CanError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if transport is not None:
            transport.close()


if __name__ == '__main__':
    raise SystemExit(main())
