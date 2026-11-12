import copy
import unittest

from dps_assistant.engine import DEFAULT
from dps_assistant.policy import choose


class TowerIsolationTests(unittest.TestCase):
    def test_free_repeat_guard_remains_available_offline_with_progress_disabled(self):
        config = copy.deepcopy(DEFAULT)
        config['modules']['progress'] = False
        guard = {'kind': 'progress', 'key': 'tower_repeat_off', 'priority': 131,
                 'mode': 'guard', 'repeat': False, 'freeEntry': True}
        scan = {'snapshot': {'loaded': True, 'connection': {'online': False},
                             'sync': {'queue': 101}}, 'actions': [guard]}
        self.assertEqual(choose(scan, config, {}, now=100), guard)
        config['running'] = False
        self.assertIsNone(choose(scan, config, {}, now=100))

    def test_repeat_guard_waits_for_inflight_travel_and_native_sync(self):
        guard = {'kind': 'progress', 'key': 'tower_repeat_off', 'priority': 131,
                 'mode': 'guard', 'repeat': False, 'freeEntry': True}
        scan = {'snapshot': {'loaded': True}, 'actions': [guard]}
        pending = {'pending_results': {'travel': {'action': {'kind': 'tower'}}}}
        self.assertIsNone(choose(scan, DEFAULT, pending, now=100))
        scan['snapshot']['sync'] = {'blocked': True}
        self.assertIsNone(choose(scan, DEFAULT, {}, now=100))


if __name__ == '__main__':
    unittest.main()
