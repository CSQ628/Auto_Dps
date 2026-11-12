from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import mimetypes
import secrets
import threading
import socket
import os
import psutil
from urllib.parse import unquote,urlsplit
from .storage import ROOT
from .loopback import LoopbackHTTPServer

class Server(LoopbackHTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    def __init__(self,engine,port=17860):
        self.engine=engine;self.csrf=secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1',port),Handler)
        self.origin=f'http://127.0.0.1:{self.server_port}'

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,value,content_type='application/json; charset=utf-8'):
        data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def valid_host(self):return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
    def do_GET(self):
        if not self.valid_host():return self.reply(403,{'error':'invalid_host'})
        path=urlsplit(self.path).path
        if path=='/api/state':
            state=self.server.engine.public_state();state['csrf']=self.server.csrf;state['transport']=self.server.transport_state();return self.reply(200,state)
        if path=='/api/health':return self.reply(200,{'app':'dps-assistant','ready':True,'transport':self.server.transport_state()})
        root=(ROOT/'web/dist').resolve();target=(root/unquote(path).lstrip('/')).resolve()
        if not target.is_relative_to(root):return self.reply(404,{'error':'not_found'})
        if not target.is_file():target=root/'index.html'
        if not target.is_file():return self.reply(503,{'error':'frontend_build_pending'})
        return self.reply(200,target.read_bytes(),mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
    def do_POST(self):
        if not self.valid_host() or self.headers.get('Origin')!=self.server.origin or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),self.server.csrf):return self.reply(403,{'error':'invalid_origin_or_csrf'})
        try:
            size=int(self.headers.get('Content-Length',0))
            if size>65536:return self.reply(413,{'error':'body_too_large'})
            value=json.loads(self.rfile.read(size) or b'{}')
            if self.path=='/api/consent':
                if value!={'accepted':True}:return self.reply(400,{'error':'请明确同意使用说明'})
                return self.reply(200,{'preferences':self.server.engine.accept_notice()})
            if self.path=='/api/config':return self.reply(200,{'config':self.server.engine.update(value)})
            if self.path=='/api/stop':
                self.server.engine.update({'running':False});return self.reply(200,{'ok':True})
            if self.path=='/api/shutdown':
                self.reply(200,{'ok':True,'pid':os.getpid(),'created':psutil.Process().create_time()});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            return self.reply(404,{'error':'not_found'})
        except (ValueError,TypeError,KeyError) as e:return self.reply(400,{'error':str(e)})
