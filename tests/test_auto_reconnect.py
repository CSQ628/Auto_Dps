"""Disconnect recovery preserves player intent, process lifetime and action reservations."""
from concurrent.futures import Future
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

import psutil
from dps_assistant import engine,runtime,storage
from dps_assistant.pause import automatic_pause_evidence,pause_info


class AutoReconnectTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)
        self.patches=[patch.object(engine,'DATA',self.path),patch.object(storage,'DATA',self.path)]
        for p in self.patches:p.start()
        self.app=engine.Engine(start=False)
        self.proc={'pid':41,'created':100,'exe':'DPS.exe','box':''}
        self.snap={'account':'fixture','loaded':True,'currencies':{},'record':{'maxCleared':1,'maxStage':1,'boxes':0},
                   'catalogue':{},'stage':{'category':0,'level':1,'running':True,'repeat':True},'characters':[],'squad':[]}
        (self.path/'save.zip').touch()
        self.app.durable['host:fixture']={'backup':{'status':'created','version':2,'path':str(self.path/'save.zip')},
                                         'uncertain':{},'cooldowns':{},'last_equipment':{}}

    def tearDown(self):
        self.app.stop()
        for p in reversed(self.patches):p.stop()
        self.folder.cleanup()

    def restart(self):
        return engine.Engine(start=False)

    def test_saved_automatic_stop_recovers_once_but_subsequent_manual_off_survives_restart(self):
        self.app.config.pop('_pause_recovery_schema',None)
        self.app.config['instances']['host:fixture']=False
        self.app.durable['host:fixture']['pause']={'reason':'protected_item_changed'}
        storage.atomic_json(self.path/'config.json',self.app.config);self.app.save()
        restarted=self.restart()
        try:
            self.assertTrue(restarted.config['instances']['host:fixture'])
            self.assertNotIn('pause',restarted.durable['host:fixture'])
            self.assertEqual(sum(e.get('result',{}).get('reason')=='automatic_pause_recovered' for e in restarted.events),1)
            restarted.update({'instances':{'host:fixture':False}})
            again=self.restart()
            try:
                self.assertFalse(again.runtime_enabled('','host:fixture'))
                self.assertEqual(pause_info(again.config,'host:fixture',again.durable['host:fixture'])['reason'],'manual_instance_pause')
            finally:again.stop()
        finally:restarted.stop()

    def test_manual_intent_is_atomic_with_config_even_if_scheduler_write_fails(self):
        original=engine.atomic_json
        def fail_scheduler(path,value):
            if Path(path).name=='scheduler.json':raise OSError('disk temporarily unavailable')
            original(path,value)
        with patch.object(engine,'atomic_json',side_effect=fail_scheduler):
            with self.assertRaises(OSError):self.app.update({'instances':{'host:fixture':False}})
        restarted=self.restart()
        try:
            self.assertFalse(restarted.config['instances']['host:fixture'])
            self.assertEqual(pause_info(restarted.config,'host:fixture',{})['reason'],'manual_instance_pause')
        finally:restarted.stop()

    def test_migration_save_failure_retries_and_global_stop_stays_closed(self):
        self.app.config.pop('_pause_recovery_schema',None)
        self.app.config.update(running=False,instances={'host:fixture':False})
        self.app.durable['host:fixture']['pause']={'reason':'protected_item_changed'}
        with patch.object(engine,'atomic_json',side_effect=OSError('busy')):
            self.app.recover_automatic_pauses();self.app.recover_automatic_pauses()
        self.assertFalse(self.app.config['instances']['host:fixture'])
        self.assertNotIn('_pause_recovery_schema',self.app.config)
        self.app.recover_automatic_pauses()
        self.assertTrue(self.app.config['instances']['host:fixture']);self.assertFalse(self.app.config['running'])
        self.assertEqual(sum(e['status']=='warning' for e in self.app.events),1)

    def test_legacy_receipt_requires_matching_config_write_and_cannot_override_manual_intent(self):
        config={'instances':{'host:a':False}}
        event={'identity':'host:a','at':101,'action':{'kind':'equipment'},'result':{'protectedChanged':[{}]}}
        self.assertIn('host:a',automatic_pause_evidence(config,{},[event],100.9))
        for modified in (1,102):self.assertFalse(automatic_pause_evidence(config,{},[event],modified))
        manual={'host:a':{'pause':{'reason':'manual_instance_pause'}}}
        self.assertFalse(automatic_pause_evidence(config,manual,[event],100.9))
        config['_instance_run_intent']={'host:a':{'enabled':False}}
        self.assertFalse(automatic_pause_evidence(config,{},[event],100.9))

    def test_discovery_miss_keeps_known_session_and_manual_binding_without_relaunch(self):
        self.app.manual_bindings['41']=self.proc
        for status in ('present','unknown'):
            with patch.object(engine,'discover',return_value=[]),patch.object(engine,'process_identity_status',return_value=status):
                result=self.app.discovered_processes()
            self.assertEqual(result[0]['created'],100)
            self.assertEqual(result[0]['identity_waiting'],status=='unknown')
            self.assertIn('41',self.app.manual_bindings)
        with patch.object(engine,'discover',return_value=[]),patch.object(engine,'process_identity_status',return_value='absent'):
            self.assertFalse(self.app.discovered_processes())
        self.assertFalse(self.app.manual_bindings)

    def test_pid_reuse_discards_old_binding_but_uses_fresh_discovery(self):
        self.app.manual_bindings['41']=self.proc
        fresh={**self.proc,'created':200,'box':'sandbox'}
        with patch.object(engine,'discover',return_value=[fresh]):
            self.assertEqual(self.app.discovered_processes(),[fresh])
        self.assertNotIn('41',self.app.manual_bindings)

    def test_temporary_permissions_are_unknown_and_changed_process_lifetime_is_absent(self):
        p=Mock();p.create_time.return_value=100;p.exe.return_value='DPS.exe'
        with patch.object(runtime.psutil,'Process',return_value=p),patch.object(runtime,'box_for',return_value=''):
            self.assertEqual(runtime.process_identity_status(self.proc),'present')
            p.exe.side_effect=psutil.AccessDenied(41)
            self.assertEqual(runtime.process_identity_status(self.proc),'unknown')
            p.create_time.return_value=200
            self.assertEqual(runtime.process_identity_status(self.proc),'absent')
            p.exe.assert_called()

    def one_loop(self):
        def submit(fn,key):
            result=Future()
            try:result.set_result(fn(key))
            except Exception as error:result.set_exception(error)
            return result
        self.app.stopping.clear()
        with patch.object(self.app.pool,'submit',side_effect=submit),patch.object(self.app.stopping,'wait',side_effect=lambda _:self.app.stopping.set()):
            self.app.loop()

    def test_failed_bridge_reconnects_without_game_restart_and_preserves_manual_stop(self):
        for manual in (False,True):
            self.app.instances={};self.app.bridges={};self.app.jobs={}
            self.app.update({'instances':{'host:fixture':not manual}})
            outer=self;commands=[];closed=[]
            class Bridge:
                started=0
                process=Mock(poll=lambda:None)
                def __init__(self,identity,failed=False):self.identity=identity;self.failed=failed
                def close(self):closed.append(self)
                def health(self,timeout=1):return {'phase':'failed' if self.failed else 'ready'}
                def call(self,op,args=None):
                    if self.failed:raise engine.BridgeFailure({'phase':'failed','error':'fixture disconnect'})
                    if op=='opportunities':return {'snapshot':copy.deepcopy(outer.snap),'actions':[{'kind':'sort','key':'sort','label':'排序','priority':70}],'issues':[]}
                    if op=='execute':commands.append(args);return {'status':'confirmed'}
                    raise AssertionError(op)
            old=Bridge(self.proc,True);self.app.bridges['41']=old
            self.app.instances['41']={'id':'41',**self.proc,'identity':'host:fixture','status':'running','confirmed':0}
            with patch.object(engine,'discover',return_value=[self.proc]),patch.object(engine,'Bridge',side_effect=Bridge),patch.object(engine,'launch') as launch:
                self.one_loop()
                self.assertIn(old,closed);self.assertNotIn('41',self.app.bridges)
                self.app.instances['41']['bridge_retry_at']=0
                self.one_loop()
                launch.assert_not_called()
            self.assertEqual(len(commands),0 if manual else 1)
            self.assertEqual(self.app.config['instances']['host:fixture'],not manual)
            self.assertFalse(any(e['status']=='error' for e in self.app.events))

    def test_one_bridge_constructor_failure_does_not_block_other_instance(self):
        sandbox={**self.proc,'pid':42,'box':'sandbox'}
        calls=[]
        def bridge(identity):
            calls.append(identity['pid'])
            if identity['pid']==41:raise OSError('temporarily unavailable')
            return Mock(identity=identity)
        with patch.object(engine,'discover',return_value=[self.proc,sandbox]),patch.object(engine,'Bridge',side_effect=bridge),patch.object(self.app,'tick'),patch.object(engine,'launch') as launch:
            self.one_loop();self.one_loop();launch.assert_not_called()
        self.assertEqual(calls,[41,42])
        self.assertGreater(self.app.instances['41']['bridge_retry_at'],time.time())
        self.assertTrue(self.app.config['running'])


class ProcessLifetimeTests(unittest.TestCase):
    def test_terminal_pid_and_pid_reuse_are_distinct_from_unreadable_process(self):
        identity={'pid':41,'created':100,'box':''}
        cases=[(Mock(create_time=lambda:100),'present'),(Mock(create_time=lambda:101),'absent'),
               (psutil.NoSuchProcess(41),'absent'),(psutil.AccessDenied(41),'unknown'),(OSError('unavailable'),'unknown')]
        for value,expected in cases:
            with self.subTest(expected=expected,value=type(value).__name__),patch.object(runtime.psutil,'Process',side_effect=value if isinstance(value,Exception) else None,return_value=value):
                self.assertEqual(runtime.process_lifetime_status(identity),expected)
        for invalid in (None,{}, {'pid':True,'created':100},{'pid':41,'created':float('nan')}):
            self.assertEqual(runtime.process_lifetime_status(invalid),'unknown')
