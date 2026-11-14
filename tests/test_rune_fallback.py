import copy
import unittest
from dps_assistant.engine import DEFAULT
from dps_assistant.parameters import normalize_config
from dps_assistant.policy import ranked_actions


class RuneFallbackTests(unittest.TestCase):
    def test_all_budget_defaults_are_zero_and_explicit_settings_are_still_editable(self):
        config=normalize_config({})
        for candidate in (DEFAULT,config):
            self.assertEqual(candidate['soul_reserve'],0)
            self.assertEqual(candidate['premium_reserve'],0)
            self.assertEqual(candidate['strategy']['skill_point_reserve'],0)
        self.assertEqual(normalize_config({'premium_reserve':7})['premium_reserve'],7)

    def fixture(self):
        return {'snapshot':{'loaded':True,'currencies':{'soul':100,'premium':9}},'actions':[
            {'kind':'rune','key':'offline','header':'OfflineReward','offlineFallback':True,'priority':1,'cost':{'goods':201,'amount':10}},
            {'kind':'rune','key':'online','header':'AttackSpeed','offlineFallback':False,'priority':94,'permanent':True,'cost':{'goods':202,'amount':8}},
            {'kind':'pet_unlock','key':'pet','priority':60}]}

    def test_all_other_eligible_growth_stays_ahead_of_pure_offline_despite_aging(self):
        scan=self.fixture();old=copy.deepcopy(scan)
        state={'scheduling_started':0,'last_module':{'rune':0,'pet_unlock':1000000}}
        self.assertEqual([a['key'] for a in ranked_actions(scan,copy.deepcopy(DEFAULT),state,1000000)],['online','pet','offline'])
        self.assertEqual(scan,old)

    def test_fallback_runs_when_ordinary_choices_are_cooling_down_and_remains_budget_checked(self):
        scan=self.fixture();config=copy.deepcopy(DEFAULT)
        state={'cooldowns':{'online':200,'pet':200}}
        self.assertEqual(ranked_actions(scan,config,state,100)[0]['key'],'offline')
        config['soul_reserve']=95;self.assertEqual(ranked_actions(scan,config,state,100),[])
        config['soul_reserve']=0;state['uncertain']={'offline':100}
        self.assertEqual(ranked_actions(scan,config,state,100),[])

    def test_offline_node_for_an_online_prerequisite_keeps_ordinary_growth_rank(self):
        scan=self.fixture();scan['actions'][0].update(offlineFallback=False,priority=95,planningReason='minimum_prerequisite')
        self.assertEqual(ranked_actions(scan,copy.deepcopy(DEFAULT),{},100)[0]['key'],'offline')


if __name__=='__main__':unittest.main()
