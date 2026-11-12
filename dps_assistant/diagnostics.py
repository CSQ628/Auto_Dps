"""Explicit diagnostic fields suitable for a player to share with a bug report."""
from .platform_paths import VERSION
from .policy import MODULES

STATUSES = frozenset(('confirmed','submitted','pending','no_change','stale','rejected','error','waiting'))
KINDS = frozenset(MODULES) | {'deposit','withdraw','skill_refund','skill_equip','skill_unequip','pet_equip','formation','mail_open','mail_claim','mail_close','offline_close','tower_return','battle_recover'}
REASONS = frozenset('user_item_operation user_popup_open view_not_ready cube_in_use native_cube_busy native_tier_not_ready native_material_not_reserved autofill_contains_protected_material native_recipe_not_ready native_preparation_failed native_cleanup_incomplete protected_or_missing_material tower_repeat_not_disabled inventory_full storage_full storage_source_changed storage_swap_changed protected_or_missing_item'.split())

def safe_reason(value):
    return value if value in REASONS else 'other_native_condition' if value else None

def feature_status(value):
    return {'confirmed': value.get('confirmed',0),
            'last_status': value.get('last_status') if value.get('last_status') in STATUSES else None,
            'last_reason': safe_reason(value.get('last_reason')), 'last_at':value.get('last_at')}



def diagnostics(state):
    instances = []
    for row in state.get('instances', []):
        snap = row.get('snapshot') or {}
        instances.append({'instance': len(instances) + 1, 'sandboxed': bool(row.get('box')),
            'status': row.get('status'), 'observation_error': bool(row.get('error')),
            'bridge_health': {k:v for k,v in (row.get('bridge_health') or {}).items()
                if k in ('phase','step','ageSeconds')},
            'bridge_performance': {k:v for k,v in (row.get('bridge_performance') or {}).items()
                if k in ('scanMs','lastScanMs','nativeCalls','cacheHits') and isinstance(v,(int,float))},
            'effective_scan_interval': row.get('effective_scan_interval'),
            'loaded': snap.get('loaded'), 'stage': snap.get('stage'),
            'snapshot_age_seconds': max(0,state.get('now',0)-snap['at']/1000) if isinstance(snap.get('at'),(int,float)) else None,
            'battle_result': {k: (snap.get('combat',{}).get('current') or {}).get(k)
                for k in ('sequence','level','difficulty','result','elapsed')},
            'pending_transitions': [{k:p.get(k) for k in ('kind','mode','level','difficulty','since')}
                for p in row.get('pending_transitions',[])],
            'characters': [{k: c.get(k) for k in ('id', 'level', 'points')} for c in snap.get('characters', [])],
            'squad': snap.get('squad'), 'battle_readiness': snap.get('battleReadiness'),
            'battle_recovery': row.get('battle_recovery'), 'record': snap.get('record'),
            'connection': snap.get('connection'), 'sync': snap.get('sync'),
            'bridge_source_hash': snap.get('bridgeSourceHash'),
            'inventory': {k:snap.get('inventory',{}).get(k) for k in ('count','capacity')},
            'storage': {k:snap.get('storage',{}).get(k) for k in ('count','capacity','safeItems','tradable')},
            'inventory_flow': {k:snap.get('inventoryFlow',{}).get(k) for k in ('movable','consumable','protectedMaterials','blockedTransfers','reservedEquipment','storageFull','staging','swapping','blocked')},
            'combining': {k:snap.get('combining',{}).get(k) for k in ('groups','ready','warehousePending','needSpace','warehouseMaterials')},
            'recycling': {k:snap.get('recycling',{}).get(k) for k in ('reservedEquipment','obsolete','inventory','storage','planned','pressureCleanup')},
            'feature_confirmations': {k: v.get('confirmed', 0) for k, v in row.get('feature_evidence', {}).items() if k in KINDS},
            'feature_status': {k: feature_status(v) for k,v in row.get('feature_evidence',{}).items() if k in KINDS},
            'recent_operations': [{'at':e.get('at'),'kind':e['action']['kind'],
                'status':e.get('status') if e.get('status') in STATUSES else None,
                'reason':safe_reason((e.get('result') or {}).get('reason')),
                'step':(e.get('result') or {}).get('step') if (e.get('result') or {}).get('step') in ('native_ready','configure','reserve','execute') else None}
                for e in state.get('events',[]) if e.get('instance')==row.get('id') and e.get('action',{}).get('kind') in KINDS][-12:]})
    config = state.get('config', {})
    return {'version': VERSION, 'captured_at': state.get('now'), 'running': config.get('running'),
            'modules': config.get('modules'), 'parameters': config.get('strategy'), 'instances': instances,
            'note': '诊断仅含运行状态、角色编号和策略参数；不含账号、昵称、存档、文件路径或控制令牌。'}
