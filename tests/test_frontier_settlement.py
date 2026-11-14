import copy
import json
import unittest

from test_farm_efficiency import fixture
from dps_assistant.policy import choose, observe_growth, progression_signature


class FrontierSettlementTests(unittest.TestCase):
    def prepare(self):
        snap, state, config = fixture()
        snap['record'].update(maxCleared=49, deaths=0)
        snap['stage'].update(level=50, difficulty=1, repeat=True)
        snap['combat']['current'].update(level=50, difficulty=1, sequence=717, elapsed=11)
        snap['progression']['farmCandidates']=[{'level':49,'difficulty':1}]
        state['growth'].update(frontier=49,since=1,deaths=0,progress_strength=progression_signature(snap))
        state['battle_observation']={'session':'process-one','outcomes':[]}
        config['strategy']['farm_retry_finish_seconds']=90
        config['strategy']['farm_retry_seconds']=7200
        farm={'kind':'progress','mode':'farm','phase':'travel','key':'farm:49','level':49,'difficulty':1,'freeEntry':True,'priority':107}
        self.scan={'snapshot':snap,'actions':[farm]}
        return snap,state,config

    def test_entered_frontier_waits_even_with_inherited_repeat_and_an_old_farming_clock(self):
        snap,state,config=self.prepare()
        growth=observe_growth(snap,state,100,config)
        self.assertTrue(growth['frontier_return_pending'])
        self.assertIsNone(choose(self.scan,config,state,100))
        snap['combat']['current']['elapsed']=1
        self.assertIsNone(choose(self.scan,config,state,110))

    def test_other_growth_and_repeat_cleanup_continue(self):
        snap,state,config=self.prepare()
        rune={'kind':'rune','key':'rune','priority':94}
        self.scan['actions'].append(rune)
        self.assertEqual(choose(self.scan,config,state,100)['kind'],'rune')
        self.scan['actions'].append({'kind':'progress','mode':'guard','repeat':False,'freeEntry':True,'key':'repeat_off','priority':130})
        self.assertEqual(choose(self.scan,config,state,101)['mode'],'guard')

    def test_bound_is_explicit_and_persisted_only_for_the_same_native_battle(self):
        snap,state,config=self.prepare()
        choose(self.scan,config,state,100)
        state=json.loads(json.dumps(state))
        self.assertIsNone(choose(self.scan,config,state,189))
        action=choose(self.scan,config,state,190)
        self.assertEqual(action['frontierReturn']['sequence'],717)
        self.assertEqual(action['frontierReturn']['waited'],90)
        snap['combat']['current']['sequence']=718
        self.assertIsNone(choose(self.scan,config,state,191))
        self.assertIsNone(choose(self.scan,config,state,280))
        self.assertIsNotNone(choose(self.scan,config,state,281))

    def test_game_restart_and_clock_rollback_reset_the_wait(self):
        for change in ('session','clock'):
            snap,state,config=self.prepare()
            choose(self.scan,config,state,100)
            if change=='session':state['battle_observation']['session']='process-two'
            now=50 if change=='clock' else 200
            self.assertIsNone(choose(self.scan,config,state,now))
            self.assertEqual(state['growth']['frontier_return']['since'],now)

    def test_native_failure_or_leaving_the_frontier_releases_the_farm_return(self):
        for change in ('Failed','Cleared','not_running','cleared_record'):
            snap,state,config=self.prepare()
            choose(self.scan,config,state,100)
            if change in ('Failed','Cleared'):snap['combat']['current']['result']=change
            if change=='not_running':snap['stage']['running']=False
            if change=='cleared_record':snap['record']['maxCleared']=50
            self.assertIsNotNone(choose(self.scan,config,state,101))
            self.assertNotIn('frontier_return',state['growth'])

    def test_frontier_clear_resumes_push_and_removes_old_wait(self):
        snap,state,config=self.prepare()
        observe_growth(snap,state,100,config)
        snap['record']['maxCleared']=50
        self.assertEqual(observe_growth(snap,state,101,config)['phase'],'push')
        self.assertNotIn('frontier_return',state['growth'])

    def test_unreliable_statistics_do_not_invent_an_active_frontier(self):
        for change in ('unavailable','sequence','elapsed','mismatch','tower'):
            snap,state,config=self.prepare()
            if change=='unavailable':snap['combat']['available']=False
            if change=='sequence':snap['combat']['current']['sequence']=True
            if change=='elapsed':snap['combat']['current']['elapsed']=float('nan')
            if change=='mismatch':snap['combat']['current']['level']=49
            if change=='tower':snap['stage']['category']=1
            self.assertIsNotNone(choose(self.scan,config,state,100))
            self.assertNotIn('frontier_return',state['growth'])

    def test_pause_and_progress_module_still_prevent_submission(self):
        for switch in ('running','progress'):
            snap,state,config=self.prepare()
            if switch=='running':config['running']=False
            else:config['modules']['progress']=False
            self.scan['actions'].append({'kind':'progress','mode':'guard','repeat':False,'requiresProgress':True,'freeEntry':True,'key':'repeat_off','priority':130})
            self.assertIsNone(choose(self.scan,config,state,100))


if __name__=='__main__':unittest.main()
