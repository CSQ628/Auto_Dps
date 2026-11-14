"""Recovery uses exact native receipts across helper lifetimes, never inferred grants."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from dps_assistant import box_receipts,engine,storage
from dps_assistant.box_receipts import BoxReceiptStore
from tools.bridge_host import BridgeHost


def receipt(key='batch',opened=3,status='confirmed',account='fixture'):
    return {'requestId':key,'account':account,'status':status,'openedCount':opened,
            'recordBefore':100,'recordAfter':100+opened,'observations':[],
            **({'pendingRecord':100+opened} if status=='pending' else {})}


class DurableReceiptTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
    def tearDown(self):self.directory.cleanup()
    def store(self,created=100):return BoxReceiptStore(42,created,self.root)

    def test_returned_receipt_survives_helper_restart_without_consuming_again(self):
        first=self.store();self.assertTrue(first.checkpoint(receipt()))
        self.assertEqual(self.store().restore(),[receipt()])

    def test_partial_credit_is_monotonic_and_pending_receipts_are_retained_when_cache_prunes(self):
        s=self.store();s.checkpoint(receipt('pending',2,'pending'))
        for i in range(40):s.checkpoint(receipt(str(i)))
        saved=self.store().restore();self.assertEqual(len(saved),32)
        self.assertIn('pending',[r['requestId'] for r in saved])
        self.assertFalse(s.checkpoint(receipt('pending',1,'pending')))
        self.assertTrue(s.checkpoint(receipt('pending',3)))
        self.assertFalse(s.checkpoint(receipt('pending',3,'pending')))

    def test_different_game_lifetime_and_copied_journal_cannot_restore_old_receipts(self):
        old=self.store();old.checkpoint(receipt())
        new=self.store(101);self.assertFalse(new.restore())
        new.path.write_bytes(old.path.read_bytes())
        reloaded=self.store(101);self.assertFalse(reloaded.restore());self.assertTrue(reloaded.failed)

    def test_corrupt_and_invalid_entries_never_become_recovery_evidence(self):
        store=self.store()
        for content in ('{broken','[]','null',json.dumps({'schema':1,'process':store.identity,'receipts':[{**receipt(status='pending'),'pendingRecord':None}]})):
            store.path.write_text(content,encoding='utf-8')
            loaded=self.store();self.assertFalse(loaded.restore());self.assertTrue(loaded.failed)
        for value in ({},receipt(opened=9),receipt(opened=True),receipt(status='unknown'),{**receipt(),'account':''}):
            self.assertFalse(store.checkpoint(value))

    def test_failed_disk_write_keeps_previous_durable_receipt_and_retries_on_next_checkpoint(self):
        s=self.store();s.checkpoint(receipt('partial',2,'pending'))
        with patch.object(box_receipts,'atomic_json',side_effect=OSError('disk busy')):
            self.assertFalse(s.checkpoint(receipt('partial',3)))
        self.assertTrue(s.failed);self.assertEqual(self.store().restore()[0]['openedCount'],2)
        self.assertTrue(s.checkpoint(receipt('partial',3)))
        self.assertFalse(s.failed);self.assertEqual(self.store().restore()[0]['openedCount'],3)


class NativeScript:
    def __init__(self,world):self.world=world;self.exports_sync=self;self.receipts={}
    def on(self,*args):pass
    def load(self):pass
    def unload(self):pass
    def dispose(self):pass
    def list_exports_sync(self):return ['opportunities','restoreboxreceipts','boxscan','openboxes']
    def restoreboxreceipts(self,rows):self.receipts={r['requestId']:copy.deepcopy(r) for r in rows}
    def boxscan(self,args):
        r=copy.deepcopy(self.receipts.get(args.get('requestId')))
        if r:r['source']='durable_bridge_receipt'
        return {'snapshot':{'account':'fixture','loaded':True,'inventory':{'count':0,'capacity':50},
                'record':{'boxes':self.world['record']},'boxes':{'total':self.world['queue'],'counts':[self.world['queue'],0,0],'freeSlots':50}},
                'actions':[{'kind':'box','key':'box:'+str(self.world['record']),'priority':99}] if self.world['queue'] else [],
                'issues':[],'scanMs':0,'receipt':r}
    def openboxes(self,args):
        key=args['requestId']
        if key in self.receipts:return copy.deepcopy(self.receipts[key])
        before=self.world['record'];self.world['native_calls']+=1;n=min(8,self.world['queue']);self.world['queue']-=n;self.world['record']+=n
        self.receipts[key]={**receipt(key,n),'recordBefore':before,'recordAfter':self.world['record']};return copy.deepcopy(self.receipts[key])


class NativeSession:
    def __init__(self,script):self.script=script
    def on(self,*args):pass
    def create_script(self,*args):return self.script
    def detach(self):pass


class HostReceiptRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        (self.root/'bridge').mkdir();(self.root/'bridge/automation.js').write_text('fixture',encoding='utf-8')
        self.world={'queue':3,'record':100,'native_calls':0};self.hosts=[]
    def tearDown(self):
        for h in self.hosts:h.close()
        self.directory.cleanup()
    def host(self,created=100):
        script=NativeScript(self.world)
        host=BridgeHost(42,self.root,lambda _:NativeSession(script),process_created=created,receipt_directory=self.root/'receipts')
        with patch('tools.bridge_host.psutil.Process',return_value=Mock(create_time=lambda:created)):host.initialize()
        self.assertEqual(host.health()['phase'],'ready');self.hosts.append(host);return host

    def test_completed_result_is_saved_before_http_delivery_and_recovered_by_new_helper(self):
        first=self.host();args={'requestId':'lost','account':'fixture'}
        result=first.call({'op':'openboxes','args':args})
        self.assertEqual(result['receiptPersistence'],'available')
        # The caller loses this HTTP body. Destroying the script removes its RAM cache.
        first.close();second=self.host()
        restored=second.call({'op':'boxscan','args':args})['receipt']
        self.assertEqual(restored['openedCount'],3);self.assertEqual(restored['source'],'durable_bridge_receipt')
        again=second.call({'op':'openboxes','args':args})
        self.assertEqual(again['openedCount'],3);self.assertEqual(self.world['native_calls'],1)

    def test_missing_receipt_and_new_game_process_cannot_fabricate_a_completed_batch(self):
        first=self.host();first.call({'op':'openboxes','args':{'requestId':'old','account':'fixture'}})
        for host,args in ((first,{'requestId':'missing'}),(self.host(101),{'requestId':'old'})):
            self.assertIsNone(host.call({'op':'boxscan','args':args})['receipt'])

    def test_engine_recovers_lost_body_after_helper_restart_then_opens_newly_dropped_boxes(self):
        with patch.object(engine,'DATA',self.root),patch.object(storage,'DATA',self.root):
            app=engine.Engine(start=False)
            try:
                (self.root/'save.zip').touch()
                app.durable['host:fixture']={'backup':{'status':'created','version':2,'path':str(self.root/'save.zip')},'cooldowns':{},'uncertain':{}}
                row={'id':'42','account':'fixture','identity':'host:fixture','status':'running','snapshot':{'at':123},
                     'box_fast_supported':True,'native_next_scan_at':time.time()+1000}
                app.instances['42']=row;first=self.host()
                class Client:
                    identity={'pid':42,'created':100,'box':''}
                    def __init__(self,host,lose=False):self.host=host;self.lose=lose
                    def call(self,op,args=None):
                        value=self.host.call({'op':op,'args':args})
                        if op=='openboxes' and self.lose:raise ConnectionResetError('lost HTTP body')
                        return value
                    def close(self):pass
                app.bridges['42']=Client(first,True);app.tick('42')
                self.assertIn('box_pending',app.durable['host:fixture'])
                first.close();app.bridges['42']=Client(self.host());self.world['queue']=2;row['next_box_scan_at']=0
                app.tick('42')
                state=app.durable['host:fixture']
                self.assertNotIn('box_pending',state);self.assertEqual(state['features']['box']['opened'],5)
                self.assertEqual(self.world['native_calls'],2);self.assertTrue(app.config['running'])
                self.assertEqual(row['snapshot']['at'],123)
            finally:app.stop()

    def test_journal_failure_warns_once_and_does_not_close_any_instance_switch(self):
        with patch.object(engine,'DATA',self.root),patch.object(storage,'DATA',self.root):
            app=engine.Engine(start=False)
            try:
                row={}
                for _ in range(3):app.observe_box_receipt_store('42',row,{'receiptPersistence':'unavailable'})
                self.assertEqual(sum(e['status']=='warning' for e in app.events),1)
                self.assertTrue(app.config['running']);self.assertFalse(app.config['instances'])
                app.observe_box_receipt_store('42',row,{'receiptPersistence':'available'})
                self.assertNotIn('box_receipt_warning',row)
            finally:app.stop()


    def test_new_game_retires_unreturned_old_batch_then_opens_its_own_queue(self):
        from dps_assistant import runtime
        with patch.object(engine,'DATA',self.root),patch.object(storage,'DATA',self.root):
            app=engine.Engine(start=False)
            try:
                (self.root/'save.zip').touch()
                app.durable['host:fixture']={'backup':{'status':'created','version':2,'path':str(self.root/'save.zip')},'cooldowns':{},'uncertain':{}}
                row={'id':'42','account':'fixture','identity':'host:fixture','status':'running','snapshot':{'at':123},
                     'box_fast_supported':True,'native_next_scan_at':time.time()+1000}
                app.instances['42']=row;first=self.host()
                class Client:
                    def __init__(self,host,created,lose=False):
                        self.host=host;self.lose=lose;self.identity={'pid':42,'created':created,'box':''}
                    def call(self,op,args=None):
                        value=self.host.call({'op':op,'args':args})
                        if op=='openboxes' and self.lose:raise ConnectionResetError('body lost')
                        return value
                    def close(self):pass
                app.bridges['42']=Client(first,100,True);app.tick('42')
                self.assertIn('box_pending',app.durable['host:fixture'])
                old_key=app.durable['host:fixture']['box_pending']['request_id']
                self.assertEqual(self.world['native_calls'],1)
                first.close();second=self.host(101)
                app.bridges['42']=Client(second,101);self.world['queue']=2;row['next_box_scan_at']=0
                with patch.object(runtime.psutil,'Process',return_value=Mock(create_time=lambda:101)):app.tick('42')
                state=app.durable['host:fixture']
                self.assertNotIn('box_pending',state)
                self.assertEqual(state['box_unresolved'][-1]['request_id'],old_key)
                self.assertEqual(state['features']['box']['opened'],2)
                self.assertEqual(state['features']['box']['confirmed'],1)
                self.assertEqual(self.world['native_calls'],2)
                self.assertEqual(self.world['queue'],0)
                self.assertNotIn(old_key,second.script.receipts)
                self.assertTrue(app.config['running']);self.assertEqual(row['snapshot']['at'],123)
            finally:app.stop()
