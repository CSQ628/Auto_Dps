import copy
import json
import unittest

from dps_assistant.combat import observe_combat
from dps_assistant.training import observe_farming
from test_farm_efficiency import fixture


class RoundCompletionTests(unittest.TestCase):
    def setup_rounds(self):
        snapshot, state, config = fixture()
        config['strategy'].update(farm_probe_seconds=60, farm_sample_seconds=30)
        return snapshot, state, config

    def poll(self, snapshot, state, config, at, rounds=((90, 135, 'Cleared'), (135, 185, 'Cleared'))):
        completed = [(n, start, end, result) for n, (start, end, result) in enumerate(rounds, 1) if end <= at]
        current = next(((n, start) for n, (start, end, _) in enumerate(rounds, 1) if start <= at < end),
                       (len(rounds) + 1, rounds[-1][1]))
        snapshot['combat']['current'].update(sequence=current[0], elapsed=at-current[1], result='InProgress')
        snapshot['combat']['records'] = [
            {'sequence': n, 'level': 9, 'difficulty': 0, 'result': result, 'elapsed': end-start,
             'characters': [{'dealt': 100, 'taken': 10, 'blocked': 0, 'healed': 0}]}
            for n, start, end, result in completed]
        snapshot['characters'][0]['expTotal'] += 10
        observe_combat(snapshot, state, 'game', at)
        return observe_farming(snapshot, state, 'game', at, config)

    def test_partially_observed_first_clear_allows_the_next_complete_round_to_finish(self):
        snapshot, state, config = self.setup_rounds()
        for at in range(100, 171, 10):
            result = self.poll(snapshot, state, config, at)
        self.assertEqual(result['level'], 9)
        self.assertFalse(result['efficiency']['measurements'][0]['ready'])
        self.assertEqual(result['efficiency']['measurements'][0]['clears'], 0)
        result = self.poll(snapshot, state, config, 180)
        self.assertEqual(result['level'], 9)
        result = self.poll(snapshot, state, config, 190)
        self.assertEqual(result['level'], 8)
        self.assertEqual(result['efficiency']['measurements'][0]['clears'], 1)
        self.assertTrue(result['efficiency']['measurements'][0]['ready'])

    def test_the_existing_total_probe_limit_still_stops_an_unfinished_second_round(self):
        snapshot, state, config = self.setup_rounds()
        rounds = ((90, 135, 'Cleared'), (135, 400, 'Cleared'))
        for at in range(100, 221, 10):
            result = self.poll(snapshot, state, config, at, rounds)
        self.assertEqual(result['level'], 8)
        self.assertFalse(result['efficiency']['measurements'][0]['ready'])
        self.assertEqual(state['farm_route']['failed_stages'], ['9:0'])

    def test_a_stalled_first_round_gets_no_extra_probe_time(self):
        snapshot, state, config = self.setup_rounds()
        for at in range(100, 161, 10):
            result = self.poll(snapshot, state, config, at, ((90, 400, 'Cleared'),))
        self.assertEqual(result['level'], 8)
        self.assertIsNone(result['efficiency']['measurements'][0]['per_minute'])

    def test_growth_does_not_reuse_an_old_clear_to_extend_the_new_strength_probe(self):
        for growth in ('equipment', 'level'):
            with self.subTest(growth=growth):
                snapshot, state, config = self.setup_rounds()
                rounds = ((90, 135, 'Cleared'), (135, 400, 'Cleared'))
                for at in range(100, 171, 10):
                    self.poll(snapshot, state, config, at, rounds)
                if growth == 'equipment':
                    snapshot['characters'][0]['equipment'] = [{'slot': 0, 'uid': 'upgrade'}]
                else:
                    snapshot['characters'][0]['level'] += 1
                for at in range(180, 241, 10):
                    result = self.poll(snapshot, state, config, at, rounds)
                self.assertEqual(result['level'], 8)
                self.assertFalse(result['efficiency']['measurements'][0]['ready'])
                self.assertEqual(result['efficiency']['measurements'][0]['clears'], 0)

    def test_pauses_offline_or_native_sync_interrupt_the_complete_round_requirement(self):
        for boundary in ('pause', 'offline', 'sync'):
            with self.subTest(boundary=boundary):
                snapshot, state, config = self.setup_rounds()
                for at in range(100, 151, 10):
                    self.poll(snapshot, state, config, at)
                if boundary == 'pause': config['running'] = False
                if boundary == 'offline': snapshot['connection']['online'] = False
                if boundary == 'sync': snapshot['battleReadiness']['syncRunning'] = True
                self.poll(snapshot, state, config, 155)
                config['running'] = True
                snapshot['connection']['online'] = True
                snapshot['battleReadiness']['syncRunning'] = False
                self.poll(snapshot, state, config, 160)
                result = self.poll(snapshot, state, config, 170)
                self.assertEqual(result['level'], 8)
                self.assertFalse(result['efficiency']['measurements'][0]['ready'])

    def test_two_fully_observed_failure_rounds_keep_the_configured_failure_threshold(self):
        snapshot, state, config = self.setup_rounds()
        rounds = ((90, 135, 'Failed'), (135, 170, 'Failed'), (170, 205, 'Failed'))
        for at in range(100, 201, 10):
            result = self.poll(snapshot, state, config, at, rounds)
        self.assertEqual(result['level'], 9)
        self.assertEqual(result['efficiency']['measurements'][0]['failures'], 1)
        result = self.poll(snapshot, state, config, 210, rounds)
        self.assertEqual(result['level'], 8)
        self.assertEqual(result['efficiency']['measurements'][0]['failures'], 2)
        self.assertTrue(result['efficiency']['measurements'][0]['ready'])

    def test_restart_does_not_duplicate_settlements_and_unrelated_rounds_do_not_extend_a_probe(self):
        snapshot, state, config = self.setup_rounds()
        for at in range(100, 171, 10):
            self.poll(snapshot, state, config, at)
        state = json.loads(json.dumps(state))
        self.poll(snapshot, state, config, 180)
        row = self.poll(snapshot, state, config, 190)
        self.assertEqual(row['efficiency']['measurements'][0]['clears'], 1)
        before = copy.deepcopy(state['farm_efficiency']['stages'])
        self.poll(snapshot, state, config, 190)
        self.assertEqual(state['farm_efficiency']['stages'], before)

        for mismatch in ('category', 'level', 'difficulty', 'farming', 'old_visit'):
            snapshot, state, config = self.setup_rounds()
            for at in range(100, 151, 10):
                self.poll(snapshot, state, config, at)
            outcome = state['battle_observation']['outcomes'][0]
            if mismatch == 'old_visit': outcome['observed'] = 0
            elif mismatch == 'farming': outcome['farming'] = False
            else: outcome[mismatch] = -1
            result = self.poll(snapshot, state, config, 160)
            self.assertEqual(result['level'], 8, mismatch)


if __name__ == '__main__':
    unittest.main()
