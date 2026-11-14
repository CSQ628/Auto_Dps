import copy
import unittest
from dps_assistant.engine import DEFAULT
from dps_assistant.policy import ranked_actions
from dps_assistant.diagnostics import diagnostics


class EquipmentWorkshopTests(unittest.TestCase):
    def test_forge_then_combine_then_recycle_respects_cooldowns_and_warehouse_preparation(self):
        for kind in ('forge','withdraw'):
            first={'kind':kind,'key':'craft','purpose':'forge','priority':85}
            scan={'snapshot':{'loaded':True,'currencies':{}},'actions':[first,
                {'kind':'combine','key':'combine','priority':108},
                {'kind':'decompose','key':'decompose','priority':102}]}
            config=copy.deepcopy(DEFAULT)
            state={'last_module':{'forge':1000,'storage':1000,'combine':0,'decompose':0}}
            self.assertEqual([a['key'] for a in ranked_actions(scan,config,state,1000)],['craft'])
            state['cooldowns']={'craft':2000}
            self.assertEqual([a['key'] for a in ranked_actions(scan,config,state,1000)],['combine'])
            state['cooldowns']['combine']=2000
            self.assertEqual([a['key'] for a in ranked_actions(scan,config,state,1000)],['decompose'])

    def test_all_observed_offline_rune_types_remain_available_after_online_growth(self):
        actions=[{'kind':'rune','key':h,'header':h,'priority':100} for h in
                 ('OfflineExpGain','OfflineGoodsGain','OfflineReward')]
        actions.append({'kind':'rune','key':'growth','header':'KillExpGain','priority':89})
        result=ranked_actions({'snapshot':{'loaded':True,'currencies':{}},'actions':actions},copy.deepcopy(DEFAULT),{},100)
        self.assertEqual([a['key'] for a in result],['growth','OfflineExpGain','OfflineGoodsGain','OfflineReward'])

    def test_material_and_retirement_diagnostics_exclude_private_item_values(self):
        row=diagnostics({'instances':[{'snapshot':{'forging':{'status':'materials_missing','materials':[
            {'id':510501,'available':0,'required':1,'protected':2,'uid':'private-uid'}],'uid':'private-uid'},
            'combining':{'nearest':[{'category':0,'minTier':5,'maxTier':6,'available':8,'required':9,'uids':['private-uid']}]},
            'recycling':{'locked':1,'socketedAllowed':True,'allowed':['private-uid']}}}]})['instances'][0]
        self.assertEqual(row['forging']['status'],'materials_missing')
        self.assertEqual(row['forge_materials'][0]['protected'],2)
        self.assertEqual(row['fusion_waiting'][0]['available'],8)
        self.assertTrue(row['recycling']['socketedAllowed'])
        self.assertNotIn('private-',str(row))

    def test_tower_defaults_off_and_upgrade_disables_old_setting_once(self):
        from dps_assistant.parameters import normalize_config, apply_patch
        self.assertFalse(DEFAULT['modules']['tower'])
        migrated=normalize_config({'modules':{'tower':True,'box':True}})
        self.assertFalse(migrated['modules']['tower'])
        self.assertTrue(migrated['modules']['box'])
        enabled=apply_patch(migrated,{'modules':{'tower':True}})
        self.assertTrue(normalize_config(enabled)['modules']['tower'])

    def test_priority_defaults_validation_and_persistence(self):
        from dps_assistant.parameters import normalize_config, apply_patch
        cfg=normalize_config(DEFAULT)
        self.assertEqual(cfg['strategy']['forge_priority_main_weapon'],1)
        self.assertEqual(cfg['strategy']['forge_priority_accessory'],1)
        cfg=apply_patch(cfg,{'strategy':{'forge_priority_accessory':1}})
        self.assertEqual(normalize_config(cfg)['strategy']['forge_priority_accessory'],1)
        with self.assertRaises(ValueError):apply_patch(cfg,{'strategy':{'forge_priority_accessory':0}})
