import copy
import unittest
from dps_assistant.engine import Engine, DEFAULT


class PlanningBudgetTests(unittest.TestCase):
    def test_bridge_planning_receives_the_same_independent_reserves_as_execution(self):
        engine=object.__new__(Engine)
        engine.config=copy.deepcopy(DEFAULT)
        engine.config.update(soul_reserve=123,premium_reserve=7,permanent_runes=False)
        engine.config['modules']['active']=False
        options=engine.bridge_options()
        self.assertEqual(options['budget'],{'soul_reserve':123,'premium_reserve':7,'permanent_runes':False})
        self.assertFalse(options['modules']['active'])
        options['budget']['premium_reserve']=0
        self.assertEqual(engine.config['premium_reserve'],7)
