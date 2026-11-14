"""Settle native per-mail receipts without inferring success from UI changes."""

import math


def mail_pending(state):
    return any(p.get('action', {}).get('kind') == 'mail_claim'
               for p in state.get('pending_results', {}).values())


def settle_mail(pending, snapshot):
    action = pending['action']
    ids = action.get('ids', [])
    if not ids or any(not isinstance(i, str) or not i for i in ids):
        return None
    observation = snapshot.get('mail', {}).get('claims', {})
    if not isinstance(snapshot.get('account'), str) or not snapshot['account']:
        return None
    results = pending.setdefault('mail_results', {})
    for receipt in observation.get('receipts', []):
        at = receipt.get('at')
        if (receipt.get('account') != snapshot.get('account') or
                type(at) not in (int, float) or not math.isfinite(at)):
            continue
        # Same-observer sequence also excludes a prior manual claim in the scan.
        same_observer = observation.get('observer') is not None and observation['observer'] == pending.get('mail_observer')
        if same_observer and receipt.get('sequence', 0) <= pending.get('mail_sequence', 0):
            continue
        # JS timestamps are milliseconds; do not lose a synchronous receipt due
        # to Python's finer timestamp precision. Within one observer use sequence.
        if not same_observer and at * 1000 < math.floor(pending['at'] * 1000):
            continue
        for item in receipt.get('results', []):
            mail_id, status = item.get('id'), item.get('status')
            if mail_id in ids and status in ('CLAIMED', 'ALREADY_CLAIMED'):
                # Keep a genuine grant if a later manual request says already claimed.
                if results.get(mail_id) != 'CLAIMED':
                    results[mail_id] = status
    if not all(i in results for i in ids):
        return None
    granted = sum(results[i] == 'CLAIMED' for i in set(ids))
    return {'status': 'confirmed' if granted else 'no_change',
            'source': 'native_mail_claim_results', 'claimed': granted,
            'alreadyClaimed': len(set(ids)) - granted}
