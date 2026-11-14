import copy
import json
import unittest

from dps_assistant.engine import DEFAULT, Engine
from dps_assistant.diagnostics import diagnostics
from dps_assistant.policy import observe_growth, progression_signature, ranked_actions, skill_repair_pending


class RepairContinuationTests(unittest.TestCase):
    def prepare(self):
        config=copy.deepcopy(DEFAULT)
        snapshot={'loaded':True,'squad':[1],'characters':[{'id':1,'level':30,'points':0,
            'skills':[{'kind':'passive','skill':'wrong','level':4}],
            'skillPlanning':{'repair':{'excess':2,'reason':'native_refund_blocked','refund':None}}}],
            'currencies':{'soul':100,'premium':0},'record':{'maxCleared':39,'deaths':0},
            'stage':{'category':0,'level':39,'difficulty':0,'repeat':True},
            'combat':{'available':True,'current':{'level':39,'difficulty':0,'elapsed':1,'result':'InProgress'}}}
        state={'growth':{'phase':'farm','frontier':39,'since':0,'deaths':0,
                         'progress_strength':progression_signature(snapshot)}}
        actions=[{'kind':'progress','key':'push','priority':108,'mode':'push'},
                 {'kind':'tower','key':'tower','priority':79,'level':1},
                 {'kind':'rune','key':'rune','priority':94}]
        return config,snapshot,state,actions

    def test_native_refusal_does_not_permanently_hold_retry_or_other_growth(self):
        config,snapshot,state,actions=self.prepare()
        self.assertFalse(skill_repair_pending(snapshot,config))
        self.assertEqual(observe_growth(snapshot,state,1000,config)['phase'],'push')
        config['modules']['tower']=True
        self.assertEqual({a['key'] for a in ranked_actions({'snapshot':snapshot,'actions':actions},config,state,1000)},
                         {'push','rune'})
        self.assertEqual(snapshot['characters'][0]['skillPlanning']['repair']['excess'],2)

    def test_endgame_tower_still_requires_normal_eligibility_after_refusal(self):
        config,snapshot,state,actions=self.prepare()
        config['modules']['tower']=True
        snapshot['catalogue']={'normalMax':160,'towerMax':20}
        snapshot['record']['maxCleared']=160
        snapshot['stage'].update(level=159,running=False,ending=True)
        state['growth']['phase']='endgame'
        keys={a['key'] for a in ranked_actions({'snapshot':snapshot,'actions':actions},config,state,1000)}
        self.assertIn('tower',keys)
        config['modules']['tower']=False
        self.assertNotIn('tower',{a['key'] for a in ranked_actions({'snapshot':snapshot,'actions':actions},config,state,1000)})

    def test_resumed_actionable_refund_and_reinvestment_hold_new_challenges(self):
        config,snapshot,state,actions=self.prepare()
        repair=snapshot['characters'][0]['skillPlanning']['repair']
        for reason in ('native_refund_blocked','refund_branch'):
            repair.update(reason=reason,refund={'skill':'wrong','level':4})
            self.assertTrue(skill_repair_pending(snapshot,config))
            self.assertEqual(observe_growth(snapshot,state,1000,config)['phase'],'farm')
            keys={a['key'] for a in ranked_actions({'snapshot':snapshot,'actions':actions},config,state,1000)}
            self.assertIn('rune',keys);self.assertNotIn('push',keys)
        repair.update(reason='fill_target',excess=0,refund=None)
        snapshot['characters'][0]['points']=1
        self.assertTrue(skill_repair_pending(snapshot,config))

    def test_refusal_does_not_bypass_pause_or_module_switch(self):
        config,snapshot,state,actions=self.prepare()
        for switch in ('running','progress'):
            current=copy.deepcopy(config)
            if switch=='running':current['running']=False
            else:current['modules']['progress']=False
            keys={a['key'] for a in ranked_actions({'snapshot':snapshot,'actions':actions},current,state,1000)}
            self.assertNotIn('push',keys)

    def reporter(self):
        config,snapshot,state,_=self.prepare()
        engine=Engine.__new__(Engine);engine.config=config;events=[]
        engine.record=lambda instance,status,message,**details:events.append(
            {'instance':instance,'status':status,'message':message,**details})
        return engine,events,snapshot,state

    def test_block_warning_is_persisted_and_deduplicated_without_claiming_a_refund(self):
        engine,events,snapshot,state=self.reporter()
        original=copy.deepcopy(snapshot);config=copy.deepcopy(engine.config)
        for _ in range(3):
            engine.observe_skill_repair_blocks('1',{'identity':'private-account'},state,snapshot)
            state=json.loads(json.dumps(state))
        self.assertEqual(len(events),1);self.assertEqual(events[0]['status'],'warning')
        self.assertEqual(events[0]['result'],{'reason':'native_refund_blocked','automationContinues':True})
        self.assertEqual(snapshot,original);self.assertEqual(engine.config,config)
        self.assertNotIn('confirmed',state);self.assertNotIn('features',state)
        safe=diagnostics({'instances':[{'id':'1','snapshot':snapshot}],'events':events})
        self.assertEqual(safe['instances'][0]['recent_operations'][0]['reason'],'native_refund_blocked')
        self.assertNotIn('private-',json.dumps(safe))

    def test_recovery_or_disabled_control_ends_episode_and_future_block_reports_again(self):
        for change in ('recovery','switch','removed'):
            engine,events,snapshot,state=self.reporter()
            engine.observe_skill_repair_blocks('1',{'identity':'private-account'},state,snapshot)
            original=copy.deepcopy(snapshot)
            if change=='recovery':snapshot['characters'][0]['skillPlanning']['repair']['reason']='aligned'
            elif change=='switch':engine.config['strategy']['allow_passive_refund']=False
            else:snapshot['characters']=[]
            engine.observe_skill_repair_blocks('1',{'identity':'private-account'},state,snapshot)
            self.assertNotIn('skill_repair_blocks',state)
            engine.config['strategy']['allow_passive_refund']=True
            engine.observe_skill_repair_blocks('1',{'identity':'private-account'},state,original)
            self.assertEqual(len(events),2)

    def test_invalid_catalogue_reports_a_distinct_warning_once(self):
        engine,events,snapshot,state=self.reporter()
        snapshot['characters'][0]['skillPlanning']['repair']={'reason':'skill_catalogue_invalid'}
        for _ in range(2):engine.observe_skill_repair_blocks('1',{'identity':'test'},state,snapshot)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['result']['reason'],'skill_catalogue_invalid')
        self.assertFalse(skill_repair_pending(snapshot,engine.config))


if __name__=='__main__':unittest.main()
