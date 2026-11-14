"""One authenticated loopback bridge per game process, including Sandboxie instances."""
import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import psutil

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
from dps_assistant.loopback import LoopbackHTTPServer
from dps_assistant.box_receipts import BoxReceiptStore
from dps_assistant.workshop_receipts import WorkshopReceiptStore


class NotReady(RuntimeError):
    def __init__(self, health):
        self.health = health
        super().__init__('bridge_initialization_failed' if health['phase'] == 'failed' else 'bridge_not_ready')


class BridgeHost:
    def __init__(self, pid, root=ROOT, attach=None, process_created=None, receipt_directory=None, workshop_receipt_directory=None):
        self.pid, self.root, self.attach = pid, root, attach
        self.started = time.monotonic()
        self.state_lock, self.operation_lock = threading.RLock(), threading.RLock()
        self.phase, self.step, self.error = 'starting', 'attach', None
        self.session = self.script = None
        self.source_hash = None
        self.closed = False
        self.process_created=process_created;self.receipt_directory=receipt_directory;self.box_store=None
        self.workshop_store=None;self.workshop_receipt_directory=workshop_receipt_directory

    def script_message(self, message, data):
        payload=message.get('payload')
        if message.get('type')=='send' and isinstance(payload,dict) and payload.get('channel')=='box_receipt':
            if self.box_store is not None:self.box_store.checkpoint(payload.get('receipt'))
            return
        if message.get('type')=='send' and isinstance(payload,dict) and payload.get('channel')=='workshop_receipt':
            if self.workshop_store is not None:self.workshop_store.checkpoint(payload.get('receipt'))
            return
        report_script_error(message,data)

    def health(self):
        # Initialization and native calls must never block this lock or the health endpoint.
        with self.state_lock:
            return {'pid': self.pid, 'phase': self.phase, 'step': self.step,
                    'ageSeconds': round(time.monotonic() - self.started, 2), 'error': self.error}

    def detached(self, reason, crash=None):
        with self.state_lock:
            if not self.closed:
                self.phase, self.error = 'failed', 'bridge_detached: ' + str(reason)

    def initialize(self):
        try:
            attach = self.attach
            if attach is None:
                import frida
                attach = frida.attach
            self.session = attach(self.pid)
            self.session.on('detached', self.detached)
            source = '\n'.join((self.root/'bridge'/name).read_text(encoding='utf-8') for name in
                               ['il2cpp.js', 'worker.js', 'systems.js', 'planner.js', 'automation.js']
                               if (self.root/'bridge'/name).exists())
            self.source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
            self.script = self.session.create_script(source)
            self.script.on('message', self.script_message)
            with self.state_lock:
                self.step = 'load'
            self.script.load()
            with self.state_lock:
                self.step = 'exports'
            exports=self.script.list_exports_sync()
            if 'opportunities' not in exports:
                raise RuntimeError('bridge_script_initialization_incomplete')
            if 'restoreboxreceipts' in exports:
                created=psutil.Process(self.pid).create_time()
                if self.process_created is not None and abs(created-self.process_created)>.001:
                    raise RuntimeError('game_process_identity_changed')
                self.box_store=BoxReceiptStore(self.pid,created,self.receipt_directory)
                self.script.exports_sync.restoreboxreceipts(self.box_store.restore())
            if 'restoreworkshopreceipts' in exports and 'workshopreceipt' in exports:
                created=psutil.Process(self.pid).create_time()
                if self.process_created is not None and abs(created-self.process_created)>.001:
                    raise RuntimeError('game_process_identity_changed')
                self.workshop_store=WorkshopReceiptStore(self.pid,created,self.workshop_receipt_directory)
                self.script.exports_sync.restoreworkshopreceipts(self.workshop_store.restore())
            with self.state_lock:
                if self.closed or self.phase == 'failed':
                    return
                self.phase, self.step = 'ready', 'ready'
        except Exception as error:
            with self.state_lock:
                self.phase, self.error = 'failed', str(error)
            print('bridge initialization failed: ' + str(error), flush=True)

    def call(self, request):
        with self.operation_lock:
            health = self.health()
            if health['phase'] != 'ready':
                raise NotReady(health)
            op = request['op']
            if op == 'backup':
                snapshot = self.script.exports_sync.snapshot()
                source = Path(snapshot['saveDirectory']).resolve()
                expected = Path.home()/'AppData/LocalLow/DetailGames/DPS/saves'
                if not source.is_relative_to(expected.resolve()):
                    raise ValueError('unexpected_save_directory')
                files = [x for x in source.rglob('*') if x.is_file() and x.suffix in ('.sav', '.bak', '.json', '.vdf')]
                if not files or sum(x.stat().st_size for x in files) > 64*1024*1024:
                    raise ValueError('backup_size_or_empty')
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for file in files:
                        archive.write(file, file.relative_to(source))
                data = buffer.getvalue()
                return {'account': snapshot['account'], 'source': str(source), 'files': len(files),
                        'sha256': hashlib.sha256(data).hexdigest(), 'zip': base64.b64encode(data).decode()}
            fn = getattr(self.script.exports_sync, op)
            result = fn(request['args']) if 'args' in request else fn()
            if self.workshop_store is not None and op in ('execute','workshopreceipt') and isinstance(result,dict):
                receipt=result.pop('workshopReceipt',None) if op=='execute' else result
                if receipt:self.workshop_store.checkpoint(receipt)
                if op=='execute':result['workshopReceiptPersistence']='unavailable' if self.workshop_store.failed else 'available'
            if self.box_store is not None and op in ('openboxes','boxscan') and isinstance(result,dict):
                receipt=result if op=='openboxes' else result.get('receipt')
                if receipt:self.box_store.checkpoint(receipt)
                result['receiptPersistence']='unavailable' if self.box_store.failed else 'available'
                result['bridgeSourceHash']=self.source_hash
            if op == 'opportunities':
                result['workshopReceiptsSupported']=self.workshop_store is not None
                result['workshopReceiptPersistence']='unavailable' if self.workshop_store is None or self.workshop_store.failed else 'available'
                result['bridgeSourceHash'] = self.source_hash
                if isinstance(result.get('snapshot'), dict):
                    result['snapshot']['bridgeSourceHash'] = self.source_hash
            elif op == 'snapshot':
                result['bridgeSourceHash'] = self.source_hash
            return result

    def close(self):
        with self.state_lock:
            self.closed = True
        with self.operation_lock:
            if self.script:
                try:
                    self.script.exports_sync.dispose()
                except Exception:
                    pass
                try:
                    self.script.unload()
                except Exception:
                    pass
            if self.session:
                try:
                    self.session.detach()
                except Exception:
                    pass


def report_script_error(message, data):
    if message.get('type') == 'error':
        print(message.get('stack') or message.get('description'), flush=True)


def handler_for(host, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def do_GET(self):
            if not self.authorized():
                return self.send_json(403, {'error': 'unauthorized'})
            if self.path not in ('/health', '/api/health'):
                return self.send_json(404, {'error': 'not_found'})
            self.send_json(200, {'result': {**host.health(), 'transport': self.server.transport_state()}, 'pid': host.pid})

        def do_POST(self):
            if not self.authorized():
                return self.send_json(403, {'error': 'unauthorized'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size < 65536:
                    return self.send_json(400, {'error': 'body_size'})
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict) or request.get('op') not in ('snapshot', 'opportunities', 'execute', 'backup', 'boxscan', 'openboxes', 'workshopreceipt'):
                    return self.send_json(400, {'error': 'unknown_operation'})
                result = host.call(request)
                self.send_json(200, {'result': result, 'pid': host.pid})
            except NotReady as error:
                self.send_json(503, {'error': str(error), 'health': error.health, 'pid': host.pid})
            except Exception as error:
                self.send_json(503, {'error': str(error), 'pid': host.pid})
    return Handler


def watch_owner(pid, created):
    while True:
        try:
            if abs(psutil.Process(pid).create_time() - created) > .01:
                break
        except psutil.NoSuchProcess:
            break
        except psutil.AccessDenied:
            pass
        threading.Event().wait(2)
    os._exit(0)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--target-created', type=float)
    parser.add_argument('--owner-pid', type=int, required=True)
    parser.add_argument('--owner-created', type=float, required=True)
    args = parser.parse_args(argv)
    host = BridgeHost(args.pid,process_created=args.target_created)
    # Bind before importing/attaching Frida: the parent can distinguish slow startup from a dead helper.
    server = LoopbackHTTPServer(('127.0.0.1', args.port), handler_for(host, args.token))
    threading.Thread(target=watch_owner, args=(args.owner_pid, args.owner_created), daemon=True).start()
    threading.Thread(target=host.initialize, daemon=True, name='bridge-initialize').start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        host.close()


if __name__ == '__main__':
    main()
