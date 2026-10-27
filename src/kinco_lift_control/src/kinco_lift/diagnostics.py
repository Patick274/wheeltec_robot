"""只读SocketCAN诊断:不加载模块,不设置网卡,不发送CAN帧."""
import json
import pathlib
import platform
import subprocess


def run_command(args):
    """参数列表直传系统命令;没有shell拼接,不需要sudo."""
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=5)
        return dict(returncode=result.returncode, stdout=result.stdout.strip(),
                    stderr=result.stderr.strip())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(returncode=-1, stdout='', stderr=str(exc))


def inspect_link(link, expected_bitrate=500000):
    """只判断SocketCAN接口状态,不据此宣称USB型号或FD125通信已验证."""
    if link is None:
        return dict(ready=False, reason='未找到指定接口.先检查USB识别和Linux内核驱动.')
    info = link.get('linkinfo', {})
    kind = info.get('info_kind')
    if kind != 'can':
        reason = ('这是vcan虚拟接口,不能控制物理FD125.' if kind == 'vcan'
                  else '此接口不是经典SocketCAN设备,不能按网口/串口直接调用.')
        return dict(ready=False, reason=reason)
    data = info.get('info_data', {})
    if 'UP' not in link.get('flags', []):
        return dict(ready=False, reason='CAN接口存在但未启用,确认接口后配置波特率并up.')
    state = str(data.get('state', '')).upper()
    if state in ('BUS-OFF', 'STOPPED', 'ERROR-PASSIVE', 'SLEEPING'):
        return dict(ready=False, reason='CAN状态异常:' + state + ';检查线路,不自动重启.')
    bitrate = data.get('bittiming', {}).get('bitrate')
    if bitrate != expected_bitrate:
        return dict(ready=False, reason='波特率不一致或无法读取:{},期望{}.'.format(bitrate, expected_bitrate))
    if not state:
        return dict(ready=False, reason='无法读取CAN控制器状态,请查看ip -details link show.')
    return dict(ready=True, reason='接口已启用且波特率一致;下一步做FD125只读SDO探测,尚不代表驱动器已通信.')


def usb_inventory(root='/sys/bus/usb/devices'):
    """读取USB VID/PID和产品名;不收集设备序列号."""
    devices = []
    base = pathlib.Path(root)
    if not base.is_dir():
        return devices
    for path in sorted(base.iterdir()):
        def read(name):
            try:
                return (path / name).read_text().strip()
            except (OSError, UnicodeError):
                return ''
        vid, pid = read('idVendor'), read('idProduct')
        if not vid or not pid:
            continue
        drivers = set()
        for interface in base.glob(path.name + ':*'):
            driver = interface / 'driver'
            try:
                if driver.exists():
                    drivers.add(driver.resolve().name)
            except OSError:
                pass
        devices.append(dict(vid=vid, pid=pid, manufacturer=read('manufacturer'),
                            product=read('product'), drivers=sorted(drivers)))
    return devices


def collect_report(interface='can0'):
    report = dict(system=platform.system(), machine=platform.machine(),
                  kernel=platform.release(), requested_interface=interface,
                  read_only=True, can_frames_sent=0)
    if platform.system() != 'Linux':
        report.update(ready=False, reason='此工具应在Jetson/Linux运行;Windows不能验证SocketCAN.')
        return report
    report['usb_devices'] = usb_inventory()
    ip = run_command(['ip', '-json', '-details', '-statistics', 'link', 'show'])
    report['ip_error'] = ip['stderr']
    try:
        links = json.loads(ip['stdout']) if ip['returncode'] == 0 else []
        if not isinstance(links, list):
            links = []
    except (ValueError, TypeError):
        links = []
        report['ip_error'] = 'ip命令没有返回可解析的JSON;安装/核对iproute2.'
    report['can_interfaces'] = [link for link in links
                                if link.get('linkinfo', {}).get('info_kind') in ('can', 'vcan')]
    chosen = next((link for link in links if link.get('ifname') == interface), None)
    report['selected_link'] = chosen
    report.update(inspect_link(chosen))
    if report['ip_error']:
        report['ready'] = False
    report['kernel_modules'] = {}
    for module in ('kvaser_usb', 'gs_usb', 'can_raw'):
        result = run_command(['modinfo', module])
        report['kernel_modules'][module] = dict(
            loaded=(pathlib.Path('/sys/module') / module).exists(),
            modinfo_available=result['returncode'] == 0,
            error=result['stderr'] if result['returncode'] != 0 else '')
    return report


def print_report(report):
    print('系统:{} / {} / {}'.format(report['system'], report['machine'], report['kernel']))
    print('检查方式:只读;未加载模块,未修改网卡,未发送CAN帧.')
    print('接口:' + report['requested_interface'])
    for device in report.get('usb_devices', []):
        print('USB {}:{} {} {};驱动={}'.format(
            device['vid'], device['pid'], device['manufacturer'], device['product'],
            ','.join(device['drivers']) or '未绑定/未知'))
    print('CAN接口列表:' + (', '.join(x['ifname'] for x in report.get('can_interfaces', [])) or '未发现'))
    for name, module in report.get('kernel_modules', {}).items():
        print('模块 {}:loaded={},modinfo={}'.format(name, module['loaded'], module['modinfo_available']))
    if report.get('ip_error'):
        print('ip命令提示:' + report['ip_error'])
    print('结论:' + report['reason'])
    print('注意:kvaser_usb是待验证的内核驱动,不是对第三方兼容固件的保证.')
