import copy
import json
import unittest
from unittest.mock import patch

from dps_assistant import engine
from dps_assistant.policy import observe_growth, progression_baseline
from dps_assistant.training import observe_farming
from test_farm_efficiency import fixture
import test_scheduler


def setup():
    snapshot, state, config = fixture()
    snapshot['record']['deaths'] = 0
    snapshot['catalogue'] = {'normalMax': 160, 'characterMax': 101}
    config['strategy'].update(farm_min_seconds=30, farm_retry_seconds=60, farm_failure_limit=1)
    state['growth'] = {'phase': 'farm', 'frontier': 10, 'since': 70, 'deaths': 0,
                       **progression_baseline(snapshot)}
    for at in (100, 110, 120):
        snapshot['combat']['current']['elapsed'] = at - 100
        snapshot['characters'][0]['expTotal'] += 100
        observe_growth(snapshot, state, at, config)
        observe_farming(snapshot, state, 'game', at, config)
    return snapshot, state, config


def settlement(snapshot, state, result='Cleared', new_round=False):
    snapshot['characters'][0]['expTotal'] += 100
    snapshot['combat']['current'].update(result=result, elapsed=30)
    state['battle_observation'] = {'outcomes': [{'sequence': 1, 'category': 0, 'level': 9,
        'difficulty': 0, 'result': result, 'farming': True, 'started': 100.1, 'observed': 130}]}
    if new_round:
        snapshot['combat']['current'].update(sequence=2, result='InProgress', elapsed=1)


class SettlementTests(unittest.TestCase):
    def test_growth_transition_keeps_the_fully_observed_last_battle_without_rerouting(self):
        for result, new_round in [('Cleared', False), ('Failed', False), ('Cleared', True)]:
            with self.subTest(result=result, new_round=new_round):
                snapshot, state, config = setup()
                settlement(snapshot, state, result, new_round)
                route = copy.deepcopy(state['farm_route'])
                self.assertEqual(observe_growth(snapshot, state, 130, config)['phase'], 'push')
                row = observe_farming(snapshot, state, 'game', 130, config, finish_previous=True)
                measured = row['efficiency']['measurements'][0]
                self.assertTrue(measured['ready'])
                self.assertEqual(measured['observed_seconds'], 30)
                self.assertEqual(measured['gained'], 300)
                self.assertEqual(measured['per_minute'], 600)
                self.assertEqual(measured['clears'] if result == 'Cleared' else measured['failures'], 1)
                self.assertEqual(row['efficiency']['tested_count'], 1)
                for field in ('level', 'difficulty', 'since', 'active_seconds', 'visit_active_seconds'):
                    self.assertEqual(state['farm_route'][field], route[field])
                self.assertNotIn('last', state['farm_efficiency'])

    def test_finalization_cannot_start_a_sample_or_repeat_after_json_reload(self):
        snapshot, state, config = setup()
        settlement(snapshot, state)
        observe_growth(snapshot, state, 130, config)
        observe_farming(snapshot, state, 'game', 130, config, finish_previous=True)
        state = json.loads(json.dumps(state))
        original = copy.deepcopy(state['farm_efficiency']['stages'])
        snapshot['characters'][0]['expTotal'] += 999
        for at in (140, 150):
            observe_farming(snapshot, state, 'game', at, config, finish_previous=True)
        self.assertEqual(state['farm_efficiency']['stages'], original)
        state.pop('farm_efficiency')
        row = observe_farming(snapshot, state, 'game', 160, config, finish_previous=True)
        self.assertEqual(row['efficiency']['measurements'], [])

    def test_main_push_without_a_previous_farm_turn_does_not_extend_sampling(self):
        snapshot, state, config = setup()
        settlement(snapshot, state)
        observe_growth(snapshot, state, 130, config)
        row = observe_farming(snapshot, state, 'game', 130, config)
        self.assertEqual(row['efficiency']['measurements'][0]['observed_seconds'], 20)
        self.assertFalse(row['efficiency']['measurements'][0]['ready'])

    def test_pauses_gaps_growth_transport_and_invalid_native_evidence_cannot_complete_a_tail(self):
        changes = [
            ('manual pause', lambda s, d, c: c.update(running=False)),
            ('module off', lambda s, d, c: c['modules'].update(progress=False)),
            ('offline', lambda s, d, c: s['connection'].update(online=False)),
            ('sync', lambda s, d, c: s['battleReadiness'].update(syncRunning=True)),
            ('manual panel', lambda s, d, c: s.update(automationBlocked=True)),
            ('unknown battle', lambda s, d, c: s['combat'].update(available=False)),
            ('incomplete roster', lambda s, d, c: s['squad'].append(2)),
            ('strength changed', lambda s, d, c: s.update(runes={'learned': 1})),
            ('experience regression', lambda s, d, c: s['characters'][0].update(expTotal=1)),
            ('sequence regression', lambda s, d, c: s['combat']['current'].update(sequence=0)),
            ('mid-battle watchdog retry', lambda s, d, c: s['combat']['current'].update(result='InProgress', elapsed=60)),
            ('pending travel', lambda s, d, c: d.update(pending_results={'travel': {'action': {'kind': 'progress', 'phase': 'travel'}}})),
            ('no complete native outcome', lambda s, d, c: d.update(battle_observation={'outcomes': []})),
        ]
        for name, change in changes:
            with self.subTest(name=name):
                snapshot, state, config = setup()
                settlement(snapshot, state)
                state['growth']['phase'] = 'push'
                change(snapshot, state, config)
                row = observe_farming(snapshot, state, 'game', 130, config, finish_previous=True)
                self.assertFalse(any(r['ready'] for r in row['efficiency']['measurements']))
        for session, at in [('new-game', 130), ('game', 160)]:
            snapshot, state, config = setup()
            settlement(snapshot, state)
            state['growth']['phase'] = 'push'
            row = observe_farming(snapshot, state, session, at, config, finish_previous=True)
            self.assertFalse(any(r['ready'] for r in row['efficiency']['measurements']))

    def test_coverage_records_a_complete_sample_while_a_retry_owns_selection(self):
        snapshot, state, config = setup()
        settlement(snapshot, state)
        state['growth']['retry_requested_at'] = 120
        row = observe_farming(snapshot, state, 'game', 130, config)
        self.assertEqual(row['level'], 9)
        self.assertEqual(row['efficiency']['tested_count'], 1)
        self.assertTrue(row['efficiency']['measurements'][0]['ready'])

    def test_outcome_spanning_an_interrupted_observation_remains_incomplete(self):
        snapshot, state, config = setup()
        config['running'] = False
        observe_farming(snapshot, state, 'game', 122, config)
        config['running'] = True
        observe_farming(snapshot, state, 'game', 125, config)
        settlement(snapshot, state)
        observe_growth(snapshot, state, 130, config)
        row = observe_farming(snapshot, state, 'game', 130, config, finish_previous=True)
        self.assertEqual(row['efficiency']['measurements'][0]['clears'], 0)
        self.assertFalse(row['efficiency']['measurements'][0]['ready'])

    def test_production_engine_finalizes_the_tail_and_dispatches_the_main_retry(self):
        harness = test_scheduler.SchedulerTests()
        harness.setUp()
        self.addCleanup(harness.tearDown)
        bridge = harness.add()
        snapshot, _, config = setup()
        snapshot.update(account='1001', currencies={'soul': 100})
        value = {'snapshot': snapshot, 'actions': [], 'issues': []}
        original = bridge.call
        # ZIP backup timestamps use real wall time, before the deterministic battle clock.
        backup_reply = original('backup')
        def call(op, args=None):
            if op == 'opportunities':
                return copy.deepcopy(value)
            if op == 'backup':
                return copy.deepcopy(backup_reply)
            return original(op, args)
        bridge.call = call
        harness.engine.config = config
        snapshot['combat']['current'].update(sequence=0, elapsed=20)
        with patch.object(engine.time, 'time', return_value=90):
            harness.engine.tick('1')
        state = harness.engine.durable['host:1001']
        state['growth'] = {'phase': 'farm', 'frontier': 10, 'since': 70, 'deaths': 0,
                           **progression_baseline(snapshot)}
        state.pop('farm_efficiency', None)
        for at in (100, 110, 120, 130):
            current = snapshot['combat']['current']
            current.update(sequence=1, elapsed=at - 100, result='InProgress')
            snapshot['characters'][0]['expTotal'] += 100
            if at == 130:
                current['result'] = 'Cleared'
                snapshot['combat']['records'] = [{**current, 'characters': [
                    {'id': 1, 'dealt': 100, 'taken': 0, 'blocked': 0, 'healed': 0}]}]
                value['actions'] = [{'kind': 'progress', 'key': 'retry-main', 'mode': 'push', 'phase': 'travel',
                    'level': 11, 'difficulty': 0, 'ticket': 0, 'priority': 60, 'label': '重试主线'}]
            with patch.object(engine.time, 'time', return_value=at):
                harness.engine.tick('1')
        row = harness.engine.instances['1']
        self.assertIsNone(row.get('error'))
        self.assertEqual(row['growth']['phase'], 'push')
        self.assertTrue(row['farming']['efficiency']['measurements'][0]['ready'])
        self.assertEqual(row['farming']['efficiency']['measurements'][0]['observed_seconds'], 30)
        self.assertEqual([c['key'] for c in bridge.commands], ['retry-main'])
        self.assertTrue(harness.engine.config['running'])


if __name__ == '__main__':
    unittest.main()
