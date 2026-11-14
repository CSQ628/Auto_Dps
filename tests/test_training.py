import copy
import unittest

from dps_assistant.combat import observe_combat
from dps_assistant.engine import DEFAULT
from dps_assistant.policy import choose
from dps_assistant.training import observe_experience, observe_farming


def snapshot():
    return {'loaded': True, 'stage': {'category': 0, 'level': 9, 'difficulty': 0, 'repeat': True, 'running': True},
            'combat': {'available': True, 'current': {'sequence': 1, 'level': 9, 'difficulty': 0, 'result': 'InProgress', 'elapsed': 1}, 'records': []},
            'squad': [1], 'characters': [{'id': 1, 'level': 10, 'exp': 50, 'expTotal': 1000, 'expNext': 500}],
            'record': {'maxCleared': 10}, 'currencies': {},
            'progression': {'farmCandidates': [{'level': n, 'difficulty': 0} for n in (9, 8, 7)]}}


def failed(seq, **kwargs):
    return {'sequence': seq, 'category': 0, 'level': 9, 'difficulty': 0, 'farming': True,
            'result': 'Failed', 'observed': 150, **kwargs}


class ExperienceTests(unittest.TestCase):
    def test_rates_use_native_totals_and_require_ten_seconds_of_continuity(self):
        s, state = snapshot(), {}
        self.assertIsNone(observe_experience(s, state, 'game', 100)['characters'][0]['per_minute'])
        s['characters'][0]['expTotal'] += 20
        self.assertIsNone(observe_experience(s, state, 'game', 105)['characters'][0]['per_minute'])
        s['characters'][0]['expTotal'] += 30
        r = observe_experience(s, state, 'game', 110)
        self.assertEqual(r['observed_seconds'], 10)
        self.assertEqual(r['characters'][0]['gained'], 50)
        self.assertEqual(r['characters'][0]['per_minute'], 300)

    def test_stage_sequence_party_changes_gaps_and_restart_do_not_mix_rewards(self):
        for change in ('stage', 'sequence', 'party', 'gap', 'session', 'decrease', 'level'):
            with self.subTest(change=change):
                s, state = snapshot(), {}
                observe_experience(s, state, 'game', 100)
                s['characters'][0]['expTotal'] += 9999
                session, at = 'game', 110
                if change == 'stage': s['stage']['category'] = 1
                if change == 'sequence': s['combat']['current']['sequence'] = 2
                if change == 'party': s['squad'] = [2]
                if change == 'gap': at = 200
                if change == 'session': session = 'another-game'
                if change == 'decrease': s['characters'][0]['expTotal'] = 999
                if change == 'level': s['characters'][0].update(level=11, exp=1)
                r = observe_experience(s, state, session, at)
                self.assertTrue(not r['available'] or r['observed_seconds'] == 0)
                self.assertTrue(all(c['per_minute'] is None for c in r['characters']))

    def test_missing_native_totals_or_stats_never_publish_an_invented_rate(self):
        for field, value in [('expTotal', None), ('expTotal', float('nan')), ('expNext', -1)]:
            s, state = snapshot(), {}
            observe_experience(s, state, 'game', 100)
            s['characters'][0][field] = value
            self.assertFalse(observe_experience(s, state, 'game', 110)['available'])
            self.assertNotIn('experience_observation', state)


class FarmRecoveryTests(unittest.TestCase):
    def test_distinct_farming_failures_wait_for_sampled_efficiency_before_switching(self):
        s, state = snapshot(), {'growth': {'phase': 'farm'}}
        observe_farming(s, state, 'game', 100)
        state['battle_observation'] = {'outcomes': [failed(1), failed(1), failed(2, category=1),
            failed(3, result='Aborted'), failed(4, farming=False), failed(5, observed=99), failed(6, difficulty=1)]}
        self.assertEqual(observe_farming(s, state, 'game', 160)['level'], 9)
        state['battle_observation']['outcomes'].append(failed(7))
        r = observe_farming(s, state, 'game', 161)
        self.assertEqual(r['level'], 9)
        self.assertEqual(r['failures'], 2)
        self.assertEqual(observe_farming(s, state, 'game', 162)['level'], 9)
        actions = [{'kind': 'progress', 'key': str(n), 'mode': 'farm', 'priority': 107, 'level': n, 'difficulty': 0} for n in (9, 8, 7)]
        self.assertEqual(choose({'snapshot': s, 'actions': actions}, DEFAULT, state, 163)['level'], 9)
        # Staying on the selected highest map is not a travel to another candidate.
        self.assertEqual(choose({'snapshot': s, 'actions': [actions[0], actions[2]]}, DEFAULT, state, 164)['level'], 9)

    def test_recovery_survives_push_and_gear_changes_but_reassesses_real_progress(self):
        for reset in ('frontier', 'level', 'session', 'config'):
            with self.subTest(reset=reset):
                s, state = snapshot(), {'growth': {'phase': 'farm'}}
                observe_farming(s, state, 'game', 100)
                state['battle_observation'] = {'outcomes': [failed(1), failed(2)]}
                observe_farming(s, state, 'game', 160)
                state['growth']['phase'] = 'push'
                s['characters'][0]['equipment'] = [{'uid': 'upgrade'}]
                self.assertEqual(observe_farming(s, state, 'game', 170)['level'], 9)
                session, config = 'game', copy.deepcopy(DEFAULT)
                if reset == 'frontier':
                    s['record']['maxCleared'] += 1
                    s['progression']['farmCandidates'] = [{'level': 11, 'difficulty': 0}, {'level': 9, 'difficulty': 0}]
                if reset == 'level': s['characters'][0]['level'] += 1
                if reset == 'session': session = 'new-game'
                if reset == 'config': config['strategy']['farm_candidate_count'] = 3
                expected = 11 if reset == 'frontier' else 9
                self.assertEqual(observe_farming(s, state, session, 180, config)['level'], expected)

    def test_no_candidate_or_lowest_candidate_never_invents_a_destination(self):
        s, state = snapshot(), {'growth': {'phase': 'farm'}}
        s['progression']['farmCandidates'] = [{'level': 7, 'difficulty': 0}]
        observe_farming(s, state, 'game', 100)
        state['battle_observation'] = {'outcomes': [failed(1, level=7), failed(2, level=7)]}
        self.assertEqual(observe_farming(s, state, 'game', 160)['level'], 7)
        s['progression']['farmCandidates'] = []
        self.assertIsNone(observe_farming(s, state, 'game', 170))
        s['progression']['farmCandidates'] = [{'level': 8, 'difficulty': 0}]
        self.assertEqual(observe_farming(s, state, 'game', 180)['level'], 8)

    def test_changed_failure_threshold_is_applied_without_losing_route(self):
        s, state = snapshot(), {'growth': {'phase': 'farm'}}
        observe_farming(s, state, 'game', 100)
        state['battle_observation'] = {'outcomes': [failed(1)]}
        config = copy.deepcopy(DEFAULT)
        config['strategy']['farm_failure_limit'] = 1
        self.assertEqual(observe_farming(s, state, 'game', 160, config)['level'], 9)

    def test_battle_attribution_marks_farming_only_after_live_repeat_observation(self):
        s, state = snapshot(), {'growth': {'phase': 'farm'}}
        observe_combat(s, state, 'game', 100)
        s['combat']['records'] = [{**s['combat']['current'], 'result': 'Failed', 'elapsed': 20,
                                  'characters': [{'id': 1, 'dealt': 1, 'taken': 1, 'blocked': 0, 'healed': 0}]}]
        result = observe_combat(s, state, 'game', 120)
        self.assertTrue(result['last_main']['farming'])


if __name__ == '__main__':
    unittest.main()
