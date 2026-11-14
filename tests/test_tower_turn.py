import unittest
from dps_assistant.tower import begin_tower_turn, observe_tower_turn
from dps_assistant.engine import DEFAULT
from dps_assistant.policy import choose


def snapshot(category=0, clears=10, fails=2):
    return {'loaded':True, 'stage':{'category':category},'record':{'normalClears':clears,'normalFails':fails},'currencies':{}}


class TowerTurnTests(unittest.TestCase):
    def test_returning_to_main_requires_a_new_native_main_result(self):
        s=snapshot();state={};begin_tower_turn(s,state,'session',1)
        observe_tower_turn(snapshot(1,11),state,'session',2)
        observe_tower_turn(snapshot(0,11),state,'session',3)
        scan={'snapshot':s,'actions':[{'kind':'tower','key':'tower:2','level':2,'priority':79},
                                    {'kind':'box','key':'box','priority':99}]}
        self.assertEqual(choose(scan,DEFAULT,state,now=1000)['kind'],'box')
        observe_tower_turn(snapshot(0,11),state,'session',1000)
        self.assertTrue(state['tower_turn']['waiting'])
        observe_tower_turn(snapshot(0,11,3),state,'session',1001)
        self.assertEqual(choose(scan,DEFAULT,state,now=1001)['kind'],'box')

    def test_process_change_and_counter_reset_do_not_carry_stale_baselines(self):
        state={};begin_tower_turn(snapshot(),state,'old',1)
        self.assertIsNone(observe_tower_turn(snapshot(),state,'new',2))
        observe_tower_turn(snapshot(1),state,'new',3)
        observe_tower_turn(snapshot(0),state,'new',4)
        observe_tower_turn(snapshot(0,0,0),state,'new',5)
        self.assertTrue(state['tower_turn']['waiting'])
        observe_tower_turn(snapshot(0,1,0),state,'new',6)
        self.assertFalse(state['tower_turn']['waiting'])

    def test_missing_counters_block_only_the_next_tower(self):
        state={};begin_tower_turn(snapshot(),state,'s',1)
        value=observe_tower_turn(snapshot(0,None,None),state,'s',500)
        self.assertTrue(value['waiting'])
        self.assertEqual(value['reason'],'native_main_result_unavailable')
