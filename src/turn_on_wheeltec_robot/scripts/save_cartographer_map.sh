#!/bin/bash
# cartographer 建图保存脚本
# 用法: ./save_cartographer_map.sh [地图名]   (默认 wheeltec_map)
# 产物: ~/wheeltec_robot/src/turn_on_wheeltec_robot/map/<地图名>.pbstream / .pgm / .yaml

set -e
MAP_NAME="${1:-wheeltec_map}"
MAP_DIR="$HOME/wheeltec_robot/src/turn_on_wheeltec_robot/map"
PBSTREAM="$MAP_DIR/$MAP_NAME.pbstream"

mkdir -p "$MAP_DIR"

echo "[1/3] 结束轨迹并执行最后一次全局优化..."
rosservice call /finish_trajectory 0

echo "[2/3] 写出 pbstream: $PBSTREAM"
rosservice call /write_state "{filename: '$PBSTREAM', include_unfinished_submaps: true}"

echo "[3/3] 转换 pbstream -> pgm/yaml ..."
rosrun cartographer_ros cartographer_pbstream_to_ros_map \
  -pbstream_filename="$PBSTREAM" \
  -map_filestem="$MAP_DIR/$MAP_NAME"

echo "完成: $MAP_DIR/$MAP_NAME.{pbstream,pgm,yaml}"
echo "导航使用: 修改 navigation.launch 的 map_file 指向 $MAP_NAME.yaml"
