"""Experience selection must continue for the members who still need levels."""
import copy
import unittest

from dps_assistant.engine import DEFAULT
from dps_assistant.training import observe_farming


def fixture(levels=(101, 100), cap=101):
    snapshot = {
        'loaded': True, 'catalogue': {'characterMax': cap},
        'stage': {'category': 0, 'level': 9, 'difficulty': 0, 'repeat': True, 'running': True},
        'combat': {'available': True, 'current': {
            'sequence': 1, 'level': 9, 'difficulty': 0, 'result': 'InProgress', 'elapsed': 1}},
        'squad': list(range(1, len(levels) + 1)),
        'characters': [{'id': i, 'level': level, 'expTotal': 1000}
                       for i, level in enumerate(levels, 1)],
        'experienceBlocked': False, 'connection': {'online': True},
        'battleReadiness': {'known': True, 'charactersInitialized': True, 'timeScale': 1,
                            'syncRunning': False, 'syncPending': False, 'missing': [],
                            'expected': len(levels), 'arrangedCount': len(levels)},
        'record': {'maxCleared': 10},
        'progression': {'farmCandidates': [{'level': n, 'difficulty': 0} for n in (9, 8)]},
    }
    config = copy.deepcopy(DEFAULT)
    config['strategy']['farm_sample_seconds'] = 30
    return snapshot, {'growth': {'phase': 'farm'}}, config


def sample(snapshot, state, config, start=100, gains=(0, 20), level=9, sequence=1):
    snapshot['stage']['level'] = level
    current = snapshot['combat']['current']
    current.update(level=level, sequence=sequence, result='InProgress', elapsed=1)
    observe_farming(snapshot, state, 'game', start, config)
    for index in range(1, 4):
        for character, gained in zip(snapshot['characters'], gains):
            character['expTotal'] += gained
        current['elapsed'] = index * 10
        if index == 3:
            current['result'] = 'Cleared'
            state.setdefault('battle_observation', {}).setdefault('outcomes', []).append({
                'sequence': sequence, 'category': 0, 'level': level, 'difficulty': 0,
                'result': 'Cleared', 'farming': True, 'started': start + .1, 'observed': start + 30})
        result = observe_farming(snapshot, state, 'game', start + index * 10, config)
    return result


class LevelCapFarmingTests(unittest.TestCase):
    def test_capped_member_does_not_zero_the_remaining_members_rate(self):
        snapshot, state, config = fixture()
        result = sample(snapshot, state, config)
        self.assertEqual(result['efficiency']['measurements'][0]['per_minute'], 120)
        self.assertEqual(result['efficiency']['levelling_characters'], [2])
        # Map 8 gives the unfinished hero twice as much, even though map 9 gives
        # the capped hero an artificial counter increase. The capped hero is irrelevant.
        result = sample(snapshot, state, config, 140, (999, 40), 8, 2)
        self.assertEqual(result['level'], 8)
        self.assertEqual([r['per_minute'] for r in result['efficiency']['measurements']], [120, 240])

    def test_every_uncapped_member_still_counts_in_the_bottleneck(self):
        snapshot, state, config = fixture((101, 99, 100))
        result = sample(snapshot, state, config, gains=(0, 100, 5))
        self.assertEqual(result['efficiency']['measurements'][0]['per_minute'], 30)
        self.assertEqual(result['efficiency']['levelling_characters'], [2, 3])

    def test_native_cap_is_used_instead_of_a_hardcoded_level(self):
        snapshot, state, config = fixture((60, 59), cap=60)
        result = sample(snapshot, state, config)
        self.assertEqual(result['efficiency']['measurements'][0]['per_minute'], 120)

    def test_unknown_cap_conservatively_keeps_all_members(self):
        for cap in (None, 0, True, '101', float('nan')):
            with self.subTest(cap=cap):
                snapshot, state, config = fixture(cap=cap)
                result = sample(snapshot, state, config)
                self.assertEqual(result['efficiency']['measurements'][0]['per_minute'], 0)

    def test_all_capped_stops_experience_probes_without_disabling_other_automation(self):
        snapshot, state, config = fixture((101, 101))
        before = copy.deepcopy(config)
        result = sample(snapshot, state, config, gains=(0, 0))
        route = state['farm_route']
        route.update(active_seconds=10000, visit_active_seconds=10000)
        result = observe_farming(snapshot, state, 'game', 140, config)
        self.assertEqual(result['level'], 9)
        self.assertFalse(route['failed_stages'])
        self.assertFalse(result['efficiency']['measurements'])
        self.assertIn('满级', result['efficiency']['reason'])
        self.assertEqual(result['efficiency']['levelling_characters'], [])
        self.assertNotIn('last', state['farm_efficiency'])
        self.assertEqual(config, before)
        self.assertEqual(state['growth']['phase'], 'farm')

    def test_reaching_cap_starts_a_new_scope_and_does_not_mix_old_rates(self):
        snapshot, state, config = fixture((100, 99))
        sample(snapshot, state, config, gains=(20, 10))
        snapshot['characters'][0]['level'] = 101
        result = observe_farming(snapshot, state, 'game', 140, config)
        self.assertFalse(result['efficiency']['measurements'])
        self.assertEqual(result['efficiency']['levelling_characters'], [2])
        result = sample(snapshot, state, config, 150, (0, 40), 9, 2)
        self.assertEqual(result['efficiency']['measurements'][0]['gained'], 120)
        self.assertEqual(result['efficiency']['measurements'][0]['observed_seconds'], 40)
        self.assertEqual(result['efficiency']['measurements'][0]['per_minute'], 180)

    def test_cap_metadata_change_invalidates_old_scope_rates(self):
        snapshot, state, config = fixture(cap=None)
        sample(snapshot, state, config)
        snapshot['catalogue']['characterMax'] = 101
        result = observe_farming(snapshot, state, 'game', 140, config)
        self.assertFalse(result['efficiency']['measurements'])
        self.assertEqual(result['efficiency']['levelling_characters'], [2])


    def test_legacy_sample_cache_is_rebased_without_changing_configuration(self):
        snapshot, state, config = fixture()
        sample(snapshot, state, config)
        before = copy.deepcopy(config)
        state['farm_efficiency']['schema'] = 3
        result = observe_farming(snapshot, state, 'game', 140, config)
        self.assertFalse(result['efficiency']['measurements'])
        self.assertEqual(config, before)

    def test_all_capped_does_not_block_normal_frontier_retry(self):
        from dps_assistant.policy import observe_growth, progression_baseline
        snapshot, state, config = fixture((101, 101))
        state['growth'] = {'phase': 'farm', 'frontier': 10, 'since': 100, 'deaths': 0,
                           **progression_baseline(snapshot)}
        sample(snapshot, state, config, gains=(0, 0))
        result = observe_growth(snapshot, state, 100 + config['strategy']['farm_retry_seconds'], config)
        self.assertEqual(result['phase'], 'push')

    def test_incomplete_or_duplicate_roster_cannot_confirm_all_capped(self):
        for boundary in ('missing', 'duplicate'):
            snapshot, state, config = fixture((101, 101))
            if boundary == 'missing':
                snapshot['characters'].pop()
            else:
                snapshot['characters'][1]['id'] = 1
            result = sample(snapshot, state, config, gains=(0, 0))
            self.assertFalse(result['efficiency']['all_at_cap'])
            self.assertFalse(result['efficiency']['measurements'])


if __name__ == '__main__':
    unittest.main()
