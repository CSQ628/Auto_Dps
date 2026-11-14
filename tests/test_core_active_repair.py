import copy
import unittest

from dps_assistant.engine import DEFAULT, Engine
from dps_assistant.policy import skill_repair_pending


class CoreActiveRepairTests(unittest.TestCase):
    def prepare(self):
        config = copy.deepcopy(DEFAULT)
        config['modules']['passive'] = False
        repair = {'controls': {'active': True, 'passive': False}, 'excess': 3,
                  'reason': 'refund_branch', 'refund': {'kind': 'active', 'skill': 'core', 'level': 4}}
        snapshot = {'squad': [1], 'characters': [{'id': 1, 'points': 0, 'skillPlanning': {'repair': repair}}]}
        return config, repair, snapshot

    def test_active_only_correction_and_fill_hold_new_challenges(self):
        config, repair, snapshot = self.prepare()
        self.assertTrue(skill_repair_pending(snapshot, config))
        repair.update(reason='fill_target', excess=0, refund=None)
        snapshot['characters'][0]['points'] = 1
        self.assertTrue(skill_repair_pending(snapshot, config))
        config['strategy']['allow_active_refund'] = False
        self.assertFalse(skill_repair_pending(snapshot, config))

    def test_refusal_and_disabled_active_module_continue_other_work(self):
        config, repair, snapshot = self.prepare()
        config['modules']['active'] = False
        self.assertFalse(skill_repair_pending(snapshot, config))
        config['modules']['active'] = True
        repair.update(reason='native_refund_blocked', refund=None)
        self.assertFalse(skill_repair_pending(snapshot, config))

    def test_active_only_warning_is_deduplicated_and_cleared_by_its_own_switch(self):
        config, repair, snapshot = self.prepare()
        repair.update(reason='native_refund_blocked', refund=None)
        engine = Engine.__new__(Engine)
        engine.config = config
        events = []
        engine.record = lambda *args, **kwargs: events.append(kwargs)
        state = {}
        for _ in range(2):
            engine.observe_skill_repair_blocks('1', {'identity': 'test'}, state, snapshot)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['action']['kind'], 'skill_refund')
        config['strategy']['allow_active_refund'] = False
        engine.observe_skill_repair_blocks('1', {'identity': 'test'}, state, snapshot)
        self.assertNotIn('skill_repair_blocks', state)


if __name__ == '__main__':
    unittest.main()
