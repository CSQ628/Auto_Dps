import copy
import unittest

from dps_assistant.combat import observe_combat
from dps_assistant.policy import observe_growth


def record(sequence=1, level=20, result='InProgress', elapsed=10):
    return {'sequence': sequence, 'level': level, 'difficulty': 0, 'result': result, 'elapsed': elapsed,
            'characters': [{'id': 1, 'dealt': 100, 'taken': 50, 'blocked': 10, 'healed': 5}]}


def snapshot(category=0, sequence=1, level=20):
    current = record(sequence, level)
    return {'stage': {'category': category, 'level': level, 'difficulty': 0},
            'combat': {'available': True, 'current': current, 'records': [copy.deepcopy(current)]}}


class CombatTests(unittest.TestCase):
    def test_only_observed_context_is_attributed_and_aborted_travel_is_excluded(self):
        snap = snapshot(category=1, level=2)
        snap['combat']['records'].extend([record(10, 20, 'Failed'), record(11, 18, 'Aborted')])
        state = {}
        self.assertEqual(observe_combat(snap, state, 'game1', 100)['recent'], [])
        snap['combat']['records'][0].update(result='Cleared', elapsed=20)
        result = observe_combat(snap, state, 'game1', 120)
        self.assertEqual(len(result['recent']), 1)
        self.assertEqual(result['recent'][0]['category'], 1)
        self.assertEqual(result['recent'][0]['dps'], 5)
        self.assertIsNone(result['last_main'])

    def test_delayed_end_record_keeps_original_category_after_a_stage_switch(self):
        state = {}
        observe_combat(snapshot(category=0, sequence=1, level=20), state, 'game', 100)
        snap = snapshot(category=1, sequence=2, level=2)
        snap['combat']['records'].append(record(1, 20, 'Failed', 50))
        result = observe_combat(snap, state, 'game', 150)
        self.assertEqual(result['last_main']['level'], 20)
        self.assertEqual(result['last_main']['category'], 0)
        self.assertEqual(len(observe_combat(snap, state, 'game', 160)['recent']), 1)

    def test_game_process_change_does_not_reuse_sequence_context(self):
        state = {}
        observe_combat(snapshot(), state, 'pid:created1', 100)
        snap = snapshot(category=1, sequence=2, level=2)
        snap['combat']['records'].append(record(1, 20, 'Failed', 50))
        self.assertEqual(observe_combat(snap, state, 'pid:created2', 160)['recent'], [])

    def test_statistics_disabled_and_invalid_results_never_create_success_or_failure(self):
        state = {}
        snap = snapshot()
        observe_combat(snap, state, 'game', 100)
        for result, elapsed, dealt in [('Aborted', 30, 10), ('Unknown', 30, 10), ('Failed', 0, 10), ('Cleared', 30, float('nan')), ('Failed', 30, -1)]:
            row = record(result=result, elapsed=elapsed)
            row['characters'][0]['dealt'] = dealt
            snap['combat']['records'] = [row]
            self.assertEqual(observe_combat(snap, state, 'game', 130)['recent'], [])
        snap['combat'].update(available=False, records=[record(result='Cleared', elapsed=30)])
        self.assertFalse(observe_combat(snap, state, 'game', 140)['available'])
        self.assertEqual(state['battle_observation']['outcomes'], [])

    def test_missing_identity_and_contradictory_category_are_never_attributed(self):
        state = {}
        snap = snapshot()
        del snap['combat']['current']['sequence']
        self.assertEqual(observe_combat(snap, state, 'game', 100)['recent'], [])
        observe_combat(snapshot(), state, 'game', 110)
        snap = snapshot(category=1)
        observe_combat(snap, state, 'game', 120)
        snap['combat']['records'][0].update(result='Failed', elapsed=30)
        self.assertEqual(observe_combat(snap, state, 'game', 140)['recent'], [])

    def test_terminal_record_seen_without_live_context_stays_unknown(self):
        snap = snapshot()
        snap['combat']['current']['result'] = 'Cleared'
        snap['combat']['records'][0]['result'] = 'Cleared'
        self.assertEqual(observe_combat(snap, {}, 'game', 100)['recent'], [])

    def test_history_is_bounded(self):
        state = {}
        for seq in range(35):
            snap = snapshot(sequence=seq)
            snap['combat']['records'][0]['result'] = 'Cleared'
            observe_combat(snap, state, 'game', 100 + seq)
        self.assertEqual(len(state['battle_observation']['outcomes']), 20)
        self.assertEqual(len(state['battle_observation']['contexts']), 24)

    def test_tower_deaths_do_not_trigger_main_farming_when_native_statistics_are_available(self):
        snap = {'stage': {'category': 0}, 'record': {'maxCleared': 19, 'deaths': 3},
                'characters': [], 'combat': {'available': True}}
        state = {}
        observe_growth(snap, state, 100)
        snap['record']['deaths'] = 15
        state['battle_observation'] = {'outcomes': [
            {'category': 1, 'level': 10, 'observed': 180, 'result': 'Failed'},
            {'category': 1, 'level': 10, 'observed': 200, 'result': 'Failed'}]}
        self.assertEqual(observe_growth(snap, state, 300)['phase'], 'push')

    def test_native_statistics_unavailable_retains_existing_death_fallback(self):
        snap = {'stage': {'category': 0}, 'record': {'maxCleared': 19, 'deaths': 3},
                'characters': [], 'combat': {'available': False}}
        state = {}
        observe_growth(snap, state, 100)
        snap['record']['deaths'] = 9
        self.assertEqual(observe_growth(snap, state, 300)['phase'], 'farm')

    def test_repeated_native_main_failures_trigger_farming_without_inventing_deaths(self):
        snap = {'stage': {'category': 0}, 'record': {'maxCleared': 19, 'deaths': 3}, 'characters': []}
        state = {}
        observe_growth(snap, state, 100)
        failed = lambda category, level, at, result='Failed': {'category': category, 'level': level, 'observed': at, 'result': result}
        state['battle_observation'] = {'outcomes': [failed(1, 20, 150), failed(0, 18, 170), failed(0, 20, 180, 'Aborted')]}
        self.assertEqual(observe_growth(snap, state, 280)['phase'], 'push')
        state['battle_observation']['outcomes'].append(failed(0, 20, 200))
        self.assertEqual(observe_growth(snap, state, 281)['phase'], 'push')
        state['battle_observation']['outcomes'].append(failed(0, 20, 270))
        self.assertEqual(observe_growth(snap, state, 282)['phase'], 'farm')
        self.assertEqual(snap['record']['deaths'], 3)


if __name__ == '__main__':
    unittest.main()
