import copy
import unittest

from dps_assistant.engine import DEFAULT
from dps_assistant.policy import choose
from dps_assistant.transitions import entry_cleared, entry_conflicts, stage_arrived


class TransitionTests(unittest.TestCase):
    def test_unknown_paid_target_blocks_changed_ticket_key_but_keeps_free_recovery(self):
        action={'kind':'progress','mode':'boss','phase':'travel','key':'boss:10:old',
                'level':10,'difficulty':1,'ticket':690100,'priority':108}
        state={'entry_uncertainty':{action['key']:{'action':action,'at':100}}}
        changed={**action,'key':'boss:10:new'}
        self.assertTrue(entry_conflicts(changed,state))
        free={'kind':'progress','mode':'farm','phase':'travel','level':9,'difficulty':0,
              'freeEntry':True,'key':'farm:9','priority':107}
        snapshot={'loaded':True,'currencies':{}}
        self.assertIsNone(choose({'snapshot':snapshot,'actions':[changed]},DEFAULT,state,200))
        self.assertFalse(entry_conflicts(free,state))
        self.assertEqual(choose({'snapshot':snapshot,'actions':[changed,free]},DEFAULT,
            {**state,'growth':{'phase':'farm'}},200)['key'],'farm:9')

    def test_arrival_requires_correct_category_level_difficulty_and_present_party(self):
        action={'kind':'progress','level':10,'difficulty':1}
        snapshot={'stage':{'category':0,'level':10,'difficulty':1,'running':True,'alivePlayers':1},
                  'battleReadiness':{'known':True,'charactersInitialized':True,'missing':[],
                                     'syncRunning':False,'syncPending':False}}
        self.assertTrue(stage_arrived(action,snapshot))
        for field,value in [('category',1),('level',1),('difficulty',0),('running',False),('alivePlayers',0)]:
            s=copy.deepcopy(snapshot);s['stage'][field]=value
            self.assertFalse(stage_arrived(action,s))
        for field,value in [('known',False),('charactersInitialized',False),('missing',[1]),
                            ('syncRunning',True),('syncPending',True)]:
            s=copy.deepcopy(snapshot);s['battleReadiness'][field]=value
            self.assertFalse(stage_arrived(action,s))

    def test_push_and_boss_arrival_requires_repeats_disabled(self):
        snapshot={'stage':{'category':0,'level':10,'difficulty':0,'running':True,
                           'repeat':True,'alivePlayers':1}}
        for mode in ('push','boss'):
            action={'kind':'progress','mode':mode,'phase':'travel','repeat':False,
                    'level':10,'difficulty':0}
            self.assertFalse(stage_arrived(action,snapshot))
            snapshot['stage']['repeat']=False
            self.assertTrue(stage_arrived(action,snapshot))
            snapshot['stage']['repeat']=True

    def test_main_and_tower_clear_records_are_not_interchangeable(self):
        snap={'record':{'maxCleared':20,'towerMaxCleared':2}}
        self.assertTrue(entry_cleared({'kind':'progress','level':10},snap,9))
        self.assertFalse(entry_cleared({'kind':'tower','level':10},snap,9))
        self.assertTrue(entry_cleared({'kind':'tower','level':2},snap,1))
        self.assertFalse(entry_cleared({'kind':'progress','level':10},snap,10))
        self.assertFalse(entry_cleared({'kind':'progress','level':10},snap,None))
