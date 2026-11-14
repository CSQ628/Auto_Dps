"""Observed milestones and feature evidence; never infer a completed playthrough."""

import math


FEATURES = {
    'box': ('宝箱', ('box',)),
    'equipment': ('换装', ('equipment',)),
    'active': ('主动技能', ('active', 'skill_equip')),
    'passive': ('被动技能', ('passive',)),
    'rune': ('符文', ('rune',)),
    'unlock': ('角色与编队', ('unlock', 'formation')),
    'pet_unlock': ('宠物', ('pet_unlock', 'pet_equip')),
    'progress': ('主线与练级', ('progress',)),
    'combine': ('合成', ('combine',)),
    'decompose': ('分解', ('decompose',)),
    'storage': ('仓库', ('deposit', 'withdraw')),
    'forge': ('锻造', ('forge',)),
    'refine': ('装备精炼', ('refine',)),
    'mail': ('邮件与离线收益', ('mail_claim', 'offline_close')),
    'tower': ('无限塔', ('tower', 'tower_return')),
}


def milestones(snapshot, features=None, config=None):
    features = features or {}
    catalog = snapshot.get('catalogue', {})
    record = snapshot.get('record', {})
    characters = snapshot.get('characters', [])
    rows = []

    def add(key, label, current, target, detail=''):
        known = all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (current, target)) and target > 0
        rows.append({'id': key, 'label': label, 'current': current, 'target': target,
                     'met': bool(known and current >= target), 'known': known, 'detail': detail})

    add('main', '主线通关', record.get('maxCleared'), catalog.get('normalMax'))
    add('tower', '无限塔通关', record.get('towerMaxCleared'), catalog.get('towerMax'))
    owned_levels = [c.get('level') for c in characters]
    lowest = min(owned_levels) if owned_levels and all(type(n) in (int,float) and math.isfinite(n) and n >= 0 for n in owned_levels) else None
    add('level', '已拥有角色等级', lowest,
        catalog.get('characterMax'), '按已拥有角色的最低等级计算')
    add('rune', '符文投资', snapshot.get('runes', {}).get('learned'), snapshot.get('runes', {}).get('total'))
    pets=snapshot.get('pets',{})
    add('pets', '可培养宠物', pets.get('eligibleUnlocked',pets.get('unlocked')), pets.get('eligibleTotal',pets.get('total')),
        '按原生所有权计算，未拥有DLC '+str(pets.get('excludedDlc',0))+' 只')
    if 'roster' in snapshot:
        roster=snapshot['roster']
        add('roster','可用角色解锁',roster.get('eligibleUnlocked'),roster.get('eligibleTotal'),
            '按原生所有权计算，未拥有DLC '+str(roster.get('excludedDlc',0))+' 名')
    plans = [c for c in snapshot.get('equipmentPlanning', []) if c.get('status') != 'not_arranged']
    add('gear', '上阵角色装备槽', sum(c['equipped'] for c in plans) if plans else None,
        sum(c['slots'] for c in plans) if plans else None, '只统计当前上阵英雄；填满槽位后仍持续比较原生收益')

    # Keep the full native goals intact. Policy restrictions explain the separate
    # automation scope; they must never turn an unfinished native goal into "met".
    modules = (config or {}).get('modules', {})
    module_for = {'main':'progress','tower':'tower','level':'progress','rune':'rune',
                  'pets':'pet_unlock','roster':'unlock','gear':'equipment'}
    automated = []
    for row in rows:
        scope = {k: row[k] for k in ('id','label','current','target','known','met','detail')}
        scope['enabled'] = modules.get(module_for[row['id']], True) is True
        if row['id'] == 'level':
            squad = snapshot.get('squad', [])
            active_ids = [n for n in squad if type(n) is int and n > 0][:3]
            active = [c for c in characters if c.get('id') in active_ids]
            levels = [c.get('level') for c in active]
            scope.update(label='上阵角色等级',current=min(levels) if levels and all(type(n) in (int,float) for n in levels) else None,
                         detail='保留玩家阵容；后备未满级仅展示，不自动轮换')
            if (len(set(active_ids)) != len(active_ids) or len(active) != len(active_ids)
                    or {c.get('id') for c in active} != set(active_ids)):scope['current']=None
        elif row['id'] == 'rune':
            runes = snapshot.get('runes', {})
            scope.update(label='全部刻印投资',current=runes.get('learned'),target=runes.get('total'),
                         detail='在线优先，离线收益最低优先级；全部节点遵守原生前置与当前预算')
            if runes.get('progressKnown') is not True:scope.update(current=None,target=None)
        scope['known'] = (all(type(v) in (int,float) and math.isfinite(v) and v >= 0 for v in (scope['current'],scope['target']))
                          and scope['target'] > 0)
        scope['met'] = bool(scope['known'] and scope['current'] >= scope['target'])
        if not scope['enabled']:scope['detail']='模块已关闭，保留原生目标；不自动计为达标'
        automated.append(scope)

    missing = [label for _, (label, kinds) in FEATURES.items()
               if not any(features.get(kind, {}).get('confirmed', 0) > 0 for kind in kinds)]
    return {'items': rows, 'met': sum(r['met'] for r in rows), 'total': len(rows),
            'all_milestones_met': all(r['met'] for r in rows), 'unverified_systems': missing,
            'automation_items': automated,
            'note': '里程碑与原生确认分开记录；达到数值目标后仍需完整毕业验收'}
