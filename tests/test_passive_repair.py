import copy
import unittest
from dps_assistant.engine import DEFAULT
from dps_assistant.parameters import normalize_config, apply_patch
from dps_assistant.policy import module_for
from dps_assistant.diagnostics import KINDS, safe_reason


class PassiveRepairTests(unittest.TestCase):
    def test_default_and_saved_refund_choice(self):
        self.assertTrue(normalize_config({})['strategy']['allow_passive_refund'])
        config=apply_patch(copy.deepcopy(DEFAULT), {'strategy': {'allow_passive_refund': False}})
        self.assertFalse(normalize_config(config)['strategy']['allow_passive_refund'])
        self.assertEqual(config['strategy']['skill_point_reserve'],0)

    def test_refund_uses_passive_module_and_diagnostics(self):
        self.assertEqual(module_for('passive_refund'),'passive')
        self.assertIn('passive_refund',KINDS)
        self.assertEqual(safe_reason('native_refund_blocked'),'native_refund_blocked')
