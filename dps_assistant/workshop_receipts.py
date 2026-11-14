"""Native workshop replies, scoped to an exact game lifetime and request.

Only returned replies are recovered. Missing or pending replies never authorize
replay, and neither inventory deltas nor elapsed time fabricate completion.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import threading

from .storage import DATA, atomic_json

KINDS = frozenset(('combine', 'forge', 'refine', 'decompose', 'deposit', 'withdraw'))
TERMINAL = frozenset(('confirmed', 'rejected', 'waiting', 'stale', 'no_change'))


def valid_receipt(value):
    if not isinstance(value, dict) or value.get('kind') not in KINDS:
        return False
    if not all(isinstance(value.get(k), str) and 0 < len(value[k]) <= limit
               for k, limit in (('requestId', 120), ('account', 256), ('key', 2048))):
        return False
    if not re.fullmatch(r'[A-Za-z0-9:_-]+', value['requestId']):
        return False
    if not isinstance(value.get('signature'), str) or not re.fullmatch(r'[0-9a-f]{64}', value['signature']):
        return False
    if type(value.get('at')) not in (int, float) or not math.isfinite(value['at']) or value['at'] <= 0:
        return False
    result = value.get('result')
    if not isinstance(result, dict) or result.get('status') not in TERMINAL | {'pending'}:
        return False
    try:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')) <= 256 * 1024
    except (TypeError, ValueError, RecursionError):
        return False


class WorkshopReceiptStore:
    def __init__(self, pid, created, directory=None):
        if (type(pid) is not int or pid <= 0 or type(created) not in (int, float)
                or not math.isfinite(created) or created <= 0):
            raise ValueError('invalid_workshop_receipt_process_identity')
        self.identity = {'pid': pid, 'created': created}
        self.lock = threading.RLock()
        self.receipts, self.failed = {}, False
        digest = hashlib.sha256(json.dumps([pid, created], separators=(',', ':')).encode()).hexdigest()
        self.path = Path(directory if directory is not None else DATA / 'workshop-receipts') / (digest + '.json')
        if not self.path.exists():
            return
        try:
            if self.path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError('workshop_receipt_store_limit')
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            rows = saved['receipts']
            if (saved.get('schema') != 1 or saved.get('process') != self.identity
                    or not isinstance(rows, list) or len(rows) > 256
                    or any(not valid_receipt(r) for r in rows)
                    or len({r['requestId'] for r in rows}) != len(rows)):
                raise ValueError('workshop_receipt_store_invalid')
            self.receipts = {r['requestId']: r for r in rows}
        except (OSError, ValueError, KeyError, TypeError):
            self.failed = True

    def restore(self):
        with self.lock:
            return copy.deepcopy(list(self.receipts.values()))

    def checkpoint(self, receipt):
        if not valid_receipt(receipt):
            return False
        with self.lock:
            key = receipt['requestId']
            previous = self.receipts.get(key)
            if previous:
                if any(previous[k] != receipt[k] for k in ('account', 'kind', 'key', 'signature', 'at')):
                    return False
                if previous['result']['status'] in TERMINAL and previous != receipt:
                    return False
                if previous == receipt and not self.failed:
                    return True
            updated = copy.deepcopy(self.receipts)
            updated[key] = copy.deepcopy(receipt)
            while len(updated) > 32:
                oldest = next((k for k, r in updated.items()
                               if k != key and r['result']['status'] in TERMINAL), None)
                if oldest is None:
                    break
                updated.pop(oldest)
            try:
                saved = {'schema': 1, 'process': self.identity, 'receipts': list(updated.values())}
                if len(updated) > 256 or len(json.dumps(saved, ensure_ascii=False).encode('utf-8')) > 4 * 1024 * 1024:
                    raise ValueError('workshop_receipt_store_limit')
                atomic_json(self.path, saved)
            except (OSError, ValueError):
                self.failed = True
                return False
            self.receipts, self.failed = updated, False
            return True
