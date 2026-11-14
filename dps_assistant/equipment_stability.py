"""Remember confirmed party loadouts while permanent growth stays unchanged."""
import hashlib
import json
import re


HISTORY_LIMIT = 512


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _history(state, epoch, current):
    history = state.get('equipment_stability', {})
    return history if history.get('epoch') == epoch and history.get('current') == current else {}


def prepare(action, snapshot, state, growth_signature):
    """Return a copy with execution context, or a reason to wait. Old bridges remain compatible."""
    context, revision = snapshot.get('equipmentContext'), action.get('itemRevision')
    if context is None or revision is None:
        return dict(action), None
    try:
        before = json.loads(context)
        item = json.loads(revision)
        if not isinstance(before, list) or not isinstance(item, list) or len(item) != 3:
            raise ValueError('invalid equipment revision')
        if item[0] != action['uid'] or type(item[1]) is not int or not isinstance(item[2], list):
            raise ValueError('candidate revision changed')
        seen = set()
        for row in before:
            if (not isinstance(row, list) or len(row) != 3 or type(row[0]) is not int
                    or type(row[1]) is not int or row[1] < 0 or not isinstance(row[2], str)
                    or (row[0], row[1]) in seen):
                raise ValueError('invalid party equipment context')
            seen.add((row[0], row[1]))
        target = (action['id'], action['slot'])
        previous = next((row for row in before if tuple(row[:2]) == target), None)
        if (json.loads(previous[2])[0] if previous else None) != action.get('previousUid'):
            raise ValueError('equipped revision changed')
        after = [row for row in before if tuple(row[:2]) != target] + [[*target, revision]]
        epoch = digest([growth_signature, snapshot.get('record', {}).get('maxStage')])
        meta = {'schema': 1, 'epoch': epoch, 'before': digest(sorted(before)),
                'after': digest(sorted(after)), 'context': context}
    except (ValueError, TypeError, KeyError, IndexError):
        return None, 'equipment_context_unavailable'
    history = _history(state, epoch, meta['before'])
    if meta['after'] in history.get('visited', []):
        return None, 'equipment_cycle'
    if len(history.get('visited', [])) >= HISTORY_LIMIT:
        return None, 'equipment_history_full'
    return {**action, 'equipmentStability': meta}, None


def record_confirmed(state, action):
    """Only called after native confirmation, including later pending settlement."""
    meta = action.get('equipmentStability', {})
    if (meta.get('schema') != 1 or any(not isinstance(meta.get(k), str)
            or re.fullmatch('[0-9a-f]{64}', meta[k]) is None for k in ('epoch', 'before', 'after'))):
        return
    # A repeated observation of the same confirmation must not erase earlier history.
    if _history(state, meta['epoch'], meta['after']):
        return
    history = _history(state, meta['epoch'], meta['before'])
    visited = list(dict.fromkeys(history.get('visited', []) or [meta['before']]))
    if meta['after'] not in visited:
        visited.append(meta['after'])
    state['equipment_stability'] = {'epoch': meta['epoch'], 'current': meta['after'],
                                    'visited': visited[:HISTORY_LIMIT]}


def describe(scan, state, growth_signature):
    """Expose a waiting reason on both independently serialized planning summaries."""
    blocked = {}
    for action in scan['actions']:
        if action['kind'] != 'equipment':
            continue
        _, reason = prepare(action, scan['snapshot'], state, growth_signature)
        if reason:
            blocked[(action['id'], action['slot'])] = reason
    snapshot = scan['snapshot']
    summaries = list(snapshot.get('equipmentPlanning', []))
    summaries += [c['equipmentPlanning'] for c in snapshot.get('characters', []) if c.get('equipmentPlanning')]
    for detail in {id(detail): detail for detail in summaries}.values():
        waiting = [s for s in detail.get('slotDetails', []) if (detail['id'], s['slot']) in blocked]
        for slot in waiting:
            slot['status'] = 'stability_wait'
        detail['stabilityWaiting'] = len(waiting)
        if waiting:
            detail['planned'] = max(0, detail.get('planned', 0) - len(waiting))
            if not detail['planned']:
                detail['status'] = 'stability_wait'
    return {'waiting': len(blocked), 'history_size': len(state.get('equipment_stability', {}).get('visited', [])),
            'history_limit': HISTORY_LIMIT, 'reasons': sorted(set(blocked.values()))}
