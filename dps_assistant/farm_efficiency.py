"""Compare observed free farming stages within one unchanged party/strength context."""
import math

from .parameters import strategy


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _key(stage):
    return str(stage['level']) + ':' + str(stage['difficulty'])


def observe_efficiency(snapshot, state, session, now, config, route, candidates, allow_selection=True):
    from .policy import strength_signature

    options = strategy(config)
    if not options['adaptive_farming']:
        state.pop('farm_efficiency', None)
        return {'enabled': False, 'measurements': []}
    identity = str((session, strength_signature(snapshot)))
    cache = state.get('farm_efficiency')
    if not cache or cache.get('identity') != identity:
        cache = {'identity': identity, 'since': now, 'stages': {}}
        state['farm_efficiency'] = cache
    keys = {_key(p): p for p in candidates}
    measurements = cache['stages']
    for key in list(measurements):
        if key not in keys or now - measurements[key]['at'] >= options['farm_recheck_seconds']:
            measurements.pop(key)

    stage = snapshot.get('stage', {})
    readiness = snapshot.get('battleReadiness', {})
    current = snapshot.get('combat', {}).get('current') or {}
    squad = snapshot.get('squad') or []
    characters = [c for c in snapshot.get('characters', []) if c.get('id') in squad]
    key = _key(stage) if 'level' in stage and 'difficulty' in stage else None
    pending = state.get('pending_results', {}).values()
    transitioning = any(p.get('action', {}).get('kind') in ('tower', 'tower_return', 'battle_recover')
                        or p.get('action', {}).get('kind') == 'progress' and p['action'].get('phase') == 'travel'
                        for p in pending)
    active = (config.get('running') is True and config.get('modules', {}).get('progress') is True
              and snapshot.get('loaded') is True and state.get('growth', {}).get('phase') == 'farm'
              and snapshot.get('experienceBlocked') is False and not snapshot.get('automationBlocked') and not transitioning
              and stage.get('category') == 0 and stage.get('repeat') is True and key in keys
              and readiness.get('known') is True and readiness.get('charactersInitialized') is True
              and readiness.get('timeScale', 0) > 0 and readiness.get('syncRunning') is False
              and readiness.get('syncPending') is False and not readiness.get('missing')
              and readiness.get('expected', 0) > 0 and readiness.get('arrangedCount', 0) > 0
              and snapshot.get('connection', {}).get('online') is True
              and snapshot.get('combat', {}).get('available') is True
              and current.get('level') == stage.get('level') and current.get('difficulty') == stage.get('difficulty')
              and current.get('result') in ('InProgress', 'Cleared', 'Failed') and _number(current.get('sequence'))
              and len(squad) == len(set(squad)) == len(characters) > 0
              and all(_number(c.get('expTotal')) and _number(c.get('level')) for c in characters))
    if active:
        totals = {str(c['id']): c['expTotal'] for c in characters}
        previous = cache.get('last', {})
        seconds = now - previous.get('at', now)
        if previous.get('key') == key and (any(totals[c] < previous.get('totals', {}).get(c, 0) for c in totals)
                                          or current['sequence'] < previous.get('sequence', current['sequence'])):
            measurements.pop(key, None)
        continuous = (previous.get('key') == key and 0 < seconds <= max(15, config.get('interval', 2) * 3)
                      and totals.keys() == previous.get('totals', {}).keys()
                      and all(totals[c] >= previous['totals'][c] for c in totals)
                      and current['sequence'] >= previous.get('sequence', current['sequence']))
        if continuous:
            bucket = measurements.setdefault(key, {'seconds': 0, 'gained': 0, 'at': now,
                                                   'clears': [], 'failures': [], 'since': previous['at']})
            # Use the least rewarded party member so dead/lagging heroes remain part of the objective.
            bucket['gained'] += min(totals[c] - previous['totals'][c] for c in totals)
            bucket['seconds'] += seconds
            bucket['at'] = now
            for outcome in state.get('battle_observation', {}).get('outcomes', []):
                if (outcome.get('category') != 0 or outcome.get('farming') is not True
                        or outcome.get('level') != stage['level'] or outcome.get('difficulty') != stage['difficulty']
                        or outcome.get('started', -1) < max(bucket['since'], cache['since'])
                        or outcome.get('observed', -1) > now):
                    continue
                field = {'Cleared': 'clears', 'Failed': 'failures'}.get(outcome.get('result'))
                sequence = outcome.get('sequence')
                if field and _number(sequence) and sequence not in bucket[field]:
                    bucket[field] = (bucket[field] + [sequence])[-40:]
        cache['last'] = {'key': key, 'at': now, 'totals': totals, 'sequence': current['sequence']}
    else:
        cache.pop('last', None)

    def ready(value):
        return value['seconds'] >= options['farm_sample_seconds'] and bool(value['clears'])

    rows = [{**keys[k], 'observed_seconds': b['seconds'], 'gained': b['gained'],
             'per_minute': b['gained'] * 60 / b['seconds'] if ready(b) else None,
             'clears': len(b['clears']), 'failures': len(b['failures']), 'ready': ready(b)}
            for k, b in measurements.items() if b['seconds'] > 0]
    result = {'enabled': True, 'sample_seconds': options['farm_sample_seconds'],
              'measurements': sorted(rows, key=lambda p: p['level'], reverse=True),
              'reason': '等待同一编队战力下的免费重复练级实测。'}
    # Failure recovery excludes this stage for the current route lifetime (until level/frontier changes).
    excluded = set(route.get('failed_stages', []))
    eligible = [p for p in candidates if _key(p) not in excluded]
    by_key = {_key(p): p for p in rows if p['ready'] and _key(p) not in excluded}
    selected = by_key.get(_key(route))
    if not active or not allow_selection or not selected or not eligible:
        return result
    # Finish the observed fight; only queue travel at an ending or the start of its next cycle.
    boundary = current.get('result') in ('Cleared', 'Failed') or _number(current.get('elapsed')) and current['elapsed'] <= 10
    if not boundary:
        result['reason'] = '实测已满足，完成当前战斗后再比较练级点。'
        return result
    unmeasured = next((p for p in eligible if _key(p) not in by_key), None)
    if unmeasured:
        target = unmeasured
        reason = '实测当前免费关卡后，比较下一个免费练级点。'
    else:
        target = max(eligible, key=lambda p: (by_key[_key(p)]['per_minute'], p['level']))
        best = by_key[_key(target)]['per_minute']
        if best <= selected['per_minute'] * (1 + options['farm_switch_gain_percent'] / 100):
            target = route
        reason = '按当前编队战力下的近期实测经验收益选择练级点。'
    result['reason'] = reason
    if _key(target) != _key(route):
        route.update(level=target['level'], difficulty=target['difficulty'], since=now, reason=reason)
    return result
