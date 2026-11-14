import copy
import unittest
from dps_assistant.policy import strength_signature, progression_signature
from dps_assistant.farm_efficiency import observe_efficiency
from test_farm_efficiency import fixture
from dps_assistant.training import observe_farming

class PetEffectsTests(unittest.TestCase):
    def test_following_is_cosmetic_and_all_owned_effects_are_the_growth_context(self):
        snap={'pets':{'equipped':'a','unlocked':2,'ownedEffects':[{'id':'a','ability':'souls','factor':5},{'id':'b','ability':'defense','factor':3}]}}
        before=(strength_signature(snap),progression_signature(snap))
        snap['pets']['equipped']='b';snap['pets']['ownedEffects'].reverse()
        self.assertEqual((strength_signature(snap),progression_signature(snap)),before)
        snap['pets']['ownedEffects'][0]['factor']=4
        self.assertNotEqual(strength_signature(snap),before[0])
        snap['pets']['ownedEffects'][0]['id']='new-owned-pet'
        self.assertNotEqual(progression_signature(snap),before[1])

    def test_follower_switch_keeps_experience_samples_but_unlocking_invalidates_them(self):
        snap,state,config=fixture();snap['pets']={'equipped':'a','unlocked':2}
        observe_farming(snap,state,'game',100,config)
        snap['characters'][0]['expTotal']+=10
        observe_farming(snap,state,'game',110,config)
        snap['pets']['equipped']='b';snap['characters'][0]['expTotal']+=10
        result=observe_farming(snap,state,'game',120,config)
        self.assertEqual(result['efficiency']['measurements'][0]['observed_seconds'],20)
        snap['pets']['unlocked']=3
        result=observe_farming(snap,state,'game',130,config)
        self.assertFalse(result['efficiency']['measurements'])

if __name__=='__main__':unittest.main()
