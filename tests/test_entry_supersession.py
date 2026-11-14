import copy
import json
import unittest
from unittest.mock import patch

from dps_assistant.engine import Engine
from dps_assistant.transitions import observe_entry_supersession
import test_scheduler


def fixture():
    action = {'kind': 'progress', 'phase': 'travel', 'mode': 'boss', 'level': 70,
              'difficulty': 1, 'ticket': 690200, 'ticketUid': 'ticket', 'key': 'entry:70'}
    entry = {'action': action, 'at': 100, 'cleared_before': 69}
    snapshot = {'loaded': True, 'record': {'maxCleared': 69},
                'stage': {'category': 0, 'level': 66, 'difficulty': 1, 'running': True,
                          'alivePlayers': 2, 'repeat': True},
                'battleReadiness': {'known': True, 'charactersInitialized': True,
                                    'expected': 3, 'arrangedCount': 3, 'squadArranged': True,
                                    'missing': [], 'syncRunning': False, 'syncPending': False,
                                    'ending': False, 'enterSequence': 50},
                'entryState': {'known': True, 'observer': 'observer-a', 'sequence': 50,
                               'free': True, 'occupied': False},
                'combat': {'available': True, 'current': {'result': 'InProgress',
                           'level': 66, 'difficulty': 1}}}
    return entry, snapshot


class EntrySupersessionTests(unittest.TestCase):
    def advance(self, snapshot, sequence=51):
        snapshot['entryState']['sequence'] = sequence
        snapshot['battleReadiness']['enterSequence'] = sequence

    def test_two_post_timeout_native_observations_survive_reload_without_success_or_replay(self):
        entry, snap = fixture()
        self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', 250, 120))
        entry = json.loads(json.dumps(entry))
        self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', 10000, 120))
        self.advance(snap)
        result = observe_entry_supersession(entry, snap, '1:1', 10001, 120)
        self.assertEqual(result['reason'], 'native_entry_superseded')
        self.assertEqual(result['sequenceBefore'], 50)
        self.assertEqual(result['sequenceAfter'], 51)
        self.assertNotIn('ticketAfter', result)
        self.assertNotEqual(result.get('status'), 'confirmed')

    def test_elapsed_time_and_ticket_counts_cannot_release_an_unknown_result(self):
        entry, snap = fixture()
        snap['entryTickets'] = [{'uid': 'ticket', 'count': 0}]
        for now in (101, 219, 250, 100000):
            self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', now, 120))

    def test_changed_observer_or_game_lifetime_requires_a_new_anchor_and_transition(self):
        for change in ('observer', 'session'):
            with self.subTest(change=change):
                entry, snap = fixture()
                observe_entry_supersession(entry, snap, '1:1', 250, 120)
                self.advance(snap)
                session = '1:2' if change == 'session' else '1:1'
                if change == 'observer': snap['entryState']['observer'] = 'observer-b'
                self.assertIsNone(observe_entry_supersession(entry, snap, session, 251, 120))
                self.advance(snap, 52)
                self.assertIsNotNone(observe_entry_supersession(entry, snap, session, 252, 120))

    def test_incomplete_occupied_paid_or_unstable_snapshots_never_release(self):
        mutations = [
            ('entryState', 'known', False), ('entryState', 'occupied', True),
            ('entryState', 'free', False), ('entryState', 'sequence', None),
            ('battleReadiness', 'known', False), ('battleReadiness', 'syncRunning', True),
            ('battleReadiness', 'syncPending', True), ('battleReadiness', 'missing', [1]),
            ('battleReadiness', 'ending', True), ('battleReadiness', 'expected', 0),
            ('battleReadiness', 'arrangedCount', 2), ('battleReadiness', 'squadArranged', False),
            ('stage', 'running', False), ('stage', 'alivePlayers', 0),
            ('combat', 'available', False)]
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                entry, snap = fixture()
                observe_entry_supersession(entry, snap, '1:1', 250, 120)
                self.advance(snap)
                snap[section][key] = value
                self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', 251, 120))
        for section in ('entryState', 'battleReadiness', 'stage', 'combat'):
            entry, snap = fixture(); snap.pop(section)
            self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', 250, 120))

    def test_mismatched_battle_readiness_or_incomplete_progression_is_not_proof(self):
        for mutation in ('combat', 'readiness', 'scan'):
            entry, snap = fixture()
            observe_entry_supersession(entry, snap, '1:1', 250, 120)
            self.advance(snap)
            if mutation == 'combat': snap['combat']['current']['level'] = 70
            if mutation == 'readiness': snap['battleReadiness']['enterSequence'] = 50
            if mutation == 'scan': snap['planningUnavailable'] = {'progression': 'fault'}
            self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', 251, 120))

    def test_sequence_reset_and_clock_rollback_do_not_count_as_supersession(self):
        entry, snap = fixture()
        observe_entry_supersession(entry, snap, '1:1', 250, 120)
        self.advance(snap, 1)
        self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', 251, 120))
        self.advance(snap, 2)
        self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', 249, 120))

    def test_own_target_and_completed_battle_are_not_cancellation_evidence(self):
        for mutation in ('target', 'completed'):
            entry, snap = fixture()
            observe_entry_supersession(entry, snap, '1:1', 250, 120)
            self.advance(snap)
            if mutation == 'target':
                snap['stage']['level'] = snap['combat']['current']['level'] = 70
            else: snap['combat']['current']['result'] = 'Cleared'
            self.assertIsNone(observe_entry_supersession(entry, snap, '1:1', 251, 120))

    def test_engine_removes_only_proven_reservation_and_never_counts_it_as_confirmed(self):
        entry, snap = fixture()
        other = copy.deepcopy(entry); other['action'].update(key='tower:3', kind='tower', level=3)
        state = {'entry_uncertainty': {'entry:70': entry, 'tower:3': other},
                 'pending_results': {'entry:70': entry}, 'uncertain': {'entry:70': 100},
                 'boss_attempt': {'level': 70, 'ticketUid': 'ticket'}, 'confirmed': 2}
        engine = Engine.__new__(Engine)
        engine.config = {'strategy': {'stage_transition_wait_seconds': 120}}
        engine.record = lambda *a, **k: events.append((a, k))
        events = []; row = {'identity': 'host:test', 'issues': []}
        with patch('dps_assistant.engine.time.time', return_value=250):
            engine.settle_pending('1', row, state, snap, session='1:1')
        self.advance(snap)
        # An unrelated tower reservation has no matching subsequent witness.
        state['entry_uncertainty']['tower:3'].pop('supersession_anchor', None)
        with patch('dps_assistant.engine.time.time', return_value=251):
            engine.settle_pending('1', row, state, snap, session='1:1')
        self.assertNotIn('entry:70', state['entry_uncertainty'])
        self.assertIn('tower:3', state['entry_uncertainty'])
        self.assertFalse(state['pending_results'])
        self.assertFalse(state['uncertain'])
        self.assertNotIn('boss_attempt', state)
        self.assertEqual(state['confirmed'], 2)
        self.assertEqual(events[-1][1]['result']['reason'], 'native_entry_superseded')

    def test_production_tick_persists_anchor_and_recovers_legacy_entry_after_scheduler_reload(self):
        harness = test_scheduler.SchedulerTests(); harness.setUp()
        try:
            bridge = harness.add(); original = bridge.call
            entry, snap = fixture()
            snap.update(account='1001', sync={}, currencies={'soul': 100})
            value = {'snapshot': snap, 'actions': [], 'issues': []}
            bridge.call = lambda op, args=None: copy.deepcopy(value) if op == 'opportunities' else original(op, args)
            harness.engine.tick('1')
            state = harness.engine.durable['host:1001']
            import time
            entry['at'] = time.time() - 300
            state.update(entry_uncertainty={'entry:70': entry}, pending_results={}, uncertain={'entry:70': entry['at']})
            harness.engine.tick('1')
            self.assertIn('supersession_anchor', entry)
            harness.engine.save()
            from dps_assistant import engine as engine_module, storage
            harness.engine.durable = storage.load_json(engine_module.DATA / 'scheduler.json', {})
            self.advance(snap)
            harness.engine.tick('1')
            recovered = harness.engine.durable['host:1001']
            self.assertFalse(recovered['entry_uncertainty'])
            self.assertFalse(recovered['uncertain'])
            self.assertEqual(bridge.commands, [])
            persisted = storage.load_json(engine_module.DATA / 'scheduler.json', {})
            self.assertFalse(persisted['host:1001']['entry_uncertainty'])
        finally:
            harness.tearDown()


if __name__ == '__main__': unittest.main()
