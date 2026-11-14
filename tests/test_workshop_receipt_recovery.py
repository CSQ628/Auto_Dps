import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from dps_assistant import engine, storage, workshop_receipts
from dps_assistant.workshop_receipts import WorkshopReceiptStore
from tools.bridge_host import BridgeHost
import test_scheduler
from test_workshop_receipt_reservations import action


def receipt(request='request', status='confirmed', kind='combine'):
    return {'requestId':request,'account':'1001','kind':kind,'key':'workshop:old',
            'signature':'a'*64,'at':100,'result':{'status':status}}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def store(self,created=100):
        return WorkshopReceiptStore(42,created,self.root)
    def test_exact_process_lifetime_and_pending_terminal_progression(self):
        first=self.store();self.assertTrue(first.checkpoint(receipt(status='pending')))
        self.assertTrue(first.checkpoint(receipt()));self.assertEqual(self.store().restore(),[receipt()])
        self.assertFalse(first.checkpoint(receipt(status='pending')))
        self.assertEqual(self.store(101).restore(),[])
        for field,value in (('account','other'),('kind','forge'),('key','new'),('signature','b'*64)):
            self.assertFalse(first.checkpoint({**receipt(),field:value}))
        self.assertEqual(first.restore(),[receipt()])
    def test_corruption_is_preserved_and_never_authorizes_replay(self):
        first=self.store();first.path.parent.mkdir(exist_ok=True);first.path.write_text('{broken',encoding='utf-8')
        next_store=self.store();self.assertTrue(next_store.failed);self.assertEqual(next_store.restore(),[])
        self.assertEqual(first.path.read_text(encoding='utf-8'),'{broken')
    def test_disk_failure_keeps_previous_state_then_recovers(self):
        first=self.store();self.assertTrue(first.checkpoint(receipt(status='pending')))
        with patch.object(workshop_receipts,'atomic_json',side_effect=OSError('disk full')):
            self.assertFalse(first.checkpoint(receipt()))
        self.assertTrue(first.failed);self.assertEqual(first.restore()[0]['result']['status'],'pending')
        self.assertTrue(first.checkpoint(receipt()));self.assertFalse(first.failed)
        self.assertEqual(self.store().restore()[0]['result']['status'],'confirmed')
    def test_finished_retention_never_discards_unresolved_requests(self):
        first=self.store();self.assertTrue(first.checkpoint(receipt('pending',status='pending')))
        for n in range(45):self.assertTrue(first.checkpoint(receipt('done-'+str(n))))
        self.assertLessEqual(len(first.restore()),32)
        self.assertIn('pending',[r['requestId'] for r in self.store().restore()])
    def test_nonfinite_oversized_and_malformed_receipts_cannot_be_restored(self):
        for value in ({**receipt(),'at':float('nan')},{**receipt(),'requestId':'bad/path'},
                      {**receipt(),'result':{'status':'confirmed','private':'x'*(256*1024)}},
                      {**receipt(),'result':{'status':'unknown'}}):
            self.assertFalse(self.store().checkpoint(value))


class NativeScript:
    def __init__(self,world):self.world=world;self.rows={};self.exports_sync=self;self.message=None
    def on(self,event,callback):self.message=callback
    def load(self):pass
    def unload(self):pass
    def dispose(self):pass
    def list_exports_sync(self):return ['opportunities','execute','restoreworkshopreceipts','workshopreceipt']
    def restoreworkshopreceipts(self,rows):self.rows={r['requestId']:copy.deepcopy(r) for r in rows}
    def opportunities(self,args):return copy.deepcopy(self.world['scan'])
    def workshopreceipt(self,query):
        r=self.rows.get(query['requestId'])
        return copy.deepcopy(r) if r and all(r[k]==v for k,v in query.items()) else None
    def execute(self,args):
        if args['kind'] not in workshop_receipts.KINDS:
            self.world['other_calls']+=1;return {'status':'confirmed'}
        self.world['before_native'](args)
        request=args['requestId']
        if request in self.rows:return {**copy.deepcopy(self.rows[request]['result']),'workshopReceipt':copy.deepcopy(self.rows[request])}
        self.world['native_calls']+=1
        r={**receipt(request,self.world['status'],args['kind']),'key':args['key']}
        self.rows[request]=copy.deepcopy(r)
        # The real JS wrapper emits before delivery; the production host callback
        # and its synchronous return checkpoint must both accept the same reply.
        self.message({'type':'send','payload':{'channel':'workshop_receipt','receipt':copy.deepcopy(r)}},None)
        if self.world.get('raise_after_message'):raise RuntimeError('RPC completion lost')
        return {**r['result'],'workshopReceipt':copy.deepcopy(r)}


class NativeSession:
    def __init__(self,script):self.script=script
    def on(self,*args):pass
    def create_script(self,*args):return self.script
    def detach(self):pass


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.harness=test_scheduler.SchedulerTests();self.harness.setUp();self.addCleanup(self.harness.tearDown)
        self.bridge=self.harness.add();self.original=self.bridge.call
        self.world={'scan':test_scheduler.scan(),'native_calls':0,'other_calls':0,'status':'confirmed','before_native':self.before_native}
        self.root=engine.DATA;self.source=self.root/'source';(self.source/'bridge').mkdir(parents=True)
        (self.source/'bridge/automation.js').write_text('fixture',encoding='utf-8');self.hosts=[]
        self.addCleanup(self.close_hosts)
    def close_hosts(self):
        for host in self.hosts:host.close()
    def before_native(self,args):
        saved=storage.load_json(engine.DATA/'scheduler.json',{})['host:1001']['pending_results'][args['key']]
        self.assertEqual(saved['request_id'],args['requestId'])
        self.assertEqual(saved['process'],{'pid':1,'created':1.0})
    def host(self,created=1):
        script=NativeScript(self.world)
        host=BridgeHost(1,self.source,lambda _:NativeSession(script),process_created=created,workshop_receipt_directory=self.root/'receipts')
        with patch('tools.bridge_host.psutil.Process',return_value=Mock(create_time=lambda:created)):host.initialize()
        self.assertEqual(host.health()['phase'],'ready');self.hosts.append(host);return host
    def connect(self,host,lose=False):
        def call(op,args=None):
            if op=='backup':return self.original(op,args)
            result=host.call({'op':op,'args':args})
            if op=='execute' and lose:raise ConnectionResetError('lost HTTP body')
            return result
        self.bridge.call=call
    def test_host_checkpoints_before_http_and_engine_recovers_each_consumption_once(self):
        for kind in ('combine','forge','refine','decompose'):
            with self.subTest(kind=kind):
                self.world['scan']['actions']=[action(kind,key='workshop:'+kind)]
                first=self.host();self.connect(first,lose=True);self.harness.engine.tick('1')
                state=self.harness.engine.durable['host:1001'];pending=state['pending_results']['workshop:'+kind]
                request=pending['request_id'];self.assertTrue(first.workshop_store.path.is_file())
                first.close();second=self.host();self.connect(second)
                self.world['scan']['actions']=[];self.harness.engine.durable=storage.load_json(engine.DATA/'scheduler.json',{})
                self.harness.engine.tick('1');state=self.harness.engine.durable['host:1001']
                self.assertNotIn('workshop:'+kind,state['pending_results']);self.assertEqual(state['features'][kind]['confirmed'],1)
                calls=self.world['native_calls'];self.harness.engine.tick('1');self.assertEqual(self.world['native_calls'],calls)
                recovered=[e for e in self.harness.engine.events if e.get('action',{}).get('kind')==kind and e.get('result',{}).get('source')=='durable_workshop_receipt']
                self.assertEqual(len(recovered),1);self.assertTrue(self.harness.engine.config['running'])
                self.assertEqual(second.script.workshopreceipt({'requestId':request,'account':'other','kind':kind,'key':'workshop:'+kind}),None)
        self.assertEqual(self.world['native_calls'],4)
    def test_read_only_refine_revalidation_is_checkpointed_and_settled_once_after_restart(self):
        self.world['status']='pending';self.world['scan']['actions']=[action('refine')]
        first=self.host();self.connect(first);self.harness.engine.tick('1')
        pending=first.workshop_store.restore()[0];first.close()
        second=self.host();self.connect(second);original=second.script.workshopreceipt
        def query(args):
            value=original(args)
            if value and value['result']['status']=='pending':
                value['result']={'status':'confirmed','recoveryEvidence':{'source':'native_refine_revalidated',
                    'originalStatus':'pending','originalProtectedChanged':[{'uid':'target'}]}}
                second.script.rows[value['requestId']]=copy.deepcopy(value)
            return value
        second.script.workshopreceipt=query
        self.world['scan']['actions']=[];self.harness.engine.tick('1')
        state=self.harness.engine.durable['host:1001'];self.assertFalse(state['pending_results'])
        self.assertEqual(state['features']['refine']['confirmed'],1);self.assertEqual(self.world['native_calls'],1)
        saved=WorkshopReceiptStore(1,1,self.root/'receipts').restore()[0]
        self.assertEqual(saved['requestId'],pending['requestId']);self.assertEqual(saved['result']['status'],'confirmed')
        self.assertEqual(saved['result']['recoveryEvidence']['originalStatus'],'pending')
        second.close();self.connect(self.host());self.harness.engine.durable=storage.load_json(engine.DATA/'scheduler.json',{})
        self.harness.engine.tick('1');self.assertEqual(self.world['native_calls'],1)
        self.assertEqual(self.harness.engine.durable['host:1001']['features']['refine']['confirmed'],1)

    def test_refine_revalidation_checkpoint_failure_retains_previous_durable_pending_reply(self):
        self.world['status']='pending';self.world['scan']['actions']=[action('refine')]
        host=self.host();self.connect(host);self.harness.engine.tick('1')
        old=host.workshop_store.restore()[0];updated=copy.deepcopy(old)
        updated['result']={'status':'confirmed','recoveryEvidence':{'source':'native_refine_revalidated','originalStatus':'pending'}}
        host.script.workshopreceipt=lambda query:copy.deepcopy(updated)
        query={k:old[k] for k in ('requestId','account','kind','key')}
        with patch.object(workshop_receipts,'atomic_json',side_effect=OSError('disk full')):
            reply=host.call({'op':'workshopreceipt','args':query})
        self.assertEqual(reply['result']['status'],'confirmed');self.assertTrue(host.workshop_store.failed)
        self.assertEqual(WorkshopReceiptStore(1,1,self.root/'receipts').restore()[0]['result']['status'],'pending')
        self.assertTrue(self.harness.engine.durable['host:1001']['pending_results'])
        host.call({'op':'workshopreceipt','args':query});self.assertFalse(host.workshop_store.failed)
        self.assertEqual(WorkshopReceiptStore(1,1,self.root/'receipts').restore()[0]['result']['status'],'confirmed')
        self.assertEqual(self.world['native_calls'],1)

    def test_unknown_native_result_survives_restart_while_independent_growth_continues(self):
        self.world['status']='pending';self.world['scan']['actions']=[action()]
        first=self.host();self.connect(first,lose=True);self.harness.engine.tick('1');first.close()
        self.connect(self.host());self.world['scan']['actions']=[action(key='changed-key'),test_scheduler.scan()['actions'][0]]
        self.harness.engine.tick('1');state=self.harness.engine.durable['host:1001']
        self.assertIn('workshop:old',state['pending_results']);self.assertEqual(self.world['native_calls'],1)
        self.assertEqual(self.world['other_calls'],1);self.assertTrue(self.harness.engine.config['running'])
    def test_native_message_saves_a_completed_reply_even_when_the_rpc_never_returns(self):
        self.world['raise_after_message']=True;self.world['scan']['actions']=[action()]
        first=self.host();self.connect(first);self.harness.engine.tick('1')
        self.assertEqual(first.workshop_store.restore()[0]['result']['status'],'confirmed')
        first.close();self.connect(self.host());self.world['scan']['actions']=[];self.harness.engine.tick('1')
        state=self.harness.engine.durable['host:1001'];self.assertFalse(state['pending_results'])
        self.assertEqual(state['features']['combine']['confirmed'],1);self.assertEqual(self.world['native_calls'],1)
    def test_different_game_lifetime_and_missing_receipts_never_release_materials(self):
        self.world['scan']['actions']=[action()];first=self.host();self.connect(first,lose=True);self.harness.engine.tick('1');first.close()
        self.bridge.identity['created']=2;self.connect(self.host(2));self.world['scan']['actions']=[action(key='changed')]
        self.harness.engine.tick('1');self.assertIn('workshop:old',self.harness.engine.durable['host:1001']['pending_results'])
        self.assertEqual(self.world['native_calls'],1)
    def test_lookup_failure_logs_once_and_does_not_block_independent_actions(self):
        self.world['status']='pending';self.world['scan']['actions']=[action()];self.connect(self.host());self.harness.engine.tick('1')
        current=self.bridge.call
        def call(op,args=None):
            if op=='workshopreceipt':raise TimeoutError('unavailable')
            return current(op,args)
        self.bridge.call=call;self.world['scan']['actions']=[test_scheduler.scan()['actions'][0]]
        for _ in range(3):self.harness.engine.tick('1')
        warnings=[e for e in self.harness.engine.events if e.get('result',{}).get('reason')=='workshop_receipt_lookup_unavailable']
        self.assertEqual(len(warnings),1);self.assertEqual(self.world['other_calls'],1)
        self.assertTrue(self.harness.engine.config['running'])
    def test_mismatched_receipt_never_confirms_another_request(self):
        self.world['status']='pending';self.world['scan']['actions']=[action()];self.connect(self.host());self.harness.engine.tick('1')
        current=self.bridge.call
        def call(op,args=None):return receipt('other') if op=='workshopreceipt' else current(op,args)
        self.bridge.call=call;self.world['scan']['actions']=[];self.harness.engine.tick('1')
        self.assertIn('workshop:old',self.harness.engine.durable['host:1001']['pending_results'])
    def test_explicit_rejection_lost_in_transport_releases_without_immediate_replay(self):
        self.world['status']='rejected';self.world['scan']['actions']=[action()];first=self.host();self.connect(first,lose=True)
        self.harness.engine.tick('1');first.close();self.connect(self.host());self.harness.engine.tick('1')
        state=self.harness.engine.durable['host:1001'];self.assertFalse(state['pending_results']);self.assertEqual(self.world['native_calls'],1)
        self.assertEqual(state['features']['combine']['last_status'],'rejected')
    def test_bounded_lookup_rotates_past_unresolved_requests_to_a_completed_reply(self):
        host=self.host();self.connect(host);self.world['scan']['actions']=[]
        self.harness.engine.tick('1');state=self.harness.engine.durable['host:1001']
        for n in range(5):
            key='workshop:'+str(n);request='request-'+str(n)
            state.setdefault('pending_results',{})[key]={'action':action(uid='material-'+str(n),key=key),'at':100,
                'request_id':request,'process':{'pid':1,'created':1.0}}
            host.script.rows[request]={**receipt(request,'confirmed' if n==4 else 'pending'),'key':key}
        self.harness.engine.tick('1');self.assertEqual(len(state['pending_results']),5)
        self.harness.engine.tick('1');self.assertEqual(len(state['pending_results']),4)
        self.assertNotIn('workshop:4',state['pending_results']);self.assertEqual(self.world['native_calls'],0)
    def test_store_warning_deduplicates_and_diagnostics_remain_private(self):
        row={}
        for _ in range(3):self.harness.engine.observe_workshop_store('1',row,{'workshopReceiptPersistence':'unavailable'})
        warnings=[e for e in self.harness.engine.events if e.get('result',{}).get('reason')=='workshop_receipt_store_unavailable']
        self.assertEqual(len(warnings),1);self.harness.engine.observe_workshop_store('1',row,{'workshopReceiptPersistence':'available'})
        self.assertNotIn('workshop_receipt_warning',row)
        from dps_assistant.diagnostics import diagnostics
        result=diagnostics({'instances':[{**row,'request_id':'private-request','account':'private-account'}]})
        self.assertEqual(result['instances'][0]['workshop_receipt_persistence'],'available');self.assertNotIn('private',str(result))


if __name__=='__main__':unittest.main()
