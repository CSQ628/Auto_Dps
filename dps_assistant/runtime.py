import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import string
import subprocess
import sys
import time
import tempfile
import hashlib
import urllib.request
import psutil
from .storage import DATA,ROOT,atomic_json
from .loopback import loopback_opener

from .platform_paths import find_game,find_sandboxie,valid_game,bridge_command
GAME=find_game()
SBIE=find_sandboxie()
_api=None
_http=loopback_opener()

def box_for(pid):
    global _api
    if not (SBIE/'SbieDll.dll').is_file():return ''
    if _api is None:
        lib=ctypes.WinDLL(str(SBIE/'SbieDll.dll'))
        _api=lib.SbieApi_QueryProcess;_api.argtypes=[W.HANDLE,W.LPWSTR,W.LPWSTR,W.LPWSTR,ctypes.POINTER(W.ULONG)];_api.restype=W.LONG
    box=ctypes.create_unicode_buffer(64);image=ctypes.create_unicode_buffer(512);sid=ctypes.create_unicode_buffer(256);session=W.ULONG()
    status=_api(pid,box,image,sid,ctypes.byref(session))
    return box.value if status==0 else ''

def discover():
    global GAME
    out=[]
    for p in psutil.process_iter():
        try:
            # process_iter caches Process objects globally; another thread can replace .info.
            info=p.as_dict(attrs=['name','exe','create_time'])
            if (info['name'] or '').lower()!='dps.exe' or not info['exe']:continue
            if not valid_game(info['exe']):continue
            GAME=Path(info['exe']).resolve()
            out.append({'pid':p.pid,'created':info['create_time'],'box':box_for(p.pid),'exe':info['exe']})
        except (psutil.Error,OSError):continue
    return out

def post(port,token,op,args=None,timeout=15):
    payload={'op':op}
    if args is not None:payload['args']=args
    req=urllib.request.Request(f'http://127.0.0.1:{port}/',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with _http.open(req,timeout=timeout) as response:body=json.load(response)
    except urllib.error.HTTPError as e:
        body=json.load(e);raise RuntimeError(body.get('error',str(e))) from e
    if 'error' in body:raise RuntimeError(body['error'])
    return body['result']

class Bridge:
    def __init__(self,identity):
        self.identity=identity;self.token=secrets.token_urlsafe(32)
        with socket.socket() as s:s.bind(('127.0.0.1',0));self.port=s.getsockname()[1]
        self.started=time.time();self.closed=False
        args=[*bridge_command(),'--pid',str(identity['pid']),'--port',str(self.port),'--token='+self.token,
              '--owner-pid',str(os.getpid()),'--owner-created',str(psutil.Process().create_time())]
        if identity['box']:args=[str(SBIE/'Start.exe'),'/silent','/wait','/box:'+identity['box'],*args]
        log=(DATA/f"bridge-{identity['pid']}.log").open('ab')
        self.process=subprocess.Popen(args,cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        log.close()
    def valid(self):
        try:
            process=psutil.Process(self.identity['pid'])
            return abs(process.create_time()-self.identity['created'])<.01 and Path(process.exe()).resolve()==Path(self.identity['exe']).resolve() and box_for(process.pid)==self.identity['box']
        except psutil.Error:return False
    def call(self,op,args=None):
        if not self.valid():raise RuntimeError('game_process_identity_changed')
        return post(self.port,self.token,op,args)
    def close(self):
        if self.closed:return
        self.closed=True
        # Sandboxie's launcher can exit before its helper, which is then reparented to SbieSvc.
        # Identify that helper by its exact script, target, port and private session token.
        for helper in psutil.process_iter():
            try:
                info=helper.as_dict(attrs=['name','cmdline']);args=info['cmdline'] or []
                source_helper=(info['name'] or '').lower() in ('python.exe','pythonw.exe') and any(Path(arg).resolve()==(ROOT/'tools/bridge_host.py').resolve() for arg in args if arg.endswith('bridge_host.py'))
                frozen_helper=getattr(sys,'frozen',False) and '--bridge-host' in args and args and Path(args[0]).resolve()==Path(sys.executable).resolve()
                if not(source_helper or frozen_helper):continue
                if not all(flag+'='+value in args or flag in args and args[args.index(flag)+1]==value for flag,value in (
                    ('--pid',str(self.identity['pid'])),('--port',str(self.port)),('--token',self.token))):continue
                helper.terminate()
            except (psutil.Error,OSError,ValueError,IndexError):pass
        # The Popen handle, not a recycled PID, determines whether the launcher is still ours.
        if self.process.poll() is not None:return
        try:
            parent=psutil.Process(self.process.pid)
            for p in parent.children(recursive=True):
                try:p.terminate()
                except psutil.Error:pass
            parent.terminate()
        except psutil.Error:pass

def backup_save(identity,directory):
    src=Path(directory)
    if identity['box']:
        # A helper in the same box reads the virtual view. Never claim a host copy covers a sandbox.
        return {'status':'required','reason':'sandbox_snapshot_pending'}
    if not src.is_dir():raise RuntimeError('save_directory_unavailable')
    target=DATA/'backups'/('process-'+str(identity['pid'])+'-'+time.strftime('%Y%m%d-%H%M%S'))
    shutil.copytree(src,target)
    atomic_json(target/'assistant-backup.json',{'identity':identity,'source':str(src),'created':time.time()})
    return {'status':'created','path':str(target)}

def launch(box=''):
    global GAME
    if GAME is None or not GAME.is_file():GAME=find_game()
    if GAME is None:raise RuntimeError('未找到已安装的 DPS 游戏，请先从 Steam 启动游戏；助手会自动接入。')
    args=[str(GAME)]
    if box:
        if not box.replace('_','').isalnum():raise ValueError('invalid_sandbox_name')
        prepare_sandbox_boot(box)
        args=[str(SBIE/'Start.exe'),'/silent','/box:'+box,*args]
    return subprocess.Popen(args,cwd=GAME.parent,creationflags=subprocess.CREATE_NO_WINDOW).pid

def sandbox_root(box):
    lib=ctypes.WinDLL(str(SBIE/'SbieDll.dll'))
    query=lib.SbieApi_QueryBoxPath
    query.argtypes=[W.LPCWSTR,W.LPWSTR,W.LPWSTR,W.LPWSTR,ctypes.POINTER(W.ULONG),ctypes.POINTER(W.ULONG),ctypes.POINTER(W.ULONG)]
    query.restype=W.LONG
    buffers=[ctypes.create_unicode_buffer(16384) for _ in range(3)]
    lengths=[W.ULONG(ctypes.sizeof(b)) for b in buffers]
    if query(box,*buffers,*[ctypes.byref(n) for n in lengths])!=0:raise RuntimeError('sandbox_root_unavailable')
    native=buffers[0].value
    dos=ctypes.WinDLL('kernel32').QueryDosDeviceW;dos.argtypes=[W.LPCWSTR,W.LPWSTR,W.DWORD];dos.restype=W.DWORD
    for letter in string.ascii_uppercase:
        target=ctypes.create_unicode_buffer(32768)
        if dos(letter+':',target,len(target)) and native.casefold().startswith(target.value.casefold()+'\\'):
            return Path(letter+':'+native[len(target.value):])
    raise RuntimeError('sandbox_root_drive_unresolved')

def prepare_sandbox_boot(box):
    source=GAME.parent/'DPS_Data'/'boot.config';root=sandbox_root(box).resolve()
    target=root/'drive'/source.drive[0]/source.relative_to(source.anchor)
    if not target.resolve().is_relative_to(root) or target.resolve()==source.resolve():raise RuntimeError('sandbox_config_path_unsafe')
    original=(target if target.is_file() else source).read_bytes()
    text=original.decode('utf-8-sig');lines=text.splitlines()
    filtered=[line for line in lines if line.split('=',1)[0].strip()!='single-instance']
    if lines==filtered:return
    backup=DATA/'backups'/('sandbox-boot-'+box+'-'+hashlib.sha256(original).hexdigest()[:16]+'.config')
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():backup.write_bytes(original)
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,delete=False) as stream:
        stream.write('\n'.join(filtered)+'\n');temporary=Path(stream.name)
    temporary.replace(target)
