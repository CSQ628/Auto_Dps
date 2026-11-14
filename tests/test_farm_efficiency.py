import copy
import unittest

from dps_assistant.engine import DEFAULT
from dps_assistant.farm_efficiency import observe_efficiency
from dps_assistant.policy import choose
from dps_assistant.training import observe_farming


def fixture():
    snapshot = {'loaded': True, 'stage': {'category': 0, 'level': 9, 'difficulty': 0, 'repeat': True, 'running': True},
                'combat': {'available': True, 'current': {'sequence': 1, 'level': 9, 'difficulty': 0,
                                                       'result': 'InProgress', 'elapsed': 20}},
                'squad': [1], 'characters': [{'id': 1, 'level': 10, 'expTotal': 1000}], 'experienceBlocked': False,
                'battleReadiness': {'known': True, 'charactersInitialized': True, 'timeScale': 1,
                                    'syncRunning': False, 'syncPending': False, 'missing': [], 'expected': 1, 'arrangedCount': 1},
                'connection': {'online': True}, 'record': {'maxCleared': 10}, 'currencies': {},
                'progression': {'farmCandidates': [{'level': n, 'difficulty': 0} for n in (9, 8)]}}
    state = {'growth': {'phase': 'farm'}}
    config = copy.deepcopy(DEFAULT)
    config['strategy']['farm_sample_seconds'] = 30
    return snapshot, state, config


def visit(snapshot, state, config, start, gain, level, sequence, outcome='Cleared'):
    snapshot['stage']['level'] = level
    current = snapshot['combat']['current']
    current.update(level=level, sequence=sequence, result='InProgress', elapsed=1)
    observe_farming(snapshot, state, 'game', start, config)
    for index in range(1, 4):
        snapshot['characters'][0]['expTotal'] += gain
        current['elapsed'] = index * 10
        if index == 3:
            current['result'] = outcome
            state.setdefault('battle_observation', {}).setdefault('outcomes', []).append(
                {'sequence': sequence, 'category': 0, 'level': level, 'difficulty': 0,
                 'result': outcome, 'farming': True, 'started': start + .1, 'observed': start + 30})
        result = observe_farming(snapshot, state, 'game', start + index * 10, config)
    return result


class FarmEfficiencyTests(unittest.TestCase):
    def test_free_candidates_are_compared_then_better_measured_stage_is_kept(self):
        snapshot, state, config = fixture()
        result = visit(snapshot, state, config, 100, 10, 9, 1)
        self.assertEqual(result['level'], 8)
        self.assertEqual(result['efficiency']['measurements'][0]['per_minute'], 60)
        result = visit(snapshot, state, config, 140, 20, 8, 2)
        self.assertEqual(result['level'], 8)
        self.assertEqual([p['per_minute'] for p in result['efficiency']['measurements']], [60, 120])
        actions = [{'kind': 'progress', 'key': str(n), 'level': n, 'difficulty': 0, 'mode': 'farm', 'priority': 107} for n in (9, 8)]
        self.assertEqual(choose({'snapshot': snapshot, 'actions': actions}, config, state, 171)['level'], 8)

    def test_returns_to_proven_faster_stage_and_hysteresis_avoids_marginal_switch(self):
        for first_gain, expected in [(20, 9), (10.5, 8)]:
            snapshot, state, config = fixture()
            visit(snapshot, state, config, 100, first_gain, 9, 1)
            result = visit(snapshot, state, config, 140, 10, 8, 2)
            self.assertEqual(result['level'], expected)

    def test_short_samples_no_clear_and_mid_battle_do_not_start_exploration(self):
        snapshot, state, config = fixture()
        observe_farming(snapshot, state, 'game', 100, config)
        for at in (110, 120, 130):
            snapshot['characters'][0]['expTotal'] += 10
            result = observe_farming(snapshot, state, 'game', at, config)
        self.assertEqual(result['level'], 9)
        self.assertIsNone(result['efficiency']['measurements'][0]['per_minute'])
        state['battle_observation'] = {'outcomes': [{'sequence': 1, 'category': 0, 'level': 9, 'difficulty': 0,
             'result': 'Cleared', 'farming': True, 'started': 101, 'observed': 135}]}
        result = observe_farming(snapshot, state, 'game', 140, config)
        self.assertEqual(result['level'], 9)
        snapshot['combat']['current']['elapsed'] = 1
        self.assertEqual(observe_farming(snapshot, state, 'game', 141, config)['level'], 8)

    def test_pause_offline_popup_tower_loading_and_paid_travel_do_not_mix_gains(self):
        for boundary in ('pause', 'offline', 'popup', 'tower', 'loading', 'travel', 'push', 'missing', 'disabled_module'):
            with self.subTest(boundary=boundary):
                snapshot, state, config = fixture()
                observe_farming(snapshot, state, 'game', 100, config)
                if boundary == 'pause': config['running'] = False
                if boundary == 'offline': snapshot['connection']['online'] = False
                if boundary == 'popup': snapshot['experienceBlocked'] = True
                if boundary == 'tower': snapshot['stage']['category'] = 1
                if boundary == 'loading': snapshot['battleReadiness']['syncRunning'] = True
                if boundary == 'travel': state['pending_results'] = {'boss': {'action': {'kind': 'progress', 'phase': 'travel'}}}
                if boundary == 'push': state['growth']['phase'] = 'push'
                if boundary == 'missing': snapshot['battleReadiness']['missing'] = [1]
                if boundary == 'disabled_module': config['modules']['progress'] = False
                snapshot['characters'][0]['expTotal'] += 99999
                observe_farming(snapshot, state, 'game', 110, config)
                self.assertFalse(state['farm_efficiency']['stages'])
                self.assertNotIn('last', state['farm_efficiency'])

    def test_strength_changes_restarts_gaps_and_rollbacks_never_reuse_mixed_rates(self):
        for boundary in ('equipment', 'level', 'session', 'gap', 'rollback', 'sequence'):
            with self.subTest(boundary=boundary):
                snapshot, state, config = fixture()
                visit(snapshot, state, config, 100, 10, 9, 1)
                if boundary == 'equipment': snapshot['characters'][0]['equipment'] = [{'slot': 0, 'uid': 'upgrade'}]
                if boundary == 'level': snapshot['characters'][0]['level'] += 1
                if boundary == 'rollback': snapshot['characters'][0]['expTotal'] = 1
                if boundary == 'sequence': snapshot['combat']['current']['sequence'] = 0
                result = observe_farming(snapshot, state, 'new-game' if boundary == 'session' else 'game',
                                         200 if boundary == 'gap' else 140, config)
                if boundary == 'gap':
                    self.assertEqual(result['efficiency']['measurements'][0]['observed_seconds'], 30)
                else:
                    self.assertFalse(result['efficiency']['measurements'])

    def test_two_failures_are_measured_before_exploring_the_next_current_chapter_map(self):
        snapshot, state, config = fixture()
        result = visit(snapshot, state, config, 100, 20, 9, 1, 'Failed')
        self.assertEqual(result['level'], 9)
        self.assertFalse(result['efficiency']['measurements'][0]['ready'])
        result = visit(snapshot, state, config, 140, 20, 9, 2, 'Failed')
        self.assertEqual(result['level'], 8)
        measured = next(p for p in result['efficiency']['measurements'] if p['level'] == 9)
        self.assertEqual(measured['failures'], 2)
        self.assertTrue(measured['ready'])
        self.assertEqual(state['farm_route']['failed_stages'], [])
        result = visit(snapshot, state, config, 180, 10, 8, 3, 'Cleared')
        self.assertEqual(result['level'], 9)
        snapshot['characters'][0]['level'] += 1
        self.assertEqual(observe_farming(snapshot, state, 'game', 220, config)['level'], 9)

    def test_expiry_and_switch_toggle_use_current_parameters(self):
        snapshot, state, config = fixture()
        visit(snapshot, state, config, 100, 10, 9, 1)
        snapshot['stage']['repeat'] = False
        result = observe_farming(snapshot, state, 'game', 2000, config)
        self.assertFalse(result['efficiency']['measurements'])
        config['strategy']['adaptive_farming'] = False
        result = observe_farming(snapshot, state, 'game', 2001, config)
        self.assertFalse(result['efficiency']['enabled'])
        self.assertNotIn('farm_efficiency', state)

    def test_minimum_party_reward_includes_lagging_hero_and_restarts_keep_elapsed_cost(self):
        snapshot, state, config = fixture()
        snapshot['squad'].append(2)
        snapshot['characters'].append({'id': 2, 'level': 10, 'expTotal': 1000})
        snapshot['battleReadiness'].update(expected=2, arrangedCount=2)
        observe_farming(snapshot, state, 'game', 100, config)
        snapshot['characters'][0]['expTotal'] += 100
        snapshot['characters'][1]['expTotal'] += 20
        snapshot['combat']['current']['sequence'] += 1
        result = observe_farming(snapshot, state, 'game', 110, config)
        row = result['efficiency']['measurements'][0]
        self.assertEqual(row['gained'], 20)
        self.assertEqual(row['observed_seconds'], 10)

    def test_short_tower_visit_with_no_main_candidates_breaks_experience_continuity(self):
        snapshot, state, config = fixture()
        observe_farming(snapshot, state, 'game', 100, config)
        main_candidates = snapshot['progression']['farmCandidates']
        snapshot['stage']['category'] = 1
        snapshot['progression']['farmCandidates'] = []
        self.assertIsNone(observe_farming(snapshot, state, 'game', 102, config))
        snapshot['characters'][0]['expTotal'] += 10000
        snapshot['stage']['category'] = 0
        snapshot['progression']['farmCandidates'] = main_candidates
        result = observe_farming(snapshot, state, 'game', 104, config)
        self.assertFalse(result['efficiency']['measurements'])


if __name__ == '__main__':
    unittest.main()
