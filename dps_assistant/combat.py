"""Attribute native battle records only after observing their stage context."""
import math


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def observe_combat(snapshot, state, session, now):
    observation = state.get('battle_observation')
    if not observation or observation.get('session') != session:
        observation = {'session': session, 'contexts': {}, 'outcomes': []}
        state['battle_observation'] = observation
    raw = snapshot.get('combat') or {}
    current, stage = raw.get('current'), snapshot.get('stage', {})
    contexts = observation['contexts']
    if (raw.get('available') and isinstance(current, dict) and _number(current.get('sequence'))
            and _number(current.get('elapsed')) and current.get('result') == 'InProgress'
            and current.get('level') == stage.get('level') and current.get('difficulty') == stage.get('difficulty')
            and stage.get('category') in (0, 1)):
        key = str(current['sequence'])
        previous = contexts.get(key)
        if previous and any(previous.get(field) != value for field, value in
                [('category', stage['category']), ('level', current['level']), ('difficulty', current['difficulty'])]):
            previous['ambiguous'] = True
        contexts.setdefault(key, {'category': stage['category'], 'level': current['level'],
                                 'difficulty': current['difficulty'], 'started': now - max(0, current.get('elapsed', 0))})
    completed = {str(item['sequence']) for item in observation['outcomes']}
    for record in raw.get('records', []) if raw.get('available') else []:
        key = str(record.get('sequence'))
        context = contexts.get(key)
        if not context or context.get('ambiguous') or key in completed or record.get('result') not in ('Cleared', 'Failed'):
            continue
        elapsed = record.get('elapsed')
        if record.get('level') != context['level'] or record.get('difficulty') != context['difficulty'] or not _number(elapsed) or elapsed <= 0:
            continue
        characters = record.get('characters', [])
        if not characters or any(not _number(c.get(field)) for c in characters for field in ('dealt', 'taken', 'blocked', 'healed')):
            continue
        observation['outcomes'].append({**context, 'sequence': record['sequence'], 'result': record['result'],
            'elapsed': elapsed, 'observed': now, 'dps': sum(c['dealt'] for c in characters) / elapsed,
            'taken': sum(c['taken'] for c in characters), 'healed': sum(c['healed'] for c in characters),
            'characters': characters})
        completed.add(key)
    # Native statistics retains ten records; keep a bounded context/history across polls.
    observation['contexts'] = dict(list(contexts.items())[-24:])
    observation['outcomes'] = observation['outcomes'][-20:]
    return {'available': bool(raw.get('available')), 'current': current,
            'recent': observation['outcomes'][-5:], 'last_main': next(
                (item for item in reversed(observation['outcomes']) if item['category'] == 0), None)}
