"""Observed milestones and feature evidence; never infer a completed playthrough."""


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
    'refine': ('镶嵌', ('refine',)),
    'mail': ('邮件与离线收益', ('mail_claim', 'offline_close')),
    'tower': ('无限塔', ('tower', 'tower_return')),
}


def milestones(snapshot, features=None):
    features = features or {}
    catalog = snapshot.get('catalogue', {})
    record = snapshot.get('record', {})
    characters = snapshot.get('characters', [])
    rows = []

    def add(key, label, current, target, detail=''):
        known = isinstance(current, (int, float)) and isinstance(target, (int, float)) and target > 0
        rows.append({'id': key, 'label': label, 'current': current, 'target': target,
                     'met': bool(known and current >= target), 'known': known, 'detail': detail})

    add('main', '主线通关', record.get('maxCleared'), catalog.get('normalMax'))
    add('tower', '无限塔通关', record.get('towerMaxCleared'), catalog.get('towerMax'))
    add('level', '已拥有角色等级', min((c['level'] for c in characters), default=None),
        catalog.get('characterMax'), '按已拥有角色的最低等级计算')
    add('rune', '符文投资', snapshot.get('runes', {}).get('learned'), snapshot.get('runes', {}).get('total'))
    pets=snapshot.get('pets',{})
    add('pets', '可培养宠物', pets.get('eligibleUnlocked',pets.get('unlocked')), pets.get('eligibleTotal',pets.get('total')),
        '按原生所有权计算，未拥有DLC '+str(pets.get('excludedDlc',0))+' 只')
    if 'roster' in snapshot:
        roster=snapshot['roster']
        add('roster','可用角色解锁',roster.get('eligibleUnlocked'),roster.get('eligibleTotal'),
            '按原生所有权计算，未拥有DLC '+str(roster.get('excludedDlc',0))+' 名')
    plans = snapshot.get('equipmentPlanning', [])
    add('gear', '角色装备槽', sum(c['equipped'] for c in plans) if plans else None,
        sum(c['slots'] for c in plans) if plans else None, '填满槽位仅是里程碑，仍持续比较原生收益')

    missing = [label for _, (label, kinds) in FEATURES.items()
               if not any(features.get(kind, {}).get('confirmed', 0) > 0 for kind in kinds)]
    return {'items': rows, 'met': sum(r['met'] for r in rows), 'total': len(rows),
            'all_milestones_met': all(r['met'] for r in rows), 'unverified_systems': missing,
            'note': '里程碑与原生确认分开记录；达到数值目标后仍需完整毕业验收'}
