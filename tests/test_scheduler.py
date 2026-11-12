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
from dps_assistant.policy import choose,observe_growth,strength_signature
from dps_assistant.runtime import Bridge


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
        farm={'kind':'progress','key':'farm:18','mode':'farm','priority':107,'freeEntry':True}
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
        farm={'kind':'progress','key':'farm:18:repeat','mode':'farm','phase':'repeat',
              'priority':107,'freeEntry':True}
        value['actions'].append(farm)
        self.assertEqual(choose(value,engine.DEFAULT,{'growth':{'phase':'farm'}}),farm)
        value['snapshot']['connection']['online']=True
        self.assertEqual(choose(value,engine.DEFAULT,{})['kind'],'rune')

    def test_tower_retries_require_progress_and_minimum_interval(self):
        value=scan();value['snapshot']['record']={'maxStage':15}
        value['actions']=[{'key':'tower:1','kind':'tower','level':1,'priority':79}]
        state={'tower_attempt':{'level':1,'max_stage':15,'at':100}}
        self.assertIsNone(choose(value,engine.DEFAULT,state,now=1000))
        value['snapshot']['record']['maxStage']=16
        self.assertIsNone(choose(value,engine.DEFAULT,state,now=200))
        self.assertIsNotNone(choose(value,engine.DEFAULT,state,now=500))

    def test_eligible_tower_gets_a_turn_between_boss_and_farming_cycles(self):
        value=scan();value['snapshot']['record']={'maxStage':20}
        tower={'key':'tower:2','kind':'tower','level':2,'priority':79}
        boss={'key':'boss:20','kind':'progress','mode':'boss','priority':108}
        farm={'key':'farm:18','kind':'progress','mode':'farm','priority':107}
        value['actions']=[tower,boss,farm]
        self.assertEqual(choose(value,engine.DEFAULT,{},now=1000)['kind'],'tower')
        state={'growth':{'phase':'farm','since':100}}
        self.assertEqual(choose(value,engine.DEFAULT,state,now=279)['mode'],'farm')
        self.assertEqual(choose(value,engine.DEFAULT,state,now=280)['kind'],'tower')
        state['tower_attempt']={'level':2,'max_stage':20,'at':200,'strength':strength_signature(value['snapshot'])}
        self.assertEqual(choose(value,engine.DEFAULT,state,now=1000)['mode'],'farm')
        value['snapshot']['runes']={'learned':5}
        self.assertEqual(choose(value,engine.DEFAULT,state,now=1000)['kind'],'tower')
        value['actions'].append({'kind':'progress','key':'guard','mode':'guard','priority':130})
        self.assertEqual(choose(value,engine.DEFAULT,state,now=1000)['key'],'guard')

    def test_permanent_rune_routes_use_separate_crystal_budget(self):
        value=scan();value['snapshot']['currencies']['premium']=4
        value['actions'][0].update(cost={'goods':202,'amount':2},permanent=True)
        self.assertIsNotNone(choose(value,engine.DEFAULT,{}))
        value['actions'][0]['cost']['amount']=3
        self.assertIsNone(choose(value,engine.DEFAULT,{}))
        value['actions'][0]['cost']['amount']=1
        config={**engine.DEFAULT,'permanent_runes':False}
        self.assertIsNone(choose(value,config,{}))
        value['actions'][0]['kind']='box'
        self.assertIsNone(choose(value,engine.DEFAULT,{}))

    def test_tower_reconsiders_verified_growth_without_new_main_stage(self):
        value=scan();value['snapshot'].update(record={'maxStage':19},runes={'learned':132})
        value['actions']=[{'key':'tower:1','kind':'tower','level':1,'priority':79}]
        state={'tower_attempt':{'level':1,'max_stage':19,'at':100,'strength':strength_signature(value['snapshot'])}}
        self.assertIsNone(choose(value,engine.DEFAULT,state,now=500))
        value['snapshot']['runes']['learned']=133
        self.assertIsNone(choose(value,engine.DEFAULT,state,now=200))
        self.assertIsNotNone(choose(value,engine.DEFAULT,state,now=500))

    def test_failures_trigger_farming_and_growth_releases_it(self):
        value=scan();snap=value['snapshot'];snap.update(stage={'category':0},record={'maxCleared':18,'deaths':100},characters=[{'id':1,'level':18}])
        state={};observe_growth(snap,state,100)
        snap['record']['deaths']=106
        self.assertEqual(observe_growth(snap,state,280)['phase'],'farm')
        value['actions']=[{'key':'repeat_off','kind':'progress','mode':'push','priority':106},
                          {'key':'farm:18','kind':'progress','mode':'farm','priority':107}]
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
        state={'uncertain':{'return:15':1},'pending_results':{'return:15':{'action':action,'at':1}}}
        self.engine.settle_pending('1',row,state,{'stage':{'level':1,'category':1,'running':False}})
        self.assertEqual(state.get('confirmed',0),0)
        self.engine.settle_pending('1',row,state,{'stage':{'level':15,'category':0,'running':True}})
        self.assertEqual(state['confirmed'],1);self.assertFalse(state['pending_results'])
        self.engine.settle_pending('1',row,state,{'stage':{'level':15,'category':0,'running':True}})
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

    def test_farm_travel_settles_before_native_repeat_is_reenabled(self):
        self.add();row=self.engine.instances['1'];row['identity']='host:1001'
        action={'key':'farm:18:travel','kind':'progress','mode':'farm','phase':'travel',
                'level':18,'repeat':True,'label':'返回练级关卡'}
        state={'uncertain':{action['key']:1},'pending_results':{action['key']:{'action':action,'at':1}}}
        self.engine.settle_pending('1',row,state,{'stage':{'category':0,'level':18,'running':False,'repeat':False}})
        self.assertEqual(state.get('confirmed',0),0)
        self.engine.settle_pending('1',row,state,{'stage':{'category':0,'level':18,'running':True,'repeat':False}})
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
        class Process:
            pid=99
            info={'name':'python.exe'}
            def as_dict(self,attrs):return {'name':'DPS.exe','exe':str(runtime.GAME),'create_time':123}
        with patch.object(runtime.psutil,'process_iter',return_value=[Process()]),patch.object(runtime,'box_for',return_value='box'):
            self.assertEqual(runtime.discover(),[{'pid':99,'created':123,'box':'box','exe':str(runtime.GAME)}])

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
