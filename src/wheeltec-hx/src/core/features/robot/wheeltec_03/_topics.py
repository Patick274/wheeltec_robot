"""wheeltec_03 话题/指令映射表（真实表）。

管道能力词 → ROS 话题名/消息类型/QoS 档（"default"/"sensor_data"/
"transient_local"）。消息类型用 rosidl 规范名 "pkg/msg/Type"
（roslibpy 腿内部转 "pkg/Type"，见族 `_worker.to_rosbridge_type`）。

**本表的信息来源与核实状态**（接入纪律：每条都要说清哪来的、核没核）：
- 话题名/消息类型推导自机器人侧 catkin 工作空间源码（PHM/src，
  2026-11-10 离线阅读）——`turn_on_wheeltec_robot/src/wheeltec_robot.cpp`
  （/PowerVoltage、/odom、/imu）、`kinco_lift_control/scripts/lift_node.py`
  （/lift/*）、`turn_on_wheeltec_robot/launch/robot_model_visualization.launch`
  （robot_description、robot_state_publisher → /tf、/tf_static、
  /joint_states）、`usb_cam/launch`（/image_raw/compressed）。
- **待真机核实**：按 docs/onboarding.md 的自省链路（scripts/
  introspection_probe.py + verify_wheeltec_03.py）在真机上跑一遍，
  逐条核对后把本段的"待核实"标注去掉。这正是提示词.txt 方法论的
  阶段 3 在该项目上的落地。

**机型差异判据**（仿 jdyw-hx 机型包契约）：同名话题在不同机型上可以是
完全不同的数据（/joint_states 的关节集由 URDF 决定），各机型包各自
一份表、互不参照——"改一处要改两处"是正常成本，不是待还的债。
"""

TOPICS: dict[str, dict[str, dict]] = {
    # 图像管道（pipe=image）：
    "image": {
        # 主摄（usb_cam 的 image_transport 压缩插件；launch 里 remap 到
        # /image_raw/compressed）。ROS1 sensor_msgs/CompressedImage 是标准
        # 类型，不涉及厂商接口包。
        # queue_length=1 + throttle 100ms：高频大流量只保最新帧
        # （jdyw-hx 实测纪律，沿用）。
        "color": {"topic": "/image_raw/compressed",
                  "msg": "sensor_msgs/msg/CompressedImage",
                  "qos": "sensor_data",
                  "roslibpy": {"queue_length": 1, "throttle_rate": 100}},
    },
    "telemetry": {
        # 装配描述（URDF，robot_state_publisher 体系的标准参数话题；
        # ROS1 下由 robot_state_publisher latch 发布——必须 transient_local
        # 语义订阅，否则永远收不到；jdyw-hx 实测 0 字符 vs 21297 字符）。
        "robot_description": {"topic": "/robot_description",
                              "msg": "std_msgs/msg/String",
                              "qos": "transient_local",
                              "rearm_dry_limit": 2},
        # 坐标系变换：静态（latch：base_footprint→base_link、laser 挂载等，
        # 见 robot_model_visualization.launch 的 static_transform_publisher）
        # 与动态（robot_pose_ekf 发 odom_combined→base_footprint 定位链）。
        # start_after：URDF 必须先装配完，TF 才开始接收（jdyw-hx 2026-10-10
        # 用户口径，沿用）。
        "tf_static": {"topic": "/tf_static",
                      "msg": "tf2_msgs/msg/TFMessage",
                      "qos": "transient_local",
                      "start_after": "robot_description",
                      "rearm_dry_limit": 10},
        "tf": {"topic": "/tf",
               "msg": "tf2_msgs/msg/TFMessage",
               "qos": "default",
               "start_after": "robot_description"},
        # 电池电压（设备在线心跳的唯一来源；wheeltec_robot_node 发布）。
        # **绝不节流**——6s 无帧判离线，节流丢帧会假离线（jdyw-hx 实测）。
        "power_voltage": {"topic": "/PowerVoltage",
                          "msg": "std_msgs/msg/Float32",
                          "qos": "default"},
        # 里程计（底盘 twist 线/角速度；wheeltec_robot_node 发布 ~高频，
        # 只用于显示 → 节流到 10Hz）。位姿权威是 TF，odom 只取速度。
        "odom": {"topic": "/odom",
                 "msg": "nav_msgs/msg/Odometry",
                 "qos": "sensor_data",
                 "roslibpy": {"queue_length": 1, "throttle_rate": 100}},
        # IMU（gyro_link 系；显示姿态用，低频节流即可）。
        "imu": {"topic": "/imu",
                "msg": "sensor_msgs/msg/Imu",
                "qos": "sensor_data",
                "roslibpy": {"queue_length": 1, "throttle_rate": 200}},
        # 关节状态（本机型 = 左右轮 continuous 关节，joint_state_publisher
        # 发零位；轮子转速不在这里）。**本机型自己一份词表**——同名话题在
        # 别的机型上可能是 6 轴臂（jdyw_01），互不参照。
        "joint_states": {"topic": "/joint_states",
                         "msg": "sensor_msgs/msg/JointState",
                         "qos": "sensor_data",
                         "roslibpy": {"queue_length": 1,
                                      "throttle_rate": 200}},
        # -- 升降柱（kinco FD125，本机型私有链路）------------------------------
        # 状态全貌（latch JSON 串：busy/位置/速度/限位/报警/会话零点等，
        # 字段集见 lift_node.py publish()；解帧在本包 _decode.py）。
        "lift_status": {"topic": "/lift/status",
                        "msg": "std_msgs/msg/String",
                        "qos": "transient_local",
                        "rearm_dry_limit": 2},
        # 相对下限位零点的绝对伸长（mm）与顶端总高（m）——显示用。
        "lift_position_mm": {"topic": "/lift/position_mm",
                             "msg": "std_msgs/msg/Float64",
                             "qos": "default",
                             "roslibpy": {"queue_length": 1,
                                          "throttle_rate": 200}},
        "lift_top_height_m": {"topic": "/lift/top_height_m",
                              "msg": "std_msgs/msg/Float64",
                              "qos": "default",
                              "roslibpy": {"queue_length": 1,
                                           "throttle_rate": 200}},
    },
}

COMMANDS: dict[str, dict[str, dict]] = {
    # **上行指令表**（本机 → 机器人）。与 TOPICS 平行、不能合并（TOPICS 是
    # 订阅闸门的词汇表）。每行 kind 决定走哪种 ROS 通信：
    # topic → publish / service → call。本机型是 ROS1 机器人，无 action
    # 服务端在案（待真机自省核实；若发现再补族层 send_goal）。
    "telemetry": {
        # 底盘速度（twist_mux 仲裁后统一进 /cmd_vel；手柄优先级高于本链路
        # 的导航/遥控——仲裁规则见机器人侧 wheeltec_joy/config/twist_mux.yaml）。
        # zero：看门狗超时回落的安全值。
        # **注意升降联锁**（机器人侧实现，本表只是记录）：底盘节点在升降
        # 未给 /lift/base_motion_permit 时强制零速——上位机发速度≠底盘会动，
        # 动不了先看 /lift/status（这是安全特性，不是故障）。
        "velocity": {"kind": "topic",
                     "topic": "/cmd_vel",
                     "msg": "geometry_msgs/msg/Twist",
                     "qos": "default",
                     "parts": ["chassis"],
                     "zero": {"linear": {"x": 0.0},
                              "angular": {"z": 0.0}}},
        # -- 升降柱服务（srv 定义见机器人侧 kinco_lift_control/srv/）------------
        # 点动：相对步长 mm（正升负降，幅值受机器人侧 max_jog_mm 限制）。
        "lift_jog": {"kind": "service",
                     "service": "/lift/jog",
                     "srv": "kinco_lift_control/srv/JogLift",
                     "parts": ["lift"]},
        # 绝对高度定位：相对会话下限位零点的 mm。
        "lift_move": {"kind": "service",
                      "service": "/lift/move",
                      "srv": "kinco_lift_control/srv/MoveLift",
                      "parts": ["lift"]},
        # 顶端总高度（米）：伸长量 = (target - initial_top_height) * 1000。
        "lift_move_top_height": {"kind": "service",
                                 "service": "/lift/move_top_height",
                                 "srv": "kinco_lift_control/srv/MoveTopHeight",
                                 "parts": ["lift"]},
        # 使能/禁止（std_srvs/SetBool）。启动默认只读——先要 enable 才能动。
        "lift_enable": {"kind": "service",
                        "service": "/lift/enable",
                        "srv": "std_srvs/srv/SetBool",
                        "parts": ["lift"]},
        # 停止（锁存当前位置）。
        "lift_stop": {"kind": "service",
                      "service": "/lift/stop",
                      "srv": "std_srvs/srv/Trigger",
                      "parts": ["lift"]},
        # 上限位受困脱离（受监督；机器人侧 limit_escape.py 是 ROS 客户端，
        # 需要 lift 节点健康运行）。
        "lift_escape_upper_limit": {"kind": "service",
                                    "service": "/lift/escape_upper_limit",
                                    "srv": "std_srvs/srv/Trigger",
                                    "parts": ["lift"]},
    },
}
