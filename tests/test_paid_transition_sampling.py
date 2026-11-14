"""A timed-out paid reservation must not become an endless active transition."""
import copy
import json
import time
import unittest
from unittest.mock import patch

from dps_assistant.engine import Engine
from dps_assistant.policy import choose, observe_growth, progression_baseline
from dps_assistant.training import observe_farming
from test_farm_efficiency import fixture
import test_scheduler


def paid_action(key='boss:11:old'):
    return {'kind': 'progress', 'mode': 'boss', 'phase': 'travel', 'key': key,
            'level': 11, 'difficulty': 0, 'repeat': False, 'ticket': 690100,
            'ticketBefore': 4, 'ticketUid': 'old', 'label': '挑战Boss', 'priority': 108}


class PaidTransitionSamplingTests(unittest.TestCase):
    def prepare(self):
        snap, state, config = fixture()
        action = paid_action()
        entry = {'action': action, 'at': 100, 'cleared_before': 10}
        state.update(uncertain={action['key']: 100}, pending_results={action['key']: copy.deepcopy(entry)},
                     entry_uncertainty={action['key']: copy.deepcopy(entry)})
        engine = Engine.__new__(Engine)
        engine.config = config
        self.events = []
        engine.record = lambda *args, **kwargs: self.events.append((args, kwargs))
        return engine, snap, state, action

    def test_timeout_preserves_original_reservation_without_refreshing_its_clock(self):
        engine, snap, state, action = self.prepare()
        with patch('dps_assistant.engine.time.time', return_value=250):
            engine.settle_pending('1', {'identity': 'test'}, state, snap)
        self.assertFalse(state['pending_results'])
        self.assertEqual(state['uncertain'][action['key']], 100)
        self.assertEqual(state['entry_uncertainty'][action['key']]['at'], 100)
        self.assertEqual(state.get('confirmed', 0), 0)

    def test_legacy_rebuilt_pending_uses_original_paid_deadline_and_does_not_delay_sampling(self):
        engine, snap, state, action = self.prepare()
        state['pending_results'][action['key']]['at'] = 245
        state['pending_results'][action['key']]['action']['ticketBefore'] = 5
        with patch('dps_assistant.engine.time.time', return_value=250):
            engine.settle_pending('1', {'identity': 'test'}, state, snap)
        self.assertFalse(state['pending_results'])
        self.assertEqual(state['entry_uncertainty'][action['key']]['action']['ticketBefore'], 4)
        observe_farming(snap, state, 'game', 251, engine.config)
        snap['characters'][0]['expTotal'] += 50
        result = observe_farming(snap, state, 'game', 261, engine.config)
        self.assertEqual(result['efficiency']['measurements'][0]['gained'], 50)

    def test_unknown_paid_result_keeps_same_target_reserved_and_free_growth_available(self):
        engine, snap, state, action = self.prepare()
        with patch('dps_assistant.engine.time.time', return_value=250):
            engine.settle_pending('1', {'identity': 'test'}, state, snap)
        state['growth']['phase'] = 'push'
        changed = {**action, 'key': 'boss:11:new', 'ticketUid': 'new'}
        independent = {'kind': 'rune', 'key': 'rune:1', 'priority': 80}
        value = choose({'snapshot': snap, 'actions': [changed, independent]}, engine.config, state, 251)
        self.assertEqual(value['kind'], 'rune')
        self.assertIsNone(choose({'snapshot': snap, 'actions': [changed]}, engine.config, state, 10000))

    def test_fresh_travel_still_blocks_sampling_and_a_second_scene_command(self):
        engine, snap, state, action = self.prepare()
        with patch('dps_assistant.engine.time.time', return_value=110):
            engine.settle_pending('1', {'identity': 'test'}, state, snap)
        observe_farming(snap, state, 'game', 111, engine.config)
        snap['characters'][0]['expTotal'] += 50
        self.assertFalse(observe_farming(snap, state, 'game', 121, engine.config)['efficiency']['measurements'])
        free = {'kind': 'progress', 'mode': 'farm', 'phase': 'travel', 'key': 'farm:9',
                'level': 9, 'difficulty': 0, 'freeEntry': True, 'priority': 107}
        self.assertIsNone(choose({'snapshot': snap, 'actions': [free]}, engine.config, state, 121))

    def test_reserved_frontier_keeps_farming_instead_of_waiting_forever_for_a_blocked_push(self):
        for phase in ('push', 'farm'):
            with self.subTest(phase=phase):
                engine, snap, state, action = self.prepare()
                state['pending_results'] = {}
                state['growth'].update(phase=phase, frontier=10, since=100, deaths=0,
                                       retry_requested_at=120, retry_trigger='retry_interval',
                                       **progression_baseline(snap))
                snap['stage']['alivePlayers'] = 1
                result = observe_growth(snap, state, 10000, engine.config)
                self.assertEqual(result['phase'], 'farm')
                self.assertTrue(result['entry_result_pending'])
                self.assertNotIn('retry_requested_at', state['growth'])
                observe_growth(snap, state, 20000, engine.config)
                self.assertEqual(state['growth']['phase'], 'farm')
                state['entry_uncertainty'] = {}
                snap['combat']['current']['elapsed'] = 1
                self.assertEqual(observe_growth(snap, state, 30000, engine.config)['phase'], 'push')

    def test_unrelated_reservation_and_actual_frontier_battle_do_not_override_progress(self):
        for unrelated in (True, False):
            with self.subTest(unrelated=unrelated):
                engine, snap, state, action = self.prepare()
                state['pending_results'] = {}
                state['growth'].update(phase='push', frontier=10, since=100, deaths=0,
                                       **progression_baseline(snap))
                if unrelated:
                    state['entry_uncertainty'][action['key']]['action']['level'] = 20
                else:
                    snap['stage']['level'] = 11
                    snap['combat']['current']['level'] = 11
                result = observe_growth(snap, state, 200, engine.config)
                self.assertEqual(result['phase'], 'push')
                self.assertFalse(result.get('entry_result_pending', False))

    def test_late_arrival_or_clear_releases_reservation_without_inventing_a_second_confirmation(self):
        for cleared in (False, True):
            with self.subTest(cleared=cleared):
                engine, snap, state, action = self.prepare()
                with patch('dps_assistant.engine.time.time', return_value=250):
                    engine.settle_pending('1', {'identity': 'test'}, state, snap)
                state = json.loads(json.dumps(state))
                if cleared:
                    snap['record']['maxCleared'] = 11
                else:
                    snap['stage'].update(level=11, difficulty=0, repeat=False, alivePlayers=1)
                with patch('dps_assistant.engine.time.time', return_value=260):
                    engine.settle_pending('1', {'identity': 'test'}, state, snap)
                self.assertFalse(state['entry_uncertainty'])
                self.assertFalse(state['uncertain'])
                self.assertEqual(state.get('confirmed', 0), 0)

    def test_engine_restart_and_repeated_scans_do_not_resurrect_timed_out_paid_travel(self):
        harness = test_scheduler.SchedulerTests()
        harness.setUp()
        try:
            bridge = harness.add()
            snap, _, config = fixture()
            snap.update(account='1001', sync={})
            snap['stage']['alivePlayers'] = 1
            snap['record']['deaths'] = 0
            value = {'snapshot': snap, 'actions': [], 'issues': []}
            original = bridge.call
            bridge.call = lambda op, args=None: copy.deepcopy(value) if op == 'opportunities' else original(op, args)
            harness.engine.tick('1')
            state = harness.engine.durable['host:1001']
            now = time.time()
            action = paid_action()
            entry = {'action': action, 'at': now - 300, 'cleared_before': 10}
            state.update(uncertain={action['key']: now - 300},
                         pending_results={action['key']: copy.deepcopy(entry)},
                         entry_uncertainty={action['key']: copy.deepcopy(entry)},
                         growth={'phase': 'farm', 'frontier': 10, 'since': now, 'deaths': 0,
                                 **progression_baseline(snap)})
            value['actions'] = [action]
            events = []
            harness.engine.record = lambda *args, **kwargs: events.append((args, kwargs))
            harness.engine.tick('1')
            self.assertFalse(state['pending_results'])
            state = json.loads(json.dumps(state))
            harness.engine.durable['host:1001'] = state
            for _ in range(4):
                harness.engine.tick('1')
            self.assertFalse(state['pending_results'])
            self.assertEqual(state['entry_uncertainty'][action['key']]['at'], now - 300)
            self.assertEqual(len(events), 1)
            self.assertEqual(bridge.commands, [])
            self.assertTrue(harness.engine.config['running'])
        finally:
            harness.tearDown()
