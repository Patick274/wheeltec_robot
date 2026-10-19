from setuptools import setup
from catkin_pkg.python_setup import generate_distutils_setup

# 将src/kinco_lift安装为Python模块；ROS自动生成的服务在kinco_lift_control.srv中。
setup(**generate_distutils_setup(
    packages=['kinco_lift'], package_dir={'': 'src'}))
