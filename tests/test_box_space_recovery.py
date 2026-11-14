import copy
import unittest
import test_box_throughput as fixture
from dps_assistant.boxes import archive_sealed_box_request
from dps_assistant.box_receipts import BoxReceiptStore,valid_receipt

def sealed(request='old',account='fixture',opened=0):
    return {'requestId':request,'account':account,'status':'unresolved','reason':'box_request_sealed','openedCount':opened,
            'sealed':{'schema':1,'source':'native_main_thread_fence','record':100,'counts':[10,2,1]}}

class BoxFenceTests(unittest.TestCase):
    setUp=fixture.FastBoxEngineTests.setUp
    tearDown=fixture.FastBoxEngineTests.tearDown
    advance=fixture.FastBoxEngineTests.advance

    def test_missing_receipt_recovers_with_a_real_fence_not_a_timeout_and_retains_credit(self):
        self.state['box_pending']={'request_id':'old','at':0,'credited':2,'process':{'pid':1,'created':1,'box':''}}
        self.state['features']={'box':{'opened':2,'confirmed':0}};calls=[]
        original=self.app.bridges['1'].call
        def call(op,args=None):
            if op=='boxscan':
                calls.append(args)
                result=original(op,args)
                result.update(boxRecoveryBarrier=1,bridgeSourceHash='current-script',receipt=sealed())
                return result
            return original(op,args)
        self.app.bridges['1'].call=call;self.app.tick('1')
        self.assertTrue(calls[0]['sealPending']);self.assertNotIn('box_pending',self.state)
        self.assertEqual(self.state['box_unresolved'][0]['credited'],2)
        self.assertEqual(self.state['box_unresolved_count'],1)
        self.assertEqual(self.state['features']['box']['opened'],10)
        self.assertEqual(self.state['features']['box']['confirmed'],1)
        self.assertEqual(self.queue,12);self.assertTrue(self.app.config['running'])
        self.assertEqual(self.app.instances['1']['status'],'running')

    def test_missing_wrong_or_unverified_fence_cannot_release_unknown(self):
        original=self.app.bridges['1'].call
        for mode in ('missing','wrong_request','wrong_account','no_marker','no_hash'):
            self.state['box_pending']={'request_id':'old','at':0,'credited':0}
            def call(op,args=None):
                result=original(op,args)
                if op=='boxscan':
                    result.update(boxRecoveryBarrier=1,bridgeSourceHash='current',receipt=sealed())
                    if mode=='missing':result['receipt']=None
                    if mode=='wrong_request':result['receipt']['requestId']='other'
                    if mode=='wrong_account':result['receipt']['account']='other'
                    if mode=='no_marker':result.pop('boxRecoveryBarrier')
                    if mode=='no_hash':result.pop('bridgeSourceHash')
                return result
            self.app.bridges['1'].call=call;self.advance();self.app.tick('1')
            self.assertIn('box_pending',self.state,mode);self.assertEqual(self.queue,20,mode)

    def test_lost_prefix_reply_is_credited_once_and_unknown_tail_is_archived(self):
        self.state['box_pending']={'request_id':'old','at':0,'credited':0};original=self.app.bridges['1'].call
        def call(op,args=None):
            result=original(op,args)
            if op=='boxscan':
                result.update(boxRecoveryBarrier=1,bridgeSourceHash='current',receipt=sealed(opened=2),
                    prefixReceipt={'requestId':'old','account':'fixture','status':'pending','openedCount':2,'pendingRecord':100})
            return result
        self.app.bridges['1'].call=call;self.app.tick('1')
        self.assertEqual(self.state['box_unresolved'][0]['credited'],2)
        self.assertEqual(self.state['features']['box']['opened'],10)
        self.assertEqual(self.state['features']['box']['confirmed'],1)

    def test_legacy_box_only_reservation_is_released_by_native_barrier_and_other_consumption_is_preserved(self):
        self.state['uncertain']={'box:0:100':0,'combine:old':0};original=self.app.bridges['1'].call
        def call(op,args=None):
            result=original(op,args)
            if op=='boxscan':result.update(boxRecoveryBarrier=1,bridgeSourceHash='current')
            return result
        self.app.bridges['1'].call=call;self.app.tick('1')
        self.assertNotIn('box:0:100',self.state['uncertain']);self.assertIn('combine:old',self.state['uncertain'])
        self.assertEqual(self.queue,12)

    def test_fence_tombstone_survives_disk_reload_and_rejects_late_old_pending(self):
        store=BoxReceiptStore(42,100,self.path/'receipt-fences')
        self.assertTrue(store.checkpoint(sealed()))
        next_store=BoxReceiptStore(42,100,self.path/'receipt-fences')
        self.assertEqual(next_store.restore(),[sealed()])
        self.assertFalse(next_store.checkpoint({'requestId':'old','account':'fixture','status':'pending','openedCount':0,'pendingRecord':100}))
        self.assertFalse(valid_receipt({**sealed(),'sealed':{'source':'elapsed_time','schema':1}}))

    def test_fence_tombstone_is_not_evicted_by_normal_receipt_cache_turnover(self):
        store=BoxReceiptStore(42,100,self.path/'receipt-turnover');self.assertTrue(store.checkpoint(sealed()))
        for n in range(40):
            self.assertTrue(store.checkpoint({'requestId':str(n),'account':'fixture','status':'confirmed','openedCount':1}))
        restored=BoxReceiptStore(42,100,self.path/'receipt-turnover')
        self.assertTrue(any(r['requestId']=='old' for r in restored.restore()))
        self.assertFalse(restored.checkpoint({'requestId':'old','account':'fixture','status':'pending','openedCount':0,'pendingRecord':100}))

    def test_legacy_pending_without_time_gets_one_observation_clock_before_sealing(self):
        self.state['box_pending']={'request_id':'old','credited':0};original=self.app.bridges['1'].call;queries=[]
        def call(op,args=None):
            result=original(op,args)
            if op=='boxscan':queries.append(args)
            return result
        self.app.bridges['1'].call=call;self.app.tick('1')
        self.assertFalse(queries[0]['sealPending']);self.assertIn('at',self.state['box_pending'])
        self.assertEqual(self.queue,20)

    def test_fence_archive_does_not_credit_unknown_openings_or_touch_unrelated_state(self):
        state={'box_pending':{'request_id':'old','credited':2},'features':{'box':{'opened':2,'confirmed':0}},'confirmed':9,'uncertain':{'forge:old':1}}
        previous=copy.deepcopy(state);self.assertIsNotNone(archive_sealed_box_request(state,sealed(opened=8),'fixture',100))
        for name in ('features','confirmed','uncertain'):self.assertEqual(state[name],previous[name])
        self.assertIsNone(archive_sealed_box_request(state,sealed(),'fixture',200))
        self.assertEqual(state['box_unresolved_count'],1)

if __name__=='__main__':unittest.main()
