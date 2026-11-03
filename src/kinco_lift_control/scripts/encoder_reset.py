#!/usr/bin/env python3
"""编码器数据复位(FD1X5手册第10章报警排除, 000.4/0x7320 多圈数据无效).

只在lift节点停止后使用(独占CAN, 避免双主站); 写完读回命令完成位, 再按提示复位故障.
用法: python3 scripts/encoder_reset.py --interface can0 --node-id 1
"""
import argparse
import sys
import time

import os
source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if os.path.isdir(source):
    sys.path.insert(0, source)
from kinco_lift.canopen import CanError, SdoClient, SocketCan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', default='can0')
    parser.add_argument('--node-id', type=int, default=1)
    args = parser.parse_args()
    transport = None
    try:
        transport = SocketCan(args.interface)
        sdo = SdoClient(transport, args.node_id)
        state = sdo.read(0x2690, size=1)
        print('2690 读出: 0x%02X (bit0=可输入命令, bit1=上一命令完成)' % state)
        if not state & 1:
            print('编码器当前不可输入命令, 中止.', file=sys.stderr)
            return 1
        fault_2601 = sdo.read(0x2601, size=2)
        print('复位前 2601 = 0x%04X' % fault_2601)
        # 手册: 10 = 复位编码器状态标记以及清除多圈数据; 多圈清除后绝对坐标系改变,
        # 必须重新标定限位计数, 不能沿用旧的raw frame.
        sdo.write(0x2690, 10, size=1)
        print('已写 2690 = 10 (复位状态标记+清多圈数据)')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = sdo.read(0x2690, size=1)
            if state & 2:
                print('命令执行完成 (2690 = 0x%02X)' % state)
                break
            time.sleep(0.05)
        else:
            print('命令完成位超时未置位, 现场检查驱动器状态.', file=sys.stderr)
            return 1
        print('下一步: 复位故障(节点/lift/reset_fault或重启驱动器), 然后重建坐标系.')
        return 0
    except (CanError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if transport is not None:
            transport.close()


if __name__ == '__main__':
    raise SystemExit(main())
