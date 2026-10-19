/*******************************************************
@company: Copyright (C) 2021, Leishen Intelligent System
@product: LSM10
@filename: lsiosr.cpp
@brief:    LSM10 激光雷达的串口(RS232)底层驱动, 负责串口的打开/配置/读写
@version:       date:       author:     comments:
@v1.0           21-2-4      yao          new
*******************************************************/
#include "lsm10_v2/lsiosr.h"

namespace ls {

/*
 * 单例模式: 获取串口对象的全局唯一实例
 * name:   串口设备路径, 例如 /dev/ttyUSB0
 * speed:  波特率, 例如 460800
 * fd:     已经打开的文件描述符(默认 0 表示尚未打开)
 * 说明:   用 static 局部变量保证对象在整个进程中只被构造一次, 且线程安全
 */
LSIOSR * LSIOSR::instance(std::string name, int speed, int fd)
{
  static LSIOSR obj(name, speed, fd);
  return &obj;
}

/*
 * 构造函数: 把串口路径和波特率保存到成员变量里
 * 注意: 这里只是"记录"参数, 真正打开串口的动作在 init() 中完成
 */
LSIOSR::LSIOSR(std::string port, int baud_rate, int fd):port_(port), baud_rate_(baud_rate), fd_(fd)
{
  printf("port = %s, baud_rate = %d\n", port.c_str(), baud_rate);
}

LSIOSR::~LSIOSR()
{
  close();
}

/*
 * 串口配置的核心函数: 设置数据位 / 校验位 / 停止位 / 波特率 / 读超时
 * nBits:  数据位位数(7 或 8)
 * nEvent: 校验位('O' 奇校验 / 'E' 偶校验 / 'N' 无校验)
 * nStop:  停止位位数(1 或 2)
 * 返回值: 0 成功, -1 失败
 *
 * Linux 下串口通过 struct termios 结构体描述, 常用字段含义:
 *   c_cflag: 控制标志(波特率、数据位、校验位、停止位等)
 *   c_iflag: 输入标志(是否校验输入等)
 *   c_cc[]:  特殊控制字符数组, 其中 VMIN/VTIME 用于控制 read 的超时行为
 */
int LSIOSR::setOpt(int nBits, uint8_t nEvent, int nStop)
{
  struct termios newtio, oldtio;
  /* 先读出当前串口的配置保存到 oldtio; 如果串口号错误, 这一步会失败并报错 */
  if (tcgetattr(fd_, &oldtio) != 0)
  {
    perror("SetupSerial 1");
    return -1;
  }
  /* 把 newtio 全部清零, 防止残留的随机值影响配置 */
  bzero(&newtio, sizeof(newtio));

  /* 步骤一: 设置基本控制标志 */
  newtio.c_cflag |= CLOCAL;   // 忽略 modem 控制线, 避免 open/read 因载波检测而阻塞
  newtio.c_cflag |= CREAD;    // 使能串口接收数据

  /* 设置数据位位数(每个字符由几位二进制表示) */
  switch (nBits)
  {
  case 7:
    newtio.c_cflag |= CS7;    // 7 位数据位
    break;
  case 8:
    newtio.c_cflag |= CS8;    // 8 位数据位(最常用)
    break;
  }

  /* 设置奇偶校验位(用于检测传输错误) */
  switch (nEvent)
  {
  case 'O': // 奇校验
    newtio.c_iflag |= (INPCK | ISTRIP);  // INPCK: 使能奇偶校验; ISTRIP: 剥掉第 8 位
    newtio.c_cflag |= PARENB;            // 使能校验位
    newtio.c_cflag |= PARODD;            // 设置为奇校验(不设 PARODD 则为偶校验)
    break;
  case 'E': // 偶校验
    newtio.c_iflag |= (INPCK | ISTRIP);
    newtio.c_cflag |= PARENB;
    newtio.c_cflag &= ~PARODD;           // 清除 PARODD 位即为偶校验
    break;
  case 'N':  // 无校验位(雷达一般用这个)
    newtio.c_cflag &= ~PARENB;           // 关闭校验位
    break;
  }

  /* 设置波特率(每秒传输的比特数), 输入输出波特率需分别设置 */
  switch (baud_rate_)
  {
  case 2400:
    cfsetispeed(&newtio, B2400);
    cfsetospeed(&newtio, B2400);
    break;
  case 4800:
    cfsetispeed(&newtio, B4800);
    cfsetospeed(&newtio, B4800);
    break;
  case 9600:
    cfsetispeed(&newtio, B9600);
    cfsetospeed(&newtio, B9600);
    break;
  case 115200:
    cfsetispeed(&newtio, B115200);
    cfsetospeed(&newtio, B115200);
    break;
  case 230400:
    cfsetispeed(&newtio, B230400);
    cfsetospeed(&newtio, B230400);
    break;
  case 460800:
    cfsetispeed(&newtio, B460800);
    cfsetospeed(&newtio, B460800);
    break;
  default:                                // 无法识别的波特率, 回退到 9600
    cfsetispeed(&newtio, B9600);
    cfsetospeed(&newtio, B9600);
    break;
  }

  /*
   * 设置停止位(每帧数据末尾的结束位)
   * CSTOPB 置位 => 2 个停止位; 清零 => 1 个停止位。绝大多数设备用 1 个停止位。
   */
  if (nStop == 1)
    newtio.c_cflag &= ~CSTOPB;
  else if (nStop == 2)
    newtio.c_cflag |= CSTOPB;

  /* 设置读超时行为:
   * VMIN = 0 且 VTIME = 0 => 非阻塞式读, 有数据就返回, 没数据立即返回 0 */
  newtio.c_cc[VTIME] = 0;
  newtio.c_cc[VMIN] = 0;

  /* 清空串口输入缓冲, 丢弃里面残留的旧数据 */
  tcflush(fd_, TCIFLUSH);

  /* 立即(TCSANOW)把新配置写入串口 */
  if ((tcsetattr(fd_, TCSANOW, &newtio)) != 0)
  {
    perror("serial set error");
    return -1;
  }

  return 0;
}

/* 清空串口输入缓冲区 */
void LSIOSR::flushinput() {
  tcflush(fd_, TCIFLUSH);
}

/*
 * 从串口读取数据
 * buffer: 存放读到的数据的缓冲区
 * length: 期望读取的字节数
 * timeout: 超时时间(毫秒), >0 时启用带超时的读取; <=0 时直接读一次
 * 返回值: 实际读到的字节数; 出错或超时返回 -1(超时返回 0)
 */
int LSIOSR::read(char *buffer, int length, int timeout)
{
  memset(buffer, 0, length);

  int totalBytesRead = 0;   // 累计读到的字节数
  int rc;                   // 单次 read/select 的返回值
  int unlink = 0;           // 循环计数, 防止一直读不到数据时死循环
  char* pb = buffer;        // 当前写入位置的指针

  if (timeout > 0)
  {
    /* 先等待串口变为可读, 最多等 timeout 毫秒 */
    rc = waitReadable(timeout);
    if (rc <= 0)
    {
      return (rc == 0) ? 0 : -1;   // rc==0 表示超时, rc<0 表示出错
    }

    int	retry = 3;                 // 单次读失败后的重试次数
    while (length > 0)             // 循环直到读满 length 字节
    {
      rc = ::read(fd_, pb, (size_t)length);

      if (rc > 0)
      {
        length -= rc;              // 剩余还需读的字节数减少
        pb += rc;                  // 写指针向后移动
        totalBytesRead += rc;

        if (length == 0)
        {
          break;                   // 已经读满, 退出
        }
      }
      else if (rc < 0)
      {
        if (errno == EAGAIN || errno == EINTR)
        {
          // 非阻塞模式下暂时没数据, 或读被信号打断, 属于正常情况, 重试
          retry--;
          if (retry <= 0)
          {
            break;
          }
        }
        else
        {
          // 真正的读错误
          printf("read error: %s\n", strerror(errno));
          retry--;
          if (retry <= 0)
          {
            break;
          }
        }
      }

      unlink++;
      rc = waitReadable(20);       // 再次等待最多 20ms 的可读
      if(unlink > 10)
        return -1;                 // 等待次数过多, 判定为读失败, 直接返回

      if (rc <= 0)
      {
        break;
      }
    }
  }
  else
  {
    /* 无超时模式: 直接读一次, 不等待 */
    rc = ::read(fd_, pb, (size_t)length);

    if (rc > 0)
    {
      totalBytesRead += rc;
    }
    else if ((rc < 0) && (errno != EINTR) && (errno != EAGAIN))
    {
      printf("read error\n");
      return -1;
    }
  }

  return totalBytesRead;
}

/*
 * 等待串口变为"可读", 内部使用 select() 系统调用实现
 * millis: 最大等待毫秒数
 * 返回值: 1 表示可读, 0 表示超时, -1 表示出错
 */
int LSIOSR::waitReadable(int millis)
{
  if (fd_ < 0)
  {
    return -1;
  }
  int serial = fd_;

  fd_set fdset;         // select 使用的文件描述符集合
  struct timeval tv;    // 超时时间
  int rc = 0;

  while (millis > 0)
  {
    /* select 的 timeval 最多只能表示约 5 秒, 所以超过 5 秒要分段等待 */
    if (millis < 5000)
    {
      tv.tv_usec = millis % 1000 * 1000;   // 不足 1 秒的部分(微秒)
      tv.tv_sec  = millis / 1000;          // 秒部分

      millis = 0;                          // 本次为最后一段等待
    }
    else
    {
      tv.tv_usec = 0;
      tv.tv_sec  = 5;                      // 先等 5 秒

      millis -= 5000;                      // 剩余时间扣掉 5 秒
    }

    FD_ZERO(&fdset);                       // 清空描述符集合
    FD_SET(serial, &fdset);                // 把串口 fd 加入"关注可读"的集合

    /* 只监测可读事件, 阻塞直到可读/超时/出错 */
    rc = select(serial + 1, &fdset, NULL, NULL, &tv);
    if (rc > 0)
    {
      /* 有描述符就绪, 再确认是不是我们的串口可读 */
      rc = (FD_ISSET(serial, &fdset)) ? 1 : -1;
      break;
    }
    else if (rc < 0)
    {
      rc = -1;   // select 出错
      break;
    }
  }

  return rc;
}


/*
 * 等待串口变为"可写", 逻辑与 waitReadable 相同, 只是监测写事件
 */
int LSIOSR::waitWritable(int millis)
{
  if (fd_ < 0)
  {
    return -1;
  }
  int serial = fd_;

  fd_set fdset;
  struct timeval tv;
  int rc = 0;

  while (millis > 0)
  {
    if (millis < 5000)
    {
      tv.tv_usec = millis % 1000 * 1000;
      tv.tv_sec  = millis / 1000;

      millis = 0;
    }
    else
    {
      tv.tv_usec = 0;
      tv.tv_sec  = 5;

      millis -= 5000;
    }

    FD_ZERO(&fdset);
    FD_SET(serial, &fdset);

    /* 这里把 fdset 放在第二参数(写集合)位置, 即监测可写事件 */
    rc = select(serial + 1, NULL, &fdset, NULL, &tv);
    if (rc > 0)
    {
      rc = (FD_ISSET(serial, &fdset)) ? 1 : -1;
      break;
    }
    else if (rc < 0)
    {
      rc = -1;
      break;
    }
  }

  return rc;
}

/*
 * 向串口发送数据(本驱动中雷达是只读设备, 该函数一般用不到)
 * 逻辑与 read 对称: 支持带超时的循环写, 或直接写一次
 */
int LSIOSR::send(const char* buffer, int length, int timeout)
{
  if (fd_ < 0)
  {
    return -1;
  }

  if ((buffer == 0) || (length <= 0))
  {
    return -1;
  }

  int	totalBytesWrite = 0;   // 累计写入字节数
  int rc;
  char* pb = (char*)buffer;


  if (timeout > 0)
  {
    rc = waitWritable(timeout);
    if (rc <= 0)
    {
      return (rc == 0) ? 0 : -1;
    }

    int	retry = 3;
    while (length > 0)
    {
      rc = write(fd_, pb, (size_t)length);
      if (rc > 0)
      {
        length -= rc;
        pb += rc;
        totalBytesWrite += rc;

        if (length == 0)
        {
          break;
        }
      }
      else
      {
        retry--;
        if (retry <= 0)
        {
          break;
        }
      }

      rc = waitWritable(50);
      if (rc <= 0)
      {
        break;
      }
    }
  }
  else
  {
    rc = write(fd_, pb, (size_t)length);
    if (rc > 0)
    {
      totalBytesWrite += rc;
    }
    else if ((rc < 0) && (errno != EINTR) && (errno != EAGAIN))
    {
      return -1;
    }
  }

  return totalBytesWrite;
}

/*
 * 串口初始化: 打开设备并配置串口参数
 * 返回值: 0 成功, -1 失败
 */
int LSIOSR::init()
{
	int error_code = 0;

	/* 以读写方式打开串口设备
	 * O_RDWR   : 可读可写
	 * O_NOCTTY : 不让该设备成为进程的控制终端
	 * O_NDELAY : 非阻塞方式打开(等价 O_NONBLOCK)
	 */
	fd_ = open(port_.c_str(), O_RDWR|O_NOCTTY|O_NDELAY);
	if (0 < fd_)
	{
		error_code = 0;
		/* 打开成功后按 8 数据位 / 无校验 / 1 停止位 配置串口 */
		setOpt(DATA_BIT_8, PARITY_NONE, STOP_BIT_1);
		printf("open_port %s  OK !\n", port_.c_str());
	}
	else
	{
		error_code = -1;
		printf("open_port %s ERROR !\n", port_.c_str());
	}
	printf("LSM10::Init\n");

	return error_code;
}

/* 关闭串口文件描述符 */
int LSIOSR::close()
{
  ::close(fd_);
}

/* 获取当前串口路径 */
std::string LSIOSR::getPort()
{
  return port_;
}

/* 设置串口路径 */
int LSIOSR::setPortName(std::string name)
{
  port_ = name;
  return 0;
}

}
