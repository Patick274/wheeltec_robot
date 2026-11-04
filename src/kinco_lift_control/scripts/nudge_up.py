#!/usr/bin/env python3
"""测试前置: 节点外直接驱动, 100rpm上行步进直到上限位开关触发, 打印触发位置.

用途: 在"软件端点内缩5mm"配置下, 机构无法经受监督路径触到物理上限位开关;
为验收escape_upper_limit, 需要先把机构送到开关上(测试前置条件, 不是释放方法).
使用前必须 rosnode kill /lift. 触发后立即写零速度并撤使能.
"""
import os
import sys
import time

source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if os.path.isdir(source):
    sys.path.insert(0, source)
from kinco_lift.canopen import SocketCan, SdoClient

RPM100_RAW = 1789569  # velocity_raw(100)
ACCEL_RAW = 107374    # acceleration_raw(100)


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
    triggered = None
    try:
        pos = sdo.read(0x6063, signed=True)
        inp = sdo.read(0x60FD)
        print('init: pos=%d inputs=0x%X' % (pos, inp), flush=True)
        if inp & 2:
            print('already on upper switch; nothing to do.', flush=True)
            return
        sdo.write(0x6040, 0x0006, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x21, 'ready')
        sdo.write(0x60FF, 0, size=4, signed=True)
        sdo.write(0x6060, 3, size=1, signed=True)
        sdo.write(0x6083, ACCEL_RAW, size=4)
        sdo.write(0x6040, 0x0007, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x23, 'switched-on')
        sdo.write(0x6040, 0x000F, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x27, 'enabled')
        print('enabled; nudging up at 100rpm, polling switch every 50ms (max 15mm).', flush=True)
        start = sdo.read(0x6063, signed=True)
        sdo.write(0x60FF, RPM100_RAW, size=4, signed=True)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 6.0:
            pos = sdo.read(0x6063, signed=True)
            inp = sdo.read(0x60FD)
            if inp & 2:
                triggered = pos
                break
            if (pos - start) * 2.25 / 65536 > 15.0:
                print('SAFETY: traveled 15mm without trigger, stopping.', flush=True)
                break
            time.sleep(0.05)
        sdo.write(0x60FF, 0, size=4, signed=True)
        time.sleep(0.5)
        settle = sdo.read(0x6063, signed=True)
        inp = sdo.read(0x60FD)
        print('trigger_read=%s settle=%d inputs=0x%X upper=%s'
              % (triggered, settle, inp, bool(inp & 2)), flush=True)
        sdo.write(0x6040, 0x0007, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x23, 'switched-on-2')
        sdo.write(0x6040, 0x0006, size=2)
        wait_word(sdo, lambda w: w & 0x6F == 0x21, 'ready-2')
        print('disabled cleanly.', flush=True)
    finally:
        try:
            sdo.write(0x60FF, 0, size=4, signed=True)
        except Exception:
            pass
        transport.close()


if __name__ == '__main__':
    main()
