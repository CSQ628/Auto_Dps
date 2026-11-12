import copy
import unittest

from dps_assistant.engine import DEFAULT, Engine
from dps_assistant.policy import choose
from dps_assistant.recovery import observe_battle_readiness


def snapshot():
    return {'loaded': True, 'stage': {'category': 0, 'level': 1, 'difficulty': 0, 'alivePlayers': 0, 'running': True},
            'squad': [400001], 'currencies': {}, 'battleReadiness': {'known': True, 'charactersInitialized': True,
            'expected': 1, 'missing': [400001], 'arrangedCount': 0, 'syncRunning': False, 'syncPending': False,
            'ending': False, 'enterSequence': 1}}


def actions():
    return [{'kind': 'battle_recover', 'key': mode, 'mode': mode, 'priority': 145, 'freeEntry': True, 'label': '恢复战场', 'category': 0, 'level': 1} for mode in ('sync', 'stage')]


class RecoveryTests(unittest.TestCase):
    def test_stable_empty_scene_waits_then_syncs_before_reentering_same_stage(self):
        s, state = snapshot(), {}
        scan = {'snapshot': s, 'actions': actions()}
        observe_battle_readiness(s, state, 'game', 100)
        self.assertIsNone(choose(scan, DEFAULT, state, 129))
        self.assertEqual(choose(scan, DEFAULT, state, 130)['mode'], 'sync')
        state['battle_recovery'].update(attempts=1, last_attempt=130)
        self.assertIsNone(choose(scan, DEFAULT, state, 219))
        self.assertEqual(choose(scan, DEFAULT, state, 220)['mode'], 'stage')

    def test_deaths_loading_transitions_and_unknown_readiness_never_trigger_recovery(self):
        for field, value in [('arrangedCount', 1), ('syncRunning', True), ('syncPending', True),
                             ('known', False), ('charactersInitialized', False), ('expected', 0)]:
            with self.subTest(field=field):
                s, state = snapshot(), {}
                s['battleReadiness'][field] = value
                self.assertFalse(observe_battle_readiness(s, state, 'game', 100)['eligible'])
                self.assertIsNone(choose({'snapshot': s, 'actions': actions()}, DEFAULT, state, 1000))
        for category, alive in [(1, 0), (0, 1)]:
            s = snapshot();s['stage'].update(category=category, alivePlayers=alive)
            self.assertFalse(observe_battle_readiness(s, {}, 'game', 100)['eligible'])

    def test_recovered_hero_clears_watchdog_and_empty_squad_prioritizes_formation(self):
        s, state = snapshot(), {}
        observe_battle_readiness(s, state, 'game', 100)
        s['stage']['alivePlayers'] = 1;s['battleReadiness'].update(missing=[], arrangedCount=1)
        self.assertFalse(observe_battle_readiness(s, state, 'game', 150)['eligible'])
        self.assertNotIn('battle_recovery', state)
        s['battleReadiness'].update(expected=0)
        scan = {'snapshot': s, 'actions': [
            {'kind': 'formation', 'key': 'arrange', 'priority': 142},
            {'kind': 'tower', 'key': 'tower', 'priority': 109, 'level': 1},
            {'kind': 'progress', 'key': 'boss', 'mode': 'boss', 'priority': 108}]}
        self.assertEqual(choose(scan, DEFAULT, {}, 200)['kind'], 'formation')

    def test_backlog_allows_free_local_recovery_and_editable_wait_is_used(self):
        s, state = snapshot(), {}
        s['sync'] = {'queue': 101}
        observe_battle_readiness(s, state, 'game', 100)
        config = copy.deepcopy(DEFAULT);config['strategy']['battle_recovery_wait_seconds'] = 10
        self.assertEqual(choose({'snapshot': s, 'actions': actions()}, config, state, 110)['mode'], 'sync')
        config['modules']['ui_cleanup'] = False
        self.assertIsNone(choose({'snapshot': s, 'actions': actions()}, config, state, 111))

    def test_scene_change_restarts_observation_instead_of_recovering_during_loading(self):
        s, state = snapshot(), {}
        observe_battle_readiness(s, state, 'game', 100)
        s['battleReadiness']['enterSequence'] += 1
        observe_battle_readiness(s, state, 'game', 130)
        self.assertIsNone(choose({'snapshot': s, 'actions': actions()}, DEFAULT, state, 140))

    def test_stopped_completed_stage_waits_for_stall_threshold_and_then_uses_stage_mode(self):
        s, state = snapshot(), {}
        s['battleReadiness'].update(missing=[], arrangedCount=1, pendingSpawn=False, timeScale=1)
        s['stage'].update(running=False, wave=10, aliveMonsters=0, alivePlayers=1)
        value=observe_battle_readiness(s,state,'game',100)
        self.assertEqual(value['reason'],'stalled_end')
        self.assertIsNone(choose({'snapshot':s,'actions':actions()},DEFAULT,state,189))
        self.assertEqual(choose({'snapshot':s,'actions':actions()},DEFAULT,state,190)['mode'],'stage')
        s['stage']['wave']+=1
        observe_battle_readiness(s,state,'game',191)
        self.assertIsNone(choose({'snapshot':s,'actions':actions()},DEFAULT,state,200))
        s['battleReadiness']['timeScale']=0
        self.assertFalse(observe_battle_readiness(s,state,'game',201)['eligible'])

    def test_pending_travel_blocks_other_stage_commands_until_actual_arrival(self):
        s, state = snapshot(), {}
        s['battleReadiness'].update(missing=[], arrangedCount=1)
        s['stage']['alivePlayers']=1
        action={'kind':'progress','key':'travel','phase':'travel','level':1,'repeat':True,'label':'练级切场','freeEntry':True}
        state['pending_results']={'travel':{'action':action,'at':10**12}}
        scan={'snapshot':s,'actions':[{'kind':'tower','key':'tower','level':1,'priority':109},
                                     {'kind':'formation','key':'formation','priority':142}]}
        self.assertIsNone(choose(scan,DEFAULT,state,200))

    def test_timeout_clears_unconfirmed_free_travel_but_never_confirms_or_replays_paid_entry(self):
        engine=Engine(start=False);engine.record=lambda *args,**kwargs:None
        try:
            for free in (True,False):
                action={'kind':'progress','key':'travel','phase':'travel','mode':'boss','level':10,
                        'repeat':False,'label':'切场','freeEntry':free}
                state={'pending_results':{'travel':{'action':action,'at':1}},'uncertain':{'travel':1}}
                engine.settle_pending('test',{'identity':'test'},state,snapshot())
                self.assertEqual(state.get('confirmed',0),0)
                self.assertFalse(state['pending_results'])
                self.assertEqual('travel' in state['uncertain'],not free)
        finally:engine.pool.shutdown(wait=True)

    def test_pending_is_confirmed_only_after_a_real_hero_returns(self):
        engine = Engine(start=False)
        engine.record = lambda *args, **kwargs: None
        try:
            action = actions()[0]
            pending = lambda: {'pending_results': {'sync': {'action': action, 'at': 10**12}}, 'uncertain': {'sync': 1}}
            state = pending();row = {'identity': 'test'};s = snapshot()
            engine.settle_pending('test', row, state, s)
            self.assertNotIn('confirmed', state)
            s['battleReadiness'].update(missing=[], arrangedCount=1);s['stage']['alivePlayers'] = 1
            engine.settle_pending('test', row, state, s)
            self.assertEqual(state['confirmed'], 1)
            self.assertEqual(state['pending_results'], {})
        finally:
            engine.pool.shutdown(wait=True)
