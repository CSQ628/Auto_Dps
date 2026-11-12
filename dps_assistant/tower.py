"""Give the main stage a complete native battle between tower attempts."""


def _counts(snapshot):
    record = snapshot.get('record', {})
    values = tuple(record.get(k) for k in ('normalClears', 'normalFails'))
    return values if all(type(v) is int and v >= 0 for v in values) else None


def begin_tower_turn(snapshot, state, session, now):
    state['tower_turn'] = {'session': session, 'waiting': True, 'since': now,
                           'main_baseline': None, 'reason': 'tower_in_progress'}


def observe_tower_turn(snapshot, state, session, now):
    turn = state.get('tower_turn')
    if turn and turn.get('session') != session:
        state.pop('tower_turn', None)
        turn = None
    if snapshot.get('stage', {}).get('category') == 1:
        if not turn:
            begin_tower_turn(snapshot, state, session, now)
            turn = state['tower_turn']
        turn.update(main_baseline=None, reason='tower_in_progress')
    elif turn and turn.get('waiting') and snapshot.get('stage', {}).get('category') == 0:
        counts = _counts(snapshot)
        baseline = turn.get('main_baseline')
        if counts is None:
            turn['reason'] = 'native_main_result_unavailable'
        elif baseline is None or any(a < b for a, b in zip(counts, baseline)):
            turn.update(main_baseline=list(counts), reason='main_battle_required')
        elif any(a > b for a, b in zip(counts, baseline)):
            turn.update(waiting=False, reason='main_battle_completed', completed_at=now)
    return {k: turn[k] for k in ('waiting', 'reason', 'since') if k in turn} if turn else None
