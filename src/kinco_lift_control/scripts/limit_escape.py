#!/usr/bin/env python3
"""上限位释放兼容入口:调用正式节点的受监督服务.

先启动lift节点,完成现场许可后显式调用;不再直接访问CAN或绕过门禁.
流程停稳后保留使能;状态和后续确认步骤见docs/PROGRESS_20261104.md.
"""
from field_p2 import main


if __name__ == '__main__':
    raise SystemExit(main(['escape_upper']))
