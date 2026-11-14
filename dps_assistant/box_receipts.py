"""Private transport receipts scoped to an exact game process lifetime.

Only results actually returned by the native bridge are checkpointed. Missing
receipts remain unknown; elapsed time and unrelated record growth do not create
a receipt. No game inventory or save file is edited here.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

from .storage import DATA,atomic_json


def valid_receipt(value):
    if not isinstance(value,dict):return False
    if not all(isinstance(value.get(k),str) and 0<len(value[k])<=limit
               for k,limit in (('account',256),('requestId',120))):return False
    opened=value.get('openedCount');status=value.get('status')
    if type(opened) is not int or not 0<=opened<=8 or status not in ('confirmed','pending','waiting','rejected'):return False
    if status in ('waiting','rejected') and opened:return False
    if status=='confirmed' and not opened:return False
    for key in ('recordBefore','recordAfter'):
        n=value.get(key)
        if n is not None and (type(n) is not int or n<0):return False
    if status=='pending' and (type(value.get('pendingRecord')) is not int or value['pendingRecord']<0):return False
    observations=value.get('observations',[])
    return isinstance(observations,list) and len(observations)<=8


class BoxReceiptStore:
    def __init__(self,pid,created,directory=None):
        if type(pid) is not int or pid<=0 or type(created) not in (int,float) or not math.isfinite(created) or created<=0:
            raise ValueError('invalid_box_receipt_process_identity')
        self.identity={'pid':pid,'created':created};self.receipts={};self.failed=False
        digest=hashlib.sha256(json.dumps([pid,created],separators=(',',':')).encode()).hexdigest()
        self.path=Path(directory if directory is not None else DATA/'box-receipts')/(digest+'.json')
        if not self.path.exists():return
        try:
            if self.path.stat().st_size>512*1024:raise ValueError('box_receipt_store_limit')
            saved=json.loads(self.path.read_text(encoding='utf-8'))
            rows=saved['receipts']
            if (saved.get('schema')!=1 or saved.get('process')!=self.identity or not isinstance(rows,list)
                    or len(rows)>256 or any(not valid_receipt(r) for r in rows)
                    or len({r['requestId'] for r in rows})!=len(rows)):
                raise ValueError('box_receipt_store_invalid')
            self.receipts={r['requestId']:r for r in rows}
        except (OSError,ValueError,KeyError,TypeError):
            # Preserve the original file; it cannot authorize recovery or replay.
            self.failed=True

    def restore(self):return copy.deepcopy(list(self.receipts.values()))

    def checkpoint(self,receipt):
        if not valid_receipt(receipt):return False
        key=receipt['requestId'];previous=self.receipts.get(key)
        if previous and (previous['account']!=receipt['account'] or previous['openedCount']>receipt['openedCount']
                or previous['status']!='pending' and receipt['status']=='pending'):
            return False
        if previous==receipt and not self.failed:return True
        updated=copy.deepcopy(self.receipts);updated[key]=copy.deepcopy(receipt)
        while len(updated)>32:
            oldest=next((k for k,v in updated.items() if k!=key and v['status']!='pending'),None)
            if oldest is None:break
            updated.pop(oldest)
        try:
            if len(updated)>256:raise ValueError('box_receipt_store_limit')
            atomic_json(self.path,{'schema':1,'process':self.identity,'receipts':list(updated.values())})
        except (OSError,ValueError):self.failed=True;return False
        self.receipts=updated;self.failed=False;return True
