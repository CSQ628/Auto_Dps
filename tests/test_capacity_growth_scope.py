import copy
import json
import unittest

from dps_assistant.policy import (choose,observe_growth,progression_baseline,progression_signature,strength_signature)
from dps_assistant.training import observe_farming,observe_experience
from test_online_rune_growth import fixture


def scoped(snapshot):
    snapshot['runes']['battleScope']={'schema':1,'policy':'online_without_storage_capacity',
                                     'signature':json.dumps([[1,3],[2,2],[6,0]],separators=(',',':'))}


class CapacityGrowthScopeTests(unittest.TestCase):
    def test_storage_expansion_keeps_farming_measurements_and_the_main_retry_clock(self):
        snap,state,config=fixture();scoped(snap);state['growth'].update(progression_baseline(snap))
        observe_farming(snap,state,'game',100,config)
        snap['characters'][0]['expTotal']+=10;observe_farming(snap,state,'game',110,config)
        before=strength_signature(snap);snap['runes'].update(learned=16,onlineLearned=11)
        snap['inventory']={'count':10,'capacity':58};snap['characters'][0]['expTotal']+=10
        self.assertEqual(strength_signature(snap),before)
        result=observe_farming(snap,state,'game',120,config)
        self.assertEqual(result['efficiency']['measurements'][0]['observed_seconds'],20)
        self.assertEqual(result['efficiency']['measurements'][0]['gained'],20)
        self.assertEqual(observe_growth(snap,state,280,config)['phase'],'farm')
        self.assertEqual(observe_growth(snap,state,700,config)['retry_trigger'],'retry_interval')

    def test_capacity_growth_preserves_the_live_experience_segment(self):
        snap,state,config=fixture();scoped(snap)
        snap['characters'][0].update(exp=100,expNext=1000)
        observe_experience(snap,state,'game',100,config)
        snap['characters'][0]['expTotal']+=10;observe_experience(snap,state,'game',110,config)
        snap['runes'].update(learned=16,onlineLearned=11);snap['characters'][0]['expTotal']+=10
        result=observe_experience(snap,state,'game',120,config)
        self.assertEqual(result['observed_seconds'],20)
        self.assertEqual(result['characters'][0]['gained'],20)

    def test_real_battle_or_experience_growth_still_invalidates_and_retries(self):
        snap,state,config=fixture();scoped(snap);state['growth'].update(progression_baseline(snap))
        observe_farming(snap,state,'game',100,config)
        snap['characters'][0]['expTotal']+=10;observe_farming(snap,state,'game',110,config)
        snap['runes']['battleScope']['signature']='[[1,4],[2,2],[6,0]]'
        result=observe_farming(snap,state,'game',120,config)
        self.assertEqual(result['efficiency']['measurements'],[])
        self.assertEqual(observe_growth(snap,state,280,config)['retry_trigger'],'party_growth')

    def test_detailed_scope_migration_preserves_an_existing_frontier_finish_wait(self):
        snap,state,config=fixture()
        state['growth'].update(retry_requested_at=250,retry_trigger='party_growth')
        snap['combat']['current']['elapsed']=80;scoped(snap)
        result=observe_growth(snap,state,280,config)
        self.assertEqual(state['growth']['retry_requested_at'],250)
        self.assertEqual(state['growth']['since'],100);self.assertTrue(result['retry_pending'])
        self.assertEqual(state['growth']['rune_strength_scope'],'battle_nodes_v1')
        restored=copy.deepcopy(state);observe_growth(snap,restored,290,config)
        self.assertEqual(restored['growth']['retry_requested_at'],250)

    def test_detailed_scope_keeps_tower_cooldown_through_migration_and_capacity_growth(self):
        snap,state,config=fixture();config['modules']['tower']=True
        snap['catalogue']={'normalMax':10};snap['record']['maxStage']=10
        snap['stage'].update(running=False,ending=True);state['growth']['phase']='endgame'
        state['tower_attempt']={'level':1,'max_stage':10,'at':100,**progression_baseline(snap)}
        scan={'snapshot':snap,'actions':[{'kind':'tower','key':'tower','level':1,'priority':79}]}
        scoped(snap);self.assertIsNone(choose(scan,config,state,500))
        snap['runes'].update(learned=16,onlineLearned=11)
        self.assertIsNone(choose(scan,config,state,501));self.assertEqual(state['tower_attempt']['at'],100)
        snap['runes']['battleScope']['signature']='[[1,4],[2,2],[6,0]]'
        self.assertIsNotNone(choose(scan,config,state,502))

    def test_node_order_is_irrelevant_but_equal_totals_with_other_investments_are_different(self):
        snap,_,_=fixture();scoped(snap);before=strength_signature(snap)
        snap['runes']['battleScope']['signature']='[[6,0],[2,2],[1,3]]'
        self.assertEqual(strength_signature(snap),before)
        snap['runes']['battleScope']['signature']='[[1,2],[2,3],[6,0]]'
        self.assertNotEqual(strength_signature(snap),before)

    def test_temporarily_missing_detailed_scope_preserves_existing_retry_wait(self):
        snap,state,config=fixture();scoped(snap);state['growth'].update(progression_baseline(snap))
        state['growth'].update(retry_requested_at=250,retry_trigger='party_growth')
        snap['combat']['current']['elapsed']=80;snap['runes'].pop('battleScope')
        self.assertTrue(observe_growth(snap,state,280,config)['retry_pending'])
        self.assertEqual(state['growth']['retry_requested_at'],250)
        self.assertEqual(state['growth']['rune_strength_scope'],'online')
        scoped(snap);observe_growth(snap,state,290,config)
        self.assertEqual(state['growth']['retry_requested_at'],250)

    def test_malformed_or_incomplete_metadata_falls_back_to_existing_online_counts(self):
        snap,_,_=fixture();baseline=progression_signature(snap)
        for bad in ({'schema':2,'policy':'online_without_storage_capacity','signature':'[[1,3]]'},
                    {'schema':1,'policy':'unknown','signature':'[[1,3]]'},
                    {'schema':1,'policy':'online_without_storage_capacity','signature':'not-json'},
                    {'schema':1,'policy':'online_without_storage_capacity','signature':'[[1,3],[1,2]]'},
                    {'schema':1,'policy':'online_without_storage_capacity','signature':'[[true,3]]'},
                    {'schema':True,'policy':'online_without_storage_capacity','signature':'[[1,3]]'},
                    *({'schema':1,'policy':'online_without_storage_capacity','signature':value} for value in
                      ['{}','null','[[1,-1]]','[[1,true]]','[[1,3,4]]','[[9007199254740992,1]]','[1,3]',
                       '['*1100+']'*1100,json.dumps([[i+1,0] for i in range(1025)])])):
            snap['runes']['battleScope']=bad
            self.assertEqual(progression_signature(snap),baseline)


if __name__=='__main__':unittest.main()
