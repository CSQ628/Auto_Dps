import copy
import json
import unittest

from dps_assistant.engine import Engine
from dps_assistant.policy import observe_growth, progression_signature, ranked_actions
from dps_assistant.training import observe_experience, observe_farming
from test_farm_efficiency import fixture


class ScanIsolationTests(unittest.TestCase):
    def prepare(self):
        snap, state, config = fixture()
        snap['record']['deaths'] = 0
        snap['characters'][0].update(exp=0, expNext=100)
        state['growth'].update(frontier=10, since=100, deaths=0, progress_strength=progression_signature(snap))
        return snap, state, config

    def test_missing_strength_keeps_growth_baseline_and_pending_retry(self):
        snap, state, config = self.prepare()
        state['growth'].update(retry_requested_at=120, retry_trigger='party_growth')
        saved = copy.deepcopy(state)
        snap['planningUnavailable'] = {'runes': 'read_failed'}
        snap['characters'][0]['equipment'] = [{'slot': 0, 'uid': 'incomplete'}]
        result = observe_growth(snap, state, 1000, config)
        self.assertEqual(state, saved)
        self.assertFalse(result.get('observation_available', True))
        self.assertEqual(result['phase'], 'farm')

    def test_incomplete_strength_does_not_create_a_false_sample_epoch(self):
        snap, state, config = self.prepare()
        observe_farming(snap, state, 'game', 100, config)
        observe_experience(snap, state, 'game', 100, config)
        snap['characters'][0]['expTotal'] += 10
        observe_farming(snap, state, 'game', 110, config)
        previous = copy.deepcopy(state['farm_efficiency'])
        snap['planningUnavailable'] = {'workshop': 'read_failed'}
        snap['characters'][0]['expTotal'] += 1000
        self.assertIsNone(observe_farming(snap, state, 'game', 115, config))
        self.assertFalse(observe_experience(snap, state, 'game', 115, config)['available'])
        self.assertEqual(state['farm_efficiency']['identity'], previous['identity'])
        self.assertEqual(state['farm_efficiency']['stages'], previous['stages'])
        self.assertNotIn('last', state['farm_efficiency'])
        self.assertNotIn('experience_observation', state)
        snap.pop('planningUnavailable')
        result = observe_farming(snap, state, 'game', 120, config)
        self.assertEqual(state['farm_efficiency']['stages'], previous['stages'])
        self.assertEqual(result['efficiency']['measurements'][0]['gained'], 10)

    def test_scheduler_refuses_stale_challenges_and_keeps_independent_growth(self):
        snap, state, config = self.prepare()
        snap['planningUnavailable'] = {'runes': 'read_failed'}
        actions = [dict(kind=kind, key=kind+str(level), mode=mode, phase=phase, level=level, priority=100, label=kind)
                   for kind, mode, phase, level in [('equipment', None, None, 1), ('tower', None, None, 1),
                   ('progress', 'push', 'travel', 11), ('progress', 'farm', 'travel', 9),
                   ('battle_recover', 'stage', None, 10), ('rune', None, None, 1)]]
        for phase in ('push', 'farm'):
            state['growth']['phase'] = phase
            result = ranked_actions({'snapshot': snap, 'actions': actions}, config, state, 150)
            self.assertEqual([a['kind'] for a in result], ['rune'])

    def test_deduplicated_warning_and_recovery_survive_scheduler_serialization(self):
        engine = Engine.__new__(Engine)
        events = []
        engine.record = lambda *args, **kwargs: events.append((args, kwargs))
        state = {}
        bad = {'planningUnavailable': {'achievements': 'temporary'}}
        for _ in range(3):
            engine.observe_scan_faults('1', {'identity': 'test'}, state, bad)
            state = json.loads(json.dumps(state))
        self.assertEqual(len(events), 1)
        engine.observe_scan_faults('1', {'identity': 'test'}, state, {})
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1][1]['result']['reason'], 'native_section_recovered')
        engine.observe_scan_faults('1', {'identity': 'test'}, state, bad)
        self.assertEqual(len(events), 3)

    def test_missing_skills_do_not_clear_the_previous_refund_warning(self):
        engine = Engine.__new__(Engine)
        state = {'skill_repair_blocks': {'1': 'native_refund_blocked'}}
        engine.observe_skill_repair_blocks('1', {}, state, {'planningUnavailable': {'characters': 'failed'}})
        self.assertEqual(state['skill_repair_blocks'], {'1': 'native_refund_blocked'})

    def test_unknown_equipment_read_never_releases_an_unconfirmed_swap(self):
        engine = Engine.__new__(Engine)
        _, _, engine.config = self.prepare()
        engine.record = lambda *args, **kwargs: self.fail('unknown equipment was settled')
        state = {'uncertain': {'equip:1': 1}, 'pending_results': {'equip:1': {
            'at': 1, 'action': {'kind': 'equipment', 'key': 'equip:1', 'id': 1, 'slot': 0,
                              'uid': 'new', 'equipmentStability': {'schema': 1}}}}}
        expected = copy.deepcopy(state)
        engine.settle_pending('1', {}, state, {'planningUnavailable': {'equipment': 'failed'},
                                             'characters': [{'id': 1}]})
        self.assertEqual(state, expected)

    def test_whole_engine_keeps_unknown_consumption_and_continues_an_independent_action(self):
        from test_scheduler import SchedulerTests, scan
        harness = SchedulerTests()
        harness.setUp()
        try:
            bridge = harness.add()
            value = scan()
            value['snapshot']['planningUnavailable'] = {'workshop': 'recipe_read'}
            original = bridge.call
            bridge.call = lambda op, args=None: copy.deepcopy(value) if op == 'opportunities' else original(op, args)
            harness.engine.tick('1')
            state = harness.engine.durable['host:1001']
            state.setdefault('uncertain', {})['combine:unknown'] = 1
            value['actions'] = []
            harness.engine.tick('1')
            self.assertIn('combine:unknown', state['uncertain'])
            self.assertEqual(len(bridge.commands), 1)
            self.assertEqual(harness.engine.instances['1']['status'], 'running')
            self.assertTrue(harness.engine.config['running'])
            value['snapshot'].pop('planningUnavailable')
            harness.engine.tick('1')
            self.assertNotIn('combine:unknown', state['uncertain'])
        finally:
            harness.tearDown()

    def test_shared_diagnostics_export_section_names_without_native_exception_text(self):
        from dps_assistant.diagnostics import diagnostics
        value = diagnostics({'instances': [{'snapshot': {'planningUnavailable': {
            'mail': 'private-account-token', 'unknown-private-field': 'secret'}}}]})
        self.assertEqual(value['instances'][0]['unavailable_planning_sections'], ['mail'])
        self.assertNotIn('private', json.dumps(value))
        self.assertNotIn('secret', json.dumps(value))
