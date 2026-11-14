import base64
import copy
import hashlib
import io
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from dps_assistant import engine, storage
from dps_assistant.policy import choose,observe_growth,progression_signature
from dps_assistant.runtime import Bridge,BridgeStarting,BridgeFailure


def scan(account='1001'):
    return {'snapshot': {'account': account, 'loaded': True, 'sync': {}, 'currencies': {'soul': 100}},
            'issues': [], 'actions': [{'key': 'rune:1:0', 'kind': 'rune', 'label': '升级', 'priority': 90,
                                      'cost': {'goods': 201, 'amount': 60}}]}


class FakeBridge:
    def __init__(self, account='1001', box=''):
        self.account = account
        self.identity = {'pid': 1, 'created': 1, 'exe': 'DPS.exe', 'box': box}
        self.process = type('Process', (), {'poll': lambda self: None})()
        self.started = time.time()
        self.closed = False
        self.commands = []
        self.backup_error = None
        self.entered = self.release = None

    def call(self, op, args=None):
        if op == 'opportunities':
            return scan(self.account)
        if op == 'backup':
            if self.backup_error:
                raise self.backup_error
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w') as archive:
                archive.writestr('character.sav', b'original-save')
            data = output.getvalue()
            return {'account': self.account, 'sha256': hashlib.sha256(data).hexdigest(),
                    'zip': base64.b64encode(data).decode(), 'files': 1}
        if op == 'execute':
            self.commands.append(args)
            if self.entered:
                self.entered.set()
                if not self.release.wait(3):
                    raise TimeoutError('test gate')
            return {'status': 'confirmed'}
        raise AssertionError(op)

    def close(self):
        self.closed = True


class SchedulerTests(unittest.TestCase):
    def mail_fixture(self, result=None, lost=False):
        bridge = self.add()
        value = scan()
        value['snapshot']['mail'] = {'unread': 2, 'claims': {'observer': 's', 'sequence': 0, 'receipts': []}}
        value['actions'] = [{'kind': 'mail_claim', 'key': 'mail_claim:a,b', 'ids': ['a', 'b'],
                             'label': '领取邮件附件', 'priority': 98}]
        original = bridge.call
        def call(op, args=None):
            if op == 'opportunities': return copy.deepcopy(value)
            if op == 'execute':
                self.assertTrue(self.engine.durable['host:1001']['pending_results'])
                saved = storage.load_json(engine.DATA/'scheduler.json', {})
                self.assertTrue(saved['host:1001']['pending_results'])
                bridge.commands.append(args)
                if lost: raise TimeoutError('lost mail reply')
                return result or {'status': 'pending'}
            return original(op, args)
        bridge.call = call
        return bridge, value

    def test_mail_reservation_survives_absent_panel_changed_batch_restart_and_lost_response(self):
        for lost in (False, True):
            with self.subTest(lost=lost):
                self.engine.durable = {};self.engine.instances = {};self.engine.bridges = {}
                bridge, value = self.mail_fixture(lost=lost)
                self.engine.tick('1')
                state = self.engine.durable['host:1001']
                self.assertIn('mail_claim:a,b', state.get('pending_results', {}))
                value['actions'] = []
                self.engine.tick('1')
                self.assertIn('mail_claim:a,b', state['uncertain'])
                state = storage.load_json(engine.DATA/'scheduler.json', {})['host:1001']
                self.engine.durable = {'host:1001': state}
                value['actions'] = [{'kind': 'mail_claim', 'key': 'mail_claim:a,b,c', 'ids': ['a', 'b', 'c'],
                                     'label': '领取邮件附件', 'priority': 98}, scan()['actions'][0]]
                # Let the unrelated rune succeed; no second mail claim may be submitted.
                previous = bridge.call
                bridge.call = lambda op,args=None: {'status':'confirmed'} if op=='execute' and args['kind']=='rune' else previous(op,args)
                self.engine.tick('1')
                self.assertEqual(len(bridge.commands), 1)
                self.assertIn('mail_claim:a,b', state['pending_results'])

    def test_mail_native_receipt_settles_once_and_definite_refusal_releases_reservation(self):
        bridge, value = self.mail_fixture()
        self.engine.tick('1')
        state = self.engine.durable['host:1001'];pending = state['pending_results']['mail_claim:a,b']
        value['actions'] = []
        value['snapshot']['mail']['claims']['receipts'] = [{'sequence': 1, 'at': pending['at']+1,
            'account': '1001', 'results': [{'id': i, 'status': 'CLAIMED'} for i in ('a','b')]}]
        self.engine.tick('1');self.engine.tick('1')
        self.assertFalse(state['pending_results'])
        self.assertEqual(state['features']['mail_claim']['confirmed'], 1)
        self.assertEqual(state['confirmed'], 1)
        self.engine.durable = {};self.engine.bridges = {};self.engine.instances = {}
        bridge, value = self.mail_fixture(result={'status':'waiting','reason':'native_mail_busy'})
        self.engine.tick('1')
        self.assertFalse(self.engine.durable['host:1001']['pending_results'])

    def test_costly_scans_delay_only_the_same_instance_and_preserve_sampling_clock(self):
        first,second=self.add(),self.add('2','1002','box')
        first_call=first.call;counts={'scan':0}
        def observed(op,args=None):
            value=first_call(op,args)
            if op=='opportunities':
                counts['scan']+=1;value['snapshot']['bridgePerformance']={'scanMs':400,'nativeCalls':100,'cacheHits':200}
            return value
        first.call=observed
        with patch.object(engine,'observe_experience',return_value={}) as exp, \
             patch.object(engine,'observe_farming',return_value={}) as farm:
            self.engine.tick('1')
        self.assertEqual(exp.call_args.args[-1]['interval'],20)
        self.assertEqual(farm.call_args.args[-1]['interval'],20)
        self.assertEqual(self.engine.config['interval'],2)
        self.engine.tick('1');self.assertEqual(counts['scan'],1)
        self.engine.tick('2');self.assertEqual(len(second.commands),1)
        self.assertEqual(first.commands[0]['kind'],'rune')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name)
        self.patches = [patch.object(engine, 'DATA', path), patch.object(storage, 'DATA', path)]
        for p in self.patches:
            p.start()
        self.engine = engine.Engine(start=False)

    def tearDown(self):
        self.engine.stop()
        for p in reversed(self.patches):
            p.stop()
        self.directory.cleanup()

    def add(self, key='1', account='1001', box=''):
        bridge = FakeBridge(account, box)
        self.engine.bridges[key] = bridge
        self.engine.instances[key] = {'id': key, 'status': 'connecting', 'confirmed': 0}
        return bridge

    def test_unsent_rune_reservation_is_rolled_back_after_disk_failure_and_retries_without_manual_input(self):
        bridge=self.add()
        value=scan();value['actions']=[]
        original=bridge.call
        bridge.call=lambda op,args=None:copy.deepcopy(value) if op=='opportunities' else original(op,args)
        self.engine.tick('1')  # Establish the original save backup before the injected failure.
        value['actions']=scan()['actions']+[{'kind':'rune','key':'unrelated','priority':90,'label':'已有预约'}]
        state=self.engine.durable['host:1001']
        state['uncertain']['unrelated']=123
        with patch.object(self.engine,'save',side_effect=OSError('disk busy')):self.engine.tick('1')
        self.assertEqual(bridge.commands,[])
        self.assertEqual(state['uncertain'],{'unrelated':123})
        self.assertTrue(self.engine.config['running'])
        self.engine.tick('1')
        self.assertEqual(len(bridge.commands),1)
        self.assertEqual(bridge.commands[0]['kind'],'rune')
        self.assertEqual(state['features']['rune']['confirmed'],1)

    def test_unsent_mail_reservation_does_not_block_a_changed_batch_after_disk_recovers(self):
        bridge,value=self.mail_fixture()
        action=value['actions'].pop();self.engine.tick('1')
        value['actions']=[action]
        with patch.object(self.engine,'save',side_effect=OSError('disk busy')):self.engine.tick('1')
        state=self.engine.durable['host:1001']
        self.assertFalse(state.get('pending_results'))
        self.assertFalse(state['uncertain'])
        self.assertEqual(bridge.commands,[])
        value['actions']=[{**action,'key':'mail_claim:a,b,c','ids':['a','b','c']}]
        self.engine.tick('1')
        self.assertEqual(len(bridge.commands),1)
        self.assertEqual(bridge.commands[0]['ids'],['a','b','c'])

    def test_atomic_scheduler_replace_failure_keeps_prior_disk_state_and_resumes_after_reload(self):
        bridge=self.add();value=scan();value['actions']=[];original=bridge.call
        bridge.call=lambda op,args=None:copy.deepcopy(value) if op=='opportunities' else original(op,args)
        self.engine.tick('1')
        previous=storage.load_json(engine.DATA/'scheduler.json',{})
        original_replace=storage.os.replace
        def replace(source,target):
            if Path(target)==engine.DATA/'scheduler.json':raise PermissionError('scheduler file busy')
            return original_replace(source,target)
        value['actions']=scan()['actions']
        with patch.object(storage.os,'replace',side_effect=replace):self.engine.tick('1')
        self.assertEqual(bridge.commands,[])
        self.assertFalse(self.engine.durable['host:1001']['uncertain'])
        self.assertEqual(storage.load_json(engine.DATA/'scheduler.json',{}),previous)
        reloaded=engine.Engine(start=False)
        try:self.assertFalse(reloaded.durable['host:1001']['uncertain'])
        finally:reloaded.stop()
        self.engine.tick('1')
        self.assertEqual(len(bridge.commands),1)
        self.assertTrue(self.engine.config['running'])

    def test_sent_rune_with_lost_response_keeps_its_reservation_and_never_replays_by_time(self):
        bridge=self.add();original=bridge.call
        def call(op,args=None):
            if op=='execute':
                bridge.commands.append(args)
                raise TimeoutError('native result unknown')
            return original(op,args)
        bridge.call=call
        self.engine.tick('1')
        state=self.engine.durable['host:1001']
        self.assertIn('rune:1:0',state['uncertain'])
        with patch.object(engine.time,'time',return_value=time.time()+100000):self.engine.tick('1')
        self.assertEqual(len(bridge.commands),1)
        self.assertIn('rune:1:0',state['uncertain'])

    def test_unsent_recovery_save_failure_preserves_attempt_count_and_retries(self):
        bridge=self.add();value=scan();value['actions']=[];original=bridge.call
        bridge.call=lambda op,args=None:copy.deepcopy(value) if op=='opportunities' else original(op,args)
        self.engine.tick('1')
        state=self.engine.durable['host:1001']
        state['battle_recovery']={'eligible':True,'since':time.time()-300,'reason':'missing_players','attempts':0,'last_attempt':0}
        previous=copy.deepcopy(state['battle_recovery'])
        value['actions']=[{'kind':'battle_recover','mode':'sync','key':'recover','label':'恢复战斗','priority':112,'freeEntry':True}]
        with patch.object(engine,'observe_battle_readiness',return_value=previous):
            with patch.object(self.engine,'save',side_effect=OSError('disk busy')):self.engine.tick('1')
            self.assertEqual(bridge.commands,[])
            self.assertEqual(state['battle_recovery'],previous)
            self.assertFalse(state.get('uncertain'))
            self.engine.tick('1')
        self.assertEqual(len(bridge.commands),1)
        self.assertEqual(state['battle_recovery']['attempts'],1)

    def test_equipment_dwell_prevents_fast_reversal_without_blocking_other_growth(self):
        state={};a={'kind':'equipment','key':'equip:a','id':1,'slot':3,'uid':'b','previousUid':'a','priority':99}
        self.engine.record_equipment(state,a,100)
        value=scan();value['actions'].append({**a,'key':'equip:c','uid':'c','previousUid':'b'})
        self.assertEqual(choose(value,engine.DEFAULT,state,now=159)['kind'],'rune')
        self.assertEqual(choose(value,engine.DEFAULT,state,now=160)['uid'],'c')
        value['actions'][-1].update(key='equip:a',uid='a')
        self.assertEqual(choose(value,engine.DEFAULT,state,now=399)['kind'],'rune')
        self.assertEqual(choose(value,engine.DEFAULT,state,now=400)['uid'],'a')

    def test_equipment_hold_is_per_slot_and_does_not_override_manual_changes(self):
        state={};a={'kind':'equipment','key':'equip:a','id':1,'slot':3,'uid':'b','previousUid':'a','priority':99}
        self.engine.record_equipment(state,a,100)
        for changed in ({'slot':4},{'id':2},{'previousUid':'manual'},{'previousUid':None}):
            value=scan();candidate={**a,'uid':'c','previousUid':'b',**changed};value['actions'].append(candidate)
            self.assertEqual(choose(value,engine.DEFAULT,state,now=101),candidate)
        self.assertEqual(choose(value,engine.DEFAULT,{},now=101),candidate)

    def test_equipment_retired_history_is_bounded_and_persists(self):
        state={}
        for n in range(25):self.engine.record_equipment(state,{'id':1,'slot':3,'uid':str(n+1),'previousUid':str(n)},100+n)
        self.assertEqual(len(state['equipment_holds']['1:3']['retired']),16)
        self.engine.durable['host:1001']=state;self.engine.save()
        saved=storage.load_json(engine.DATA/'scheduler.json',{})
        self.assertEqual(saved['host:1001']['equipment_holds'],state['equipment_holds'])
        self.engine.record_equipment(state,{'id':1,'slot':3,'uid':'new','previousUid':'old'},1000)
        self.assertEqual(state['equipment_holds']['1:3']['retired'],{'old':1300})

    def test_tower_clear_requires_new_native_record_and_settles_only_its_pending_entry(self):
        state={'tower_attempt':{'level':2,'cleared_before':1},'pending_results':{
            'tower:2':{'action':{'kind':'tower','level':2}},'other':{'action':{'kind':'tower','level':3}}},
            'uncertain':{'tower:2':1,'other':1}}
        row={'identity':'host:1001'}
        self.engine.observe_tower_clear('1',row,state,{'record':{'towerMaxCleared':1}})
        self.assertEqual(self.engine.events,[])
        self.engine.observe_tower_clear('1',row,state,{'record':{'towerMaxCleared':2}})
        self.assertEqual(len(self.engine.events),1)
        self.assertEqual(self.engine.events[0]['action']['kind'],'tower_clear')
        self.assertEqual(state['tower_clears']['2'],{'before':1,'after':2})
        self.assertNotIn('tower:2',state['pending_results']);self.assertIn('other',state['pending_results'])
        self.engine.observe_tower_clear('1',row,state,{'record':{'towerMaxCleared':2}})
        self.assertEqual(len(self.engine.events),1)
        for attempt in ({'level':1},{'level':1,'cleared_before':1}):
            state['tower_attempt']=attempt
            self.engine.observe_tower_clear('1',row,state,{'record':{'towerMaxCleared':1}})
        self.assertEqual(len(self.engine.events),1)

    def test_budget_and_premium_never_spent(self):
        config = copy.deepcopy(engine.DEFAULT)
        config['soul_reserve'] = 50
        self.assertIsNone(choose(scan(), config, {}))
        config['soul_reserve'] = 40
        self.assertIsNotNone(choose(scan(), config, {}))
        value = scan()
        value['actions'][0]['cost']['goods'] = 202
        self.assertIsNone(choose(value, config, {}))

    def test_pause_native_sync_and_disabled_modules_block(self):
        config = copy.deepcopy(engine.DEFAULT)
        config['running'] = False
        self.assertIsNone(choose(scan(), config, {}))
        config['running'] = True
        config['modules']['rune'] = False
        self.assertIsNone(choose(scan(), config, {}))
        config['modules']['rune'] = True
        value = scan()
        value['snapshot']['sync'] = {'blocked': True}
        self.assertIsNone(choose(value, config, {}))
        value['snapshot']['sync'] = {}
        value['snapshot']['automationBlocked'] = ['DG.UI.ConfirmPopup']
        self.assertIsNone(choose(value, config, {}))

    def test_unknown_does_not_replay_after_wall_clock_expiry(self):
        self.assertIsNone(choose(scan(), engine.DEFAULT, {'uncertain': {'rune:1:0': 1}}, now=9999999999))

    def test_sync_backlog_keeps_free_farming_and_ticket_guard_available(self):
        value=scan();value['snapshot']['sync']={'queue':151,'blocked':False}
        farm={'kind':'progress','key':'farm:18','mode':'farm','level':18,'difficulty':0,'priority':107,'freeEntry':True}
        value['actions'].append(farm)
        self.assertEqual(choose(value,engine.DEFAULT,{'growth':{'phase':'farm'}}),farm)
        guard={'kind':'progress','key':'guard:20','mode':'guard','priority':130,'freeEntry':True}
        value['actions'].append(guard)
        self.assertEqual(choose(value,engine.DEFAULT,{}),guard)
        value['snapshot']['sync']['blocked']=True
        self.assertIsNone(choose(value,engine.DEFAULT,{}))

    def test_sync_backlog_never_allows_spending_or_unverified_stage_changes(self):
        value=scan();value['snapshot']['sync']={'queue':151}
        value['actions'] += [
            {'kind':'progress','key':'paid-farm','mode':'farm','priority':107},
            {'kind':'progress','key':'push','mode':'push','priority':106,'freeEntry':True},
            {'kind':'tower','key':'paid-tower','priority':112,'freeEntry':True},
        ]
        self.assertIsNone(choose(value,engine.DEFAULT,{'growth':{'phase':'farm'}}))
        value['actions']=[{'kind':'tower_return','key':'free-return','priority':112,'freeEntry':True}]
        self.assertEqual(choose(value,engine.DEFAULT,{})['key'],'free-return')
        value['actions'][0]['freeEntry']=False
        self.assertIsNone(choose(value,engine.DEFAULT,{}))

    def test_native_offline_blocks_investment_even_before_queue_grows(self):
        value=scan();value['snapshot']['connection']={'online':False}
        self.assertIsNone(choose(value,engine.DEFAULT,{}))
        farm={'kind':'progress','key':'farm:18:repeat','mode':'farm','level':18,'difficulty':0,'phase':'repeat',
              'priority':107,'freeEntry':True}
        value['actions'].append(farm)
        self.assertEqual(choose(value,engine.DEFAULT,{'growth':{'phase':'farm'}}),farm)
        value['snapshot']['connection']['online']=True
        self.assertEqual(choose(value,engine.DEFAULT,{})['kind'],'rune')

    def test_tower_retries_require_progress_and_minimum_interval(self):
        tower_config=copy.deepcopy(engine.DEFAULT);tower_config['modules']['tower']=True
        value=scan();value['snapshot']['record']={'maxStage':15,'maxCleared':15}
        value['snapshot']['catalogue']={'normalMax':15}
        value['snapshot']['stage']={'category':0,'level':15,'running':False,'ending':True}
        value['actions']=[{'key':'tower:1','kind':'tower','level':1,'priority':79}]
        state={'tower_attempt':{'level':1,'max_stage':15,'at':100}}
        self.assertIsNone(choose(value,tower_config,state,now=1000))
        value['snapshot']['record']['maxStage']=16
        self.assertIsNone(choose(value,tower_config,state,now=200))
        self.assertIsNotNone(choose(value,tower_config,state,now=500))

    def test_tower_never_preempts_frontier_or_runs_during_farming(self):
        tower_config=copy.deepcopy(engine.DEFAULT);tower_config['modules']['tower']=True
        value=scan();value['snapshot']['record']={'maxStage':20,'maxCleared':20}
        value['snapshot']['catalogue']={'normalMax':20}
        value['snapshot']['stage']={'category':0,'level':20,'running':False,'ending':True}
        tower={'key':'tower:2','kind':'tower','level':2,'priority':109}
        boss={'key':'boss:21','kind':'progress','mode':'boss','priority':108}
        farm={'key':'farm:20','kind':'progress','mode':'farm','level':20,'difficulty':0,'priority':107}
        value['actions']=[tower,boss]
        self.assertEqual(choose(value,tower_config,{},now=1000)['key'],'boss:21')
        state={'growth':{'phase':'farm','since':100}}
        value['snapshot']['stage']['level']=20
        value['actions']=[tower,farm]
        self.assertEqual(choose(value,tower_config,state,now=279)['key'],'farm:20')
        self.assertEqual(choose(value,tower_config,state,now=1000)['key'],'farm:20')
        value['actions']=[tower]
        self.assertIsNone(choose(value,tower_config,state,now=1000))
        value['snapshot']['stage']['level']=21
        state={'growth':{'phase':'push','since':100}}
        self.assertIsNone(choose(value,tower_config,state,now=1000))
        state['tower_attempt']={'level':2,'max_stage':20,'at':200,'progress_strength':progression_signature(value['snapshot'])}
        self.assertIsNone(choose(value,tower_config,state,now=1000))
        value['snapshot']['runes']={'learned':5}
        self.assertIsNone(choose(value,tower_config,state,now=1000))
        value['actions'].append({'kind':'progress','key':'guard','mode':'guard','priority':130})
        self.assertEqual(choose(value,tower_config,state,now=1000)['key'],'guard')

    def test_tower_is_rejected_until_the_native_main_story_frontier_is_complete(self):
        tower_config=copy.deepcopy(engine.DEFAULT);tower_config['modules']['tower']=True
        value=scan();value['snapshot']['record']={'maxStage':39,'maxCleared':39}
        value['snapshot']['catalogue']={'normalMax':160}
        value['snapshot']['stage']={'category':0,'level':39,'running':False,'ending':True}
        value['actions']=[{'key':'tower:2','kind':'tower','level':2,'priority':79}]
        self.assertIsNone(choose(value,tower_config,{},now=1000))
        value['snapshot']['record']['maxCleared']=160
        value['snapshot']['stage']['level']=160
        self.assertEqual(choose(value,tower_config,{},now=1001)['key'],'tower:2')
        for missing in ({'normalMax':0},{},None):
            value['snapshot']['catalogue']=missing or {}
            self.assertIsNone(choose(value,tower_config,{},now=1002))

    def test_permanent_rune_routes_use_separate_crystal_budget(self):
        value=scan();value['snapshot']['currencies']['premium']=4
        value['actions'][0].update(cost={'goods':202,'amount':2},permanent=True)
        self.assertIsNotNone(choose(value,engine.DEFAULT,{}))
        value['actions'][0]['cost']['amount']=3
        self.assertIsNotNone(choose(value,engine.DEFAULT,{}))
        self.assertIsNone(choose(value,{**engine.DEFAULT,'premium_reserve':2},{}))
        value['actions'][0]['cost']['amount']=5
        self.assertIsNone(choose(value,engine.DEFAULT,{}))
        value['actions'][0]['cost']['amount']=1
        config={**engine.DEFAULT,'permanent_runes':False}
        self.assertIsNone(choose(value,config,{}))
        value['actions'][0]['kind']='box'
        self.assertIsNone(choose(value,engine.DEFAULT,{}))

    def test_tower_reconsiders_verified_growth_without_new_main_stage(self):
        tower_config=copy.deepcopy(engine.DEFAULT);tower_config['modules']['tower']=True
        value=scan();value['snapshot'].update(stage={'category':0,'level':19,'running':False,'ending':True},record={'maxStage':19,'maxCleared':19},runes={'learned':132})
        value['snapshot']['catalogue']={'normalMax':19}
        value['actions']=[{'key':'tower:1','kind':'tower','level':1,'priority':79}]
        state={'tower_attempt':{'level':1,'max_stage':19,'at':100,'progress_strength':progression_signature(value['snapshot'])}}
        self.assertIsNone(choose(value,tower_config,state,now=500))
        value['snapshot']['runes']['learned']=133
        self.assertIsNone(choose(value,tower_config,state,now=200))
        self.assertIsNotNone(choose(value,tower_config,state,now=500))

    def test_failures_trigger_farming_and_growth_releases_it(self):
        value=scan();snap=value['snapshot'];snap.update(stage={'category':0},record={'maxCleared':18,'maxStage':18,'deaths':100},characters=[{'id':1,'level':18}])
        state={};observe_growth(snap,state,100)
        snap['record']['deaths']=106
        self.assertEqual(observe_growth(snap,state,280)['phase'],'farm')
        value['actions']=[{'key':'repeat_off','kind':'progress','mode':'push','level':19,'priority':106},
                          {'key':'farm:18','kind':'progress','mode':'farm','level':18,'difficulty':0,'priority':107}]
        self.assertEqual(choose(value,engine.DEFAULT,state,now=281)['mode'],'farm')
        snap['characters'][0]['level']=19
        self.assertEqual(observe_growth(snap,state,459)['phase'],'farm')
        self.assertEqual(observe_growth(snap,state,460)['phase'],'push')
        self.assertEqual(choose(value,engine.DEFAULT,state,now=461)['mode'],'push')

    def test_fairness_prevents_box_backlog_starving_permanent_growth(self):
        value=scan();value['actions']=[{'kind':'box','key':'box:1','priority':99},
                                      {'kind':'rune','key':'rune:1','priority':89}]
        state={'scheduling_started':100,'last_module':{'box':299,'rune':100}}
        self.assertEqual(choose(value,engine.DEFAULT,state,now=300)['kind'],'rune')
        value['actions'].append({'kind':'progress','key':'guard:20','priority':130,'mode':'guard'})
        self.assertEqual(choose(value,engine.DEFAULT,state,now=10000)['key'],'guard:20')

    def test_durable_scheduler_services_low_priority_growth_amid_continuous_loot(self):
        bridge=self.add();original=bridge.call;start=1_700_001_000;clock={'now':start}
        def observed(op,args=None):
            if op=='opportunities':
                value=scan();value['actions'][0]['priority']=60
                value['actions'].append({'kind':'box','key':'box:'+str(clock['now']),
                                         'label':'持续开箱','priority':99})
                return value
            return original(op,args)
        bridge.call=observed
        for now in range(start,start+1301,10):
            clock['now']=now
            with patch.object(engine.time,'time',return_value=now):self.engine.tick('1')
            self.assertNotEqual(self.engine.instances['1']['status'],'recovering',str(self.engine.instances['1'].get('error')))
            if now-start in (400,800,1200):
                self.engine.durable=storage.load_json(engine.DATA/'scheduler.json',{})
        state=storage.load_json(engine.DATA/'scheduler.json',{})['host:1001']
        self.assertGreaterEqual(state['features']['rune']['confirmed'],2)
        self.assertGreater(state['features']['box']['confirmed'],0)
        self.assertEqual(state['confirmed'],len(bridge.commands))
        self.assertFalse(state.get('uncertain'))

    def test_return_to_main_does_not_depend_on_tower_module(self):
        value=scan();value['actions']=[{'key':'return:15','kind':'tower_return','level':15,'priority':112}]
        config=copy.deepcopy(engine.DEFAULT);config['modules']['tower']=False
        self.assertEqual(choose(value,config,{})['kind'],'tower_return')

    def test_equipment_turns_rotate_across_all_three_characters(self):
        value=scan();value['actions']=[{'kind':'equipment','id':id,'slot':0,'key':f'equip:{id}','priority':99,'gain':.2} for id in (1,2,3)]
        value['actions'].append({'kind':'box','key':'box:0','priority':99})
        state={'last_equipment':{'1':90,'2':91,'3':92}}
        selected=[]
        for now in (100,102,104):
            action=choose(value,engine.DEFAULT,state,now=now);selected.append(action['id'])
            state['last_equipment'][str(action['id'])]=now
        self.assertEqual(selected,[1,2,3])

    def test_pending_equipment_requires_matching_character_slot_and_uid(self):
        self.add();row=self.engine.instances['1'];row['identity']='host:1001'
        action={'key':'equip:2','kind':'equipment','id':2,'slot':3,'uid':'new','label':'换装'}
        state={'uncertain':{'equip:2':1},'pending_results':{'equip:2':{'action':action,'at':1}}}
        for character,slot,uid in [(1,3,'new'),(2,2,'new'),(2,3,'old')]:
            self.engine.settle_pending('1',row,state,{'characters':[{'id':character,'equipment':[{'slot':slot,'uid':uid}]}]})
            self.assertEqual(state.get('confirmed',0),0)
        snap={'characters':[{'id':2,'equipment':[{'slot':3,'uid':'new'}]}]}
        self.engine.settle_pending('1',row,state,snap)
        self.engine.settle_pending('1',row,state,snap)
        self.assertEqual(state['confirmed'],1);self.assertEqual(row['equipment_evidence']['2']['confirmed'],1)

    def test_async_return_is_only_confirmed_after_running_main_stage(self):
        self.add();row=self.engine.instances['1'];row['identity']='host:1001'
        action={'key':'return:15','kind':'tower_return','level':15,'label':'返回主线'}
        state={'uncertain':{'return:15':1},'pending_results':{'return:15':{'action':action,'at':engine.time.time()}}}
        self.engine.settle_pending('1',row,state,{'stage':{'level':1,'category':1,'running':False}})
        self.assertEqual(state.get('confirmed',0),0)
        self.engine.settle_pending('1',row,state,{'stage':{'level':15,'category':0,'running':True,'alivePlayers':1}})
        self.assertEqual(state['confirmed'],1);self.assertFalse(state['pending_results'])
        self.engine.settle_pending('1',row,state,{'stage':{'level':15,'category':0,'running':True,'alivePlayers':1}})
        self.assertEqual(state['confirmed'],1)

    def test_boss_clear_requires_native_clear_record_and_is_only_reported_once(self):
        self.add();row=self.engine.instances['1'];row['identity']='host:1001'
        state={'boss_attempt':{'level':20,'ticket':690100,'ticketUid':'entry','ticketBefore':3}}
        self.engine.observe_boss_clear('1',row,state,{'record':{'maxCleared':19},'entryTickets':[{'uid':'entry','count':3}]})
        self.assertIn('boss_attempt',state)
        self.engine.observe_boss_clear('1',row,state,{'record':{'maxCleared':20},'entryTickets':[{'uid':'entry','count':2}]})
        self.assertNotIn('boss_attempt',state)
        self.assertEqual(state['boss_clears']['20']['ticketAfter'],2)
        events=[e for e in self.engine.events if e.get('action',{}).get('kind')=='boss_clear']
        self.assertEqual(len(events),1)
        self.engine.observe_boss_clear('1',row,state,{'record':{'maxCleared':21}})
        self.assertEqual(len([e for e in self.engine.events if e.get('action',{}).get('kind')=='boss_clear']),1)

    def test_farming_waits_for_growth_before_another_boss_attempt(self):
        value=scan();value['actions']=[{'kind':'progress','key':'boss:20','mode':'boss','priority':108}]
        self.assertIsNone(choose(value,engine.DEFAULT,{'growth':{'phase':'farm'}}))
        self.assertEqual(choose(value,engine.DEFAULT,{'growth':{'phase':'push'}})['mode'],'boss')

    def test_backup_failure_blocks_gameplay(self):
        bridge = self.add()
        bridge.backup_error = OSError('virtual save unavailable')
        self.engine.tick('1')
        self.assertEqual(bridge.commands, [])
        self.assertEqual(self.engine.instances['1']['status'], 'recovering')

    def test_lost_paid_reply_remains_reserved_across_missing_scan_timeout_and_new_ticket(self):
        bridge=self.add();original=bridge.call
        action={'kind':'progress','mode':'boss','phase':'travel','level':10,'difficulty':0,
                'ticket':690100,'ticketUid':'old','ticketBefore':1,'key':'boss:10:old','priority':108,'label':'Boss'}
        current=scan();current['actions']=[action]
        def call(op,args=None):
            if op=='opportunities':return copy.deepcopy(current)
            if op=='execute':
                bridge.commands.append(args)
                raise TimeoutError('reply lost after submission')
            return original(op,args)
        bridge.call=call
        self.engine.tick('1')
        state=self.engine.durable['host:1001']
        self.assertEqual(len(bridge.commands),1)
        self.assertIn(action['key'],state['entry_uncertainty'])
        current['actions']=[]
        self.engine.tick('1')
        self.assertIn(action['key'],state['uncertain'])
        state['pending_results'][action['key']]['at']=1
        self.engine.tick('1')
        self.assertFalse(state['pending_results'])
        current['actions']=[{**action,'key':'boss:10:new','ticketUid':'new'}]
        self.engine.tick('1')
        self.assertEqual(len(bridge.commands),1)
        current['actions']=[]
        current['snapshot']['stage']={'category':0,'level':10,'difficulty':0,'running':True,'repeat':False,'alivePlayers':1}
        self.engine.tick('1')
        self.assertFalse(state['entry_uncertainty'])
        self.assertNotIn(action['key'],state['uncertain'])

    def test_farm_travel_settles_before_native_repeat_is_reenabled(self):
        self.add();row=self.engine.instances['1'];row['identity']='host:1001'
        action={'key':'farm:18:travel','kind':'progress','mode':'farm','phase':'travel',
                'level':18,'repeat':True,'label':'返回练级关卡'}
        state={'uncertain':{action['key']:1},'pending_results':{action['key']:{'action':action,'at':engine.time.time()}}}
        self.engine.settle_pending('1',row,state,{'stage':{'category':0,'level':18,'running':False,'repeat':False}})
        self.assertEqual(state.get('confirmed',0),0)
        self.engine.settle_pending('1',row,state,{'stage':{'category':0,'level':18,'running':True,'repeat':False,'alivePlayers':1}})
        self.assertEqual(state['confirmed'],1)
        self.assertFalse(state['pending_results'])
        self.assertFalse(state['uncertain'])

    def test_connecting_helper_gets_startup_grace_without_repeated_replacement(self):
        bridge=self.add()
        bridge.call=lambda *args: (_ for _ in ()).throw(ConnectionRefusedError('[WinError 10061]'))
        for elapsed in (0,2,15,29):
            with patch.object(engine.time,'time',return_value=bridge.started+elapsed):self.engine.tick('1')
            self.assertIs(self.engine.bridges.get('1'),bridge)
            self.assertFalse(bridge.closed)

    def test_unready_helper_is_replaced_after_startup_grace(self):
        bridge=self.add()
        bridge.call=lambda *args: (_ for _ in ()).throw(ConnectionRefusedError('[WinError 10061]'))
        with patch.object(engine.time,'time',return_value=bridge.started+31):self.engine.tick('1')
        self.assertNotIn('1',self.engine.bridges)
        self.assertTrue(bridge.closed)

    def test_terminal_helper_is_replaced_without_waiting_for_startup_grace(self):
        bridge=self.add();bridge.process.poll=lambda:1
        bridge.call=lambda *args: (_ for _ in ()).throw(ConnectionRefusedError('[WinError 10061]'))
        self.engine.tick('1')
        self.assertNotIn('1',self.engine.bridges)
        self.assertTrue(bridge.closed)

    def test_slow_initialization_is_visible_and_survives_exited_sandbox_launcher(self):
        bridge=self.add();bridge.process.poll=lambda:0
        health={'phase':'starting','step':'load','pid':1}
        bridge.call=lambda *args: (_ for _ in ()).throw(BridgeStarting(health))
        with patch.object(engine.time,'time',return_value=bridge.started+45):self.engine.tick('1')
        self.assertIs(self.engine.bridges.get('1'),bridge)
        self.assertFalse(bridge.closed)
        self.assertEqual(self.engine.instances['1']['status'],'connecting')
        self.assertIsNone(self.engine.instances['1']['error'])
        self.assertEqual(self.engine.instances['1']['bridge_health'],health)
        self.assertEqual(self.engine.events,[])

    def test_failed_initialization_replaces_owned_helper_without_waiting_for_exit(self):
        bridge=self.add()
        bridge.call=lambda *args: (_ for _ in ()).throw(BridgeFailure({'phase':'failed','error':'attach denied'}))
        self.engine.tick('1')
        self.assertNotIn('1',self.engine.bridges)
        self.assertTrue(bridge.closed)
        self.assertIn('attach denied',self.engine.instances['1']['error'])
        self.assertGreater(self.engine.instances['1']['bridge_retry_at'],time.time())
        self.assertEqual(self.engine.instances['1']['bridge_failures'],1)

    def test_live_starting_health_survives_transport_error_until_initialization_deadline(self):
        bridge=self.add();bridge.process.poll=lambda:0
        bridge.call=lambda *args: (_ for _ in ()).throw(ConnectionRefusedError('[WinError 10061]'))
        bridge.health=lambda timeout=1:{'phase':'starting','step':'attach'}
        with patch.object(engine.time,'time',return_value=bridge.started+45):self.engine.tick('1')
        self.assertIs(self.engine.bridges.get('1'),bridge)
        with patch.object(engine.time,'time',return_value=bridge.started+91):self.engine.tick('1')
        self.assertNotIn('1',self.engine.bridges)
        self.assertTrue(bridge.closed)

    def test_live_health_preserves_reparented_helper_and_lost_execute_is_not_replayed(self):
        bridge=self.add();bridge.process.poll=lambda:0
        bridge.health=lambda timeout=1:{'phase':'ready'}
        original=bridge.call
        def call(op,args=None):
            if op=='execute':
                bridge.commands.append(args)
                raise TimeoutError('reply lost after submission')
            return original(op,args)
        bridge.call=call
        self.engine.tick('1')
        self.assertIs(self.engine.bridges.get('1'),bridge)
        self.assertFalse(bridge.closed)
        self.assertIn('rune:1:0',self.engine.durable['host:1001']['uncertain'])
        self.engine.tick('1')
        self.assertEqual(len(bridge.commands),1)

    def test_module_switches_reach_both_planning_and_execution(self):
        bridge=self.add();original=bridge.call;seen=[]
        def call(op,args=None):
            seen.append((op,copy.deepcopy(args)))
            return original(op,args)
        bridge.call=call
        self.engine.update({'modules':{'combine':False,'decompose':True,'storage':False}})
        self.engine.tick('1')
        planned=next(args for op,args in seen if op=='opportunities')
        executed=next(args['strategy'] for op,args in seen if op=='execute')
        for options in (planned,executed):
            self.assertFalse(options['modules']['combine']);self.assertTrue(options['modules']['decompose'])
            self.assertFalse(options['modules']['storage'])

    def test_timeout_has_actionable_message_and_keeps_responsive_helper(self):
        import urllib.error
        bridge=self.add();bridge.health=lambda timeout=1:{'phase':'ready'}
        bridge.call=lambda *args: (_ for _ in ()).throw(urllib.error.URLError('timed out'))
        with patch.object(engine.time,'time',return_value=bridge.started+100):self.engine.tick('1')
        self.assertIs(self.engine.bridges['1'],bridge);self.assertFalse(bridge.closed)
        self.assertIn('直连通道',self.engine.instances['1']['error'])
        self.assertNotIn('urlopen',self.engine.events[-1]['message'])

    def test_close_finds_reparented_helper_without_terminating_other_sessions_or_game(self):
        from dps_assistant.runtime import ROOT
        terminated=[]
        class Helper:
            def __init__(self,name,token='this-session',port='12000',target='1',script=None):
                self.info={'name':name,'cmdline':['python',str(script or ROOT/'tools/bridge_host.py'),
                    '--pid',target,'--port',port,'--token',token]}
            def terminate(self):terminated.append(self)
            def as_dict(self,attrs):return {key:self.info[key] for key in attrs}
        owned=Helper('python.exe')
        owned_equals=Helper('python.exe')
        owned_equals.info['cmdline'][-2:]=['--token=this-session']
        others=[Helper('python.exe',token='other-session'),Helper('python.exe',port='12001'),
                Helper('python.exe',target='2'),Helper('python.exe',script=ROOT/'unrelated/bridge_host.py'),Helper('DPS.exe')]
        bridge=Bridge.__new__(Bridge);bridge.identity={'pid':1};bridge.port=12000;bridge.token='this-session';bridge.closed=False
        bridge.process=type('ExitedLauncher',(),{'poll':lambda self:0})()
        with patch('dps_assistant.runtime.psutil.process_iter',return_value=[owned,owned_equals,*others]):bridge.close()
        self.assertEqual(terminated,[owned,owned_equals])

    def test_discovery_does_not_read_process_iter_shared_info_dictionary(self):
        from dps_assistant import runtime
        game=Path(self.directory.name)/'DPS.exe'
        game.touch();(game.parent/'GameAssembly.dll').touch()
        metadata=game.parent/'DPS_Data/il2cpp_data/Metadata/global-metadata.dat'
        metadata.parent.mkdir(parents=True);metadata.touch()
        class Process:
            pid=99
            info={'name':'python.exe'}
            def as_dict(self,attrs):return {'name':'DPS.exe','exe':str(game),'create_time':123}
        with patch.object(runtime,'GAME',None),patch.object(runtime.psutil,'process_iter',return_value=[Process()]),patch.object(runtime,'box_for',return_value='box'):
            self.assertEqual(runtime.discover(),[{'pid':99,'created':123,'box':'box','exe':str(game)}])
            self.assertIsNone(runtime.GAME)

    def test_sandbox_multi_instance_config_preserves_host_and_other_options(self):
        from dps_assistant import runtime
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game=root/'game'/'DPS.exe';source=game.parent/'DPS_Data'/'boot.config'
            source.parent.mkdir(parents=True);original='single-instance=\ngc-max-time-slice=3\nbuild-guid=example\n'
            source.write_text(original,encoding='utf-8');virtual=root/'virtual';virtual.mkdir()
            with patch.object(runtime,'GAME',game),patch.object(runtime,'DATA',root/'data'),patch.object(runtime,'sandbox_root',return_value=virtual):
                runtime.prepare_sandbox_boot('testbox');runtime.prepare_sandbox_boot('testbox')
            target=virtual/'drive'/source.drive[0]/source.relative_to(source.anchor)
            self.assertEqual(source.read_text(encoding='utf-8'),original)
            self.assertEqual(target.read_text(encoding='utf-8'),'gc-max-time-slice=3\nbuild-guid=example\n')
            backups=list((root/'data'/'backups').glob('*.config'))
            self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_text(encoding='utf-8'),original)

    def test_backup_digest_mismatch_blocks_gameplay(self):
        bridge = self.add()
        original = bridge.call
        def bad(op, args=None):
            result = original(op, args)
            if op == 'backup':
                result['sha256'] = '0' * 64
            return result
        bridge.call = bad
        self.engine.tick('1')
        self.assertEqual(bridge.commands, [])

    def test_sandbox_and_host_accounts_keep_separate_backups_and_budgets(self):
        host, sandbox = self.add(), self.add('2', '1002', 'box')
        for key in ('1', '2'):
            self.engine.tick(key)
        self.assertEqual([host.commands[0]['account'], sandbox.commands[0]['account']], ['1001', '1002'])
        paths = [Path(s['backup']['path']) for s in self.engine.durable.values()]
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(p.is_file() for p in paths))
        self.assertEqual([s['confirmed'] for s in self.engine.durable.values()], [1, 1])

    def test_pause_acknowledgement_waits_for_inflight_and_blocks_next(self):
        bridge = self.add()
        bridge.entered, bridge.release = threading.Event(), threading.Event()
        worker = threading.Thread(target=self.engine.tick, args=('1',))
        worker.start()
        self.assertTrue(bridge.entered.wait(2))
        paused = threading.Event()
        def pause():
            self.engine.update({'running': False})
            paused.set()
        setter = threading.Thread(target=pause)
        setter.start()
        self.assertFalse(paused.wait(.05))
        bridge.release.set()
        worker.join(3)
        setter.join(3)
        self.assertTrue(paused.is_set())
        self.engine.tick('1')
        self.assertEqual(len(bridge.commands), 1)

    def test_duplicate_account_only_has_one_writer(self):
        host, sandbox = self.add(), self.add('2', '1001', 'box')
        self.engine.tick('1')
        self.engine.tick('2')
        self.assertEqual(len(host.commands), 1)
        self.assertEqual(sandbox.commands, [])
        self.assertEqual(self.engine.instances['2']['status'], 'duplicate')

    def test_process_reuse_or_box_change_invalidates_bridge(self):
        bridge = Bridge.__new__(Bridge)
        bridge.identity = {'pid': 1, 'created': 100, 'exe': 'DPS.exe', 'box': 'box'}
        fake = type('P', (), {'pid': 1, 'create_time': lambda self: 101, 'exe': lambda self: 'DPS.exe'})()
        with patch('dps_assistant.runtime.psutil.Process', return_value=fake), patch('dps_assistant.runtime.box_for', return_value='box'):
            self.assertFalse(bridge.valid())
            fake.create_time = lambda: 100
            self.assertTrue(bridge.valid())
        with patch('dps_assistant.runtime.psutil.Process', return_value=fake), patch('dps_assistant.runtime.box_for', return_value='other'):
            self.assertFalse(bridge.valid())


if __name__ == '__main__':
    unittest.main()
