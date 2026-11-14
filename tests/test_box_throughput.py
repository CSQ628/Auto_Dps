"""Loot cadence, batch accounting and durable outcome recovery."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dps_assistant import engine,storage
from dps_assistant.boxes import apply_box_receipt,settle_legacy_boxes


class BoxReceiptTests(unittest.TestCase):
    def test_partial_confirmation_and_later_settlement_credit_each_box_once(self):
        state={'box_pending':{'request_id':'batch','credited':0}}
        receipt={'requestId':'batch','status':'pending','openedCount':2}
        self.assertEqual(apply_box_receipt(state,receipt,100)['delta'],2)
        self.assertEqual(apply_box_receipt(state,receipt,101)['delta'],0)
        state=json.loads(json.dumps(state))
        self.assertEqual(apply_box_receipt(state,{**receipt,'status':'confirmed','openedCount':3},102)['delta'],1)
        self.assertEqual(state['features']['box']['opened'],3)
        self.assertEqual(state['features']['box']['confirmed'],1)
        self.assertEqual(state['confirmed'],1)
        self.assertNotIn('box_pending',state)
        self.assertIsNone(apply_box_receipt(state,receipt,103))

    def test_missing_or_unrelated_receipt_never_releases_a_lost_reply(self):
        state={'box_pending':{'request_id':'batch','credited':2}}
        for receipt in (None,{'requestId':'wrong','status':'confirmed','openedCount':3},
                        {'requestId':'batch','status':'confirmed','openedCount':1}):
            before=copy.deepcopy(state);self.assertIsNone(apply_box_receipt(state,receipt,999999));self.assertEqual(state,before)

    def test_old_single_open_is_held_across_new_grade_or_empty_queue_until_record_grows(self):
        state={'uncertain':{'box:0:100':1,'equipment:fixture':1}}
        settle_legacy_boxes(state,100);self.assertIn('box:0:100',state['uncertain'])
        settle_legacy_boxes(state,101);self.assertNotIn('box:0:100',state['uncertain']);self.assertIn('equipment:fixture',state['uncertain'])


class FastBoxEngineTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)
        self.patches=[patch.object(engine,'DATA',self.path),patch.object(storage,'DATA',self.path)]
        for p in self.patches:p.start()
        self.app=engine.Engine(start=False);self.backup=self.path/'save.zip';self.backup.write_bytes(b'fixture')
        self.calls=[];self.receipt=None;self.pending=False;self.lost=False;self.queue=20;self.record=100
        self.snap={'account':'fixture','loaded':True,'inventory':{'count':0,'capacity':50},
                   'boxes':{'counts':[20,0,0],'total':20,'freeSlots':50},'record':{'boxes':100},'at':123,
                   'connection':{'online':True},'sync':{},'automationBlocked':[],'manualBlockedKinds':[]}
        outer=self
        class Bridge:
            identity={'pid':1,'created':1,'box':''}
            def call(self,op,args=None):
                outer.calls.append(op)
                if op=='boxscan':
                    snap=copy.deepcopy(outer.snap);snap['record']['boxes']=outer.record
                    snap['boxes'].update(total=outer.queue,counts=[outer.queue,0,0])
                    actions=[{'kind':'box','key':'box:0:'+str(outer.record),'priority':99}] if outer.queue else []
                    return {'snapshot':snap,'runtime':{'ready':True,'maintenance':{'active':False}},'actions':actions,'scanMs':2,'receipt':outer.receipt}
                if op=='openboxes':
                    outer.assertIn('box_pending',outer.app.durable['host:fixture'])
                    outer.assertEqual(outer.app.durable['host:fixture']['box_pending']['process'],self.identity)
                    n=min(8,outer.queue);outer.queue-=n;outer.record+=n
                    outer.receipt={'requestId':args['requestId'],'status':'pending' if outer.pending else 'confirmed','openedCount':n}
                    if outer.lost:raise OSError('lost reply')
                    return copy.deepcopy(outer.receipt)
                raise AssertionError('Unexpected expensive call '+op)
            def close(self):pass
        self.app.bridges['1']=Bridge()
        self.row={'id':'1','status':'running','account':'fixture','identity':'host:fixture','snapshot':copy.deepcopy(self.snap),
                  'box_fast_supported':True,'native_next_scan_at':time.time()+1000}
        self.app.instances['1']=self.row
        self.state={'backup':{'status':'created','version':2,'path':str(self.backup)},'uncertain':{},'cooldowns':{}}
        self.app.durable['host:fixture']=self.state

    def tearDown(self):
        self.app.stop()
        for p in reversed(self.patches):p.stop()
        self.folder.cleanup()

    def advance(self):self.row['next_box_scan_at']=0

    def test_fast_lane_drains_queues_during_full_scan_backoff_without_freshening_exp_clock(self):
        for _ in range(3):self.advance();self.app.tick('1')
        self.assertEqual(self.queue,0);self.assertEqual(self.state['features']['box']['opened'],20)
        self.assertNotIn('opportunities',self.calls);self.assertNotIn('execute',self.calls)
        self.assertEqual(self.row['snapshot']['at'],123)
        self.assertEqual(self.row['effective_scan_interval'] if 'effective_scan_interval' in self.row else None,None)

    def test_repeated_tick_inside_one_second_does_not_repoll_or_consume(self):
        self.app.tick('1');self.app.tick('1');self.assertEqual(self.calls,['boxscan','openboxes'])

    def test_a_fast_batch_does_not_take_the_due_normal_growth_turn(self):
        self.snap.update(currencies={'soul':100,'premium':2},stage={'category':0,'level':159,'difficulty':0,'running':True,'repeat':True,'ending':False,'alivePlayers':1},
                         catalogue={'normalMax':160,'towerMax':20,'characterMax':101},squad=[1],characters=[{'id':1,'level':80,'expTotal':100}],
                         progression={'farmCandidates':[{'level':159,'difficulty':0}]})
        self.snap['record'].update(maxCleared=160,maxStage=160,towerMaxCleared=1,deaths=0,normalClears=10,normalFails=0)
        rune={'kind':'rune','key':'rune-fixture','header':'NormalMonster','priority':60,'label':'成长刻印','cost':{'goods':201,'amount':1}}
        original=self.app.bridges['1'].call
        def call(op,args=None):
            if op=='opportunities':
                self.calls.append(op)
                return {'snapshot':copy.deepcopy(self.snap),'boxFastPath':1,'actions':[rune,{'kind':'box','key':'box:0:108','priority':99}],'issues':[]}
            if op=='execute':self.calls.append('execute:'+args['kind']);return {'status':'confirmed'}
            return original(op,args)
        self.app.bridges['1'].call=call;self.row['native_next_scan_at']=0
        self.app.tick('1')
        self.assertEqual(self.calls,['boxscan','openboxes','opportunities','execute:rune'])
        self.assertEqual(self.state['features']['rune']['confirmed'],1)

    def test_lost_reply_is_recovered_by_receipt_without_repeating_consumption(self):
        self.lost=True;self.app.tick('1');self.assertIn('box_pending',self.state)
        self.lost=False;self.queue=0;self.advance();self.app.tick('1')
        self.assertNotIn('box_pending',self.state);self.assertEqual(self.calls.count('openboxes'),1)
        self.assertEqual(self.state['features']['box']['opened'],8)

    def test_bridge_restart_without_receipt_keeps_durable_reservation_even_when_record_grows(self):
        self.lost=True;self.app.tick('1');self.receipt=None;self.record+=100
        self.advance();self.app.tick('1');self.assertIn('box_pending',self.state);self.assertEqual(self.calls.count('openboxes'),1)

    def test_pauses_disabled_instance_and_duplicate_account_prevent_fast_calls(self):
        for kind in ('global','module','instance','duplicate','backup'):
            config=copy.deepcopy(self.app.config);others=copy.deepcopy(self.app.instances)
            if kind=='global':self.app.config['running']=False
            if kind=='module':self.app.config['modules']['box']=False
            if kind=='instance':self.app.config['instances']['host:fixture']=False
            if kind=='duplicate':self.app.instances['2']={'account':'fixture','status':'running'}
            if kind=='backup':self.state['backup']['status']='required'
            self.advance();self.app.tick('1');self.assertEqual(self.calls,[],kind)
            self.app.config=config;self.app.instances=others;self.state['backup']['status']='created'

    def test_legacy_unknown_single_result_blocks_all_grades_in_fast_lane(self):
        self.state['uncertain']['box:2:100']=1
        self.app.tick('1');self.assertEqual(self.calls,['boxscan'])


    def test_queued_batch_records_its_exact_game_lifetime_before_native_submission(self):
        self.lost=True
        self.app.tick('1')
        self.assertEqual(self.state['box_pending'].get('process'),{'pid':1,'created':1,'box':''})

    def test_ended_game_archives_unknown_batch_and_resumes_current_queue_without_old_credit(self):
        self.state['box_pending']={'request_id':'old','credited':2,'at':1,'record_before':100,
                                   'process':{'pid':1,'created':1,'box':''}}
        self.state['features']={'box':{'confirmed':0,'opened':2}}
        self.app.bridges['1'].identity={'pid':1,'created':2,'box':''}
        self.queue=10;self.record=103
        with patch.object(engine,'process_lifetime_status',return_value='absent',create=True) as probe:
            self.app.tick('1')
        self.assertEqual(self.calls,['boxscan','openboxes'])
        probe.assert_called_once_with({'pid':1,'created':1,'box':''})
        self.assertEqual(self.state['features']['box']['opened'],10)
        self.assertEqual(self.state['features']['box']['confirmed'],1)
        self.assertNotIn('box_pending',self.state)
        history=self.state['box_unresolved']
        self.assertEqual(history[-1]['request_id'],'old')
        self.assertEqual(history[-1]['reason'],'origin_process_ended')
        self.assertEqual(history[-1]['credited'],2)
        self.assertEqual(self.state['box_unresolved_count'],1)
        self.assertTrue(any(e['status']=='warning' and e.get('result',{}).get('reason')=='box_origin_process_ended' for e in self.app.events))
        self.assertTrue(self.app.config['running']);self.assertFalse(self.app.config['instances'])
        self.assertEqual(self.row['snapshot']['at'],123)
        restarted=engine.Engine(start=False)
        try:
            saved=restarted.durable['host:fixture']
            self.assertNotIn('box_pending',saved)
            self.assertEqual(saved['box_unresolved'][-1]['request_id'],'old')
            self.assertEqual(saved['features']['box']['opened'],10)
        finally:restarted.stop()
        # An old late body cannot credit the abandoned batch again.
        self.assertIsNone(apply_box_receipt(self.state,{'requestId':'old','status':'confirmed','openedCount':3},999))
        self.assertEqual(self.state['features']['box']['opened'],10)

    def test_live_or_unverifiable_origin_and_same_lifetime_never_release_by_time_or_record(self):
        for status,current in [('present',{'pid':2,'created':2,'box':''}),
                               ('unknown',{'pid':2,'created':2,'box':''}),
                               ('absent',{'pid':1,'created':1,'box':''})]:
            with self.subTest(status=status,current=current):
                self.state['box_pending']={'request_id':'old','credited':0,'at':1,'record_before':1,
                                           'process':{'pid':1,'created':1,'box':''}}
                self.app.bridges['1'].identity=current;self.record=999999;self.advance();self.calls.clear()
                with patch.object(engine,'process_lifetime_status',return_value=status,create=True):self.app.tick('1')
                self.assertEqual(self.calls,['boxscan'])
                self.assertIn('box_pending',self.state)
                self.assertNotIn('box_unresolved',self.state)

    def test_legacy_unscoped_and_different_environment_pending_are_not_guessed(self):
        for origin in [None,{'pid':1,'created':1,'box':'other'}, {'pid':True,'created':1,'box':''},
                       {'pid':1,'created':float('nan'),'box':''}]:
            with self.subTest(origin=origin):
                self.state['box_pending']={'request_id':'old','credited':0,'at':1,'process':origin}
                self.app.bridges['1'].identity={'pid':2,'created':2,'box':''};self.advance();self.calls.clear()
                with patch.object(engine,'process_lifetime_status',return_value='absent',create=True):self.app.tick('1')
                self.assertEqual(self.calls,['boxscan']);self.assertIn('box_pending',self.state)

    def test_retirement_save_failure_restores_hold_and_does_not_start_new_consumption(self):
        self.state['box_pending']={'request_id':'old','credited':0,'at':1,
                                   'process':{'pid':1,'created':1,'box':''}}
        self.app.bridges['1'].identity={'pid':2,'created':2,'box':''};before=copy.deepcopy(self.state)
        with patch.object(engine,'process_lifetime_status',return_value='absent',create=True),patch.object(self.app,'save',side_effect=OSError('disk busy')):
            self.app.tick('1')
        self.assertEqual(self.calls,['boxscan']);self.assertEqual(self.state,before)

    def test_manual_off_keeps_ended_batch_and_prevents_recovery_dispatch(self):
        self.state['box_pending']={'request_id':'old','credited':0,'at':1,
                                   'process':{'pid':1,'created':1,'box':''}}
        self.app.bridges['1'].identity={'pid':2,'created':2,'box':''}
        self.app.config['instances']['host:fixture']=False
        with patch.object(engine,'process_lifetime_status',return_value='absent',create=True) as probe:self.app.tick('1')
        self.assertFalse(self.calls);probe.assert_not_called();self.assertIn('box_pending',self.state)

    def test_pre_submission_save_failure_removes_unsent_hold_and_retries_automatically(self):
        with patch.object(self.app,'save',side_effect=OSError('disk busy')):self.app.tick('1')
        self.assertEqual(self.calls,['boxscan'])
        self.assertNotIn('box_pending',self.state)
        self.assertEqual(self.queue,20);self.assertEqual(self.record,100)
        self.advance();self.app.tick('1')
        self.assertEqual(self.calls,['boxscan','boxscan','openboxes'])
        self.assertEqual(self.state['features']['box']['opened'],8)
        self.assertTrue(self.app.config['running']);self.assertFalse(self.app.config['instances'])


if __name__=='__main__':unittest.main()
