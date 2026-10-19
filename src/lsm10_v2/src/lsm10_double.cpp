#include "ros/ros.h"
#include "sensor_msgs/LaserScan.h"
#include <pcl/point_types.h>
#include <pcl/point_cloud.h>
#include <boost/thread.hpp>
#include <cmath>
#include <algorithm>
#include <limits>

#ifndef DEG2RAD
#define DEG2RAD(x) ((x) * M_PI / 180.0)
#endif

std::string frame_id;
std::string scan_topic_;
double lidar1_rotate, lidar2_rotate, lidar1_xoffset, lidar2_xoffset, lidar1_yoffset, lidar2_yoffset;

boost::mutex g_mutex;
sensor_msgs::LaserScan g_scan1;
sensor_msgs::LaserScan g_scan2;
bool g_have_scan1 = false;
bool g_have_scan2 = false;
ros::Publisher g_pub;

static void fuseAndPublish(const sensor_msgs::LaserScan &msg1,
                           const sensor_msgs::LaserScan &msg2)
{
  if (msg1.ranges.empty() || msg2.ranges.empty())
    return;

  double angle_min = msg1.angle_min;
  double angle_max = msg1.angle_max;
  double angle_increment = msg1.angle_increment;
  size_t node_count = msg1.ranges.size();

  sensor_msgs::LaserScan scan_msg;
  // 用两帧里更早的时间戳，保证该时刻的 tf 已可用，避免 rviz/gmapping 外推导致频闪
  scan_msg.header.stamp = (msg1.header.stamp < msg2.header.stamp) ? msg1.header.stamp : msg2.header.stamp;
  scan_msg.header.frame_id = frame_id;
  scan_msg.angle_min = angle_min;
  scan_msg.angle_max = angle_max;
  scan_msg.angle_increment = angle_increment;
  scan_msg.scan_time = (msg1.scan_time > 0) ? msg1.scan_time : 0.05;  // 一圈的时间，约 0.05s@20Hz
  scan_msg.time_increment = scan_msg.scan_time / (double)(node_count - 1);
  scan_msg.range_min = std::min(msg1.range_min, msg2.range_min);
  scan_msg.range_max = std::max(msg1.range_max, msg2.range_max);
  scan_msg.ranges.assign(node_count, std::numeric_limits<float>::infinity());
  scan_msg.intensities.assign(node_count, 0.0f);

  // 把某一帧雷达投影到融合坐标系，取每格最近距离
  auto project = [&](const sensor_msgs::LaserScan &scan, double rotate, double xoff, double yoff) {
    for (size_t i = 0; i < scan.ranges.size(); i++) {
      float r = scan.ranges[i];
      if (!std::isfinite(r))
        continue;
      double a = scan.angle_min + scan.angle_increment * i;
      double x = r * cos(a);
      double y = r * sin(a);
      double px = x * cos(DEG2RAD(rotate)) - y * sin(DEG2RAD(rotate)) + xoff;
      double py = x * sin(DEG2RAD(rotate)) + y * cos(DEG2RAD(rotate)) + yoff;
      double range = hypot(px, py);
      double ang = atan2(py, px);
      int idx = (int)round((ang - angle_min) / angle_increment);
      if (idx >= 0 && idx < (int)node_count && range < scan_msg.ranges[idx]) {
        scan_msg.ranges[idx] = (float)range;
        scan_msg.intensities[idx] = scan.intensities[i];
      }
    }
  };

  project(msg1, lidar1_rotate, lidar1_xoffset, lidar1_yoffset);
  project(msg2, lidar2_rotate, lidar2_xoffset, lidar2_yoffset);

  g_pub.publish(scan_msg);
}

static void scan1Cb(const sensor_msgs::LaserScan::ConstPtr &msg)
{
  boost::lock_guard<boost::mutex> lock(g_mutex);
  g_scan1 = *msg;
  g_have_scan1 = true;
  if (g_have_scan2)
    fuseAndPublish(g_scan1, g_scan2);
}

static void scan2Cb(const sensor_msgs::LaserScan::ConstPtr &msg)
{
  boost::lock_guard<boost::mutex> lock(g_mutex);
  g_scan2 = *msg;
  g_have_scan2 = true;
  if (g_have_scan1)
    fuseAndPublish(g_scan1, g_scan2);
}

int main(int argc, char **argv)
{
  ros::init(argc, argv, "lsm10_v2_double");
  ROS_INFO("Lsm10_v2_double init");
  ros::NodeHandle nh;
  ros::NodeHandle nh_private("~");
  nh_private.param<std::string>("frame_id", frame_id, "laser");
  nh_private.param<std::string>("scan_topic", scan_topic_, "/scan");
  nh_private.param<double>("lidar1_rotate", lidar1_rotate, 0);
  nh_private.param<double>("lidar2_rotate", lidar2_rotate, 0);
  nh_private.param<double>("lidar1_xoffset", lidar1_xoffset, 0);
  nh_private.param<double>("lidar2_xoffset", lidar2_xoffset, 0);
  nh_private.param<double>("lidar1_yoffset", lidar1_yoffset, 0);
  nh_private.param<double>("lidar2_yoffset", lidar2_yoffset, 0);

  ros::Subscriber sub1 = nh.subscribe<sensor_msgs::LaserScan>(
      "/scan1", 10, scan1Cb, ros::TransportHints().tcpNoDelay());
  ros::Subscriber sub2 = nh.subscribe<sensor_msgs::LaserScan>(
      "/scan2", 10, scan2Cb, ros::TransportHints().tcpNoDelay());
  g_pub = nh.advertise<sensor_msgs::LaserScan>(scan_topic_, 10);

  ros::spin();
  return 0;
}
