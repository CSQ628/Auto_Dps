import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

import psutil
from dps_assistant import runtime
from dps_assistant.loopback import LoopbackHTTPServer, loopback_opener
from tools.bridge_host import BridgeHost, handler_for


def client(port, pid=123):
    bridge = runtime.Bridge.__new__(runtime.Bridge)
    bridge.identity = {'pid': pid, 'box': ''}
    bridge.port, bridge.token = port, 'test-session'
    bridge.closed, bridge.started = False, runtime.time.time()
    bridge.closing, bridge.last_health = threading.Event(), None
    bridge.valid = lambda: True
    return bridge


class Script:
    def __init__(self, block=None):
        self.exports_sync = self
        self.block = block
        self.entered = threading.Event()
        self.executions = 0
        self.exports = ['opportunities', 'snapshot', 'execute', 'dispose']

    def on(self, *args):
        pass

    def load(self):
        self.entered.set()
        if self.block and not self.block.wait(5):
            raise TimeoutError('test initialization gate')

    def list_exports_sync(self):
        return self.exports

    def opportunities(self):
        return {'snapshot': {'account': 'test'}, 'actions': [], 'issues': []}

    def snapshot(self):
        return {'account': 'test'}

    def execute(self, args):
        self.executions += 1
        return {'status': 'confirmed'}

    def dispose(self):
        pass

    def unload(self):
        pass


class Session:
    def __init__(self, script):
        self.script = script

    def on(self, *args):
        pass

    def create_script(self, source):
        return self.script

    def detach(self):
        pass


class BridgeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root/'bridge').mkdir()
        (self.root/'bridge/automation.js').write_text('test source', encoding='utf-8')
        self.servers = []

    def tearDown(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join(3)
        self.directory.cleanup()

    def serve(self, host, port=0, handler=None):
        server = LoopbackHTTPServer(('127.0.0.1', port), handler or handler_for(host, 'test-session'))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return server

    def test_health_and_rejection_remain_available_during_slow_attach_and_load(self):
        for phase in ('attach', 'load'):
            with self.subTest(phase=phase):
                release, entered = threading.Event(), threading.Event()
                script = Script(release if phase == 'load' else None)
                def attach(pid):
                    entered.set()
                    if phase == 'attach' and not release.wait(5):
                        raise TimeoutError('test attach gate')
                    return Session(script)
                host = BridgeHost(123, self.root, attach)
                server = self.serve(host)
                initializer = threading.Thread(target=host.initialize, daemon=True)
                initializer.start()
                try:
                    self.assertTrue((entered if phase == 'attach' else script.entered).wait(2))
                    bridge = client(server.server_port)
                    health = bridge.health()
                    self.assertEqual((health['phase'], health['step']), ('starting', phase))
                    with self.assertRaises(runtime.BridgeStarting):
                        runtime.post(server.server_port, bridge.token, 'execute', {})
                    self.assertEqual(script.executions, 0)
                finally:
                    release.set()
                    initializer.join(3)
                self.assertFalse(initializer.is_alive())
                result = bridge.call('opportunities')
                self.assertEqual(result['snapshot']['account'], 'test')
                self.assertEqual(len(result['snapshot']['bridgeSourceHash']), 64)
                self.assertEqual(bridge.health()['phase'], 'ready')
                host.close()

    def test_starting_and_failed_health_are_authenticated(self):
        script = Script()
        script.exports = []
        host = BridgeHost(123, self.root, lambda pid: Session(script))
        server = self.serve(host)
        for phase in ('starting', 'failed'):
            with self.subTest(phase=phase):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    loopback_opener().open(f'http://127.0.0.1:{server.server_port}/health', timeout=2)
                self.assertEqual(error.exception.code, 403)
                self.assertEqual(client(server.server_port).health()['phase'], phase)
                if phase == 'starting':
                    host.initialize()
        with self.assertRaisesRegex(runtime.BridgeFailure, 'bridge_script_initialization_incomplete'):
            client(server.server_port).call('opportunities')
        self.assertEqual(script.executions, 0)
        host.close()

    def test_refused_first_health_recovers_when_listener_becomes_available(self):
        host = BridgeHost(123, self.root, lambda pid: Session(Script()))
        host.initialize()
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
        bridge = client(port)
        original = bridge.health
        attempts = []
        def health(timeout=1):
            attempts.append(True)
            try:
                return original(timeout)
            except urllib.error.URLError:
                if len(attempts) == 1:
                    self.serve(host, port)
                raise
        bridge.health = health
        self.assertEqual(bridge.call('snapshot')['account'], 'test')
        self.assertGreaterEqual(len(attempts), 2)
        host.close()

    def test_known_initialization_failure_is_not_retried_as_transport_failure(self):
        bridge = client(1)
        bridge.health = lambda timeout=1: {'phase': 'failed', 'error': 'attach denied'}
        with patch.object(runtime, 'post') as post:
            with self.assertRaisesRegex(runtime.BridgeFailure, 'attach denied'):
                bridge.call('opportunities')
            post.assert_not_called()

    def test_startup_wait_is_bounded_and_cancellable(self):
        bridge = client(1)
        bridge.health = lambda timeout=1: {'phase': 'starting', 'step': 'load'}
        with self.assertRaises(runtime.BridgeStarting):
            bridge.wait_ready(timeout=0)
        bridge.started -= runtime.BRIDGE_STARTUP_SECONDS
        with self.assertRaises(runtime.BridgeFailure):
            bridge.wait_ready(timeout=0)
        bridge.started = runtime.time.time()
        bridge.closing.set()
        with self.assertRaisesRegex(RuntimeError, 'bridge_closed'):
            bridge.wait_ready()

    def test_only_observation_retries_a_lost_reply(self):
        for op in ('snapshot', 'opportunities', 'execute', 'backup'):
            with self.subTest(op=op):
                host = BridgeHost(123, self.root)
                host.phase = 'ready'
                base = handler_for(host, 'test-session')
                attempts = []
                class LostReply(base):
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']))
                        attempts.append(True)
                        if len(attempts) == 1:
                            self.connection.shutdown(socket.SHUT_RDWR)
                            self.connection.close()
                        else:
                            self.send_json(200, {'result': {'status': 'confirmed'}, 'pid': 123})
                server = self.serve(host, handler=LostReply)
                bridge = client(server.server_port)
                if op in ('snapshot', 'opportunities'):
                    self.assertEqual(bridge.call(op), {'status': 'confirmed'})
                    self.assertEqual(len(attempts), 2)
                else:
                    with self.assertRaises((OSError, runtime.http.client.HTTPException)):
                        bridge.call(op)
                    self.assertEqual(len(attempts), 1)

    def test_native_operation_error_is_not_automatically_retried(self):
        bridge = client(1)
        bridge.wait_ready = lambda: None
        with patch.object(runtime, 'post', side_effect=RuntimeError('native unavailable')) as post:
            with self.assertRaisesRegex(RuntimeError, 'native unavailable'):
                bridge.call('opportunities')
            self.assertEqual(post.call_count, 1)

    def test_response_timeout_switches_read_channel_and_pins_next_execute_to_working_channel(self):
        script=Script();host=BridgeHost(123,self.root,lambda pid:Session(script));host.initialize()
        bridge=client(self.serve(host).server_port)
        original=runtime._http.open
        def open_request(request,**kwargs):
            if request.get_method()=='POST':raise urllib.error.URLError('timed out')
            return original(request,**kwargs)
        with patch.object(runtime._http,'open',side_effect=open_request) as native, \
             patch.object(runtime._system_http,'open',wraps=runtime._system_http.open) as system:
            self.assertEqual(bridge.call('snapshot')['account'],'test')
            self.assertFalse(bridge.prefer_native)
            self.assertEqual(bridge.call('execute',{})['status'],'confirmed')
            self.assertEqual(sum(c.args[0].get_method()=='POST' for c in native.call_args_list),1)
            self.assertEqual(sum(c.args[0].get_method()=='POST' for c in system.call_args_list),2)
            self.assertEqual(script.executions,1)
        host.close()

    def test_execute_response_timeout_is_never_replayed_on_another_channel(self):
        bridge=client(1)
        with patch.object(runtime._http,'open',side_effect=urllib.error.URLError('timed out')) as native, \
             patch.object(runtime._system_http,'open') as system:
            with self.assertRaises(urllib.error.URLError):bridge.call('execute',{})
            self.assertEqual(native.call_count,1);system.assert_not_called()

    def test_proxy_timeout_string_is_transport_failure_but_native_error_is_distinct(self):
        self.assertTrue(runtime.transport_error(urllib.error.URLError('timed out')))
        self.assertFalse(runtime.transport_error(RuntimeError('native timed out')))
        self.assertIn('直连通道',runtime.bridge_error_message(urllib.error.URLError('timed out')))
        self.assertIn('游戏主线程',runtime.bridge_error_message(RuntimeError('main_thread_timeout')))

    def test_repeated_observation_failures_stop_after_three_attempts(self):
        bridge = client(1)
        bridge.wait_ready = lambda: None
        with patch.object(runtime, 'post', side_effect=ConnectionResetError('reply lost')) as post, \
             patch.object(bridge.closing, 'wait', return_value=False):
            with self.assertRaises(ConnectionResetError):
                bridge.call('snapshot')
            self.assertEqual(post.call_count, 3)

    def test_identity_change_during_startup_prevents_business_request(self):
        bridge = client(1)
        def ready():
            bridge.valid = lambda: False
        bridge.wait_ready = ready
        with patch.object(runtime, 'post') as post:
            with self.assertRaisesRegex(RuntimeError, 'game_process_identity_changed'):
                bridge.call('opportunities')
            post.assert_not_called()

    def test_health_stays_responsive_while_execute_holds_native_lock(self):
        entered, release = threading.Event(), threading.Event()
        script = Script()
        original = script.execute
        def execute(args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test execute gate')
            return original(args)
        script.execute = execute
        host = BridgeHost(123, self.root, lambda pid: Session(script))
        host.initialize()
        bridge = client(self.serve(host).server_port)
        results = []
        worker = threading.Thread(target=lambda: results.append(bridge.call('execute', {})))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(bridge.health(timeout=1)['phase'], 'ready')
        finally:
            release.set()
            worker.join(3)
            host.close()
        self.assertEqual(results, [{'status': 'confirmed'}])

    def test_detached_session_reports_failure_instead_of_stale_ready(self):
        host = BridgeHost(123, self.root, lambda pid: Session(Script()))
        host.initialize()
        bridge = client(self.serve(host).server_port)
        host.detached('process-terminated')
        with self.assertRaisesRegex(runtime.BridgeFailure, 'process-terminated'):
            bridge.call('snapshot')
        host.close()

    def test_source_and_desktop_dispatch_expose_failure_health_for_missing_target(self):
        # A nonexistent PID exercises both real entry points without attaching to any game.
        root = Path(__file__).resolve().parents[1]
        for entry in ([sys.executable, str(root/'tools/bridge_host.py')],
                      [sys.executable, str(root/'desktop_entry.py'), '--bridge-host']):
            with self.subTest(entry=Path(entry[1]).name):
                with socket.socket() as reserved:
                    reserved.bind(('127.0.0.1', 0))
                    port = reserved.getsockname()[1]
                pid = 2147483647
                process = subprocess.Popen([*entry, '--pid', str(pid), '--port', str(port),
                                            '--token=test-session', '--owner-pid', str(os.getpid()),
                                            '--owner-created', str(psutil.Process().create_time())],
                                           cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    bridge = client(port, pid)
                    with self.assertRaises(runtime.BridgeFailure):
                        bridge.wait_ready(timeout=8)
                    health = bridge.health()
                    self.assertEqual(health['phase'], 'failed')
                    self.assertTrue(health['error'])
                    self.assertIsNone(process.poll())
                finally:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
