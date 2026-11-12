import json
import os
import threading
from pathlib import Path

from .platform_paths import RESOURCE_ROOT
ROOT=RESOURCE_ROOT
DATA=Path(os.environ.get('DPS_ASSISTANT_DATA',str(Path(os.environ['LOCALAPPDATA'])/'DPSAssistant')))
DATA.mkdir(parents=True,exist_ok=True)
_write_lock=threading.RLock()

def atomic_json(path,value):
    with _write_lock:
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix(path.suffix+'.tmp')
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,path)

def load_json(path,default):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return default

def event(value):
    with _write_lock:
        with (DATA/'actions.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n')

def recent_events(limit=200):
    try:
        with (DATA/'actions.jsonl').open('rb') as f:
            f.seek(0,2);size=f.tell();f.seek(max(0,size-2*1024*1024))
            lines=f.read().splitlines()
        result=[]
        for line in lines:
            try:result.append(json.loads(line))
            except (ValueError,UnicodeError):continue
        return result[-limit:]
    except OSError:return []
