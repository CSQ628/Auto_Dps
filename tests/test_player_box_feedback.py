"""Player failure paths keep switches on and recover only proven unsent requests."""
import copy
import json
import unittest
from unittest.mock import patch
import test_box_throughput as box_fixture
from test_bridge_readiness import client
from dps_assistant import runtime
from dps_assistant.boxes import box_status


class PlayerBoxFeedbackTests(unittest.TestCase):
    setUp=box_fixture.FastBoxEngineTests.setUp
    tearDown=box_fixture.FastBoxEngineTests.tearDown
    advance=box_fixture.FastBoxEngineTests.advance

    def test_multiple_unsent_responses_retry_until_success_without_pausing_or_double_consumption(self):
        original=self.app.bridges['1'].call;attempts=[]
        def call(op,args=None):
            if op=='openboxes':
                attempts.append(args['requestId'])
                if len(attempts)<3:
                    self.receipt={'requestId':args['requestId'],'account':'fixture','status':'waiting',
                                  'reason':'native_request_not_started','executionState':'not_started','openedCount':0}
                    return self.receipt
            return original(op,args)
        self.app.bridges['1'].call=call
        for _ in range(3):
            self.advance();self.state['box_retry_at']=0;self.app.tick('1')
            self.assertNotIn('box_pending',self.state)
            self.assertEqual(self.row['status'],'running')
            self.assertTrue(self.app.config['running']);self.assertFalse(self.app.config['instances'])
        self.assertEqual(len(set(attempts)),3);self.assertEqual(self.queue,12)
        self.assertEqual(self.state['features']['box']['opened'],8)
        restarted=type(self.app)(start=False)
        try:
            self.assertNotIn('box_pending',restarted.durable['host:fixture'])
            self.assertTrue(restarted.config['running'])
        finally:restarted.stop()

    def test_repeated_read_failures_remain_enabled_back_off_and_recover_automatically(self):
        original=self.app.bridges['1'].call;attempts=[]
        def call(op,args=None):
            if op=='boxscan' and len(attempts)<7:
                attempts.append(True);raise ConnectionResetError('transient connection')
            return original(op,args)
        self.app.bridges['1'].call=call
        delays=[]
        for _ in range(7):
            self.advance();self.app.tick('1');delays.append(self.row['box_retry']['delay'])
            self.assertEqual(self.row['status'],'running');self.assertNotIn('box_pending',self.state)
            self.assertTrue(self.app.config['running']);self.assertFalse(self.app.config['instances'])
        self.assertEqual(delays,[2,4,8,16,30,30,30]);self.assertEqual(self.queue,20)
        self.advance();self.app.tick('1');self.assertEqual(self.queue,12)
        self.assertNotIn('box_retry',self.row);self.assertNotIn('box_error',self.row)
        self.assertTrue(any(e.get('result',{}).get('reason')=='box_connection_recovered' for e in self.app.events))

    def test_six_sandbox_accounts_isolate_failed_connection_manual_pause_and_healthy_boxes(self):
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace
        calls=[]
        for n in range(2,8):
            key=str(n);account='player'+key;identity='sandbox'+key+':'+account
            snap=copy.deepcopy(self.snap);snap['account']=account
            def call(op,args=None,n=n,snap=snap):
                if n==2:raise ConnectionResetError('one sandbox unavailable')
                if op=='boxscan':return {'snapshot':copy.deepcopy(snap),'scanMs':1,
                    'actions':[{'kind':'box','key':'box:0:100','priority':99}],'issues':[]}
                if op=='openboxes':
                    calls.append(n);return {'requestId':args['requestId'],'status':'confirmed','openedCount':1}
                raise AssertionError(op)
            self.app.bridges[key]=SimpleNamespace(identity={'pid':n,'created':100+n,'box':'sandbox'+key},call=call,close=lambda:None)
            self.app.instances[key]={'id':key,'identity':identity,'account':account,'status':'running',
                                     'snapshot':snap,'box_fast_supported':True}
            self.app.durable[identity]={'backup':self.state['backup'],'uncertain':{},'cooldowns':{}}
        self.app.update({'instances':{'sandbox3:player3':False}})
        before=copy.deepcopy(self.app.config)
        with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(self.app.tick_boxes,map(str,range(2,8))))
        self.assertEqual(sorted(calls),[4,5,6,7]);self.assertEqual(self.app.config,before)
        self.assertEqual(self.app.instances['2']['box_status']['reason'],'box_connection_retry')
        self.assertEqual(self.app.instances['2']['status'],'running')
        for n in range(4,8):self.assertEqual(self.app.durable['sandbox'+str(n)+':player'+str(n)]['features']['box']['opened'],1)

    def test_empty_queue_does_not_hide_an_unknown_consumption_receipt(self):
        scan={'snapshot':{'boxes':{'total':0,'freeSlots':5}},'actions':[]}
        self.assertEqual(box_status(scan,self.app.config,{'box_pending':{'request_id':'lost'}},[],100)['reason'],'box_result_unconfirmed')

    def test_waiting_condition_logs_once_then_emits_recovery_without_disabling(self):
        self.row['box_status']={'reason':'native_sync_backlog','total':10,'freeSlots':8}
        for _ in range(10):self.app.observe_box_wait('1',self.row)
        waiting=[e for e in self.app.events if e.get('result',{}).get('reason')=='native_sync_backlog']
        self.assertEqual(len(waiting),1);self.assertTrue(waiting[0]['result']['automationContinues'])
        self.row['box_status']['reason']='box_ready';self.app.observe_box_wait('1',self.row)
        self.assertNotIn('box_wait_reason',self.row);self.assertTrue(self.app.config['running'])

    def test_box_observation_uses_three_transport_attempts_but_openboxes_is_never_replayed(self):
        bridge=client(1);bridge.wait_ready=lambda:None
        with patch.object(runtime,'post',side_effect=[ConnectionResetError('first'),TimeoutError('second'),{'snapshot':{}}]) as post:
            self.assertEqual(bridge.call('boxscan',{}),{'snapshot':{}})
            self.assertEqual(post.call_count,3)
            self.assertEqual([c.kwargs['prefer_native'] for c in post.call_args_list],[True,False,True])
        with patch.object(runtime,'post',side_effect=TimeoutError('reply unknown')) as post:
            with self.assertRaises(TimeoutError):bridge.call('openboxes',{})
            self.assertEqual(post.call_count,1)

    def test_user_pause_still_blocks_retries_and_is_explicitly_logged(self):
        self.app.update({'instances':{'host:fixture':False}})
        for _ in range(5):self.advance();self.app.tick('1')
        self.assertFalse(self.calls);self.assertFalse(self.app.config['instances']['host:fixture'])
        self.assertTrue(any(e.get('result',{}).get('reason')=='manual_instance_pause' for e in self.app.events))


class LostCancellationReceiptTests(unittest.TestCase):
    def test_cancelled_before_native_is_saved_even_if_the_http_reply_is_lost(self):
        import test_durable_box_receipts as fixture
        context=fixture.HostReceiptRecoveryTests('runTest');context.setUp()
        try:
            first=context.host();cmd={'requestId':'unsent','account':'fixture'}
            r={'requestId':'unsent','account':'fixture','status':'waiting','openedCount':0,
               'reason':'native_request_not_started','executionState':'not_started','observations':[]}
            def lose_reply(args):
                first.script_message({'type':'send','payload':{'channel':'box_receipt','receipt':r}},None)
                raise ConnectionResetError('lost HTTP delivery')
            first.script.openboxes=lose_reply
            with self.assertRaises(ConnectionResetError):first.call({'op':'openboxes','args':cmd})
            first.close();restored=context.host().call({'op':'boxscan','args':cmd})['receipt']
            self.assertEqual(restored['executionState'],'not_started')
            self.assertEqual(restored['openedCount'],0);self.assertEqual(context.world['native_calls'],0)
        finally:context.tearDown()
