import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dps_assistant import engine, storage
from dps_assistant.parameters import PARAMETERS, DEFAULT_STRATEGY, normalize_config, apply_patch, strategy
from dps_assistant.tuning import operation_allowed
from dps_assistant.policy import choose, skill_repair_pending


class DetailedParameterTests(unittest.TestCase):
    def test_tradable_append_permission_is_checked_again_before_dispatch(self):
        options=copy.deepcopy(DEFAULT_STRATEGY)
        action={'kind':'refine','slot':0,'allowTradableTarget':True,'targetGrade':7}
        self.assertTrue(operation_allowed(action,options))
        options['refine_tradable_equipment']=False
        self.assertFalse(operation_allowed(action,options))
        options['refine_tradable_equipment']=True
        for grade in (None,0,8,True,'7'):
            self.assertFalse(operation_allowed({**action,'targetGrade':grade},options))

    def test_all_original_defaults_and_every_module_are_preserved(self):
        previous=json.loads(Path('tests/base-parameter-defaults.json').read_text(encoding='utf-8'))
        current={p['key']:p['default'] for p in PARAMETERS}
        self.assertEqual({k:current[k] for k in previous},previous)
        self.assertEqual(len(current),173)
        for module in engine.MODULES:
            self.assertTrue(any(module in p['modules'] and p['section']!='基础参数' for p in PARAMETERS),module)
        self.assertFalse(engine.DEFAULT['modules']['tower'])

    def test_bridge_sanitizes_every_detailed_control_with_identical_schema_defaults_and_bounds(self):
        js="const fs=require('fs'),vm=require('vm'),c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+';globalThis.rules=detailedParameterRules;',c);process.stdout.write(JSON.stringify({rules:c.rules,defaults:c.bridgeStrategy()}));"
        value=json.loads(subprocess.check_output(['node','-e',js],encoding='utf-8'))
        for spec in PARAMETERS:
            if spec['section']=='基础参数':continue
            self.assertEqual(value['defaults'][spec['key']],spec['default'])
            self.assertEqual(value['rules'][spec['key']],{k:spec[k] for k in ('type','default','min','max','step','options') if k in spec})

    def test_full_custom_strategy_survives_atomic_save_and_restart_without_touching_basic_values(self):
        original=copy.deepcopy(engine.DEFAULT)
        changed={}
        for spec in PARAMETERS:
            if spec['section']=='基础参数':continue
            changed[spec['key']]=False if spec['type']=='boolean' else spec['options'][-1]['value'] if spec['type']=='choice' else spec['max']
        with tempfile.TemporaryDirectory() as d,patch.object(engine,'DATA',Path(d)),patch.object(storage,'DATA',Path(d)):
            first=engine.Engine(start=False)
            try:first.update({'strategy':changed})
            finally:first.stop()
            second=engine.Engine(start=False)
            try:
                self.assertEqual({k:second.config['strategy'][k] for k in changed},changed)
                for p in PARAMETERS:
                    if p['section']=='基础参数':
                        target=second.config if p['scope']=='root' else second.config['strategy']
                        expected=original if p['scope']=='root' else original['strategy']
                        self.assertEqual(target[p['key']],expected[p['key']])
            finally:second.stop()

    def test_invalid_values_leave_entire_patch_unchanged(self):
        original=normalize_config(engine.DEFAULT)
        for spec in PARAMETERS:
            if spec['section']=='基础参数':continue
            bad=1 if spec['type']=='boolean' else 'unknown' if spec['type']=='choice' else spec['max']+1
            with self.subTest(key=spec['key']),self.assertRaises(ValueError):apply_patch(original,{'strategy':{'box_grade_0':False,spec['key']:bad}})
        self.assertEqual(original,normalize_config(engine.DEFAULT))

    def test_stale_disabled_combine_does_not_starve_recycling_or_other_categories(self):
        config=copy.deepcopy(engine.DEFAULT);config['strategy']['combine_refinement']=False
        actions=[{'kind':'combine','category':2,'maxGrade':1,'tier':0,'key':'refinement','priority':108},
                 {'kind':'decompose','maxGrade':1,'key':'recycle','priority':102}]
        scan={'snapshot':{'loaded':True,'currencies':{}},'actions':actions}
        self.assertEqual(choose(scan,config,{},100)['key'],'recycle')
        actions.append({'kind':'combine','category':0,'maxGrade':1,'tier':1,'key':'equipment','priority':108})
        self.assertEqual(choose(scan,config,{},100)['key'],'equipment')

    def test_disabled_skill_spending_does_not_hold_progress_in_a_ghost_repair(self):
        config=copy.deepcopy(engine.DEFAULT);config['strategy'].update(active_upgrade=False,passive_upgrade=False)
        snapshot={'characters':[{'id':1,'points':3,'skillPlanning':{'repair':{'excess':4,'controls':{'active':True,'passive':True}}}}],'squad':[1]}
        self.assertFalse(skill_repair_pending(snapshot,config))

    def test_dispatch_respects_sources_parts_and_all_auxiliary_suboperations(self):
        pairs=[({'kind':'box','grade':2},'box_grade_2'),({'kind':'formation'},'formation_fill'),
               ({'kind':'unlock'},'unlock_characters'),({'kind':'pet_equip'},'pet_follow_enabled'),
               ({'kind':'pet_unlock'},'pet_unlock_enabled'),({'kind':'deposit'},'storage_deposit'),
               ({'kind':'withdraw','purpose':'refine'},'storage_withdraw_refine'),
               ({'kind':'withdraw','purpose':'recycle'},'storage_withdraw_recycle'),
               ({'kind':'sort','place':'storage'},'sort_storage'),({'kind':'mail_claim'},'mail_claim_enabled'),
               ({'kind':'mail_close'},'mail_close_enabled'),({'kind':'offline_close'},'offline_close_enabled'),
               ({'kind':'battle_recover','reason':'stalled_end'},'recovery_stall'),
               ({'kind':'equipment','slot':6,'source':'inventory','empty':True},'equipment_part_accessory'),
               ({'kind':'active','level':0},'active_learn'),({'kind':'passive','level':2},'passive_upgrade')]
        for action,key in pairs:
            with self.subTest(key=key):
                self.assertTrue(operation_allowed(action,strategy()))
                self.assertFalse(operation_allowed(action,strategy({'strategy':{key:False}})))

    def test_custom_launch_sources_only_start_the_selected_environment(self):
        with tempfile.TemporaryDirectory() as d,patch.object(engine,'DATA',Path(d)),patch.object(storage,'DATA',Path(d)):
            app=engine.Engine(start=False)
            try:
                app.config['strategy'].update(launch_main=False,launch_sandbox=True)
                with patch.object(engine,'game_presence',return_value='absent'),patch.object(engine,'launch',return_value=True) as launch:
                    app.launch_missing(set(),['sandbox'],1000)
                    self.assertEqual(launch.call_count,1);self.assertEqual(launch.call_args.args[0],'sandbox')
                    app.config['strategy'].update(launch_main=True,launch_sandbox=False)
                    app.launch_missing(set(),['sandbox'],2000)
                    self.assertEqual(launch.call_count,2);self.assertEqual(launch.call_args.args[0],'')
            finally:app.stop()

    def test_stale_rune_and_material_recalls_obey_new_subcontrols(self):
        for action,key in [({'kind':'rune','header':'OfflineExpGain','level':0},'rune_offline'),
                           ({'kind':'withdraw','purpose':'combine','category':2,'maxGrade':1,'tier':0},'combine_refinement'),
                           ({'kind':'withdraw','purpose':'forge','part':7},'forge_part_accessory'),
                           ({'kind':'withdraw','purpose':'refine','slot':0},'refine_part_main_weapon')]:
            self.assertTrue(operation_allowed(action,strategy()))
            self.assertFalse(operation_allowed(action,strategy({'strategy':{key:False}})))
