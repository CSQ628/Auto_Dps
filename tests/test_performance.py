import copy
import math
import unittest

from dps_assistant.performance import observe_scan_cost
from dps_assistant.training import observe_experience


class ScanPerformanceTests(unittest.TestCase):
    def test_expensive_scan_backs_off_and_cheap_scan_recovers_gradually(self):
        row={}
        observe_scan_cost(row,{'scanMs':200,'nativeCalls':100,'cacheHits':300},2,100)
        self.assertEqual(row['effective_scan_interval'],10)
        self.assertEqual(row['native_next_scan_at'],110)
        observe_scan_cost(row,{'scanMs':20},2,110)
        self.assertAlmostEqual(row['effective_scan_interval'],8.2)
        self.assertEqual(row['bridge_performance']['lastScanMs'],20)
        self.assertEqual(row['native_next_scan_at'],118.2)

    def test_spacing_is_bounded_by_config_and_independent_per_instance(self):
        heavy,light={},{}
        observe_scan_cost(heavy,{'scanMs':10000},2,100)
        observe_scan_cost(light,{'scanMs':1},60,100)
        self.assertEqual(heavy['effective_scan_interval'],30)
        self.assertEqual(light['effective_scan_interval'],60)

    def test_missing_or_invalid_metrics_do_not_delay_scanning(self):
        for performance in (None,{},[],{'scanMs':-1},{'scanMs':True},{'scanMs':'100'},
                            {'scanMs':math.inf},{'scanMs':math.nan}):
            row={};observe_scan_cost(row,performance,2,100)
            self.assertEqual(row,{})

    def test_experience_remains_continuous_at_measured_scan_spacing(self):
        # Long but deliberate spacing must not turn every sample into an observation gap.
        snapshot={'loaded':True,'stage':{'category':0,'level':3,'difficulty':0,'running':True},
                  'squad':[1],'characters':[{'id':1,'level':1,'exp':0,'expTotal':0,'expNext':100}],
                  'combat':{'available':True,'current':{'sequence':1,'level':3,'difficulty':0,'result':'InProgress'}},
                  'connection':{'online':True},'sync':{}}
        state={};config={'running':True,'interval':30}
        observe_experience(snapshot,state,'session',100,config)
        after=copy.deepcopy(snapshot);after['characters'][0].update(exp=30,expTotal=30)
        result=observe_experience(after,state,'session',130,config)
        self.assertEqual(result['characters'][0]['per_minute'],60)


if __name__=='__main__':
    unittest.main()
