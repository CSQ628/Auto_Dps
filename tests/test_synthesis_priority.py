"""Category preferences must survive the planner-to-scheduler boundary."""
import copy
import json
import subprocess
import unittest

from dps_assistant.engine import DEFAULT
from dps_assistant.policy import choose


CATEGORIES = ('equipment', 'accessory', 'refinement', 'craft')
NATIVE_PLANS = r"""
const fs=require('fs'),vm=require('vm'),input=JSON.parse(process.argv[1]);
const entries=input.categories.map((category,index)=>{
 const info={uid:'material-'+category,id:1000+category,count:9,kind:[1,4,16,8][category],grade:1,tier:category===2?0:1};
 return {place:index===input.stored?'storage':'inventory',index:0,info,item:{info}};
});
const recipes=input.categories.map(category=>({ID:category+1,CraftType:0,FusionType:[0,1,3,4][category],Grade:1,MinTier:category===2?0:1,MaxTier:2,RequireCubeLevel:0,FusionCount:9}));
const storage={get_TabCount:()=>1,IsTabUnlocked:()=>true,get_OccupiedCount:()=>1,get_SlotCountPerTab:()=>49,get_IsFull:()=>false};
const im={get_Storage:()=>storage,get_Cube:()=>({get_Level:()=>20}),GetEquipment:()=>({get_Has:()=>[]})};
const c={call:(o,n,a=[])=>o[n](...a),list:x=>x,itemInfo:p=>p.info,isTradable:()=>false,
 protectedItem:()=>false,canMoveStoredItem:()=>true,workshopCapacity:()=>9,
 canRecycleItem:()=>false,containerEntries:()=>entries,keyHash:x=>x,
 fixtureCatalogue:{recipes,tiers:[{tier:1,min:1}],normalMax:160,towerMax:20,maxCharacterLevel:101}};
vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+';catalogueCache=fixtureCatalogue;equipmentPlans=()=>[];',c);
const snapshot={characters:[{id:1,level:10}],squad:[1],record:{maxCleared:9},inventory:{count:1,capacity:50}},actions=[];
c.inventoryOpportunities(snapshot,{},im,(kind,key,label,priority,data)=>actions.push({kind,key,label,priority,...data}),[],c.bridgeStrategy({...input.options,modules:{forge:false,refine:false,decompose:false}}));
process.stdout.write(JSON.stringify(actions));
"""


def action(category, stored=False):
    return {'kind': 'withdraw' if stored else 'combine', 'key': 'category-' + str(category),
            'purpose': 'combine', 'category': category, 'maxGrade': 1,
            'tier': 0 if category == 2 else 1, 'priority': 107 if stored else 108}


class SynthesisPriorityTests(unittest.TestCase):
    def config(self, preferred=0):
        config = copy.deepcopy(DEFAULT)
        config['strategy'].update({'combine_' + name + '_priority': 10 for name in CATEGORIES})
        config['strategy']['combine_' + CATEGORIES[preferred] + '_priority'] = 1
        return config

    def choose(self, actions, config, state=None, snapshot=None):
        return choose({'snapshot': {'loaded': True, 'currencies': {'soul': 0}, **(snapshot or {})},
                       'actions': actions}, config, state or {}, 1000)

    def test_native_plans_follow_all_four_category_preferences_across_inventory_and_storage(self):
        for preferred in range(4):
            for other in range(4):
                if preferred == other:
                    continue
                config = self.config(preferred)
                for stored in (0, 1):
                    with self.subTest(preferred=preferred, other=other, stored=stored):
                        plans = json.loads(subprocess.check_output(
                            ['node', '-e', NATIVE_PLANS, json.dumps({
                                'categories': [preferred, other], 'stored': stored,
                                'options': config['strategy']})], encoding='utf-8'))
                        self.assertEqual(len(plans), 2)
                        self.assertEqual(self.choose(plans, config)['category'], preferred)

    def test_storage_aging_does_not_override_explicit_category_preferences(self):
        state = {'last_module': {'combine': 999, 'storage': 0}}
        self.assertEqual(self.choose([action(2, True), action(0)], self.config(), state)['category'], 0)

    def test_equal_priorities_keep_existing_storage_and_recipe_order(self):
        config = copy.deepcopy(DEFAULT)
        for priority in (1, 7):
            config['strategy'].update({'combine_' + name + '_priority': priority for name in CATEGORIES})
            self.assertEqual(self.choose([action(0), action(2, True)], config)['category'], 0)
            self.assertEqual(self.choose([action(3), action(1)], config)['category'], 3)

    def test_disabled_preferred_category_does_not_block_lower_priority_synthesis(self):
        config = self.config()
        config['strategy']['combine_equipment'] = False
        self.assertEqual(self.choose([action(0), action(2)], config)['category'], 2)

    def test_unavailable_preferred_action_does_not_block_an_eligible_category(self):
        config = self.config()
        for state in ({'cooldowns': {'category-0': 1100}}, {'uncertain': {'category-0': {}}}):
            with self.subTest(state=state):
                self.assertEqual(self.choose([action(0), action(2)], config, state)['category'], 2)
        costly = {**action(0), 'cost': {'goods': 201, 'amount': 1}}
        self.assertEqual(self.choose([costly, action(2)], config)['category'], 2)
        config['strategy']['storage_withdraw_combine'] = False
        self.assertEqual(self.choose([action(0, True), action(2)], config)['category'], 2)

    def test_preferences_preserve_forging_and_unrelated_urgent_work(self):
        config = self.config()
        forge = {'kind': 'forge', 'part': 1, 'key': 'forge', 'priority': 109}
        self.assertEqual(self.choose([action(0), action(2, True), forge], config)['kind'], 'forge')
        urgent = {'kind': 'formation', 'key': 'formation', 'priority': 142}
        self.assertEqual(self.choose([action(0), action(2, True), urgent], config)['kind'], 'formation')


if __name__ == '__main__':
    unittest.main()
