#!/usr/bin/env bash
# 测试入口：不需要 ROS/真机（parser/decode/契约为纯数据测试）
cd "$(dirname "$0")/.." || exit 1
PYTHONPATH=src python -m pytest test/ "$@"
