from pathlib import Path
import tempfile
import unittest
from dps_assistant.updates import VersionChecker, release_state, existing_instance_notice


class UpdateTests(unittest.TestCase):
    def test_versions_are_compared_numerically_and_only_stable_releases_are_used(self):
        payload={'tag_name':'v1.0.10','draft':False,'prerelease':False,'html_url':'javascript:unsafe'}
        result=release_state(payload,'1.0.3')
        self.assertEqual(result['status'],'available')
        self.assertEqual(result['url'],'https://github.com/weixiao030/Auto_Dps/releases/tag/v1.0.10')
        self.assertEqual(release_state(payload,'1.0.11')['status'],'current')
        for value in ('v1.0.3-beta','untrusted text',None):
            with self.assertRaises(ValueError):release_state({**payload,'tag_name':value})
        with self.assertRaises(ValueError):release_state({**payload,'prerelease':True})

    def test_a_new_package_warns_when_the_background_instance_is_older(self):
        self.assertIn('后台仍在运行 v1.0.2',existing_instance_notice('1.0.3','1.0.2'))
        self.assertIsNone(existing_instance_notice('1.0.3','1.0.3'))
        self.assertIsNone(existing_instance_notice('1.0.3','1.0.10'))

    def test_network_failures_do_not_block_automation_or_erase_a_new_version_notice(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'updates.json'
            checker=VersionChecker('1.0.3',path,lambda:{'tag_name':'v1.0.4','draft':False,'prerelease':False})
            checker.refresh();self.assertEqual(checker.state()['status'],'available')
            def offline():raise OSError('unreachable')
            checker.fetch=offline;checker.refresh();self.assertEqual(checker.state()['latest'],'1.0.4')
            restored=VersionChecker('1.0.3',path,offline);self.assertEqual(restored.state()['status'],'available')
            restored.refresh();self.assertEqual(restored.state()['status'],'available')
