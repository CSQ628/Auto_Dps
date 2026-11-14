import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dps_assistant import connections, engine, storage, runtime
from dps_assistant.policy import ranked_actions


def make_game(root):
    path = root/'游戏目录'/'DPS.exe'
    path.parent.mkdir(parents=True)
    path.touch()
    (path.parent/'GameAssembly.dll').touch()
    metadata = path.parent/'DPS_Data/il2cpp_data/Metadata/global-metadata.dat'
    metadata.parent.mkdir(parents=True)
    metadata.touch()
    return path


class ConnectionTests(unittest.TestCase):
    def test_directory_and_executable_paths_require_complete_game_files(self):
        with tempfile.TemporaryDirectory() as folder:
            game = make_game(Path(folder))
            for path in (str(game), str(game.parent), '"'+str(game)+'"'):
                self.assertEqual(connections.game_executable(path), str(game.resolve()))
            for path in ('', 'DPS.exe', str(game.parent.parent), 42, None):
                with self.assertRaises(ValueError):
                    connections.game_executable(path)

    def test_binding_rejects_pid_reuse_and_non_game_processes(self):
        process = type('Process', (), {'create_time': lambda self: 100,
                    'name': lambda self: 'DPS.exe', 'exe': lambda self: 'game',
                    'is_running': lambda self: True})()
        with patch.object(connections.psutil, 'Process', return_value=process), \
                patch.object(connections, 'game_executable', return_value='verified/DPS.exe'):
            self.assertEqual(connections.live_process(12, 100)['created'], 100)
            with self.assertRaisesRegex(ValueError, '复用'):
                connections.live_process(12, 99)
            for pid in (True, -1, 0, '12', 12.5):
                with self.assertRaises(ValueError):
                    connections.live_process(pid)
            process.name = lambda: 'other.exe'
            with self.assertRaisesRegex(ValueError, '不是 DPS'):
                connections.live_process(12)

    def test_manual_path_persists_without_changing_strategy_or_launching(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); game = make_game(root)
            with patch.object(engine, 'DATA', root), patch.object(storage, 'DATA', root):
                first = engine.Engine(start=False); second = None
                try:
                    before = copy.deepcopy(first.config)
                    self.assertEqual(first.bind({'path': str(game.parent)})['status'], 'saved')
                    self.assertEqual(first.config, before)
                    second = engine.Engine(start=False)
                    self.assertEqual(second.connection['game_path'], str(game.resolve()))
                    with patch.object(engine, 'atomic_json', side_effect=OSError('full')):
                        with self.assertRaises(OSError):
                            first.bind({'path': str(game)})
                    self.assertEqual(first.connection, second.connection)
                finally:
                    first.stop()
                    if second: second.stop()

    def test_manual_process_binding_keeps_automatic_instances_and_unique_account_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(engine, 'DATA', root), patch.object(storage, 'DATA', root):
                app = engine.Engine(start=False)
                try:
                    app.instances['7'] = {'id':'7','pid':7,'created':100,'identity':'host:account'}
                    app.config['instances'] = {'host:account':False,'box:other':False}
                    with patch.object(engine, 'live_process', return_value={'pid':7,'created':100,'exe':'DPS.exe'}), \
                            patch.object(engine, 'box_for', return_value=''):
                        result = app.bind({'pid':7,'created':100})
                    self.assertEqual(result['status'], 'connecting')
                    self.assertEqual(app.instances['7']['binding'], 'manual')
                    self.assertTrue(app.config['instances']['host:account'])
                    self.assertFalse(app.config['instances']['box:other'])
                    self.assertEqual(app.manual_bindings['7']['created'], 100)
                    for payload in ({}, {'pid':7,'path':'game'}, {'pid':7,'command':'other'}):
                        with self.assertRaises(ValueError): app.bind(payload)
                finally: app.stop()

    def test_scanning_a_sandbox_does_not_replace_host_launch_path(self):
        with tempfile.TemporaryDirectory() as folder:
            game = make_game(Path(folder))
            process = type('Process', (), {'pid':7,'as_dict':lambda self,attrs:
                {'name':'DPS.exe','exe':str(game),'create_time':100}})()
            with patch.object(runtime, 'GAME', Path('host/DPS.exe')), \
                    patch.object(runtime.psutil, 'process_iter', return_value=[process]), \
                    patch.object(runtime, 'box_for', return_value='sandbox'):
                self.assertEqual(runtime.discover()[0]['box'], 'sandbox')
                self.assertEqual(runtime.GAME, Path('host/DPS.exe'))


class CompatibilitySchedulingTests(unittest.TestCase):
    def test_manual_panel_filters_conflicts_but_keeps_other_growth(self):
        config = copy.deepcopy(engine.DEFAULT)
        actions = [{'kind':kind,'key':kind,'priority':90} for kind in ('equipment','rune','active')]
        scan = {'snapshot':{'loaded':True,'manualBlockedKinds':['equipment'],'currencies':{}},'actions':actions}
        self.assertEqual({a['kind'] for a in ranked_actions(scan, config, {}, 100)}, {'rune','active'})
        scan['snapshot']['automationBlocked'] = ['unknown-confirmation']
        self.assertEqual(ranked_actions(scan, config, {}, 100), [])

    def test_sort_waits_for_eligible_item_work_and_runs_before_low_priority_growth(self):
        config = copy.deepcopy(engine.DEFAULT)
        actions = [{'kind':kind,'key':kind,'priority':priority,'category':0,'maxGrade':1,'tier':1} for kind,priority in
                   [('sort',20),('combine',108),('decompose',102),('rune',90)]]
        scan = {'snapshot':{'loaded':True,'currencies':{}},'actions':actions}
        state = {'cooldowns':{}}
        self.assertEqual(ranked_actions(scan, config, state, 100)[0]['kind'], 'combine')
        self.assertNotIn('sort', [a['kind'] for a in ranked_actions(scan, config, state, 100)])
        state['cooldowns'] = {'combine':200,'decompose':200}
        self.assertEqual(ranked_actions(scan, config, state, 100)[0]['kind'], 'sort')


class FailureAtomicityTests(unittest.TestCase):
    def test_failed_binding_does_not_enable_or_mark_an_instance(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(engine,'DATA',root),patch.object(storage,'DATA',root):
                app=engine.Engine(start=False)
                try:
                    app.instances['7']={'created':100,'identity':'host:a'}
                    app.config['instances']={'host:a':False}
                    with patch.object(engine,'live_process',return_value={'pid':7,'created':100,'exe':'DPS.exe'}),patch.object(engine,'box_for',return_value=''),patch.object(engine,'atomic_json',side_effect=OSError('full')):
                        with self.assertRaises(OSError):app.bind({'pid':7,'created':100})
                    self.assertFalse(app.config['instances']['host:a'])
                    self.assertNotIn('binding',app.instances['7'])
                    self.assertEqual(app.manual_bindings,{})
                finally:app.stop()

    def test_recipe_precedes_recycling_even_after_long_wait(self):
        config=copy.deepcopy(engine.DEFAULT)
        for kind in ('combine','withdraw'):
            scan={'snapshot':{'loaded':True,'currencies':{}},'actions':[
                {'kind':kind,'key':kind,'priority':107,'purpose':'combine','category':0,'maxGrade':1,'tier':1},
                {'kind':'decompose','key':'recycle','priority':102}]}
            state={'last_module':{'combine':1000,'storage':1000,'decompose':0}}
            self.assertEqual(ranked_actions(scan,config,state,1000)[0]['kind'],kind)
            self.assertNotIn('decompose',[a['kind'] for a in ranked_actions(scan,config,state,1000)])
            state['cooldowns']={kind:2000}
            self.assertEqual(ranked_actions(scan,config,state,1000)[0]['kind'],'decompose')


class BindingHTTPTests(unittest.TestCase):
    def test_connections_and_binding_use_existing_origin_and_csrf_guards(self):
        import json,threading,urllib.request,urllib.error
        from dps_assistant.server import Server
        from dps_assistant.loopback import loopback_opener
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game=make_game(root)
            with patch.object(engine,'DATA',root),patch.object(storage,'DATA',root),patch.object(engine,'discover',return_value=[]):
                app=engine.Engine(start=False);server=Server(app,0)
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                opener=loopback_opener();base=server.origin
                def request(value,token=None):
                    headers={'Content-Type':'application/json','Origin':base}
                    if token is not None:headers['X-CSRF-Token']=token
                    return urllib.request.Request(base+'/api/bind',data=json.dumps(value).encode(),headers=headers)
                try:
                    self.assertTrue(json.load(opener.open(base+'/api/connections'))['automatic'])
                    with self.assertRaises(urllib.error.HTTPError) as denied:opener.open(request({'path':str(game)}))
                    self.assertEqual(denied.exception.code,403)
                    self.assertEqual(json.load(opener.open(request({'path':str(game)},server.csrf)))['status'],'saved')
                    self.assertEqual(app.connection['game_path'],str(game.resolve()))
                    with self.assertRaises(urllib.error.HTTPError) as invalid:opener.open(request({'pid':True},server.csrf))
                    self.assertEqual(invalid.exception.code,400)
                    with patch.object(engine,'atomic_json',side_effect=OSError('full')):
                        with self.assertRaises(urllib.error.HTTPError) as failed:opener.open(request({'path':str(game)},server.csrf))
                        self.assertEqual(failed.exception.code,500)
                        self.assertIn('未能保存',json.load(failed.exception)['error'])
                finally:server.shutdown();server.server_close();worker.join(3);app.stop()
