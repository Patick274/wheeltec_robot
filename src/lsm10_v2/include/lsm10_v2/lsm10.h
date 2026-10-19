/*******************************************************
@company: Copyright (C) 2021, Leishen Intelligent System
@product: LSM10
@filename: lsm10.h
@brief:    LSM10 激光雷达 ROS 驱动类的声明
@version:       date:       author:     comments:
@v1.0           21-2-4      yao          new
*******************************************************/
#ifndef LSM10_H
#define LSM10_H
#include <boost/date_time/posix_time/posix_time.hpp>  // 时间相关(用于计算转速)
#include <boost/thread.hpp>                            // 线程、互斥锁、条件变量
#include <string>
#include <ros/ros.h>
#include <sensor_msgs/LaserScan.h>                     // 标准激光点云消息
#include "lsm10_v2/lsiosr.h"

namespace ls {

/* 单个扫描点的结构: 角度(度)、距离(米)、强度 */
typedef struct {
    double degree;
    double range;
    double intensity;
} ScanPoint;

/*
 * LSM10 雷达驱动主类
 * 职责: 串口数据接收解析(recvThread) + 点云发布(pubScanThread)
 */
class LSM10
{
public:
  LSM10();
  ~LSM10();
    /**
    * 实例化雷达(单例)
    * port: 串口号,
    * baud_rate: 波特率 460800
    */
    static LSM10* instance();

    /**
    * 获取雷达数据
    * poins: 雷达点的数据。类型为ScanPoint数组
    */
    int getScan(std::vector<ScanPoint> &points, ros::Time &scan_time, float &scan_duration);

    /**
    * 获取软件版本号
    * version: 返回版本号
    */
    int getVersion(std::string &version);

    int getRate();       // 声明但未实现, 实际用的是 getRPM()

    double getRPM();     // 返回实测转速(转/秒)

  private:
    void initParam();    // 从参数服务器读取配置
    void recvThread();   // 接收线程: 读串口 + 解析报文
    void pubScanThread();// 发布线程: 组装并发布 LaserScan

    std::vector<ScanPoint> scan_points_;     // 正在累积的"当前一圈"点云
    std::vector<ScanPoint> scan_points_bak_; // 已收齐的"上一圈"点云(供发布)

    LSIOSR * serial_;                 // 串口驱动对象
    boost::thread *recv_thread_;      // 接收线程句柄
    boost::thread *pubscan_thread_;   // 发布线程句柄
    boost::mutex pubscan_mutex_;      // 发布线程的互斥锁(配合条件变量)
    boost::mutex mutex_;              // 保护 scan_points_ / scan_points_bak_ 的锁
    boost::condition_variable pubscan_cond_;  // 条件变量: 通知发布线程"一圈数据就绪"

    bool is_shutdown_;    // 关闭标志, 置位后各线程退出
    int data_len_;        // 接收缓冲区大小(字节)
    int points_size_;     // 一圈总点数(1008)
    int rpm_;             // 标称转速(转/分)
    double real_rpm_;     // 实测转速(转/秒)

    ros::Time pre_time_;  // 上一圈数据的结束时间
    ros::Time time_;      // 当前圈数据的结束时间
	ros::Publisher device_pub;   // 设备信息(difop)发布器

    std::string serial_port_;     // 串口设备路径
    int baud_rate_;               // 波特率
    std::string scan_topic_;      // 点云发布话题
    std::string frame_id_;        // 点云坐标系名

    ros::NodeHandle n_;           // 节点句柄(创建发布器用)
    ros::Publisher pub_;          // LaserScan 点云发布器
    int truncated_mode_;          // 是否启用角度截断(屏蔽指定角度)
    double min_distance,max_distance;   // 有效距离范围(米)
    std::vector<int> disable_angle_min_range, disable_angle_max_range, disable_angle_range_default;  // 屏蔽角度区间
};

}

#endif
