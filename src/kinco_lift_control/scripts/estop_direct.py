#!/usr/bin/env python3
"""脏杀看门狗失效时的人工兜底: 绕开(已死的)节点直写60FF=0并撤使能.

仅在"kill -9节点后驱动器未按600ms看门狗自停"时使用; 正常情况不要运行.
与limit_escape旧直接版同理: 使用前应确保lift节点已死/已停, 避免双主站抢SDO.
"""
import os
import sys
import time

source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if os.path.isdir(source):
    sys.path.insert(0, source)
from kinco_lift.canopen import SocketCan, SdoClient


def main():
    transport = SocketCan('can0')
    sdo = SdoClient(transport, 1)
    try:
        pos = sdo.read(0x6063, signed=True)
        vel = sdo.read(0x606C, signed=True)
        print('before: pos=%d vel=%d' % (pos, vel), flush=True)
        sdo.write(0x60FF, 0, size=4, signed=True)
        sdo.write(0x6040, 0x0006, size=2)
        time.sleep(0.5)
        pos = sdo.read(0x6063, signed=True)
        vel = sdo.read(0x606C, signed=True)
        print('after:  pos=%d vel=%d' % (pos, vel), flush=True)
    finally:
        transport.close()


if __name__ == '__main__':
    main()
