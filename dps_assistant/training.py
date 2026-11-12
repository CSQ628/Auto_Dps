"""Observed experience and recovery from repeatedly failing a cleared farming stage."""
import math

from .parameters import strategy


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def observe_experience(snapshot, state, session, now, config=None):
    from .policy import strength_signature

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


def observe_farming(snapshot, state, session, now, config=None):
    options = strategy(config)
    candidates = snapshot.get('progression', {}).get('farmCandidates') or []
    candidates = sorted([p for p in candidates if isinstance(p.get('level'), int) and p['level'] > 0
                         and p['level'] <= snapshot.get('record', {}).get('maxCleared', 0)
                         and _number(p.get('difficulty'))], key=lambda p: p['level'], reverse=True)
    route = state.get('farm_route')
    if not candidates:
        # In the tower there is no main-stage list. Keep the route for the return,
        # but never rank another farming action without a freshly verified candidate.
        return None
    identity = str((session, snapshot.get('record', {}).get('maxCleared'), snapshot.get('squad'),
                    sorted((c['id'], c.get('level')) for c in snapshot.get('characters', [])),
                    options['farm_level_offset'], options['farm_candidate_count']))
    if not route or route.get('identity') != identity:
        route = {'identity': identity, **candidates[0], 'since': now, 'baseline': candidates[0]['level'],
                 'reason': '从免费已通关关卡开始练级。'}
        state['farm_route'] = route
    target = next((p for p in candidates if (p['level'], p['difficulty']) == (route['level'], route['difficulty'])), None)
    if target is None:
        lower = next((p for p in candidates if p['level'] < route['level']), None)
        if lower is None:
            return None
        route.update(**lower, since=now, reason='当前目标不可用，接续更低的免费关卡。')
    failures = {r['sequence'] for r in state.get('battle_observation', {}).get('outcomes', [])
                if _number(r.get('sequence')) and r.get('category') == 0 and r.get('farming') is True
                and r.get('result') == 'Failed' and r.get('level') == route['level']
                and r.get('difficulty') == route['difficulty'] and r.get('observed', 0) >= route['since']}
    lower = next((p for p in candidates if p['level'] < route['level']), None)
    if len(failures) >= options['farm_failure_limit'] and state.get('growth', {}).get('phase') == 'farm':
        if lower:
            old = route['level']
            route.update(**lower, since=now, reason=f'第 {old} 关练级反复失败，已自动下调；等级或主线提升后重新评估。')
            failures = set()
        else:
            route['reason'] = '已到备用范围内最低免费关卡，继续成长并等待主线重试。'
    return {**{k: route[k] for k in ('level', 'difficulty', 'baseline', 'reason')},
            'failures': len(failures), 'failure_limit': options['farm_failure_limit']}
