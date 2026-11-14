import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dps_assistant import equipment_stability as stable, policy
import test_scheduler as scheduler
from dps_assistant import engine

scheduler_scan = scheduler.scan


def revision(uid, socket_value=1):
    return json.dumps([uid, 100, [{'index': 0, 'id': 10, 'ability': 'Attack', 'value': socket_value}]])


def fixture():
    snapshot = scheduler_scan()['snapshot']
    snapshot.update(squad=[1, 2], record={'maxCleared': 39, 'maxStage': 40},
                    runes={'learned': 11, 'onlineLearned': 10, 'offlineLearned': 1, 'progressKnown': True},
                    pets={'unlocked': 1}, characters=[{'id': 1, 'level': 30, 'skills': [], 'activeLoadout': []},
                                                     {'id': 2, 'level': 30, 'skills': [], 'activeLoadout': []}])
    snapshot['equipmentContext'] = json.dumps([[1, 0, revision('A')], [1, 1, revision('X')], [2, 0, revision('Z')]])
    return snapshot


def action(snapshot, uid, hero=1, slot=0, socket_value=1):
    previous = next((r for r in json.loads(snapshot['equipmentContext']) if r[:2] == [hero, slot]), None)
    return {'kind': 'equipment', 'key': 'equip:' + uid, 'label': '换装', 'priority': 99,
            'id': hero, 'slot': slot, 'uid': uid, 'previousUid': json.loads(previous[2])[0] if previous else None,
            'itemRevision': revision(uid, socket_value), 'gain': .006}


def prepared(snapshot, state, uid, **kwargs):
    return stable.prepare(action(snapshot, uid, **kwargs), snapshot, state, policy.equipment_growth_signature(snapshot))


def confirm(snapshot, state, uid, **kwargs):
    candidate, reason = prepared(snapshot, state, uid, **kwargs)
    if reason:
        raise AssertionError(reason)
    stable.record_confirmed(state, candidate)
    rows = json.loads(snapshot['equipmentContext'])
    rows = [r for r in rows if r[:2] != [candidate['id'], candidate['slot']]]
    rows.append([candidate['id'], candidate['slot'], candidate['itemRevision']])
    snapshot['equipmentContext'] = json.dumps(sorted(rows))
    return candidate


class EquipmentStabilityTests(unittest.TestCase):
    def test_confirmed_return_is_blocked_after_cooldown_and_survives_restart(self):
        snapshot, state = fixture(), {}
        confirm(snapshot, state, 'B')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scheduler.json'
            path.write_text(json.dumps(state), encoding='utf-8')
            restored = json.loads(path.read_text(encoding='utf-8'))
        value = {'snapshot': snapshot, 'actions': [action(snapshot, 'A'), scheduler_scan()['actions'][0]]}
        self.assertEqual(policy.choose(value, copy.deepcopy(engine.DEFAULT), restored, now=10000)['kind'], 'rune')
        self.assertEqual(prepared(snapshot, restored, 'A')[1], 'equipment_cycle')
        self.assertEqual(len(restored['equipment_stability']['visited']), 2)

    def test_cross_slot_and_cross_character_cycle_is_blocked_but_new_synergy_allowed(self):
        snapshot, state = fixture(), {}
        confirm(snapshot, state, 'B')
        confirm(snapshot, state, 'Y', slot=1)
        confirm(snapshot, state, 'W', hero=2)
        confirm(snapshot, state, 'A')  # A with new other gear is a new full loadout.
        confirm(snapshot, state, 'X', slot=1)
        self.assertEqual(prepared(snapshot, state, 'Z', hero=2)[1], 'equipment_cycle')

    def test_real_growth_and_manual_equipment_changes_reopen_evaluation(self):
        for change in ('level', 'skill', 'loadout', 'rune', 'pet', 'frontier', 'maxStage', 'formation', 'manual', 'socket'):
            with self.subTest(change=change):
                snapshot, state = fixture(), {}
                confirm(snapshot, state, 'B')
                if change == 'level': snapshot['characters'][0]['level'] += 1
                if change == 'skill': snapshot['characters'][0]['skills'] = [{'kind': 'passive', 'skill': 'health', 'level': 1}]
                if change == 'loadout': snapshot['characters'][0]['activeLoadout'] = ['strike']
                if change == 'rune': snapshot['runes'].update(learned=12, onlineLearned=11)
                if change == 'pet': snapshot['pets']['unlocked'] += 1
                if change == 'frontier': snapshot['record']['maxCleared'] += 1
                if change == 'maxStage': snapshot['record']['maxStage'] += 1
                if change == 'formation': snapshot['squad'].reverse()
                if change in ('manual', 'socket'):
                    rows = json.loads(snapshot['equipmentContext'])
                    rows[1][2] = revision('MANUAL' if change == 'manual' else 'X', 2)
                    snapshot['equipmentContext'] = json.dumps(rows)
                self.assertIsNone(prepared(snapshot, state, 'A')[1])

    def test_temporary_battle_offline_growth_and_bench_changes_do_not_reset_history(self):
        snapshot, state = fixture(), {}
        confirm(snapshot, state, 'B')
        snapshot.update(stage={'level': 35, 'wave': 20}, combat={'dps': 999}, currencies={'soul': 3000000})
        snapshot['runes'].update(learned=12, offlineLearned=2)
        snapshot['pets']['equipped'] = 'different-appearance'
        snapshot['characters'].append({'id': 9, 'level': 101, 'equipment': [{'uid': 'bench'}]})
        self.assertEqual(prepared(snapshot, state, 'A')[1], 'equipment_cycle')

    def test_candidate_socket_revision_allows_same_uid_with_changed_effect(self):
        snapshot, state = fixture(), {}
        confirm(snapshot, state, 'B')
        self.assertIsNone(prepared(snapshot, state, 'A', socket_value=2)[1])
        self.assertEqual(prepared(snapshot, state, 'A')[1], 'equipment_cycle')

    def test_legacy_and_initial_empty_loadout_remain_eligible(self):
        snapshot, state = fixture(), {}
        legacy = action(snapshot, 'B'); legacy.pop('itemRevision')
        self.assertEqual(stable.prepare(legacy, snapshot, state, 'g'), (legacy, None))
        stable.record_confirmed(state, legacy)
        self.assertNotIn('equipment_stability', state)
        snapshot['equipmentContext'] = '[]'
        self.assertIsNone(prepared(snapshot, state, 'starter')[1])

    def test_corrupt_or_stale_metadata_waits_without_recording_success(self):
        for context in ('bad json', 'null', '[[1,0,"bad"]]', '[[1,0,"a"],[1,0,"b"]]'):
            snapshot = fixture(); candidate = action(snapshot, 'B'); snapshot['equipmentContext'] = context
            self.assertEqual(stable.prepare(candidate, snapshot, {}, 'g')[1], 'equipment_context_unavailable')
        snapshot = fixture(); candidate = action(snapshot, 'B'); candidate['previousUid'] = 'changed'
        self.assertEqual(stable.prepare(candidate, snapshot, {}, 'g')[1], 'equipment_context_unavailable')

    def test_history_limit_keeps_earliest_state_until_real_growth(self):
        snapshot, state = fixture(), {}
        for n in range(stable.HISTORY_LIMIT - 1): confirm(snapshot, state, str(n))
        self.assertEqual(len(state['equipment_stability']['visited']), stable.HISTORY_LIMIT)
        self.assertEqual(prepared(snapshot, state, 'new')[1], 'equipment_history_full')
        self.assertEqual(prepared(snapshot, state, 'A')[1], 'equipment_cycle')
        snapshot['characters'][0]['level'] += 1
        confirm(snapshot, state, 'new')
        self.assertEqual(len(state['equipment_stability']['visited']), 2)

    def test_both_independent_ui_summaries_show_waiting(self):
        snapshot, state = fixture(), {}
        confirm(snapshot, state, 'B')
        summary = {'id': 1, 'planned': 1, 'status': 'upgrade_ready', 'slotDetails': [{'slot': 0, 'status': 'upgrade_ready'}]}
        snapshot['equipmentPlanning'] = [summary]
        snapshot['characters'][0]['equipmentPlanning'] = copy.deepcopy(summary)
        value = {'snapshot': snapshot, 'actions': [action(snapshot, 'A')]}
        self.assertEqual(policy.equipment_planning_status(value, state)['waiting'], 1)
        for detail in (summary, snapshot['characters'][0]['equipmentPlanning']):
            self.assertEqual(detail['planned'], 0)
            self.assertEqual(detail['status'], 'stability_wait')
            self.assertEqual(detail['slotDetails'][0]['status'], 'stability_wait')


class EquipmentSettlementTests(unittest.TestCase):
    setUp = scheduler.SchedulerTests.setUp
    tearDown = scheduler.SchedulerTests.tearDown
    add = scheduler.SchedulerTests.add


def _settlement_test(self, outcome):
    bridge = self.add(); snapshot = fixture(); value = {'snapshot': snapshot, 'actions': [action(snapshot, 'B')], 'issues': []}
    original = bridge.call
    def call(op, args=None):
        if op == 'opportunities': return copy.deepcopy(value)
        if op == 'execute':
            bridge.commands.append(args)
            saved = json.loads((engine.DATA / 'scheduler.json').read_text(encoding='utf-8'))
            self.assertIn('equipmentStability', saved['host:1001']['pending_results'][args['key']]['action'])
            if outcome == 'lost': raise TimeoutError('lost equipment reply')
            return {'status': outcome}
        return original(op, args)
    bridge.call = call
    self.engine.tick('1'); state = self.engine.durable['host:1001']
    if outcome == 'confirmed':
        self.assertEqual(len(state['equipment_stability']['visited']), 2)
    else:
        self.assertNotIn('equipment_stability', state)
    if outcome in ('pending', 'lost'):
        value['actions'] = [action(snapshot, 'C'), scheduler_scan()['actions'][0]]
        self.assertEqual(policy.choose(value, self.engine.config, state)['kind'], 'rune')
        snapshot['characters'][0]['equipment'] = [{'slot': 0, 'uid': 'B'}]
        self.engine.settle_pending('1', self.engine.instances['1'], state, snapshot)
        self.assertEqual(len(state['equipment_stability']['visited']), 2)
        self.engine.settle_pending('1', self.engine.instances['1'], state, snapshot)
        self.assertEqual(len(state['equipment_stability']['visited']), 2)
    if outcome in ('rejected', 'stale'):
        self.assertFalse(state.get('pending_results'))
    self.assertTrue(self.engine.config['running'])


for _outcome in ('confirmed', 'pending', 'lost', 'rejected', 'stale'):
    setattr(EquipmentSettlementTests, 'test_native_' + _outcome,
            lambda self, outcome=_outcome: _settlement_test(self, outcome))


def _unconfirmed_replan(self, manual_change):
    bridge = self.add(); snapshot = fixture(); value = {'snapshot': snapshot, 'actions': [action(snapshot, 'B')], 'issues': []}
    original = bridge.call
    def call(op, args=None):
        if op == 'opportunities': return copy.deepcopy(value)
        if op == 'execute':
            bridge.commands.append(args)
            raise TimeoutError('lost equipment reply without native confirmation')
        return original(op, args)
    bridge.call = call
    self.engine.tick('1'); state = self.engine.durable['host:1001']; pending = next(iter(state['pending_results'].values()))
    snapshot['characters'][0]['equipment'] = [{'slot': 0, 'uid': 'manual' if manual_change else 'A'}]
    with patch.object(engine.time, 'time', return_value=pending['at']+29):
        self.engine.settle_pending('1', self.engine.instances['1'], state, snapshot)
    self.assertTrue(state['pending_results'])
    with patch.object(engine.time, 'time', return_value=pending['at']+31):
        self.engine.settle_pending('1', self.engine.instances['1'], state, snapshot)
    self.assertFalse(state['pending_results']); self.assertFalse(state['uncertain'])
    self.assertNotIn('equipment_stability', state)
    self.assertTrue(self.engine.config['running'])
    self.assertEqual(self.engine.events[-1]['result']['reason'], 'equipment_unconfirmed_replan')

EquipmentSettlementTests.test_lost_unapplied_reply_replans_after_wait = lambda self: _unconfirmed_replan(self, False)
EquipmentSettlementTests.test_lost_reply_respects_later_manual_change = lambda self: _unconfirmed_replan(self, True)
