#!/usr/bin/env python3
"""上限位逃生: 节点外直接驱动, 以100rpm下行直到上限位开关释放(最多5x1s).

仅用于"机构停在上限位开关上、节点所有软路径拒绝"的人工处置场景.
使用前必须 rosnode kill /lift (节点独占CAN会话). 方向: up_direction=1, 下行=负速度.
"""
import os
import sys
import time

source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if os.path.isdir(source):
    sys.path.insert(0, source)
from kinco_lift.canopen import SocketCan, SdoClient

RPM100_RAW = 1789569  # velocity_raw(100) = 100*512*65536/1875
ACCEL_RAW = 107374    # acceleration_raw(100) = 100*65536*65536/4000000


def wait_word(sdo, pred, label, timeout=3.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        w = sdo.read(0x6041, size=2)
        if pred(w):
            return w
        time.sleep(0.05)
    raise RuntimeError('statusword wait timeout: ' + label)


def main():
    transport = SocketCan('can0')
    sdo = SdoClient(transport, 1)
    try:
        w = sdo.read(0x6041, size=2)
        pos = sdo.read(0x6063, signed=True)
        inp = sdo.read(0x60FD)
        print('init: sw=0x%04X pos=%d inputs=0x%X (bit1=upper)' % (w, pos, inp), flush=True)
        if not (inp & 2):
            print('upper limit NOT active; nothing to escape, aborting writes.', flush=True)
            return
        # 关断->就绪->速度模式->使能 (复用节点握手顺序, 不武装节点保护).
        sdo.write(0x6040, 0x0006, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x21, 'ready')
        sdo.write(0x60FF, 0, size=4, signed=True)
        sdo.write(0x6060, 3, size=1, signed=True)
        sdo.write(0x6083, ACCEL_RAW, size=4)
        sdo.write(0x6040, 0x0007, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x23, 'switched-on')
        sdo.write(0x6040, 0x000F, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x27, 'enabled')
        print('enabled in velocity mode; descending in 1s steps until switch releases.', flush=True)
        for step in range(5):
            sdo.write(0x60FF, -RPM100_RAW, size=4, signed=True)
            time.sleep(1.0)
            sdo.write(0x60FF, 0, size=4, signed=True)
            time.sleep(0.3)
            pos = sdo.read(0x6063, signed=True)
            inp = sdo.read(0x60FD)
            print('step %d: pos=%d inputs=0x%X upper=%s' % (step + 1, pos, inp, bool(inp & 2)), flush=True)
            if not (inp & 2):
                print('upper switch RELEASED.', flush=True)
                break
        else:
            print('WARNING: switch still active after 5 steps (~19mm).', flush=True)
        sdo.write(0x6040, 0x0007, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x23, 'switched-on-2')
        sdo.write(0x6040, 0x0006, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x21, 'ready-2')
        print('disabled cleanly. Done.', flush=True)
    finally:
        try:
            sdo.write(0x60FF, 0, size=4, signed=True)
        except Exception:
            pass
        transport.close()


if __name__ == '__main__':
    main()
