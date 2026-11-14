"""Keep uncertain paid travel reserved until native arrival or a clear proves its result."""


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
