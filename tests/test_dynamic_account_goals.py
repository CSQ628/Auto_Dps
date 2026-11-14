import copy
import unittest

from dps_assistant.completion import milestones
from dps_assistant.policy import main_story_complete
from test_level_cap_farming import fixture
from dps_assistant.training import observe_farming


class DynamicAccountGoalsTests(unittest.TestCase):
    def test_interleaved_players_use_their_own_native_targets_and_formation(self):
        a={'account':'a','catalogue':{'characterMax':9,'normalMax':30,'towerMax':8},
           'record':{'maxCleared':30},'squad':[1], 'characters':[{'id':1,'level':9}],
           'roster':{'eligibleUnlocked':1,'eligibleTotal':1,'excludedDlc':1}}
        b={'account':'b','catalogue':{'characterMax':140,'normalMax':200,'towerMax':40},
           'record':{'maxCleared':30},'squad':[1,2],
           'characters':[{'id':1,'level':108},{'id':2,'level':4},{'id':3,'level':1}],
           'roster':{'eligibleUnlocked':1,'eligibleTotal':4,'excludedDlc':0}}
        before=copy.deepcopy((a,b))
        for _ in range(4):
            for snap,current,target,finished in [(a,9,9,True),(b,4,140,False)]:
                rows={r['id']:r for r in milestones(snap)['automation_items']}
                self.assertEqual((rows['level']['current'],rows['level']['target']), (current,target))
                self.assertEqual(rows['level']['met'],finished)
                self.assertEqual(main_story_complete(snap),finished)
        self.assertEqual((a,b),before)

    def test_native_goal_expansion_and_roster_unlock_are_recomputed(self):
        snap={'catalogue':{'characterMax':9,'normalMax':30},'record':{'maxCleared':30},
              'squad':[1],'characters':[{'id':1,'level':9}]}
        self.assertTrue(main_story_complete(snap))
        snap['catalogue'].update(characterMax=14,normalMax=40)
        snap['characters'].append({'id':2,'level':1})
        result=milestones(snap);raw={r['id']:r for r in result['items']};auto={r['id']:r for r in result['automation_items']}
        self.assertFalse(main_story_complete(snap));self.assertEqual(raw['level']['current'],1)
        self.assertEqual((auto['level']['current'],auto['level']['target']),(9,14))
        self.assertFalse(auto['level']['met']);snap['squad'].append(2)
        self.assertEqual(next(r for r in milestones(snap)['automation_items'] if r['id']=='level')['current'],1)

    def test_farming_cache_and_cap_scope_do_not_leak_between_player_states(self):
        a,sa,config=fixture((9,),9);b,sb,_=fixture((140,108),140)
        for now in [100,110,120]:
            ra=observe_farming(a,sa,'process-a',now,config)
            rb=observe_farming(b,sb,'process-b',now,config)
            self.assertTrue(ra['efficiency']['all_at_cap'])
            self.assertEqual(ra['efficiency']['levelling_characters'],[])
            self.assertFalse(rb['efficiency']['all_at_cap'])
            self.assertEqual(rb['efficiency']['levelling_characters'],[2])
        self.assertIsNot(sa['farm_efficiency'],sb['farm_efficiency'])

    def test_missing_native_caps_never_borrow_the_other_players_goals(self):
        populated={'catalogue':{'characterMax':9},'squad':[1],'characters':[{'id':1,'level':9}]}
        milestones(populated)
        result=milestones({'squad':[1],'characters':[{'id':1,'level':108}]})
        row=next(r for r in result['automation_items'] if r['id']=='level')
        self.assertIsNone(row['target']);self.assertFalse(row['known']);self.assertFalse(row['met'])
