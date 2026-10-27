/*******************************************************
@company: Copyright (C) 2021, Leishen Intelligent System
@product: LSM10
@filename: lsiosr.h
@brief:    LSM10 激光雷达串口驱动类的声明
@version:       date:       author:     comments:
@v1.0           21-2-4      yao          new
*******************************************************/
#ifndef LSIOSR_H
#define LSIOSR_H

/* 以下头文件为 Linux 串口编程所需:
 * termios.h: 串口配置结构体与相关函数(tcgetattr/tcsetattr 等)
 * fcntl.h:   open 所需的文件控制标志
 * unistd.h:  read/write/close 等系统调用
 */
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <termios.h>
#include <errno.h>
#include <unistd.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>
#include <fstream>
#include <iostream>

// 波特率宏定义(每秒比特数)
#define     BAUD_2400       2400
#define     BAUD_4800       4800
#define     BAUD_9600       9600
#define     BAUD_57600     	57600
#define     BAUD_115200     115200
#define	    BAUD_230400	    230400
#define     BAUD_460800     460800

// 奇偶校验位
#define     PARITY_ODD    	'O' // 奇数校验
#define     PARITY_EVEN   	'E' // 偶数校验
#define     PARITY_NONE   	'N' // 无奇偶校验位

// 停止位
#define     STOP_BIT_1     	1
#define     STOP_BIT_2     	2

// 数据位
#define     DATA_BIT_7     	7
#define     DATA_BIT_8     	8

namespace ls
{
/* 串口驱动类: 封装了 Linux 串口的打开,配置,读,写操作 */
class LSIOSR{
public:
  /* 单例工厂方法: 返回全局唯一的串口对象 */
  static LSIOSR* instance(std::string name, int speed, int fd = 0);

  ~LSIOSR();

  /* 从串口中读取数据 */
  int read(char *buffer, int length, int timeout = 30);

  /* 向串口传数据 */
  int send(const char* buffer, int length, int timeout = 30);

  /* 清空串口输入缓冲区 */
  void flushinput();

  /* 串口初始化: 打开设备并配置参数 */
  int init();

  /* 关闭串口 */
  int close();

  /* 获取串口号(设备路径) */
  std::string getPort();

  /* 设置串口号(设备路径) */
  int setPortName(std::string name);

private:
  /* 构造函数私有, 只能通过 instance() 创建, 实现单例 */
  LSIOSR(std::string name, int speed, int fd);

  /* 等待串口可写 / 可读(内部用 select 实现) */
  int waitWritable(int millis);
  int waitReadable(int millis);

  /* 串口配置函数: 设置数据位/校验位/停止位/波特率 */
  int setOpt(int nBits, uint8_t nEvent, int nStop);

  std::string port_;   // 串口设备路径, 例如 /dev/ttyUSB0
  int baud_rate_;      // 波特率, 例如 460800

  int fd_;             // 串口打开后的文件描述符(整数句柄)
};
}
#endif
