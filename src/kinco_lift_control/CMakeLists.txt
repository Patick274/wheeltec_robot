cmake_minimum_required(VERSION 3.0.2)
project(kinco_lift_control)
# 编译自定义ROS服务；控制逻辑本身是Python，不构建C++电机程序。
find_package(catkin REQUIRED COMPONENTS message_generation rospy std_msgs std_srvs geometry_msgs nav_msgs)
catkin_python_setup()
add_service_files(FILES MoveLift.srv JogLift.srv)
generate_messages()
catkin_package(CATKIN_DEPENDS message_runtime rospy std_msgs std_srvs geometry_msgs nav_msgs)
catkin_install_python(PROGRAMS scripts/lift_node.py scripts/probe_drive.py scripts/diagnose_can.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION})
install(DIRECTORY launch config docs DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})
install(FILES README.md explain.yaml DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})
