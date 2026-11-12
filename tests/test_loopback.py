import threading
import unittest
from unittest.mock import patch
import os
from http.server import BaseHTTPRequestHandler
from dps_assistant.loopback import LoopbackHTTPServer, loopback_opener, _Connection


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LoopbackTests(unittest.TestCase):
    def test_explicit_system_preference_uses_system_socket_first(self):
        from unittest.mock import Mock
        sock=Mock();connection=_Connection('127.0.0.1',timeout=4,prefer_native=False)
        with patch('dps_assistant.loopback._make_socket',return_value=(sock,'system')) as make:
            connection.connect()
        make.assert_called_once_with(False)
        sock.connect.assert_called_once_with(('127.0.0.1',80))
        self.assertEqual(sock.settimeout.call_args.args,(4,))

    def test_failover_shares_connect_budget_and_restores_full_read_timeout(self):
        from unittest.mock import Mock,call
        failed,working=Mock(),Mock();failed.connect.side_effect=TimeoutError('provider_changed')
        connection=_Connection('127.0.0.1',timeout=4)
        with patch('dps_assistant.loopback._make_socket',side_effect=[(failed,'native'),(working,'system')]) as make, \
             patch('dps_assistant.loopback.time.monotonic',side_effect=[100,100,102]):
            connection.connect()
        self.assertEqual(make.call_args_list,[call(True),call(False)])
        failed.close.assert_called_once()
        self.assertEqual(failed.settimeout.call_args_list,[call(2)])
        self.assertEqual(working.settimeout.call_args_list,[call(2),call(4)])
        self.assertIs(connection.sock,working)

    def test_http_roundtrip_uses_real_native_loopback(self):
        server = LoopbackHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for _ in range(3):
                with loopback_opener().open('http://127.0.0.1:'+str(server.server_port)+'/api/health', timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b'{"ok":true}')
        finally:
            server.shutdown(); server.server_close(); thread.join(3)

    @unittest.skipUnless(os.name == 'nt', 'Windows provider failover')
    def test_missing_native_provider_falls_back_to_system(self):
        with patch('dps_assistant.loopback._windows_socket', side_effect=OSError('provider_changed')):
            server = LoopbackHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                self.assertEqual(server.transport_state()['mode'], 'system')
                with loopback_opener().open('http://127.0.0.1:'+str(server.server_port), timeout=3) as response:
                    self.assertEqual(response.read(), b'{"ok":true}')
            finally:
                server.shutdown(); server.server_close(); thread.join(3)

    def test_repeated_accept_failures_reopen_listener_without_replaying_actions(self):
        server = LoopbackHTTPServer(('127.0.0.1', 0), Handler)
        original = server.socket
        class BrokenAccept:
            def accept(self):
                raise OSError(10053, 'simulated_provider_change')
            def close(self):
                original.close()
        server.socket = BrokenAccept()
        for _ in range(3):
            with self.assertRaises(OSError):
                server.get_request()
        self.assertEqual(server.transport_state()['recoveries'], 1)
        self.assertEqual(server.transport_state()['last_error'], 10053)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with loopback_opener().open('http://127.0.0.1:'+str(server.server_port), timeout=3) as response:
                self.assertEqual(response.read(), b'{"ok":true}')
        finally:
            server.shutdown(); server.server_close(); thread.join(3)

    def test_serving_loop_tracks_replaced_socket_after_provider_failure(self):
        server = LoopbackHTTPServer(('127.0.0.1', 0), Handler)
        original = server.socket
        class BrokenAccept:
            def fileno(self):
                return original.fileno()
            def accept(self):
                raise OSError(10053, 'simulated_provider_change')
            def close(self):
                original.close()
        server.socket = BrokenAccept()
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            succeeded = False
            for _ in range(6):
                try:
                    with loopback_opener().open('http://127.0.0.1:'+str(server.server_port), timeout=2) as response:
                        succeeded = response.read() == b'{"ok":true}'
                        if succeeded:
                            break
                except OSError:
                    pass
            self.assertTrue(succeeded)
            self.assertEqual(server.transport_state()['recoveries'], 1)
            self.assertTrue(thread.is_alive())
        finally:
            server.shutdown(); server.server_close(); thread.join(3)

    def test_transport_rejects_external_hosts_and_tunnels(self):
        with self.assertRaisesRegex(ValueError, 'loopback_address_required'):
            _Connection('example.invalid').connect()
        connection = _Connection('127.0.0.1'); connection.set_tunnel('example.invalid')
        with self.assertRaisesRegex(ValueError, 'loopback_address_required'):
            connection.connect()

    def test_loopback_bypasses_environment_and_system_proxy_with_no_bypass_rules(self):
        server = LoopbackHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxies={'http':'http://127.0.0.1:1','https':'http://127.0.0.1:1','all':'socks5://127.0.0.1:1'}
            with patch.dict(os.environ, {'HTTP_PROXY':proxies['http'],'HTTPS_PROXY':proxies['https'],
                                         'ALL_PROXY':proxies['all'],'NO_PROXY':'','no_proxy':''}), \
                 patch('urllib.request.getproxies', return_value=proxies), \
                 patch('urllib.request.proxy_bypass', return_value=False):
                with loopback_opener().open('http://127.0.0.1:'+str(server.server_port)+'/health', timeout=2) as response:
                    self.assertEqual(response.read(), b'{"ok":true}')
        finally:
            server.shutdown();server.server_close();thread.join(3)


if __name__ == '__main__':
    unittest.main()
