#!/usr/bin/env python3
"""只读通信探测工具，不需要启动ROS或编译自定义服务。

在本包目录执行：
  python3 scripts/probe_drive.py --simulate
  python3 scripts/probe_drive.py --interface can0 --node-id 1
只读对象，不使能、不写参数；探测退出后再启动正式控制节点。
"""
import argparse
import json
import os
import sys

# 直接从源码运行时补充模块路径；catkin安装后使用安装环境中的Python模块。
source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if os.path.isdir(source):
    sys.path.insert(0, source)
from kinco_lift.canopen import CanError, SdoClient, SocketCan
from kinco_lift.simulator import SimulatedCan


def main():
    """选择真实/模拟传输，读取六项对象，输出JSON；退出时始终关闭连接。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', default='can0')
    parser.add_argument('--node-id', type=int, default=1)
    parser.add_argument('--simulate', action='store_true')
    args = parser.parse_args()
    transport = None
    try:
        transport = SimulatedCan(args.node_id) if args.simulate else SocketCan(args.interface)
        sdo = SdoClient(transport, args.node_id)
        result = {
            'simulate': args.simulate,
            'statusword': '0x{:04X}'.format(sdo.read(0x6041, size=2)),
            'actual_position_6063': sdo.read(0x6063, signed=True),
            'actual_velocity_raw_606C': sdo.read(0x606C, signed=True),
            'digital_inputs_60FD': '0x{:08X}'.format(sdo.read(0x60FD)),
            'error_status_2601': '0x{:04X}'.format(sdo.read(0x2601, size=2)),
            'mode': sdo.read(0x6060, size=1, signed=True),
        }
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
