#!/usr/bin/env python3
"""在Jetson运行：python3 scripts/diagnose_can.py --interface can0 [--json]。

不需要ROS，不加载内核模块，不修改接口，不打开CAN套接字，不发送报文。
适用于排查Kvaser兼容版本是否已经形成SocketCAN网络接口。
"""
import argparse
import json
import os
import sys

# Windows重定向终端可能默认cp1252；固定UTF-8以保证中文诊断可复制。
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if os.path.isdir(source):
    sys.path.insert(0, source)
from kinco_lift.diagnostics import collect_report, print_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', default='can0')
    parser.add_argument('--json', action='store_true', help='输出便于复制的JSON诊断报告')
    args = parser.parse_args()
    report = collect_report(args.interface)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
