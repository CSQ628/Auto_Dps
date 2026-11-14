"""Maintenance must survive restarts and never replay an uncertain native exit."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from dps_assistant import engine, storage


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)
        self.patches=[patch.object(engine,'DATA',self.path),patch.object(storage,'DATA',self.path),patch.object(engine,'game_presence',return_value='absent')]
        for p in self.patches:p.start()
        self.e=engine.Engine(start=False);self.commands=[]
        self.native={'ready':False,'maintenance':{'known':True,'active':True,'canExit':True}}
        outer=self
        class Bridge:
            identity={'pid':1,'created':1,'box':'','exe':'DPS.exe'}
            started=time.time()
            def call(self,op,args=None):
                if op=='opportunities':return {'snapshot':None,'runtime':copy.deepcopy(outer.native),'actions':[],'issues':[]}
                if op=='execute':
                    saved=json.loads((outer.path/'runtime-state.json').read_text(encoding='utf-8'))
                    assert saved['']['maintenance']['exit_session']=='1:1'
                    outer.commands.append(args)
                    return {'status':'submitted','source':'native_maintenance_exit'}
                raise AssertionError(op)
            def close(self):pass
        self.e.bridges['1']=Bridge();self.e.instances['1']={'id':'1','pid':1,'box':'','created':1,'snapshot':None}

    def tearDown(self):
        self.e.stop()
        for p in reversed(self.patches):p.stop()
        self.folder.cleanup()

    def test_prelogin_maintenance_exits_once_without_backup_or_growth_and_survives_restart(self):
        self.e.tick('1');self.e.tick('1')
        self.assertEqual([c['kind'] for c in self.commands],['maintenance_exit'])
        self.assertEqual(self.e.instances['1']['status'],'maintenance')
        self.assertFalse(self.e.durable)
        restarted=engine.Engine(start=False)
        try:
            self.assertEqual(restarted.runtime_state,self.e.runtime_state)
            with patch.object(engine,'launch') as launch:
                restarted.launch_missing(set(),[],time.time())
                launch.assert_not_called()
            waiting=restarted.public_state()['instances'][0]
            self.assertEqual(waiting['status'],'maintenance');self.assertIsNone(waiting['snapshot'])
        finally:restarted.stop()

    def test_global_instance_and_cleanup_pauses_prevent_native_exit(self):
        for mode in ('global','instance','cleanup'):
            with self.subTest(mode=mode):
                self.e.config['running']=mode!='global'
                self.e.config['instances']={'host:fixture':mode!='instance'}
                self.e.config['modules']['ui_cleanup']=mode!='cleanup'
                self.e.tick('1')
        self.assertFalse(self.commands)

    def test_lost_exit_reply_is_reserved_before_native_call_and_not_replayed(self):
        bridge=self.e.bridges['1'];call=bridge.call
        def lost(op,args=None):
            result=call(op,args)
            if op=='execute':raise ConnectionResetError('reply lost')
            return result
        bridge.call=lost
        self.e.tick('1');self.e.tick('1')
        self.assertEqual(len(self.commands),1)
        self.assertEqual(self.e.instances['1']['status'],'maintenance')
        self.assertIsNone(self.e.instances['1'].get('error'))

    def test_bridge_destruction_after_native_exit_is_expected_and_does_not_log_an_error(self):
        self.e.tick('1')
        self.e.bridges['1'].call=lambda *args:(_ for _ in ()).throw(RuntimeError('script has been destroyed'))
        self.e.tick('1')
        self.assertEqual(self.e.instances['1']['status'],'maintenance')
        self.assertFalse(any(e['status']=='error' for e in self.e.events))

    def test_retry_reservation_is_persisted_before_launch_and_uses_progressive_backoff(self):
        self.e.tick('1');entry=self.e.runtime_state[''];first=entry['maintenance']['retry_at']
        with patch.object(engine,'launch') as launch:
            self.e.launch_missing(set(),[],first-1);launch.assert_not_called()
            self.e.launch_missing(set(),[],first+1);self.assertEqual(launch.call_count,1)
            persisted=json.loads((self.path/'runtime-state.json').read_text(encoding='utf-8'))
            self.assertGreater(persisted['']['maintenance']['retry_at'],first+1)
            self.e.launch_missing(set(),[],first+2);self.assertEqual(launch.call_count,1)
        self.e.bridges['1'].identity={**self.e.bridges['1'].identity,'created':2}
        self.e.tick('1')
        self.assertEqual(entry['maintenance']['attempts'],2)
        self.assertGreaterEqual(entry['maintenance']['retry_at']-time.time(),599)

    def test_inactive_handler_without_loaded_login_does_not_clear_maintenance(self):
        self.e.tick('1');self.native['maintenance']['active']=False
        self.e.tick('1')
        self.assertTrue(self.e.runtime_state['']['maintenance']['active'])
        self.assertEqual(self.e.instances['1']['status'],'maintenance')

    def test_disabled_instance_prevents_missing_process_launch(self):
        self.e.config['instances']={'host:fixture':False}
        with patch.object(engine,'launch') as launch:
            self.e.launch_missing(set(),[],time.time());launch.assert_not_called()

    def test_repeated_maintenance_caps_backoff_and_keeps_environments_independent(self):
        bridge=self.e.bridges['1']
        for n in range(1,9):
            bridge.identity={**bridge.identity,'created':n}
            self.e.tick('1')
        hold=self.e.runtime_state['']['maintenance']
        self.assertEqual(hold['attempts'],4)
        self.assertLessEqual(hold['retry_at']-time.time(),1800)
        self.e.runtime_state['sandbox']={'maintenance':{'active':True,'retry_at':time.time()+600}}
        with patch.object(engine,'launch') as launch:
            self.e.launch_missing(set(),['sandbox'],time.time()+1801)
            self.assertEqual(launch.call_count,2)

    def test_unknown_loading_is_connecting_without_false_maintenance_or_action(self):
        self.native={'ready':False,'maintenance':{'known':False,'active':False,'canExit':False}}
        self.e.tick('1')
        self.assertEqual(self.e.instances['1']['status'],'connecting')
        self.assertFalse(self.commands)

    def test_loaded_online_login_clears_hold_but_offline_or_unknown_does_not(self):
        self.e.tick('1');row=self.e.instances['1'];bridge=self.e.bridges['1']
        for connection in ({'online':False,'loggedIn':True},{'online':True,'loggedIn':False},{}):
            self.e.observe_runtime(bridge,row,{'runtime':{'ready':True,'maintenance':{'known':True,'active':False}},'snapshot':{'connection':connection}})
            self.assertTrue(self.e.runtime_state['']['maintenance']['active'])
        self.e.observe_runtime(bridge,row,{'runtime':{'ready':True,'maintenance':{'known':True,'active':False}},'snapshot':{'connection':{'online':True,'loggedIn':True}}})
        self.assertNotIn('maintenance',self.e.runtime_state[''])


if __name__=='__main__':unittest.main()
