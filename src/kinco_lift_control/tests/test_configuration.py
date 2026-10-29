"""无第三方依赖的本包扁平标量配置核对,不是通用YAML解析器."""
import ast
import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kinco_lift.controller import LiftConfig


def flat_config(path):
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        key, separator, value = line.partition(':')
        if not separator or key in result:
            raise ValueError('Invalid/duplicate flat parameter: ' + key)
        value = value.strip()
        if value in ('null', '~'):
            result[key] = None
        elif value in ('true', 'false'):
            result[key] = value == 'true'
        else:
            try:
                result[key] = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                result[key] = value
    return result


class ConfigurationTests(unittest.TestCase):
    def test_lift_text_files_use_lf(self):
        extensions = {'.py', '.launch', '.yaml', '.yml', '.srv', '.xml', '.md', '.txt'}
        special = {'.gitattributes', '.gitignore', '.editorconfig'}
        for path in ROOT.rglob('*'):
            if path.is_file() and (path.suffix in extensions or path.name in special):
                with self.subTest(path=str(path.relative_to(ROOT))):
                    self.assertNotIn(b'\r', path.read_bytes(), 'Use LF, not CRLF/CR.')
        self.assertIn('end_of_line = lf', (ROOT / '.editorconfig').read_text())

    def test_modified_chassis_files_use_lf(self):
        chassis = ROOT.parent / 'turn_on_wheeltec_robot'
        if not chassis.exists():
            self.skipTest('Sibling chassis package not available.')
        for name in ('CMakeLists.txt', 'src/wheeltec_robot.cpp', 'include/wheeltec_robot.h',
                     'include/lift_motion_gate.h', 'test/lift_motion_gate_test.cpp',
                     'launch/include/base_serial.launch', '.gitattributes', '.editorconfig'):
            with self.subTest(path=name):
                self.assertNotIn(b'\r', (chassis / name).read_bytes(), 'Use LF, not CRLF/CR.')

    def test_physical_stays_locked_and_uses_confirmed_scaling(self):
        cfg = LiftConfig(flat_config(ROOT / 'config/lift.yaml'))
        self.assertFalse(cfg.motion_enabled)
        self.assertFalse(cfg.commissioned)
        self.assertFalse(cfg.limits_verified)
        self.assertFalse(cfg.keyboard_enabled)
        self.assertEqual(cfg.counts, 65536)
        self.assertEqual(cfg.mm_rev, 2.25)
        # 2026-10-28 用户实测H0=2.05m(下限位静止);此前必须为None,未知不能填占位值.
        self.assertEqual(cfg.initial_top_height, 2.05)
        self.assertEqual(cfg.moving_max_rpm, 100)

    def test_simulated_overlay_and_launch_are_consistent(self):
        params = flat_config(ROOT / 'config/lift.yaml')
        params.update(flat_config(ROOT / 'config/simulation.yaml'))
        cfg = LiftConfig(params)
        self.assertTrue(cfg.keyboard_enabled)
        self.assertEqual(cfg.zones.down_switch, 3060000)
        self.assertEqual(cfg.zones.up_switch, 119390000)
        launch = ET.parse(ROOT / 'launch/lift.launch').getroot()
        self.assertEqual(launch.find('arg[@name="simulate"]').attrib['default'], 'false')
        self.assertEqual(ET.parse(ROOT / 'package.xml').findtext('name'), 'kinco_lift_control')
        cmake = (ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
        self.assertIn('scripts/lift_keyboard.py', cmake)
        self.assertIn('MoveTopHeight.srv', cmake)


if __name__ == '__main__':
    unittest.main()
