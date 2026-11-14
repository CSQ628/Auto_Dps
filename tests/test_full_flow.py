"""Whole scheduler paths: post-story growth and uncertain travel recovery."""
import base64
import copy
import hashlib
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from dps_assistant import engine, storage
from dps_assistant.combat import observe_combat
from dps_assistant.completion import milestones
from dps_assistant.policy import choose, observe_growth
from dps_assistant.training import observe_farming
from dps_assistant.transitions import stage_transition


def snapshot():
    return {'account': 'fixture', 'loaded': True, 'currencies': {'soul': 100, 'premium': 2},
            'record': {'maxCleared': 160, 'maxStage': 160, 'towerMaxCleared': 1,
                       'deaths': 0, 'normalClears': 10, 'normalFails': 0},
            'catalogue': {'normalMax': 160, 'towerMax': 20, 'characterMax': 101},
            'stage': {'category': 0, 'level': 159, 'difficulty': 0, 'running': True,
                      'ending': False, 'repeat': True, 'alivePlayers': 1},
            'squad': [1], 'characters': [{'id': 1, 'level': 80, 'expTotal': 100}],
            'connection': {'online': True}, 'sync': {}, 'experienceBlocked': False,
            'battleReadiness': {'known': True, 'charactersInitialized': True, 'expected': 1,
                                'missing': [], 'arrangedCount': 1, 'syncRunning': False,
                                'syncPending': False, 'timeScale': 1},
            'progression': {'farmCandidates': [{'level': n, 'difficulty': 0} for n in (159, 158)]}}


def travel(kind='progress', paid=False):
    return {'kind': kind, 'mode': 'boss' if paid else 'farm', 'phase': 'travel',
            'key': kind + (':paid' if paid else ':free'), 'label': '切场',
            'level': 2 if kind == 'tower' else 159, 'difficulty': 0,
            'repeat': False if paid else True, 'freeEntry': not paid,
            'ticket': 123 if paid else 0, 'priority': 107}


class PostStoryTests(unittest.TestCase):
    def test_completed_main_story_enters_stable_endgame_instead_of_retrying_nonexistent_frontier(self):
        snap, state = snapshot(), {}
        for now in (100, 1000, 100000):
            self.assertEqual(observe_growth(snap, state, now)['phase'], 'endgame')
        actions = [travel(), {'kind': 'progress', 'mode': 'push', 'key': 'nonexistent', 'priority': 108}]
        self.assertEqual(choose({'snapshot': snap, 'actions': actions}, engine.DEFAULT, state, 100001)['mode'], 'farm')
        snap['catalogue']['normalMax'] = 170
        self.assertEqual(observe_growth(snap, state, 100002)['phase'], 'push')
        self.assertEqual(choose({'snapshot': snap, 'actions': actions}, engine.DEFAULT, state, 100003)['mode'], 'push')

    def test_endgame_requires_a_valid_native_cap(self):
        for maximum in (None, 0, True, float('inf')):
            snap = snapshot(); snap['catalogue']['normalMax'] = maximum
            self.assertNotEqual(observe_growth(snap, {}, 100)['phase'], 'endgame')

    def test_tower_uses_only_an_ended_main_battle_and_keeps_a_full_main_turn_between_attempts(self):
        tower_config=copy.deepcopy(engine.DEFAULT);tower_config['modules']['tower']=True
        snap, state = snapshot(), {'growth': {'phase': 'endgame'}}
        tower = {'kind': 'tower', 'key': 'tower:2', 'level': 2, 'priority': 79}
        actions = [tower, travel()]
        value = {'snapshot': snap, 'actions': actions}
        self.assertEqual(choose(value, tower_config, state, 100)['kind'], 'progress')
        snap['stage'].update(running=False, ending=True)
        self.assertEqual(choose(value, tower_config, state, 101)['kind'], 'tower')
        state['tower_turn'] = {'waiting': True}
        self.assertEqual(choose(value, tower_config, state, 102)['kind'], 'progress')
        config = copy.deepcopy(tower_config); config['modules']['tower'] = False
        state['tower_turn']['waiting'] = False
        self.assertEqual(choose(value, config, state, 103)['kind'], 'progress')

    def test_existing_tower_returns_even_after_both_modules_are_disabled(self):
        config = copy.deepcopy(engine.DEFAULT)
        config['modules'].update(tower=False, progress=False)
        action = {'kind': 'tower_return', 'key': 'return', 'priority': 112, 'freeEntry': True}
        value = {'snapshot': snapshot(), 'actions': [action]}
        self.assertEqual(choose(value, config, {}, 100)['kind'], 'tower_return')
        config['running'] = False
        self.assertIsNone(choose(value, config, {}, 101))

    def test_endgame_combat_and_experience_remain_valid_farming_observations(self):
        snap, state, config = snapshot(), {'growth': {'phase': 'endgame'}}, copy.deepcopy(engine.DEFAULT)
        config['strategy']['farm_sample_seconds'] = 30
        current = {'level': 159, 'difficulty': 0, 'sequence': 1, 'elapsed': 1, 'result': 'InProgress'}
        snap['combat'] = {'available': True, 'current': current, 'records': []}
        for now in (100, 110, 120, 130):
            snap['characters'][0]['expTotal'] += 10
            current['elapsed'] += 10
            observe_combat(snap, state, 'game', now)
            if now == 130:
                state['battle_observation']['outcomes'].append({'category': 0, 'level': 159, 'difficulty': 0,
                    'sequence': 1, 'result': 'Cleared', 'farming': True, 'started': 100.1, 'observed': now})
            result = observe_farming(snap, state, 'game', now, config)
        self.assertTrue(state['battle_observation']['contexts']['1']['farming'])
        self.assertTrue(result['efficiency']['measurements'][0]['ready'])
        self.assertEqual(result['efficiency']['measurements'][0]['per_minute'], 60)

    def test_nonfinite_boolean_and_negative_milestones_never_claim_completion(self):
        for value in (True, float('nan'), float('inf'), -1):
            snap = {'record': {'maxCleared': value}, 'catalogue': {'normalMax': 1}}
            self.assertFalse(milestones(snap)['items'][0]['known'])


class TravelRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)
        self.patches = [patch.object(engine, 'DATA', self.path), patch.object(storage, 'DATA', self.path)]
        for p in self.patches: p.start()
        self.engine = engine.Engine(start=False)
        self.engine.update({'modules':{'tower':True}})
        self.snap = snapshot()
        self.actions = [travel()]
        self.result = {'status': 'pending'}
        self.commands = []
        outer = self
        class Bridge:
            identity = {'pid': 1, 'created': 1, 'box': '', 'exe': 'DPS.exe'}
            started = time.time()
            process = type('Process', (), {'poll': lambda self: None})()
            def call(self, op, args=None):
                if op == 'opportunities': return {'snapshot': copy.deepcopy(outer.snap), 'actions': outer.actions, 'issues': []}
                if op == 'execute':
                    outer.commands.append(args)
                    # The reservation must already survive an application restart here.
                    persisted = json.loads((outer.path/'scheduler.json').read_text(encoding='utf-8'))['host:fixture']
                    if stage_transition(args): assert args['key'] in persisted['pending_results']
                    if isinstance(outer.result, Exception): raise outer.result
                    return outer.result
                if op == 'backup':
                    output = io.BytesIO()
                    with zipfile.ZipFile(output, 'w') as archive: archive.writestr('save', b'fixture')
                    data = output.getvalue()
                    return {'account': 'fixture', 'zip': base64.b64encode(data).decode(),
                            'sha256': hashlib.sha256(data).hexdigest(), 'files': 1}
                raise AssertionError(op)
            def close(self): pass
            def health(self, timeout=1): return {'phase': 'ready'}
        self.bridge = Bridge()
        self.engine.bridges['1'] = self.bridge
        self.row = {'id': '1', 'status': 'connecting', 'confirmed': 0}
        self.engine.instances['1'] = self.row

    def tearDown(self):
        self.engine.stop()
        for p in reversed(self.patches): p.stop()
        self.folder.cleanup()

    def test_maintenance_wait_and_loaded_login_resume_preserve_uncertain_paid_entry(self):
        self.snap['record']['maxCleared']=159
        self.actions=[{**travel(paid=True),'level':160,'ticketUid':'ticket','ticketBefore':1}]
        self.engine.tick('1')
        state=self.engine.durable['host:fixture'];pending=copy.deepcopy(state['entry_uncertainty'])
        original=self.bridge.call
        native={'ready':False,'maintenance':{'known':True,'active':True,'canExit':False}}
        def scan(op,args=None):
            if op=='opportunities':return {'snapshot':copy.deepcopy(self.snap) if native['ready'] else None,'runtime':copy.deepcopy(native),'actions':self.actions,'issues':[]}
            return original(op,args)
        self.bridge.call=scan
        self.engine.tick('1')
        self.assertEqual(self.row['status'],'maintenance')
        self.assertEqual(state['entry_uncertainty'],pending)
        self.assertEqual(len(self.commands),1)
        native.update(ready=True,maintenance={'known':True,'active':False,'canExit':False})
        self.snap['connection']['loggedIn']=True
        self.engine.tick('1')
        self.assertEqual(self.row['status'],'running')
        self.assertNotIn('maintenance',self.engine.runtime_state[''])
        self.assertEqual(state['entry_uncertainty'],pending)
        self.assertEqual(len(self.commands),1)

    def test_frontier_clear_farming_tower_return_and_next_tower_form_one_continuous_flow(self):
        self.snap['record']['maxCleared'] = 159
        self.snap['stage'].update(level=159, repeat=True)
        boss = travel(paid=True)
        boss.update(level=160, ticketUid='boss-ticket', ticketBefore=1)
        self.actions = [boss]
        self.engine.tick('1')
        self.assertEqual(self.commands[-1]['mode'], 'boss')
        self.snap['record']['maxCleared'] = 160
        self.snap['stage'].update(level=160, running=False, ending=True)
        self.actions = [travel()]
        self.engine.tick('1')
        self.assertEqual(self.row['growth']['phase'], 'endgame')
        self.assertEqual(self.commands[-1]['mode'], 'farm')
        self.snap['stage'].update(level=159, running=True, ending=False, repeat=False)
        self.actions = [{**travel(), 'key': 'repeat', 'phase': 'repeat'}]
        self.result = {'status': 'confirmed'}
        self.engine.tick('1')
        self.assertEqual(self.commands[-1]['phase'], 'repeat')
        self.snap['stage'].update(repeat=True, running=False, ending=True)
        self.actions = [travel('tower')]
        self.result = {'status': 'pending'}
        self.engine.tick('1')
        self.assertEqual(self.commands[-1]['kind'], 'tower')
        self.snap['stage'].update(category=1, level=2, running=True, ending=False, repeat=False)
        self.actions = []
        self.engine.tick('1')
        self.snap['record']['towerMaxCleared'] = 2
        self.snap['stage'].update(running=False, ending=True)
        self.actions = [{**travel(), 'kind': 'tower_return', 'key': 'return'}]
        self.engine.tick('1')
        self.assertEqual(self.commands[-1]['kind'], 'tower_return')
        self.snap['stage'].update(category=0, level=159, running=True, ending=False)
        self.actions = []
        self.engine.tick('1')
        self.assertTrue(self.row['tower_turn']['waiting'])
        self.snap['record']['normalClears'] += 1
        self.snap['stage'].update(running=False, ending=True)
        self.actions = [{**travel('tower'), 'key': 'tower:3', 'level': 3}]
        self.engine.tick('1')
        self.assertEqual(self.commands[-1]['level'], 3)
        self.assertEqual([a['kind'] for a in self.commands],
                         ['progress', 'progress', 'progress', 'tower', 'tower_return', 'tower'])
        self.assertTrue(any(e.get('action', {}).get('kind') == 'boss_clear' for e in self.engine.events))
        self.assertTrue(any(e.get('action', {}).get('kind') == 'tower_clear' for e in self.engine.events))

    def test_lost_free_travel_response_is_reserved_and_a_changed_key_cannot_overlap_it(self):
        self.snap['stage']['level'] = 158
        self.result = TimeoutError('response lost after possible travel')
        self.engine.tick('1')
        state = self.engine.durable['host:fixture']
        self.assertIn(travel()['key'], state['pending_results'])
        self.assertFalse(state.get('entry_uncertainty'))
        self.actions = [{**travel(), 'key': 'different-free-key'}]
        self.engine.tick('1')
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(len(self.row['pending_transitions']), 1)
        self.snap['stage']['level'] = 159
        self.actions = []  # Fresh native scan no longer offers the completed travel.
        self.engine.tick('1')
        self.assertFalse(state['pending_results'])
        self.assertEqual(state['features']['progress']['confirmed'], 1)

    def test_timeout_of_free_travel_releases_serialization_but_obeys_retry_cooldown(self):
        self.snap['stage']['level'] = 158
        self.result = TimeoutError('response lost')
        self.engine.tick('1')
        state = self.engine.durable['host:fixture']; key = travel()['key']
        with patch.object(engine.time, 'time', return_value=time.time() + 121):
            self.engine.tick('1')
        self.assertNotIn(key, state['pending_results'])
        self.assertNotIn(key, state['uncertain'])
        self.assertEqual(len(self.commands), 1)

    def test_definitive_native_refusal_releases_reservation_without_confirmation(self):
        self.result = {'status': 'waiting', 'reason': 'native_squad_transition_active'}
        self.engine.tick('1')
        state = self.engine.durable['host:fixture']
        self.assertFalse(state['pending_results'])
        self.assertFalse(state['uncertain'])
        self.assertEqual(state.get('confirmed', 0), 0)

    def test_fast_clear_between_scans_proves_paid_arrival_without_replaying_a_new_ticket(self):
        self.snap['record']['maxCleared'] = 158
        self.actions = [travel(paid=True)]
        self.actions[0].update(ticketUid='ticket', ticketBefore=3)
        self.engine.tick('1')
        state = self.engine.durable['host:fixture']; key = self.actions[0]['key']
        self.assertEqual(state['pending_results'][key]['cleared_before'], 158)
        self.snap['record']['maxCleared'] = 159
        self.snap['stage'].update(level=160, running=False, alivePlayers=0)
        self.actions = []
        self.engine.tick('1')
        self.assertFalse(state['pending_results'])
        self.assertFalse(state['entry_uncertainty'])
        self.assertEqual(state['features']['progress']['confirmed'], 1)
        self.assertEqual(len(self.commands), 1)

    def test_unknown_paid_timeout_keeps_target_reserved_across_application_restart(self):
        self.snap['record']['maxCleared'] = 158
        action = travel(paid=True); action.update(ticketUid='ticket', ticketBefore=3)
        self.actions = [action]; self.result = TimeoutError('unknown paid result')
        self.engine.tick('1')
        state = self.engine.durable['host:fixture']
        with patch.object(engine.time, 'time', return_value=time.time() + 121): self.engine.tick('1')
        self.assertFalse(state['pending_results'])
        self.assertIn(action['key'], state['entry_uncertainty'])
        restarted = engine.Engine(start=False)
        try:
            self.assertIn(action['key'], restarted.durable['host:fixture']['entry_uncertainty'])
            value = {'snapshot': self.snap, 'actions': [{**action, 'key': 'new-ticket'}]}
            self.assertIsNone(choose(value, restarted.config, restarted.durable['host:fixture'], time.time()+10000))
        finally: restarted.stop()

    def test_legacy_free_travel_reservation_is_migrated_and_cannot_stick_forever(self):
        self.actions = []
        self.engine.tick('1')
        state = self.engine.durable['host:fixture']
        self.snap['stage']['level'] = 158
        self.actions = [travel()]
        state['uncertain'][travel()['key']] = time.time() - 121
        self.engine.tick('1')
        self.assertFalse(state.get('pending_results'))
        self.assertFalse(state['uncertain'])
        self.assertEqual(self.commands, [])
        self.assertGreater(state['cooldowns'][travel()['key']], time.time())

    def test_unentered_free_tower_timeout_can_retry_after_cooldown(self):
        self.actions = [travel('tower')]
        self.snap['stage'].update(running=False, ending=True)
        self.result = TimeoutError('free tower response lost')
        self.engine.tick('1')
        state = self.engine.durable['host:fixture']
        self.assertIn('tower_attempt', state)
        with patch.object(engine.time, 'time', return_value=time.time() + 121): self.engine.tick('1')
        self.assertNotIn('tower_turn', state)
        self.assertNotIn('tower_attempt', state)
        self.assertFalse(state['uncertain'])

    def test_paid_entry_metadata_commits_once_and_save_failure_is_proven_unsent(self):
        self.actions=[];self.engine.tick('1')
        state=self.engine.durable['host:fixture']
        self.snap['record']['maxCleared']=158
        action=travel(paid=True);action.update(ticketUid='ticket',ticketBefore=3)
        self.actions=[action]
        with patch.object(self.engine,'save',side_effect=OSError('disk busy')):self.engine.tick('1')
        self.assertEqual(self.commands,[])
        self.assertFalse(state.get('uncertain'))
        self.assertFalse(state.get('entry_uncertainty'))
        self.assertFalse(state.get('pending_results'))
        self.assertNotIn('boss_attempt',state)
        saved=[];original=self.engine.save
        def save():
            saved.append(copy.deepcopy(state));original()
        with patch.object(self.engine,'save',side_effect=save):self.engine.tick('1')
        self.assertEqual(len(self.commands),1)
        pre_submit=[s for s in saved if s.get('boss_attempt')]
        # The sole pre-native commit contains the paid hold and boss bookkeeping together.
        self.assertTrue(pre_submit)
        self.assertIn(action['key'],saved[0]['pending_results'])
        self.assertIn(action['key'],saved[0]['entry_uncertainty'])
        self.assertEqual(saved[0]['boss_attempt']['ticketBefore'],3)
        self.assertEqual(len(saved),2)  # One pre-native commit, one result commit.

    def test_unsent_tower_save_failure_restores_turn_and_attempt_then_retries(self):
        self.actions=[];self.engine.tick('1')
        self.snap['stage'].update(running=False,ending=True)
        self.actions=[travel('tower')]
        with patch.object(self.engine,'save',side_effect=OSError('disk busy')):self.engine.tick('1')
        state=self.engine.durable['host:fixture']
        self.assertEqual(self.commands,[])
        self.assertFalse(state.get('uncertain'))
        self.assertNotIn('tower_turn',state)
        self.assertNotIn('tower_attempt',state)
        self.engine.tick('1')
        self.assertEqual(len(self.commands),1)
        self.assertEqual(self.commands[0]['kind'],'tower')
        self.assertTrue(state['tower_turn']['waiting'])
