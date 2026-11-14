import copy
import unittest
from dps_assistant.engine import DEFAULT
from dps_assistant.policy import (observe_growth, progression_signature,
                                  ranked_actions, skill_repair_pending)


class SkillRepairCoordinationTests(unittest.TestCase):
    def fixture(self):
        config=copy.deepcopy(DEFAULT)
        snapshot={'loaded':True,'squad':[1], 'characters':[{
            'id':1,'level':30,'points':0,'skills':[{'kind':'passive','skill':'a','level':4}],
            'skillPlanning':{'repair':{'reason':'aligned','excess':0}}}],
            'currencies':{'soul':100,'premium':0},'record':{'maxCleared':39,'deaths':0},
            'stage':{'category':0,'level':39,'difficulty':1,'repeat':True},
            'combat':{'available':True,'current':{'level':39,'difficulty':1,'elapsed':1,'result':'InProgress'}}}
        return config,snapshot

    def test_refund_does_not_trigger_growth_retry_until_reinvestment_finishes(self):
        config,snapshot=self.fixture()
        state={'growth':{'phase':'farm','frontier':39,'since':0,'deaths':0,
                         'progress_strength':progression_signature(snapshot)}}
        c=snapshot['characters'][0];c['skills'][0]['level']=3;c['points']=1
        c['skillPlanning']['repair']={'reason':'refund_branch','excess':2}
        growth=observe_growth(snapshot,state,1000,config)
        self.assertEqual(growth['phase'],'farm');self.assertTrue(growth['skill_repair_pending'])
        self.assertNotIn('retry_requested_at',state['growth'])
        c['skillPlanning']['repair']={'reason':'fill_target','excess':0}
        self.assertTrue(skill_repair_pending(snapshot,config))
        c['points']=0;c['skills'][0]['level']=4;c['skills'].append({'kind':'passive','skill':'b','level':1})
        c['skillPlanning']['repair']={'reason':'aligned','excess':0}
        self.assertEqual(observe_growth(snapshot,state,1001,config)['phase'],'push')

    def test_repair_holds_new_challenges_but_keeps_skills_and_recovery_running(self):
        config,snapshot=self.fixture();config['modules']['tower']=True
        snapshot['characters'][0]['skillPlanning']['repair']={'reason':'refund_branch','excess':2}
        actions=[{'kind':'passive_refund','key':'refund','priority':109},
                 {'kind':'sort','key':'sort','priority':108},
                 {'kind':'progress','key':'push','priority':108,'mode':'push'},
                 {'kind':'progress','key':'guard','priority':130,'mode':'guard'},
                 {'kind':'tower_return','key':'return','priority':112},
                 {'kind':'tower','key':'tower','priority':79,'level':1}]
        ranked=ranked_actions({'snapshot':snapshot,'actions':actions},config,{},1000)
        self.assertEqual({a['key'] for a in ranked},{'refund','guard','return'})
        config['modules']['passive']=False
        self.assertFalse(skill_repair_pending(snapshot,config))
        ranked=ranked_actions({'snapshot':snapshot,'actions':actions},config,{},1000)
        self.assertIn('push',{a['key'] for a in ranked})

    def test_reserve_heroes_and_disabled_refund_do_not_hold_frontier(self):
        config,snapshot=self.fixture()
        reserve={'id':2,'points':0,'skillPlanning':{'repair':{'excess':10}}}
        snapshot['characters'].append(reserve)
        self.assertFalse(skill_repair_pending(snapshot,config))
        snapshot['squad']=[2]
        self.assertTrue(skill_repair_pending(snapshot,config))
        config['strategy']['allow_passive_refund']=False
        self.assertFalse(skill_repair_pending(snapshot,config))
