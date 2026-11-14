"""Settle paid travel only from native arrival, clears or later cancellation evidence."""

import math


def stage_target(action):
    return (1 if action['kind'] == 'tower' else action.get('category', 0),
            action.get('level'), action.get('difficulty', 0))


def stage_transition(action):
    return action.get('kind') in ('tower', 'tower_return', 'battle_recover') or (
        action.get('kind') == 'progress' and action.get('phase') == 'travel')


def paid_entry(action):
    travel = action['kind'] in ('tower', 'tower_return') or (
        action['kind'] == 'progress' and action.get('phase') == 'travel')
    return travel and (action.get('ticket', 0) > 0 or action.get('freeEntry') is False)


def entry_conflicts(action, state):
    return paid_entry(action) and any(stage_target(item['action']) == stage_target(action)
        for item in state.get('entry_uncertainty', {}).values())


def stage_arrived(action, snapshot):
    stage = snapshot.get('stage', {})
    category, level, difficulty = stage_target(action)
    if not (stage.get('category') == category and stage.get('level') == level
            and stage.get('difficulty', 0) == difficulty and stage.get('running') is True
            and stage.get('alivePlayers', 0) > 0):
        return False
    if (action.get('kind') == 'progress' and action.get('phase') == 'travel'
            and action.get('mode') in ('push', 'boss') and stage.get('repeat') is not False):
        return False
    readiness = snapshot.get('battleReadiness')
    return readiness is None or (readiness.get('known') is True
        and readiness.get('charactersInitialized') is True and not readiness.get('missing')
        and readiness.get('syncRunning') is False and readiness.get('syncPending') is False)


def entry_cleared(action, snapshot, cleared_before):
    category, level, _ = stage_target(action)
    record = snapshot.get('record', {})
    return (isinstance(level, int) and level > 0 and isinstance(cleared_before, int)
        and cleared_before < level and record.get(
        'towerMaxCleared' if category == 1 else 'maxCleared', -1) >= level)


def observe_entry_supersession(entry, snapshot, session, now, timeout):
    """A later native free entry invalidates older asynchronous entry work.

    The bridge queue expires after ten seconds. After its observation deadline,
    anchor a stable native free battle, then require another native entry in the
    same script and game lifetime. Never infer success or a ticket balance.
    """
    at = entry.get('at')
    if (not session or not isinstance(at, (int, float)) or not math.isfinite(at)
            or now - at < max(120, timeout) or snapshot.get('loaded') is not True
            or not paid_entry(entry['action'])):
        return None
    if any(k in snapshot.get('planningUnavailable', {}) for k in ('characters', 'progression')):
        return None
    observed = snapshot.get('entryState', {})
    readiness = snapshot.get('battleReadiness', {})
    stage = snapshot.get('stage', {})
    combat = snapshot.get('combat', {})
    current = combat.get('current') or {}
    sequence = observed.get('sequence')
    expected = readiness.get('expected')
    if (observed.get('known') is not True or observed.get('occupied') is not False
            or observed.get('free') is not True or not observed.get('observer')
            or type(sequence) is not int or sequence < 0
            or readiness.get('enterSequence') != sequence
            or readiness.get('known') is not True or readiness.get('charactersInitialized') is not True
            or type(expected) is not int or expected <= 0 or readiness.get('arrangedCount') != expected
            or readiness.get('squadArranged') is not True or readiness.get('missing') != []
            or readiness.get('syncRunning') is not False or readiness.get('syncPending') is not False
            or readiness.get('ending') is not False
            or type(stage.get('category')) is not int or stage['category'] not in (0, 1)
            or type(stage.get('level')) is not int or stage['level'] <= 0
            or type(stage.get('difficulty')) is not int or stage['difficulty'] < 0
            or stage.get('running') is not True or stage.get('alivePlayers', 0) <= 0
            or combat.get('available') is not True or current.get('result') != 'InProgress'
            or current.get('level') != stage.get('level')
            or current.get('difficulty') != stage.get('difficulty')
            or stage_target(entry['action']) == (stage.get('category'), stage.get('level'), stage.get('difficulty'))):
        return None
    anchor = entry.get('supersession_anchor', {})
    if (anchor.get('session') != session or anchor.get('observer') != observed['observer']
            or type(anchor.get('sequence')) is not int or sequence < anchor['sequence']
            or not isinstance(anchor.get('at'), (int, float)) or not math.isfinite(anchor['at'])):
        entry['supersession_anchor'] = {'session': session, 'observer': observed['observer'],
                                       'sequence': sequence, 'at': now}
        return None
    if sequence <= anchor['sequence'] or now <= anchor['at']:
        return None
    return {'status': 'no_change', 'reason': 'native_entry_superseded',
            'sequenceBefore': anchor['sequence'], 'sequenceAfter': sequence,
            'observed_stage': {k: stage[k] for k in ('category', 'level', 'difficulty')}}
