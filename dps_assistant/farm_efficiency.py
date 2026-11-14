"""Compare observed free farming stages within one unchanged party/strength context."""
import math

from .parameters import strategy


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _key(stage):
    return str(stage['level']) + ':' + str(stage['difficulty'])


stage_key = _key


def exploration_state(snapshot, state, session):
    # Coverage survives levels, gear upgrades and sample expiry; rates never do.
    identity = str((session, tuple(snapshot.get('squad', []))))
    coverage = state.get('farm_exploration')
    if not coverage or coverage.get('identity') != identity:
        coverage = {'identity': identity, 'visited': {}, 'measured': {}}
        state['farm_exploration'] = coverage
    return coverage


def observe_efficiency(snapshot, state, session, now, config, route, candidates, allow_selection=True, finalize_previous=False):
    from .policy import strength_signature

    options = strategy(config)
    if not options['adaptive_farming']:
        state.pop('farm_efficiency', None)
        return {'enabled': False, 'measurements': []}
    squad = snapshot.get('squad') or []
    characters = [c for c in snapshot.get('characters', []) if c.get('id') in squad]
    native_cap = snapshot.get('catalogue', {}).get('characterMax')
    level_cap = native_cap if type(native_cap) is int and native_cap > 0 else None
    # Only a native, known cap permits excluding a hero. A missing cap keeps
    # the old conservative scope; capped heroes still participate in combat.
    learners = [c for c in characters if level_cap is None
                or type(c.get('level')) is not int or c['level'] != level_cap]
    roster_valid = (len(squad) == len(set(squad)) == len(characters) > 0
                    and {c.get('id') for c in characters} == set(squad))
    all_at_cap = bool(roster_valid and level_cap is not None and not learners)
    identity = str((session, strength_signature(snapshot), level_cap,
                    tuple(sorted(c['id'] for c in learners))))
    cache = state.get('farm_efficiency')
    if not cache or cache.get('identity') != identity or cache.get('schema') != 4:
        cache = {'schema': 4, 'identity': identity, 'since': now, 'stages': {}}
        state['farm_efficiency'] = cache
    coverage = exploration_state(snapshot, state, session)
    keys = {_key(p): p for p in candidates}
    measurements = cache['stages']
    for key in list(measurements):
        if key not in keys or now - measurements[key]['at'] >= options['farm_recheck_seconds']:
            measurements.pop(key)

    stage = snapshot.get('stage', {})
    readiness = snapshot.get('battleReadiness', {})
    current = snapshot.get('combat', {}).get('current') or {}
    key = _key(stage) if 'level' in stage and 'difficulty' in stage else None
    pending = state.get('pending_results', {}).values()
    transitioning = any(p.get('action', {}).get('kind') in ('tower', 'tower_return', 'battle_recover')
                        or p.get('action', {}).get('kind') == 'progress' and p['action'].get('phase') == 'travel'
                        for p in pending)
    eligible = (config.get('running') is True and config.get('modules', {}).get('progress') is True
              and snapshot.get('loaded') is True
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
              and roster_valid and bool(learners)
              and all(_number(c.get('expTotal')) and _number(c.get('level')) for c in characters))
    phase = state.get('growth', {}).get('phase')
    active = eligible and phase in ('farm', 'endgame')
    previous = cache.get('last', {})
    gap_limit = max(15, config.get('interval', 2) * 3)
    # The growth observer may release a frontier retry on this exact settlement.
    # Consume only the tail of an already valid segment in this same strength
    # epoch; never start or extend farming while pushing, or select another map.
    finishing = (eligible and finalize_previous and phase == 'push' and key == _key(route)
                 and previous.get('key') == key and 0 < now - previous.get('at', now) <= gap_limit
                 and (current.get('result') in ('Cleared', 'Failed')
                      or current.get('result') == 'InProgress' and _number(current.get('elapsed'))
                      and current['elapsed'] <= 10))
    if active and key == _key(route):
        # Growth invalidates rates and grants a fresh strength-specific probe below.
        # A separate visit clock bounds repeated grants without mixing those rates.
        visit_marker = str((session, tuple(squad), key, route['since']))
        if route.get('probe_visit_marker') != visit_marker:
            route.update(probe_visit_marker=visit_marker, visit_active_seconds=0)
            route.pop('visit_probe_last', None)
        visit_interval = now - route.get('visit_probe_last', now)
        if 0 < visit_interval <= max(15, config.get('interval', 2) * 3):
            route['visit_active_seconds'] += visit_interval
        route['visit_probe_last'] = now
        # Probe time and reward samples must refer to the same strength epoch.
        marker = str((key, route['since'], cache['identity'], cache['since']))
        if route.get('visit_marker') != marker:
            coverage['visited'][key] = now
            route.update(visit_marker=marker, active_seconds=0)
            route.pop('probe_last', None)
        interval = now - route.get('probe_last', now)
        if 0 < interval <= max(15, config.get('interval', 2) * 3):
            route['active_seconds'] = route.get('active_seconds', 0) + interval
        route['probe_last'] = now
    else:
        route.pop('probe_last', None)
        route.pop('visit_probe_last', None)
    if active or finishing:
        totals = {str(c['id']): c['expTotal'] for c in learners}
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
                                                   'clears': [], 'failures': [], 'gained_by_character': {c: 0 for c in totals},
                                                   'since': previous['at']})
            # Compare each member's cumulative reward; native updates need not arrive in the same scan.
            for character in totals:
                bucket['gained_by_character'][character] += totals[character] - previous['totals'][character]
            bucket['gained'] = min(bucket['gained_by_character'].values())
            bucket['seconds'] += seconds
            bucket['at'] = now
            for outcome in state.get('battle_observation', {}).get('outcomes', []):
                if (outcome.get('category') != 0 or outcome.get('farming') is not True
                        or outcome.get('level') != stage['level'] or outcome.get('difficulty') != stage['difficulty']
                        or outcome.get('started', -1) < max(bucket['since'], cache['since'], previous['segment_since'])
                        or outcome.get('observed', -1) > now):
                    continue
                field = {'Cleared': 'clears', 'Failed': 'failures'}.get(outcome.get('result'))
                sequence = outcome.get('sequence')
                if field and _number(sequence) and sequence not in bucket[field]:
                    bucket[field] = (bucket[field] + [sequence])[-40:]
        if active:
            cache['last'] = {'key': key, 'at': now, 'totals': totals, 'sequence': current['sequence'],
                             'segment_since': previous['segment_since'] if continuous else now}
        else:
            cache.pop('last', None)
    else:
        cache.pop('last', None)

    def ready(value):
        return (value['seconds'] >= options['farm_sample_seconds']
                and (bool(value['clears']) or len(value['failures']) >= options['farm_failure_limit']))

    rows = [{**keys[k], 'observed_seconds': b['seconds'], 'gained': b['gained'],
             'per_minute': b['gained'] * 60 / b['seconds'] if ready(b) else None,
             'clears': len(b['clears']), 'failures': len(b['failures']), 'ready': ready(b)}
            for k, b in measurements.items() if b['seconds'] > 0]
    frontier = snapshot.get('record', {}).get('maxCleared', 0)
    chapter = max(1, math.ceil(frontier / 10)) if _number(frontier) else 1
    candidate_levels = [p['level'] for p in keys.values()]
    result = {'enabled': True, 'sample_seconds': options['farm_sample_seconds'],
              'candidate_count': len(keys), 'tested_count': sum(k in coverage['measured'] for k in keys),
              'visited_count': sum(k in coverage['visited'] for k in keys),
              'measurements': sorted(rows, key=lambda p: p['level'], reverse=True),
              'chapter': chapter,
              'band_min': min(candidate_levels), 'band_max': max(candidate_levels),
              'levelling_characters': [c['id'] for c in learners], 'level_cap': level_cap,
              'all_at_cap': all_at_cap,
              'reason': ('上阵英雄已全部满级，停止按经验轮换地图；装备、刻印和主线流程继续。'
                         if all_at_cap else
                         '仅比较未满级上阵英雄的最低经验收益；等待当前章节免费关卡实测。')}
    if all_at_cap:
        # Do not mark a full-level party as a stalled/failed experience probe.
        cache.pop('last', None)
        for field in ('probe_last', 'visit_probe_last', 'visit_marker', 'probe_visit_marker',
                      'active_seconds', 'visit_active_seconds'):
            route.pop(field, None)
        return result
    excluded = set(route.get('failed_stages', []))
    eligible = [p for p in candidates if _key(p) not in excluded]
    by_key = {_key(p): p for p in rows if p['ready'] and _key(p) not in excluded}
    selected = by_key.get(_key(route))
    result['recent_tested_count'] = len(by_key)
    if (active or finishing) and selected and key == _key(route):
        coverage['measured'][key] = now
        result['tested_count'] = sum(k in coverage['measured'] for k in keys)
    if finishing:
        result['reason'] = '保留练级末场的同战力实测结果，继续主线重试。'
    if not active or not allow_selection or key != _key(route):
        return result
    probe_limit = max(options['farm_sample_seconds'], options['farm_probe_seconds'])
    visit_exhausted = route.get('visit_active_seconds', 0) >= 2 * probe_limit
    # The first battle may have started before our first valid sample. Its
    # native settlement proves progress, but cannot count as a fully observed
    # round. Give the next continuously observed round a chance to finish,
    # within the existing total visit limit. Normal stages have no Boss timer.
    bucket = measurements.get(key, {})
    context = state.get('battle_observation', {}).get('contexts', {}).get(str(current.get('sequence')), {})
    round_waiting = (not selected and not visit_exhausted and bool(bucket)
                     and current.get('result') == 'InProgress' and _number(current.get('elapsed'))
                     and context.get('category') == 0 and context.get('farming') is True
                     and context.get('level') == stage['level'] and context.get('difficulty') == stage['difficulty']
                     and _number(context.get('started'))
                     and context['started'] >= max(bucket['since'], cache['since'], previous.get('segment_since', now))
                     and any(outcome.get('category') == 0 and outcome.get('farming') is True
                             and outcome.get('level') == stage['level'] and outcome.get('difficulty') == stage['difficulty']
                             and outcome.get('result') in ('Cleared', 'Failed')
                             and _number(outcome.get('elapsed')) and outcome['elapsed'] > 0
                             and _number(outcome.get('sequence')) and outcome['sequence'] < current['sequence']
                             and _number(outcome.get('observed'))
                             and max(route['since'], cache['since']) <= outcome['observed'] <= now
                             for outcome in state.get('battle_observation', {}).get('outcomes', [])))
    timed_out = not selected and (visit_exhausted or route.get('active_seconds', 0) >= probe_limit and not round_waiting)
    if round_waiting and route.get('active_seconds', 0) >= probe_limit:
        result['reason'] = '本图已有真实结算，等待当前完整观测的一轮结束；累计试打上限仍有效。'
    if timed_out:
        excluded.add(key)
        route['failed_stages'] = sorted(excluded)
        route.setdefault('failed_at', {})[key] = now
        eligible = [p for p in eligible if _key(p) != key]
        result['reason'] = ('该图累计试打已达上限，成长变化后仍无可比较样本，轮换其他高级免费图。'
                            if visit_exhausted else
                            '该图试打超时仍无可比较样本，轮换其他高级免费图；战力成长或有效期到后可重试。')
    elif not selected:
        return result
    if not eligible:
        result['reason'] = '当前高级候选尚无可靠通关，不回退低级图，保留当前免费场景并等待成长与主线重试。'
        return result
    # A stalled probe may escape mid-battle. Normal comparisons finish the current battle.
    boundary = current.get('result') in ('Cleared', 'Failed') or _number(current.get('elapsed')) and current['elapsed'] <= 10
    if not timed_out and not boundary:
        result['reason'] = '实测已满足，完成当前战斗后再比较练级点。'
        return result
    unknown = sorted((p for p in eligible if _key(p) not in by_key),
                     key=lambda p: (coverage['visited'].get(_key(p), -1), -p['level']))
    best = max(by_key.values(), key=lambda p: (p['per_minute'], p['level']), default=None)
    gain = 1 + options['farm_switch_gain_percent'] / 100
    if timed_out:
        target = unknown[0] if unknown else best or eligible[0]
        reason = result['reason']
    elif route.get('exploit_until', 0) > now:
        return result | {'reason': '暂留近期实测更快的图积累经验，随后继续轮测未验证地图。'}
    elif best and _key(best) != key and best['per_minute'] > selected['per_minute'] * gain:
        target = best
        route['exploit_until'] = now + options['farm_min_seconds']
        reason = '返回近期实测更快的免费图积累经验，之后继续轮测。'
    elif unknown:
        target = unknown[0]
        reason = '完成当前图实测，按轮换顺序试打其他高级免费已通关图。'
    else:
        target = best if best and best['per_minute'] > selected['per_minute'] * gain else route
        reason = '当前候选已完成近期实测，按经验收益与切换阈值选点。'
    result['reason'] = reason
    if _key(target) != _key(route):
        route.update(level=target['level'], difficulty=target['difficulty'], since=now, reason=reason)
    return result
