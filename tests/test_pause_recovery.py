"""Non-destructive inventory changes must never switch off host or sandbox accounts."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from dps_assistant import engine, storage
from dps_assistant.pause import pause_info


class PauseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)
        self.patches=[patch.object(engine,'DATA',self.path),patch.object(storage,'DATA',self.path)]
        for p in self.patches:p.start()
        self.app=engine.Engine(start=False);self.result={'status':'confirmed'};self.commands=[]
        self.snap={'account':'fixture','loaded':True,'currencies':{'soul':100,'premium':2},
            'record':{'maxCleared':1,'maxStage':1,'boxes':0},'catalogue':{},
            'stage':{'category':0,'level':1,'difficulty':0,'running':True,'repeat':True},
            'characters':[],'squad':[],'connection':{'online':True},'sync':{}}
        outer=self
        class Bridge:
            identity={'pid':1,'created':1,'box':'','exe':'DPS.exe'}
            started=time.time()
            process=type('Process',(),{'poll':lambda self:None})()
            def call(self,op,args=None):
                if op=='opportunities':return {'snapshot':copy.deepcopy(outer.snap),'actions':[
                    {'kind':'sort','key':'sort:'+str(len(outer.commands)),'label':'原生排序','priority':70}], 'issues':[]}
                if op=='execute':outer.commands.append(args);return copy.deepcopy(outer.result)
                raise AssertionError(op)
            def close(self):pass
            def health(self,timeout=1):return {'phase':'ready'}
        self.bridge=Bridge();self.app.bridges['1']=self.bridge
        self.app.instances['1']={'id':'1','status':'connecting','confirmed':0}
        saved=self.path/'save.zip';saved.touch()
        self.backup={'status':'created','version':2,'path':str(saved)}
        self.prepare('')

    def prepare(self,box):
        self.bridge.identity={**self.bridge.identity,'box':box}
        identity=(box or 'host')+':fixture'
        self.app.durable[identity]={'backup':self.backup,'uncertain':{},'cooldowns':{},'last_equipment':{}}
        return identity

    def tearDown(self):
        self.app.stop()
        for p in reversed(self.patches):p.stop()
        self.folder.cleanup()

    def test_host_and_sandbox_stay_enabled_after_repeated_layout_and_confirmation_changes(self):
        for box in ('','sandbox'):
            identity=self.prepare(box)
            self.result={'status':'confirmed','protectedChanged':[{'uid':'diagnostic-only'}],'tradeChanged':[]}
            for _ in range(20):
                self.app.tick('1')
                self.assertTrue(self.app.config['instances'].get(identity,True))
                self.assertEqual(self.app.instances['1']['status'],'running')
                self.assertIsNone(self.app.public_state()['instances'][0]['pause'])
            self.assertNotIn('pause',self.app.durable[identity])
        self.assertEqual(len(self.commands),40)

    def test_actual_trade_damage_warns_without_pausing_host_or_sandbox(self):
        for box in ('','sandbox'):
            identity=self.prepare(box)
            self.result={'status':'confirmed','tradeChanged':[{'reason':'trade_flag_lost'}]}
            for _ in range(3):self.app.tick('1')
            self.assertTrue(self.app.config['instances'].get(identity,True))
            self.assertEqual(self.app.instances['1']['status'],'running')
            self.assertIsNone(self.app.public_state()['instances'][0]['pause'])
        warnings=[e for e in self.app.events if e['status']=='warning']
        self.assertEqual(len(warnings),6);self.assertEqual(len(self.commands),6)
        self.assertTrue(all(e['result']['reason']=='tradable_state_changed' for e in warnings))
        self.assertTrue(any(json.loads(line)['status']=='warning' for line in (self.path/'actions.jsonl').read_text(encoding='utf-8').splitlines()))

    def test_manual_resume_clears_old_protective_cause_without_rearming_it(self):
        for box in ('','sandbox'):
            identity=self.prepare(box)
            self.app.config['instances'][identity]=False
            self.app.durable[identity]['pause']={'reason':'protected_item_changed','at':time.time()}
            self.app.update({'instances':{identity:True}})
            self.result={'status':'confirmed','protectedChanged':[{'place':'storage'}],
                         'tradeChanged':[{'reason':'tradable_quantity_lost'}]}
            for _ in range(8):self.app.tick('1')
            self.assertTrue(self.app.config['instances'][identity])
            self.assertNotIn('pause',self.app.durable[identity])
            self.assertIsNone(self.app.public_state()['instances'][0]['pause'])

    def test_manual_and_global_pause_are_distinct_and_never_auto_resumed(self):
        self.app.tick('1');self.app.update({'instances':{'host:fixture':False}})
        self.app.tick('1')
        self.assertEqual(self.app.public_state()['instances'][0]['pause']['reason'],'manual_instance_pause')
        self.app.update({'running':False})
        self.assertEqual(self.app.public_state()['instances'][0]['pause']['reason'],'global_paused')
        self.app.update({'running':True})
        self.assertFalse(self.app.config['instances']['host:fixture'])

    def test_warning_never_writes_config_or_changes_any_instance_switch(self):
        self.result={'status':'confirmed','tradeChanged':[{'reason':'trade_flag_lost'}]}
        original=engine.atomic_json
        def write(path,value):
            if Path(path).name=='config.json':raise AssertionError('warnings must not change config')
            return original(path,value)
        with patch.object(engine,'atomic_json',side_effect=write):
            self.app.tick('1');self.app.tick('1')
        self.assertEqual(len(self.commands),2)
        self.assertEqual(self.app.instances['1']['status'],'running')
        self.assertFalse(any(e['status']=='error' for e in self.app.events))
        self.assertFalse(self.app.config['instances'])

    def test_stale_protective_reason_cannot_pause_enabled_instance_after_restart(self):
        self.app.durable['host:fixture']['pause']={'reason':'protected_item_changed','at':1}
        self.app.save()
        restarted=engine.Engine(start=False)
        try:
            self.assertIsNone(pause_info(restarted.config,'host:fixture',restarted.durable['host:fixture']))
            self.assertTrue(restarted.runtime_enabled('','host:fixture'))
        finally:restarted.stop()

    def test_unknown_legacy_pause_is_not_misrepresented_as_manual(self):
        self.assertEqual(pause_info({'instances':{'host:a':False}},'host:a',{})['reason'],'legacy_instance_pause')

    def test_failed_manual_resume_keeps_config_and_pause_unchanged(self):
        self.app.update({'instances':{'host:fixture':False}})
        saved=copy.deepcopy(self.app.durable['host:fixture']['pause'])
        with patch.object(engine,'atomic_json',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.app.update({'instances':{'host:fixture':True}})
        self.assertFalse(self.app.config['instances']['host:fixture'])
        self.assertEqual(self.app.durable['host:fixture']['pause'],saved)
