"""Observed experience and recovery from repeatedly failing a cleared farming stage."""
import math

from .parameters import strategy, high_farm_minimum
from .farm_efficiency import observe_efficiency, exploration_state


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def observe_experience(snapshot, state, session, now, config=None):
    from .policy import strength_signature, planning_strength_available

    if not planning_strength_available(snapshot):
        state.pop('experience_observation', None)
        return {'available': False, 'reason': 'native_planning_unavailable', 'characters': []}
    stage = snapshot.get('stage', {})
    current = snapshot.get('combat', {}).get('current') or {}
    squad = [n for n in snapshot.get('squad', []) if isinstance(n, int) and n > 0]
    characters = [c for c in snapshot.get('characters', []) if c.get('id') in squad]
    valid = (stage.get('running') is True and stage.get('category') in (0, 1)
             and snapshot.get('combat', {}).get('available') is True
             and current.get('result') == 'InProgress' and _number(current.get('sequence'))
             and current.get('level') == stage.get('level') and current.get('difficulty') == stage.get('difficulty')
             and len(squad) == len(set(squad)) == len(characters) > 0
             and {c['id'] for c in characters} == set(squad)
             and all(_number(c.get(f)) for c in characters for f in ('exp', 'expTotal', 'expNext', 'level')))
    if not valid:
        state.pop('experience_observation', None)
        return {'available': False, 'reason': 'waiting_for_native_experience', 'characters': []}
    totals = {str(c['id']): c['expTotal'] for c in characters}
    context = str((session, stage['category'], stage['level'], stage['difficulty'], current['sequence'],
                   stage.get('repeat'), strength_signature(snapshot)))
    previous = state.get('experience_observation', {})
    interval = now - previous.get('at', now)
    gap_limit = max(15, (config or {}).get('interval', 2) * 3)
    continuous = (previous.get('context') == context and 0 < interval <= gap_limit
                  and totals.keys() == previous.get('totals', {}).keys()
                  and all(totals[k] >= previous['totals'][k] for k in totals))
    if continuous:
        seconds = previous['seconds'] + interval
        gained = {k: previous['gained'][k] + totals[k] - previous['totals'][k] for k in totals}
    else:
        seconds, gained = 0, {k: 0 for k in totals}
    state['experience_observation'] = {'context': context, 'at': now, 'totals': totals, 'seconds': seconds, 'gained': gained}
    return {'available': True, 'observed_seconds': seconds, 'characters': [
        {'id': c['id'], 'level': c['level'], 'exp': c['exp'], 'exp_next': c['expNext'],
         'gained': gained[str(c['id'])], 'per_minute': gained[str(c['id'])] * 60 / seconds if seconds >= 10 else None}
        for c in characters]}


def observe_farming(snapshot, state, session, now, config=None, finish_previous=False):
    from .policy import planning_strength_available

    if not planning_strength_available(snapshot):
        state.get('farm_efficiency', {}).pop('last', None)
        route = state.get('farm_route', {})
        route.pop('probe_last', None)
        route.pop('visit_probe_last', None)
        return None
    options = strategy(config)
    candidates = snapshot.get('progression', {}).get('farmCandidates') or []
    candidates = sorted([p for p in candidates if isinstance(p.get('level'), int) and p['level'] > 0
                         and p['level'] <= snapshot.get('record', {}).get('maxCleared', 0)
                         and _number(p.get('difficulty'))], key=lambda p: p['level'], reverse=True)
    minimum = high_farm_minimum(snapshot, options)
    candidates = [p for p in candidates if p['level'] >= minimum]
    coverage = exploration_state(snapshot, state, session)
    route = state.get('farm_route')
    if not candidates:
        # In the tower there is no main-stage list. Keep the route for the return,
        # but never rank another farming action without a freshly verified candidate.
        state.get('farm_efficiency', {}).pop('last', None)
        if route:
            route.pop('probe_last', None)
            route.pop('visit_probe_last', None)
        return None
    from .policy import arranged_characters
    identity = str((session, snapshot.get('record', {}).get('maxCleared'), snapshot.get('squad'),
                    [(c['id'], c.get('level')) for c in arranged_characters(snapshot)],
                    options['farm_level_offset'], options['farm_candidate_count']))
    if not route or route.get('identity') != identity:
        initial = candidates[0]
        route = {'identity': identity, **initial, 'since': now, 'baseline': initial['level'],
                 'reason': '优先最高免费已通关图，只在当前高级范围内比较经验效率。'}
        state['farm_route'] = route
    target = next((p for p in candidates if (p['level'], p['difficulty']) == (route['level'], route['difficulty'])), None)
    if target is None:
        lower = next((p for p in candidates if p['level'] < route['level']), None)
        route.update(**(lower or candidates[0]), since=now, reason='当前目标不可用，接续已核实的免费关卡。')
    from .policy import strength_signature
    strength = strength_signature(snapshot)
    if route.get('failure_strength') != strength:
        route.update(failure_strength=strength, failed_stages=[], failed_at={})
    for key, at in list(route.get('failed_at', {}).items()):
        if now - at >= options['farm_recheck_seconds']:
            route['failed_at'].pop(key)
            route['failed_stages'] = [k for k in route['failed_stages'] if k != key]
    failures = {r['sequence'] for r in state.get('battle_observation', {}).get('outcomes', [])
                if _number(r.get('sequence')) and r.get('category') == 0 and r.get('farming') is True
                and r.get('result') == 'Failed' and r.get('level') == route['level']
                and r.get('difficulty') == route['difficulty'] and r.get('observed', 0) >= route['since']}
    previous_target = (route['level'], route['difficulty'])
    # A pending frontier retry owns the next battle boundary; do not travel to another farm first.
    retry_pending = state.get('growth', {}).get('phase') == 'farm' and 'retry_requested_at' in state.get('growth', {})
    efficiency = observe_efficiency(snapshot, state, session, now, config or {}, route, candidates,
                                    allow_selection=not retry_pending,
                                    finalize_previous=finish_previous and state.get('growth', {}).get('phase') == 'push')
    if (previous_target == (route['level'], route['difficulty']) and failures
            and len(failures) >= options['farm_failure_limit'] and state.get('growth', {}).get('phase') in ('farm', 'endgame')):
        route['reason'] = (f'第 {route["level"]} 关已有 {len(failures)} 次失败结算；继续按原生经验采样，'
                           '不因失败次数盲目降图。')
    return {**{k: route[k] for k in ('level', 'difficulty', 'baseline', 'reason')},
            'failures': len(failures), 'failure_limit': options['farm_failure_limit'], 'efficiency': efficiency}
