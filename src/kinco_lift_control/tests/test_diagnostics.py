"""诊断逻辑测试：不接USB/CAN，不修改网络配置。"""
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from kinco_lift.diagnostics import collect_report, inspect_link


def can_link():
    return dict(ifname='can0', flags=['UP'], operstate='UNKNOWN',
                linkinfo=dict(info_kind='can', info_data=dict(
                    state='ERROR-ACTIVE', bittiming=dict(bitrate=500000))))


class DiagnosticTests(unittest.TestCase):
    def test_unknown_operstate_is_normal_for_can(self):
        self.assertTrue(inspect_link(can_link())['ready'])

    def test_missing_interface(self):
        self.assertFalse(inspect_link(None)['ready'])

    def test_ethernet_rejected(self):
        self.assertFalse(inspect_link(dict(ifname='eth0', flags=['UP']))['ready'])

    def test_vcan_rejected_for_physical_use(self):
        link = can_link()
        link['linkinfo']['info_kind'] = 'vcan'
        self.assertFalse(inspect_link(link)['ready'])

    def test_down_interface(self):
        link = can_link()
        link['flags'] = []
        self.assertFalse(inspect_link(link)['ready'])

    def test_wrong_bitrate(self):
        link = can_link()
        link['linkinfo']['info_data']['bittiming']['bitrate'] = 250000
        self.assertFalse(inspect_link(link)['ready'])

    def test_bus_off_and_error_passive(self):
        for state in ('BUS-OFF', 'ERROR-PASSIVE', 'STOPPED'):
            link = can_link()
            link['linkinfo']['info_data']['state'] = state
            self.assertFalse(inspect_link(link)['ready'])

    def test_unknown_controller_state(self):
        link = can_link()
        del link['linkinfo']['info_data']['state']
        self.assertFalse(inspect_link(link)['ready'])

    def test_non_linux_never_runs_commands(self):
        with patch('kinco_lift.diagnostics.platform.system', return_value='Windows'), patch(
                'kinco_lift.diagnostics.run_command') as run:
            self.assertFalse(collect_report()['ready'])
            run.assert_not_called()

    def test_linux_report_readonly(self):
        import json
        def command(args):
            return dict(returncode=0, stdout=json.dumps([can_link()]) if args[0] == 'ip' else '',
                        stderr='')
        with patch('kinco_lift.diagnostics.platform.system', return_value='Linux'), patch(
                'kinco_lift.diagnostics.usb_inventory', return_value=[]), patch(
                'kinco_lift.diagnostics.run_command', side_effect=command) as run:
            report = collect_report()
            self.assertTrue(report['ready'])
            self.assertEqual(report['can_frames_sent'], 0)
            self.assertTrue(all(call.args[0][0] in ('ip', 'modinfo') for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
