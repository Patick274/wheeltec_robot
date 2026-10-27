/*******************************************************
@company: Copyright (C) 2021, Leishen Intelligent System
@product: LSM10
@filename: lsm10.cpp
@brief:    LSM10 激光雷达 ROS 驱动主逻辑:
           1) 通过串口读取雷达原始数据
           2) 解析报文, 提取角度/距离/转速等信息
           3) 组装成一圈完整的点云, 发布为 sensor_msgs/LaserScan 消息
@version:       date:       author:     comments:
@v1.0           21-2-4      yao          new
*******************************************************/
#include "lsm10_v2/lsm10.h"
#include <stdio.h>
#include <signal.h>
#include<lsm10_v2/difop.h>

namespace ls{

/*
 * 单例模式: 返回 LSM10 驱动对象的全局唯一实例
 */
LSM10 * LSM10::instance()
{
  static LSM10 obj;
  return &obj;
}

/*
 * 构造函数: 初始化参数,创建发布器,打开串口,启动两个工作线程
 */
LSM10::LSM10()
{
  int code = 0;
  initParam();   // 从 ROS 参数服务器读取配置(串口号/波特率/话题名等)

  /* 创建两个发布器:
   * 1. pub_:        发布标准 LaserScan 点云消息, 供 SLAM/导航等使用
   * 2. device_pub:  发布自定义的 difop 消息(设备信息, 如转速)
   */
  pub_ = n_.advertise<sensor_msgs::LaserScan>(scan_topic_, 3);
  device_pub = n_.advertise<lsm10_v2::difop>("difop_information", 100);

  /* 获取串口对象并初始化(打开串口,配置参数) */
  serial_ = LSIOSR::instance(serial_port_, baud_rate_);
  code = serial_->init();
  if(code != 0)
  {
    /* 串口打开失败则直接退出整个程序 */
    ros::shutdown();
    exit(0);
  }

  /* 启动两个后台线程:
   * 1. recvThread:    不断从串口读数据并解析
   * 2. pubScanThread: 等一圈数据收齐后发布 LaserScan 消息
   */
  recv_thread_ = new boost::thread(boost::bind(&LSM10::recvThread, this));
  pubscan_thread_ = new boost::thread(boost::bind(&LSM10::pubScanThread, this));
}

/*
 * 析构函数: 设置停止标志, 中断并回收两个线程, 关闭串口
 */
LSM10::~LSM10()
{
  printf("start LSM10::~LSM10()\n");

  is_shutdown_ = true;            // 通知所有线程退出

  /* 先停发布线程 */
  pubscan_thread_->interrupt();   // 打断可能阻塞在条件变量上的线程
  pubscan_thread_->join();        // 等待线程结束
  pubscan_thread_ = NULL;
  delete pubscan_thread_;

  /* 再停接收线程 */
  recv_thread_->interrupt();
  recv_thread_->join();

  recv_thread_ = NULL;
  delete recv_thread_;

  /* 关闭串口 */
  serial_->close();
  serial_ = NULL;
  delete serial_;
  printf("end LSM10::~LSM10()\n");
}

/*
 * 从 ROS 参数服务器读取配置参数
 * nh("~") 表示私有命名空间, 即参数名前面带节点名前缀, 便于在 launch 文件里为每个节点单独配置
 */
void LSM10::initParam()
{
  std::string scan_topic = "/scan";        // 默认发布话题
  std::string frame_id = "laser_link";     // 默认坐标系名
  std::string port = "/dev/ttyUSB0";       // 默认串口
  ros::NodeHandle nh("~");
  nh.param("scan_topic", scan_topic_, scan_topic);       // 发布话题名
  nh.param("frame_id", frame_id_, frame_id);             // 点云坐标系
  nh.param("serial_port", serial_port_, port);           // 串口设备路径
  nh.param("baud_rate", baud_rate_, 460800);             // 波特率
  nh.param("rpm", rpm_, 600);                            // 标称转速(转/分)
  nh.param<double>("min_distance",min_distance,0);       // 有效距离下限(米)
  nh.param<double>("max_distance",max_distance,30);      // 有效距离上限(米)
  nh.param("truncated_mode", truncated_mode_, 0);        // 是否启用角度截断(屏蔽指定角度范围)
  nh.param<std::vector<int>>("disable_min", disable_angle_min_range, disable_angle_range_default); // 屏蔽区间起始角
  nh.param<std::vector<int>>("disable_max", disable_angle_max_range, disable_angle_range_default); // 屏蔽区间结束角

  is_shutdown_ = false;

  data_len_ = 180;            // 接收缓冲区大小(字节), 大于一帧报文, 留有余量
  points_size_ = 360 * 42 / 15;   // 一圈的总点数 = 360° / (15°/42点) = 1008 点
  scan_points_.resize(points_size_);  // 预分配存放一圈点云的数组
}

/*
 * 取出一圈完整的扫描数据
 * points:      输出参数, 拷贝一圈的点(角度/距离/强度)
 * scan_time:   输出参数, 这圈数据的起始时间戳
 * scan_duration: 输出参数, 这圈数据持续的时间(秒)
 * 返回: 0
 */
int LSM10::getScan(std::vector<ScanPoint> &points, ros::Time &scan_time, float &scan_duration)
{
  boost::unique_lock<boost::mutex> lock(mutex_);          // 加锁, 防止与接收线程并发读写
  points.assign(scan_points_bak_.begin(), scan_points_bak_.end());  // 拷贝已收齐的那一圈
  scan_time = pre_time_;                                  // 这圈数据的起始时间
  scan_duration = (time_ - pre_time_).toSec();            // 结束时间减起始时间得到圈耗时
  return 0;
}

/*
 * 返回软件版本号
 */
int LSM10::getVersion(std::string &version)
{
  version = "lsm10_v1_0";
  return 0;
}

/*
 * 返回实测转速(转/秒), 由接收线程在角度回绕时计算
 */
double LSM10::getRPM()
{
  return real_rpm_;
}

/*
 * 接收线程: 持续从串口读取数据, 解析雷达报文
 *
 * LSM10 报文格式(距离数据包, 共 90 字节):
 *   [0]    0xA5  帧头
 *   [1]    0x5A  帧头
 *   [2-3]  起始角度, 值 / 100 得到度数(例如 12345 -> 123.45°)
 *   [4-5]  转速相关字段, 2500000 / 值 得到转速
 *   [6-89] 42 个距离点, 每个点 2 字节, 值 / 1000 得到米; 0xFFFF 表示该点无效(无回波)
 *
 * 每帧 42 点覆盖 15°, 所以一圈 360° 需要 24 帧共 1008 点.
 */
void LSM10::recvThread()
{
  char * packet_bytes = new char[data_len_];   // 接收缓冲区
  int idx = 0;                                 // 当前这一圈已经累积的点数(下标)
  double degree;                               // 当前帧的起始角度
  double last_degree = 0;                      // 上一帧的起始角度, 用于判断是否回绕

  boost::posix_time::ptime t1,t2;              // 记录一圈开始/结束的时间, 用于算转速
  t1 = boost::posix_time::microsec_clock::universal_time();

  while(!is_shutdown_&&ros::ok()){

    /* 每次读 90 字节(恰好一帧报文的大小) */
    int count = serial_->read(packet_bytes, 90);

    /* 逐字节扫描, 寻找帧头 0xA5 0x5A */
    for (int i = 0; i < count; i++)
    {
        int k = packet_bytes[i];
        k < 0 ? k += 256 : k;                 // char 是有符号的, 转成 0~255 的无符号值
        int y = packet_bytes[i + 1];
        y < 0 ? y += 256 : y;

        int k_1 = packet_bytes[i + 2];
        k_1 < 0 ? k_1 += 256 : k_1;
        int y_1 = packet_bytes[i + 3];
        y_1 < 0 ? y_1 += 256 : y_1;

        if (k == 0xA5 && y == 0x5A)           // 命中"距离数据包"帧头
        {
            if(i != 0)
            {
                /* 帧头不在缓冲区起始位置, 说明前面有偏移/残留字节,
                 * 再读 i 个字节以补齐一帧(用于数据流重新对齐) */
                serial_->read(packet_bytes + 90 - i, i);
            }

            /* 解析起始角度: 2 字节, 高字节*256+低字节, 再除以 100 得到度 */
            int s = packet_bytes[i + 2];
            s < 0 ? s += 256 : s;
            int z = packet_bytes[i + 3];
            z < 0 ? z += 256 : z;

            boost::unique_lock<boost::mutex> lock(mutex_);

            //if ((s * 256 + z) / 100.f > 360)
            //	degree = 0;
            //else
                degree = (s * 256 + z) / 100.f;

            /* 解析并发布转速信息 */
            lsm10_v2::difopPtr Difop_data = lsm10_v2::difopPtr(
                        new lsm10_v2::difop());
            s = packet_bytes[i + 4];
            s < 0 ? s += 256 : s;
            z = packet_bytes[i + 5];
            z < 0 ? z += 256 : z;

            /* 2500000 是标定常数, 除以这个值得到转速 */
            Difop_data->MotorSpeed = float(2500000.0 / (s * 256 + z));

            device_pub.publish(Difop_data);

            /* 解析 42 个距离点 */
            int invalidValue = 0;             // 统计无效点(值为 0xFFFF)的个数
            for (size_t num = 2; num < 86; num+=2)
            {
                int s = packet_bytes[i + num + 4];
                s < 0 ? s += 256 : s;
                int z = packet_bytes[i + num + 5];
                z < 0 ? z += 256 : z;

                if ((s * 256 + z) != 0xFFFF)  // 有效点
                {
                    if (idx >= points_size_)
                        break;  // 丢包导致角度回绕包丢失时, 防止数组越界写
                    scan_points_[idx].range = double(s * 256 + (z)) / 1000.f;  // 距离: 毫米 -> 米
                    scan_points_[idx].intensity = 0;                            // 强度暂未使用, 置 0
                    idx++;
                }
                else
                {
                    invalidValue++;           // 该点无回波, 记为无效
                }
            }

            /* 上面统计的是"无效点"个数, 这里反算出"有效点"个数 */
            invalidValue = 42 - invalidValue;

            /* 给有效点分配角度:
             * 每个点在其 15° 扇区内均匀分布, 步长 = 15° / 有效点数 */
            for (size_t i = 0; i < invalidValue; i++)
            {
                if ((degree + (15.0 / invalidValue * i)) > 360)
                    /* 角度越过 360° 时回绕到 0° 起 */
                    scan_points_[idx-invalidValue+i].degree = degree + (15.0 / invalidValue * i) - 360;
                else
                    scan_points_[idx-invalidValue+i].degree = degree + (15.0 / invalidValue * i);
            }

            lock.unlock();

            /* 判断是否完成一整圈: 起始角度突然变小(从 ~360° 跳回 ~0°)即为回绕 */
            if (degree < last_degree)
            {
                idx = 0;   // 新一轮开始, 重置计数

                /* 计算实测转速: 一圈耗时(微秒) -> 转/秒 */
                t2 = boost::posix_time::microsec_clock::universal_time();
                boost::posix_time::millisec_posix_time_system_config::time_duration_type t_elapse;
                t_elapse = t2 - t1;
                real_rpm_ = 1000000.0 / t_elapse.ticks();   // 1e6 / 圈耗时(微秒) = 圈/秒
                t1 = t2;   // 记录新一轮的起始时间

                boost::unique_lock<boost::mutex> lock(mutex_);
                /* 把刚收齐的这一圈数据备份出来, 供发布线程使用 */
                scan_points_bak_.resize(scan_points_.size());
                scan_points_bak_.assign(scan_points_.begin(), scan_points_.end());
                /* 清空当前数组, 准备接收下一圈 */
                for(int k=0; k<scan_points_.size(); k++)
                {
                    scan_points_[k].range = 0;
                    scan_points_[k].degree = 0;
                }
                pre_time_ = time_;   // 这一圈结束时间 -> 作为上一圈的时间戳
                lock.unlock();

                pubscan_cond_.notify_one();   // 唤醒发布线程, 让它把这一圈发出去
                time_ = ros::Time::now();
            }

            last_degree = degree;   // 记录本帧角度, 供下一帧判断回绕
        }
        else if (k == 0xA5 && y == 0xFF && k_1 == 00 && y_1 == 0x5A)
        {
            /* 命中"设备信息包"帧头(0xA5 0xFF 0x00 0x5A)
             * 该包包含温度,高压,转速等信息, 此处暂未启用, 保留示例代码 */
            /*lsm10_v2::difopPtr Difop_data = lsm10_v2::difopPtr(
                        new lsm10_v2::difop());

            //温度
            int s = packet_bytes[i + 12];
            s < 0 ? s += 256 : s;
            int z = packet_bytes[i + 13];
            z < 0 ? z += 256 : z;
            Difop_data->Temperature = (float(s * 256 + z) / 4096 * 330 - 50);

            //高压
            s = packet_bytes[i + 14];
            s < 0 ? s += 256 : s;
            z = packet_bytes[i + 15];
            z < 0 ? z += 256 : z;
            Difop_data->HighPressure = (float(s * 256 + z) / 4096 * 3.3 * 101);

            //转速
            s = packet_bytes[i + 16];
            s < 0 ? s += 256 : s;
            z = packet_bytes[i + 17];
            z < 0 ? z += 256 : z;
            Difop_data->MotorSpeed = (float(1000000 / (s * 256 + z) / 24));

            device_pub.publish(Difop_data);*/
        }
    }
  }
  if (packet_bytes)
  {
    delete[] packet_bytes;
    packet_bytes = NULL;
  }
}

/*
 * 发布线程: 等待接收线程收齐一圈数据后, 组装并发布 LaserScan 消息
 */
void LSM10::pubScanThread()
{
  bool wait_for_wake = true;   // 是否需要等待唤醒
  boost::unique_lock<boost::mutex> lock(pubscan_mutex_);

  while (ros::ok() && !is_shutdown_)
  {
    while (wait_for_wake)
    {
      pubscan_cond_.wait(lock);   // 阻塞等待接收线程的 notify 唤醒
      wait_for_wake = false;
    }

    std::vector<ScanPoint> points;
    ros::Time start_time;
    float scan_time;
    this->getScan(points, start_time, scan_time);  // 取一圈数据
    int count = points.size();
    if (count <= 0)
    {
      wait_for_wake = true;   // 数据为空则继续等, 避免忙等占满 CPU
      continue;
    }

    /* 构造 LaserScan 消息 */
    sensor_msgs::LaserScan msg;
    msg.header.frame_id = frame_id_;
    msg.header.stamp = start_time;
    msg.angle_min = -M_PI;        // 起始角度 -180°
    msg.angle_max = M_PI;         // 结束角度 180°
    msg.angle_increment = (msg.angle_max - msg.angle_min) / count;  // 相邻点角间距
    msg.range_min = 0.02;         // 最近有效距离(米)
    msg.range_max = 50;           // 最远有效距离(米)
    msg.ranges.resize(count);
    msg.intensities.resize(count);
    msg.scan_time = scan_time;                              // 一圈耗时
    msg.time_increment = scan_time / (double)(count - 1);   // 相邻点时间间隔

    /* 先把所有点初始化为"无穷远"(无有效回波) */
    for(int k=0; k<count; k++)
    {
        msg.ranges[k] = std::numeric_limits<float>::infinity();
        msg.intensities[k] = 0;
    }

    /* 逐个点填入 ranges/intensities */
    for (int i = 0; i < count; i++) {
        /* 把"角度"映射为数组下标:
         * 下标 = 1008 - 角度 * 42 / 15
         * 这里做了方向反转, 使下标顺序符合 LaserScan 的 -180°~180° 约定 */
        int point_idx = 1008 - points[i].degree * 42 / 15;

        if(point_idx < 0 || point_idx > 1007)
        {
            continue;   // 越界的点丢弃
        }

      if (points[i].range == 0.0) {
        /* 距离为 0 视为无效, 用无穷大表示 */
        msg.ranges[point_idx] = std::numeric_limits<float>::infinity();
        msg.intensities[point_idx] = 0;
      }
      else if(points[i].range<min_distance||points[i].range>max_distance){
        /* 超出有效距离范围的点也置为无穷远 */
        msg.ranges[point_idx] = std::numeric_limits<float>::infinity();
        msg.intensities[point_idx] = 0;
      }
      else {
        /* 有效点: 填入实际距离与强度 */
        double dist = points[i].range;
        msg.ranges[point_idx] = (float) dist;
        msg.intensities[point_idx] = points[i].intensity;
      }

      /* 若启用截断模式, 把指定角度区间内的点屏蔽掉(置为无穷远) */
      if(truncated_mode_==1)
            {
                for (int j = 0; j < disable_angle_max_range.size(); ++j) {
          if ((point_idx >= (disable_angle_min_range[j] * count / 360) ) &&
              (point_idx <= (disable_angle_max_range[j] * count / 360 ))) {
            msg.ranges[point_idx] = std::numeric_limits<float>::infinity();
            msg.intensities[point_idx] = 0;
          }
        }
            }
    }
    pub_.publish(msg);   // 发布这一圈点云
    wait_for_wake = true;  // 重新进入等待状态
  }
}

}

/*
 * 信号处理函数: 收到 Ctrl+C(SIGINT)或 SIGTERM 时优雅退出
 */
void handleSig(int signo)
{
  printf("handleSig\n");
  ros::shutdown();
  exit(0);
}

/*
 * 主函数: 注册信号处理 -> 初始化 ROS -> 创建雷达驱动 -> 进入 ROS 事件循环
 */
int main(int argv, char **argc)
{
  signal(SIGINT, handleSig);   // 捕获 Ctrl+C
  signal(SIGTERM, handleSig);  // 捕获终止信号
  ros::init(argv, argc, "lsm10");   // 初始化 ROS, 节点名 "lsm10"

  ls::LSM10* lsm10 = ls::LSM10::instance();  // 创建雷达驱动(单例)

  ros::spin();   // 进入 ROS 循环, 处理回调(本例主要是让两个线程持续运行)
  return 0;
}
