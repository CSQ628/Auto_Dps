"""Wait for stable native evidence before trying to recover a missing battle party."""


def observe_battle_readiness(snapshot, state, session, now):
    readiness = snapshot.get('battleReadiness') or {}
    stage = snapshot.get('stage') or {}
    ready = (readiness.get('known') is True and readiness.get('charactersInitialized') is True
             and readiness.get('expected', 0) > 0 and readiness.get('syncRunning') is False
             and readiness.get('syncPending') is False and stage.get('category') == 0 and readiness.get('timeScale') != 0)
    missing = ready and readiness.get('missing') and readiness.get('arrangedCount') == 0 and stage.get('alivePlayers') == 0
    stalled = (ready and not readiness.get('missing') and readiness.get('arrangedCount', 0) > 0
               and stage.get('running') is False and stage.get('wave', 0) > 0 and stage.get('aliveMonsters') == 0
               and readiness.get('pendingSpawn') is False)
    reason = 'missing_party' if missing else 'stalled_end' if stalled else None
    eligible = reason is not None
    if not eligible:
        previous = state.get('battle_recovery', {})
        if previous.get('session') != session or stage.get('alivePlayers', 0) > 0 or readiness.get('expected') == 0:
            state.pop('battle_recovery', None)
        elif previous:
            previous.update(eligible=False, since=now)
        return {'eligible': False}
    context = str((session, tuple(snapshot.get('squad', [])), stage.get('category'), stage.get('level'),
                   stage.get('difficulty'), readiness.get('enterSequence'), reason, stage.get('wave'),
                   snapshot.get('record', {}).get('clears'), snapshot.get('record', {}).get('kills')))
    current = state.get('battle_recovery', {})
    if current.get('session') != session:
        current = {}
    if current.get('context') != context:
        # Keep the previous attempt's backoff if native recovery has only started loading.
        current = {'context': context, 'session': session, 'since': now, 'attempts': current.get('attempts', 0),
                   'last_attempt': current.get('last_attempt', 0)}
        state['battle_recovery'] = current
    current.update(eligible=True, reason=reason)
    return {'eligible': True, 'reason': reason, 'empty_seconds': max(0, now-current['since']),
            'attempts': current['attempts'], 'missing': readiness['missing']}
