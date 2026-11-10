"""robot 族层：机型无关的注册表/帧类型/roslibpy 链路。

**族父级禁 import 机型子级**——机型包（wheeltec_03/…）由装配根
（app/composition.py 的 model_pkgs）登记注入，族层只见契约不见机型
（仿 jdyw-hx core-development-guide §六）。
"""

from ._catalog import RobotCatalog, RobotEntry
from ._config import DEFAULT_ROBOTS, RobotSpec, load_robots, save_robots
from ._frames import (CameraFrame, RobotDescriptionFrame, TelemetryFrame,
                      TfFrame)
from ._worker import RobotLink, to_rosbridge_type

__all__ = ["RobotCatalog", "RobotEntry", "RobotSpec", "DEFAULT_ROBOTS",
           "load_robots", "save_robots",
           "CameraFrame", "RobotDescriptionFrame", "TelemetryFrame", "TfFrame",
           "RobotLink", "to_rosbridge_type"]
