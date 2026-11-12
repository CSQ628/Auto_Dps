import json
import unittest
from dps_assistant.diagnostics import diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_export_uses_allowlist_and_excludes_account_save_and_private_values(self):
        raw = {'now': 10, 'csrf': 'secret-token', 'config': {'running': True, 'strategy': {'battle_recovery_wait_seconds': 30}},
               'data_directory': 'C:/private/path', 'instances': [{'box': 'private-box-name', 'account': 'private-account',
                'error': 'C:/private/path secret-token', 'snapshot': {'account': 'private-account', 'nickname': 'private-name',
                'saveDirectory': 'private-save', 'squad': [400001], 'characters': [{'id': 400001, 'level': 2}],
                'battleReadiness': {'known': True, 'missing': [400001]}}}], 'events': [{'token': 'secret-token'}]}
        value = diagnostics(raw);text = json.dumps(value)
        for secret in ('private-', 'secret-token', 'C:/private'):
            self.assertNotIn(secret, text)
        self.assertTrue(value['instances'][0]['observation_error'])
        self.assertEqual(value['instances'][0]['battle_readiness']['missing'], [400001])
