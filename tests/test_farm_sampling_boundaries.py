import unittest

from test_farm_efficiency import fixture
from dps_assistant.training import observe_farming


class FarmSamplingBoundaryTests(unittest.TestCase):
    def test_staggered_party_rewards_are_compared_over_the_entire_sample(self):
        snapshot, state, config = fixture()
        snapshot['squad'].append(2)
        snapshot['characters'].append({'id': 2, 'level': 10, 'expTotal': 1000})
        snapshot['battleReadiness'].update(expected=2, arrangedCount=2)
        observe_farming(snapshot, state, 'game', 100, config)
        snapshot['characters'][0]['expTotal'] += 100
        observe_farming(snapshot, state, 'game', 110, config)
        snapshot['characters'][1]['expTotal'] += 100
        result = observe_farming(snapshot, state, 'game', 120, config)
        self.assertEqual(result['efficiency']['measurements'][0]['gained'], 100)
        snapshot['combat']['current']['result'] = 'Cleared'
        state['battle_observation'] = {'outcomes': [{'sequence': 1, 'category': 0, 'level': 9,
            'difficulty': 0, 'result': 'Cleared', 'farming': True, 'started': 100.1, 'observed': 130}]}
        result = observe_farming(snapshot, state, 'game', 130, config)
        self.assertEqual(result['efficiency']['measurements'][0]['per_minute'], 200)

    def test_a_battle_spanning_a_pause_cannot_prove_a_complete_observed_clear(self):
        snapshot, state, config = fixture()
        observe_farming(snapshot, state, 'game', 100, config)
        snapshot['characters'][0]['expTotal'] += 10
        observe_farming(snapshot, state, 'game', 110, config)
        config['running'] = False
        observe_farming(snapshot, state, 'game', 112, config)
        config['running'] = True
        observe_farming(snapshot, state, 'game', 120, config)
        snapshot['combat']['current']['result'] = 'Cleared'
        state['battle_observation'] = {'outcomes': [{'sequence': 1, 'category': 0, 'level': 9,
            'difficulty': 0, 'result': 'Cleared', 'farming': True, 'started': 100.1, 'observed': 130}]}
        observe_farming(snapshot, state, 'game', 130, config)
        result = observe_farming(snapshot, state, 'game', 140, config)
        row = result['efficiency']['measurements'][0]
        self.assertEqual(row['observed_seconds'], 30)
        self.assertEqual(row['clears'], 0)
        self.assertFalse(row['ready'])

        snapshot['combat']['current'].update(sequence=2, result='InProgress')
        observe_farming(snapshot, state, 'game', 150, config)
        observe_farming(snapshot, state, 'game', 160, config)
        snapshot['combat']['current']['result'] = 'Cleared'
        state['battle_observation']['outcomes'].append({'sequence': 2, 'category': 0, 'level': 9,
            'difficulty': 0, 'result': 'Cleared', 'farming': True, 'started': 140.1, 'observed': 170})
        result = observe_farming(snapshot, state, 'game', 170, config)
        self.assertTrue(result['efficiency']['measurements'][0]['ready'])
        self.assertEqual(result['efficiency']['measurements'][0]['clears'], 1)

    def test_each_hero_keeps_their_own_gain_across_valid_observation_segments(self):
        snapshot, state, config = fixture()
        snapshot['squad'].append(2)
        snapshot['characters'].append({'id': 2, 'level': 10, 'expTotal': 1000})
        snapshot['battleReadiness'].update(expected=2, arrangedCount=2)
        observe_farming(snapshot, state, 'game', 100, config)
        snapshot['characters'][0]['expTotal'] += 100
        snapshot['characters'][1]['expTotal'] += 20
        observe_farming(snapshot, state, 'game', 110, config)
        snapshot['connection']['online'] = False
        observe_farming(snapshot, state, 'game', 112, config)
        snapshot['characters'][0]['expTotal'] += 999
        snapshot['characters'][1]['expTotal'] += 888
        snapshot['connection']['online'] = True
        observe_farming(snapshot, state, 'game', 120, config)
        snapshot['characters'][0]['expTotal'] += 20
        snapshot['characters'][1]['expTotal'] += 100
        result = observe_farming(snapshot, state, 'game', 130, config)
        row = result['efficiency']['measurements'][0]
        self.assertEqual(row['gained'], 120)
        self.assertEqual(row['observed_seconds'], 20)

    def test_legacy_aggregated_samples_are_discarded_when_the_schema_changes(self):
        snapshot, state, config = fixture()
        observe_farming(snapshot, state, 'game', 100, config)
        snapshot['characters'][0]['expTotal'] += 20
        observe_farming(snapshot, state, 'game', 110, config)
        cache = state['farm_efficiency']
        cache.pop('schema')
        cache['stages']['9:0'].pop('gained_by_character')
        result = observe_farming(snapshot, state, 'game', 120, config)
        self.assertFalse(result['efficiency']['measurements'])
        self.assertEqual(state['farm_efficiency']['schema'], 2)


if __name__ == '__main__':
    unittest.main()
