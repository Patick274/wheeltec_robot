#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import math
import yaml

import rospy
from rviz import bindings as rviz

from python_qt_binding import QtCore, QtWidgets
from geometry_msgs.msg import PoseWithCovarianceStamped, PoseStamped


def yaw_to_quaternion(yaw):
    from geometry_msgs.msg import Quaternion
    q = Quaternion()
    q.z = math.sin(yaw * 0.5)
    q.w = math.cos(yaw * 0.5)
    return q


def pose_stamped_to_dict(msg):
    # yaw from quaternion (2D assumption)
    q = msg.pose.orientation
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return {
        'name': '',
        'frame_id': msg.header.frame_id if msg.header.frame_id else 'map',
        'x': float(msg.pose.position.x),
        'y': float(msg.pose.position.y),
        'z': float(msg.pose.position.z),
        'yaw': float(yaw),
    }


class RvizNavConsole(QtWidgets.QMainWindow):
    def __init__(self):
        super(RvizNavConsole, self).__init__()
        self.setWindowTitle('RViz-style Navigation Console')
        self.resize(1500, 900)

        self.goal_topic = rospy.get_param('~goal_topic', '/move_base_simple/goal')
        self.initialpose_topic = rospy.get_param('~initialpose_topic', '/initialpose')
        self.map_topic = rospy.get_param('~map_topic', '/map')
        self.scan_topic = rospy.get_param('~scan_topic', '/scan')
        self.pointcloud_topic = rospy.get_param('~pointcloud_topic', '/camera/depth/color/points')
        self.global_path_topic = rospy.get_param('~global_path_topic', '/move_base/NavfnROS/plan')
        self.local_path_topic = rospy.get_param('~local_path_topic', '/move_base/TrajectoryPlannerROS/local_plan')
        self.amcl_topic = rospy.get_param('~amcl_topic', '/amcl_pose')
        self.fixed_frame = rospy.get_param('~fixed_frame', 'map')
        self.yaml_path = rospy.get_param('~waypoints_yaml', os.path.expanduser('~/waypoints.yaml'))

        self.waypoints = []
        self.latest_initial_pose = None

        self._build_ui()
        self._setup_ros()
        self._setup_rviz()
        self._load_waypoints_silent(self.yaml_path)

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout(central)

        # RViz panel
        self.render_panel = rviz.RenderPanel()
        layout.addWidget(self.render_panel, 1)

        # Right side controls
        side = QtWidgets.QWidget()
        side.setMinimumWidth(360)
        side_layout = QtWidgets.QVBoxLayout(side)
        layout.addWidget(side)

        tool_group = QtWidgets.QGroupBox('Interactive tools')
        tool_layout = QtWidgets.QVBoxLayout(tool_group)
        self.btn_init_tool = QtWidgets.QPushButton('2D Pose Estimate')
        self.btn_goal_tool = QtWidgets.QPushButton('2D Nav Goal')
        self.btn_select_tool = QtWidgets.QPushButton('Select / Interact')
        tool_layout.addWidget(self.btn_init_tool)
        tool_layout.addWidget(self.btn_goal_tool)
        tool_layout.addWidget(self.btn_select_tool)
        side_layout.addWidget(tool_group)

        display_group = QtWidgets.QGroupBox('Display toggles')
        disp_layout = QtWidgets.QVBoxLayout(display_group)
        self.chk_map = QtWidgets.QCheckBox('Map')
        self.chk_robot = QtWidgets.QCheckBox('Robot pose arrow (/amcl_pose)')
        self.chk_scan = QtWidgets.QCheckBox('LaserScan')
        self.chk_cloud = QtWidgets.QCheckBox('PointCloud2')
        self.chk_global_path = QtWidgets.QCheckBox('Global path')
        self.chk_local_path = QtWidgets.QCheckBox('Local path')
        for chk in [self.chk_map, self.chk_robot, self.chk_scan, self.chk_cloud,
                    self.chk_global_path, self.chk_local_path]:
            chk.setChecked(True)
            disp_layout.addWidget(chk)
        side_layout.addWidget(display_group)

        init_group = QtWidgets.QGroupBox('Initial pose')
        init_layout = QtWidgets.QVBoxLayout(init_group)
        self.lbl_initial = QtWidgets.QLabel('Latest /initialpose: None')
        self.btn_publish_initial = QtWidgets.QPushButton('Republish latest initial pose')
        init_layout.addWidget(self.lbl_initial)
        init_layout.addWidget(self.btn_publish_initial)
        side_layout.addWidget(init_group)

        wp_group = QtWidgets.QGroupBox('Saved patrol waypoints')
        wp_layout = QtWidgets.QVBoxLayout(wp_group)
        self.list_waypoints = QtWidgets.QListWidget()
        self.list_waypoints.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        wp_layout.addWidget(self.list_waypoints)

        row1 = QtWidgets.QHBoxLayout()
        self.btn_add_latest_goal = QtWidgets.QPushButton('Add last clicked goal')
        self.btn_delete_wp = QtWidgets.QPushButton('Delete selected')
        row1.addWidget(self.btn_add_latest_goal)
        row1.addWidget(self.btn_delete_wp)
        wp_layout.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        self.btn_clear_wp = QtWidgets.QPushButton('Clear all')
        self.btn_move_up = QtWidgets.QPushButton('Up')
        self.btn_move_down = QtWidgets.QPushButton('Down')
        row2.addWidget(self.btn_clear_wp)
        row2.addWidget(self.btn_move_up)
        row2.addWidget(self.btn_move_down)
        wp_layout.addLayout(row2)

        row3 = QtWidgets.QHBoxLayout()
        self.edit_yaml = QtWidgets.QLineEdit(self.yaml_path)
        self.btn_save_yaml = QtWidgets.QPushButton('Save YAML')
        row3.addWidget(self.edit_yaml)
        row3.addWidget(self.btn_save_yaml)
        wp_layout.addLayout(row3)

        row4 = QtWidgets.QHBoxLayout()
        self.btn_load_yaml = QtWidgets.QPushButton('Load YAML')
        self.btn_export_current = QtWidgets.QPushButton('Save clicked goals now')
        row4.addWidget(self.btn_load_yaml)
        row4.addWidget(self.btn_export_current)
        wp_layout.addLayout(row4)

        note = QtWidgets.QLabel(
            'Usage:\n'
            '1) click "2D Pose Estimate" then drag on map to set initial pose\n'
            '2) click "2D Nav Goal" then drag on map to add patrol goals\n'
            '3) clicked goals are captured from /move_base_simple/goal and can be saved to YAML'
        )
        note.setWordWrap(True)
        wp_layout.addWidget(note)

        side_layout.addWidget(wp_group, 1)

        self.status_bar = QtWidgets.QStatusBar()
        self.setStatusBar(self.status_bar)

        # Signals
        self.btn_init_tool.clicked.connect(self.activate_init_tool)
        self.btn_goal_tool.clicked.connect(self.activate_goal_tool)
        self.btn_select_tool.clicked.connect(self.activate_select_tool)
        self.btn_add_latest_goal.clicked.connect(self.add_last_clicked_goal)
        self.btn_delete_wp.clicked.connect(self.delete_selected_waypoint)
        self.btn_clear_wp.clicked.connect(self.clear_waypoints)
        self.btn_move_up.clicked.connect(self.move_selected_up)
        self.btn_move_down.clicked.connect(self.move_selected_down)
        self.btn_save_yaml.clicked.connect(self.save_yaml)
        self.btn_load_yaml.clicked.connect(self.load_yaml)
        self.btn_export_current.clicked.connect(self.save_yaml)
        self.btn_publish_initial.clicked.connect(self.republish_initial_pose)

    def _setup_ros(self):
        self.initial_pub = rospy.Publisher(self.initialpose_topic, PoseWithCovarianceStamped, queue_size=1, latch=True)
        self.goal_sub = rospy.Subscriber(self.goal_topic, PoseStamped, self._on_goal_clicked, queue_size=10)
        self.initial_sub = rospy.Subscriber(self.initialpose_topic, PoseWithCovarianceStamped, self._on_initial_pose, queue_size=10)
        self.last_clicked_goal = None

    def _setup_rviz(self):
        self.manager = rviz.VisualizationManager(self.render_panel)
        self.render_panel.initialize(self.manager.getSceneManager(), self.manager)
        self.manager.initialize()
        self.manager.startUpdate()
        self.manager.setFixedFrame(self.fixed_frame)

        root = self.manager.getRootDisplayGroup()

        self.map_display = self.manager.createDisplay('rviz/Map', 'Map', True)
        self.map_display.subProp('Topic').setValue(self.map_topic)
        self.map_display.subProp('Alpha').setValue(0.7)

        self.robot_display = self.manager.createDisplay('rviz/PoseWithCovariance', 'RobotPose', True)
        self.robot_display.subProp('Topic').setValue(self.amcl_topic)
        self.robot_display.subProp('Shape').setValue('Arrow')
        self.robot_display.subProp('Color').setValue('255; 25; 0')
        self.robot_display.subProp('Alpha').setValue(1.0)

        self.scan_display = self.manager.createDisplay('rviz/LaserScan', 'LaserScan', True)
        self.scan_display.subProp('Topic').setValue(self.scan_topic)
        self.scan_display.subProp('Style').setValue('Flat Squares')
        self.scan_display.subProp('Size (m)').setValue(0.03)

        self.cloud_display = self.manager.createDisplay('rviz/PointCloud2', 'PointCloud', True)
        self.cloud_display.subProp('Topic').setValue(self.pointcloud_topic)
        self.cloud_display.subProp('Style').setValue('Flat Squares')
        self.cloud_display.subProp('Size (Pixels)').setValue(3)

        self.global_path_display = self.manager.createDisplay('rviz/Path', 'GlobalPath', True)
        self.global_path_display.subProp('Topic').setValue(self.global_path_topic)
        self.global_path_display.subProp('Line Style').setValue('Lines')
        self.global_path_display.subProp('Line Width').setValue(0.03)

        self.local_path_display = self.manager.createDisplay('rviz/Path', 'LocalPath', True)
        self.local_path_display.subProp('Topic').setValue(self.local_path_topic)
        self.local_path_display.subProp('Line Style').setValue('Lines')
        self.local_path_display.subProp('Line Width').setValue(0.03)

        self.tool_manager = self.manager.getToolManager()
        self.tool_interact = self.tool_manager.addTool('rviz/Interact')
        self.tool_init = self.tool_manager.addTool('rviz/SetInitialPose')
        self.tool_goal = self.tool_manager.addTool('rviz/SetGoal')

        self.chk_map.toggled.connect(self.map_display.setEnabled)
        self.chk_robot.toggled.connect(self.robot_display.setEnabled)
        self.chk_scan.toggled.connect(self.scan_display.setEnabled)
        self.chk_cloud.toggled.connect(self.cloud_display.setEnabled)
        self.chk_global_path.toggled.connect(self.global_path_display.setEnabled)
        self.chk_local_path.toggled.connect(self.local_path_display.setEnabled)

        self.activate_select_tool()

    def activate_select_tool(self):
        self.tool_manager.setCurrentTool(self.tool_interact)
        self.status_bar.showMessage('Current tool: Interact', 3000)

    def activate_init_tool(self):
        self.tool_manager.setCurrentTool(self.tool_init)
        self.status_bar.showMessage('Current tool: 2D Pose Estimate', 3000)

    def activate_goal_tool(self):
        self.tool_manager.setCurrentTool(self.tool_goal)
        self.status_bar.showMessage('Current tool: 2D Nav Goal', 3000)

    def _on_goal_clicked(self, msg):
        self.last_clicked_goal = pose_stamped_to_dict(msg)
        if not self.last_clicked_goal['name']:
            self.last_clicked_goal['name'] = 'point_{:02d}'.format(len(self.waypoints) + 1)
        self.status_bar.showMessage(
            'Captured clicked goal: x={:.3f}, y={:.3f}, yaw={:.3f}'.format(
                self.last_clicked_goal['x'], self.last_clicked_goal['y'], self.last_clicked_goal['yaw']), 5000)

    def _on_initial_pose(self, msg):
        self.latest_initial_pose = msg
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        text = 'Latest /initialpose: x={:.3f}, y={:.3f}, yaw={:.3f}'.format(p.x, p.y, yaw)
        self.lbl_initial.setText(text)

    def republish_initial_pose(self):
        if self.latest_initial_pose is None:
            self.status_bar.showMessage('No initial pose captured yet.', 3000)
            return
        self.latest_initial_pose.header.stamp = rospy.Time.now()
        self.initial_pub.publish(self.latest_initial_pose)
        self.status_bar.showMessage('Republished latest initial pose.', 3000)

    def add_last_clicked_goal(self):
        if self.last_clicked_goal is None:
            self.status_bar.showMessage('No clicked goal captured yet. Use 2D Nav Goal first.', 4000)
            return
        wp = dict(self.last_clicked_goal)
        wp['name'] = 'point_{:02d}'.format(len(self.waypoints) + 1)
        self.waypoints.append(wp)
        self._refresh_waypoint_list()
        self.status_bar.showMessage('Added waypoint {}'.format(wp['name']), 3000)

    def delete_selected_waypoint(self):
        row = self.list_waypoints.currentRow()
        if row < 0:
            return
        del self.waypoints[row]
        self._renumber_waypoints()
        self._refresh_waypoint_list()

    def clear_waypoints(self):
        self.waypoints = []
        self._refresh_waypoint_list()
        self.status_bar.showMessage('Cleared all waypoints.', 3000)

    def move_selected_up(self):
        row = self.list_waypoints.currentRow()
        if row <= 0:
            return
        self.waypoints[row - 1], self.waypoints[row] = self.waypoints[row], self.waypoints[row - 1]
        self._renumber_waypoints()
        self._refresh_waypoint_list(select_row=row - 1)

    def move_selected_down(self):
        row = self.list_waypoints.currentRow()
        if row < 0 or row >= len(self.waypoints) - 1:
            return
        self.waypoints[row + 1], self.waypoints[row] = self.waypoints[row], self.waypoints[row + 1]
        self._renumber_waypoints()
        self._refresh_waypoint_list(select_row=row + 1)

    def _renumber_waypoints(self):
        for i, wp in enumerate(self.waypoints):
            wp['name'] = 'point_{:02d}'.format(i + 1)

    def _refresh_waypoint_list(self, select_row=None):
        self.list_waypoints.clear()
        for wp in self.waypoints:
            text = '{name}: x={x:.3f}, y={y:.3f}, yaw={yaw:.3f}, frame={frame_id}'.format(**wp)
            self.list_waypoints.addItem(text)
        if select_row is not None and 0 <= select_row < self.list_waypoints.count():
            self.list_waypoints.setCurrentRow(select_row)

    def save_yaml(self):
        path = self.edit_yaml.text().strip()
        if not path:
            self.status_bar.showMessage('Please input a YAML path first.', 3000)
            return
        data = {
            'initial_pose': None,
            'waypoints': self.waypoints,
        }
        if self.latest_initial_pose is not None:
            p = self.latest_initial_pose.pose.pose.position
            q = self.latest_initial_pose.pose.pose.orientation
            siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
            yaw = math.atan2(siny_cosp, cosy_cosp)
            data['initial_pose'] = {
                'frame_id': self.latest_initial_pose.header.frame_id if self.latest_initial_pose.header.frame_id else self.fixed_frame,
                'x': float(p.x),
                'y': float(p.y),
                'z': float(p.z),
                'yaw': float(yaw),
            }
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        self.status_bar.showMessage('Saved YAML: {}'.format(path), 4000)

    def load_yaml(self):
        path = self.edit_yaml.text().strip()
        self._load_waypoints_silent(path)

    def _load_waypoints_silent(self, path):
        if not path or not os.path.exists(path):
            return
        with open(path, 'r') as f:
            data = yaml.safe_load(f) or {}
        self.waypoints = data.get('waypoints', [])
        self._renumber_waypoints()
        self._refresh_waypoint_list()
        self.status_bar.showMessage('Loaded YAML: {}'.format(path), 3000)


def main():
    rospy.init_node('rviz_nav_console', anonymous=False)
    app = QtWidgets.QApplication([])
    win = RvizNavConsole()
    win.show()
    app.exec_()


if __name__ == '__main__':
    main()
