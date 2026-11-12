"""Each game process gets its own loopback bridge, launched inside its Sandboxie box if present."""
import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import frida
import psutil

p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--token',required=True)
p.add_argument('--owner-pid',type=int,required=True);p.add_argument('--owner-created',type=float,required=True)
a=p.parse_args();root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(root))
from dps_assistant.loopback import LoopbackHTTPServer

def watch_owner():
    while True:
        try:
            if abs(psutil.Process(a.owner_pid).create_time()-a.owner_created)>.01:break
        except psutil.NoSuchProcess:break
        except psutil.AccessDenied:pass
        threading.Event().wait(2)
    # Also covers a helper stuck before it opens its HTTP listener.
    os._exit(0)

threading.Thread(target=watch_owner,daemon=True).start()
session=frida.attach(a.pid)
source='\n'.join((root/'bridge'/n).read_text(encoding='utf-8') for n in ['il2cpp.js','worker.js','systems.js','planner.js','automation.js'] if (root/'bridge'/n).exists())
source_hash=hashlib.sha256(source.encode('utf-8')).hexdigest()
script=session.create_script(source)
def report_script_error(message,data):
    if message.get('type')=='error':print(message.get('stack') or message.get('description'),flush=True)
script.on('message',report_script_error)
script.load()
if 'opportunities' not in script.list_exports_sync():
    script.unload();session.detach();raise RuntimeError('bridge_script_initialization_incomplete')
lock=threading.RLock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send_json(self,status,value):
        data=json.dumps(value,ensure_ascii=False).encode('utf-8');self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+a.token):return self.send_json(403,{'error':'unauthorized'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<65536: return self.send_json(400,{'error':'body_size'})
            request=json.loads(self.rfile.read(size));op=request.get('op')
            if op not in ('snapshot','opportunities','execute','backup'):return self.send_json(400,{'error':'unknown_operation'})
            with lock:
                if op=='backup':
                    snapshot=script.exports_sync.snapshot()
                    source=Path(snapshot['saveDirectory']).resolve()
                    expected=Path.home()/'AppData/LocalLow/DetailGames/DPS/saves'
                    if not source.is_relative_to(expected.resolve()):raise ValueError('unexpected_save_directory')
                    files=[x for x in source.rglob('*') if x.is_file() and x.suffix in ('.sav','.bak','.json','.vdf')]
                    if not files or sum(x.stat().st_size for x in files)>64*1024*1024:raise ValueError('backup_size_or_empty')
                    buffer=io.BytesIO()
                    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
                        for file in files:archive.write(file,file.relative_to(source))
                    data=buffer.getvalue()
                    result={'account':snapshot['account'],'source':str(source),'files':len(files),'sha256':hashlib.sha256(data).hexdigest(),'zip':base64.b64encode(data).decode()}
                else:
                    fn=getattr(script.exports_sync,op)
                    result=fn(request['args']) if 'args' in request else fn()
                    if op=='opportunities':result['snapshot']['bridgeSourceHash']=source_hash
                    elif op=='snapshot':result['bridgeSourceHash']=source_hash
            self.send_json(200,{'result':result,'pid':a.pid})
        except Exception as e:self.send_json(503,{'error':str(e),'pid':a.pid})

try:LoopbackHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
finally:
    try:script.exports_sync.dispose()
    finally:session.detach()
