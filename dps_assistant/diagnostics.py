"""Explicit diagnostic fields suitable for a player to share with a bug report."""
from .platform_paths import VERSION
from .policy import MODULES
from .boxes import BOX_REASONS
from .pause import PAUSE_REASONS
import math

STATUSES = frozenset(('confirmed','submitted','pending','no_change','stale','rejected','error','waiting','warning'))
KINDS = frozenset(MODULES) | {'deposit','withdraw','sort','passive_refund','skill_refund','skill_equip','skill_unequip','pet_equip','formation','mail_open','mail_claim','mail_close','offline_close','tower_return','battle_recover','maintenance_exit'}
REASONS = frozenset('forge_result_unconfirmed box_receipt_store_unavailable connection_recovered automatic_pause_recovered tradable_state_changed user_item_operation user_popup_open view_not_ready cube_in_use native_cube_busy native_tier_not_ready native_material_not_reserved autofill_contains_protected_material native_recipe_not_ready native_preparation_failed native_cleanup_incomplete protected_or_missing_material tower_repeat_not_disabled inventory_full storage_full storage_source_changed storage_swap_changed protected_or_missing_item sort_conservation_failed offline_rune_disabled'.split())
REASONS |= {'native_refund_blocked','skill_refund_unconfirmed','skills_reallocating','skill_learn_unconfirmed','skill_catalogue_invalid','skill_build_changed','skill_level_changed'}
REASONS |= {'frontier_battle_in_progress','refine_target_changed','refine_socket_unavailable','refine_result_unconfirmed','material_quantity_changed','protected_refine_material','native_attachment_not_ready','equipment_not_accepted'}
REASONS |= BOX_REASONS | {'sort_protected_stack','box_queue_changed'}
REASONS |= frozenset(('native_mail_observer_unavailable','native_mail_busy','native_mail_list_changed','native_mail_already_claimed'))
REASONS |= {'workshop_receipt_store_unavailable','workshop_receipt_lookup_unavailable','workshop_receipt_capacity','workshop_result_unconfirmed'}
REASONS |= {'combine_result_unconfirmed','decompose_result_unconfirmed'}
REASONS |= {'native_entry_superseded','box_conditions_recovered','box_connection_recovered','manual_global_pause','manual_global_resume','manual_instance_pause'}
REASONS |= {'event_log_unavailable','event_log_recovered','instance_worker_failed','instance_worker_recovered'}
REASONS |= {'legacy_storage_replanned','storage_request_id_required','storage_result_unconfirmed'}
REASONS |= {'box_request_sealed','legacy_box_request_blocked','inventory_relief'}

def safe_reason(value):
    return value if value in REASONS else 'other_native_condition' if value else None

def feature_status(value):
    return {'confirmed': value.get('confirmed',0),
            'opened':value.get('opened'),
            'last_status': value.get('last_status') if value.get('last_status') in STATUSES else None,
            'last_reason': safe_reason(value.get('last_reason')), 'last_at':value.get('last_at')}



def pause_status(value):
    if not isinstance(value,dict) or value.get('reason') not in PAUSE_REASONS:return None
    result={'reason':value['reason']}
    if value.get('scope') in ('all','instance'):result['scope']=value['scope']
    if type(value.get('at')) in (int,float) and math.isfinite(value['at']):result['at']=value['at']
    if type(value.get('changed_count')) is int and value['changed_count']>0:result['changed_count']=value['changed_count']
    if value.get('action_kind') in KINDS:result['action_kind']=value['action_kind']
    return result


def diagnostics(state):
    instances = []
    for row in state.get('instances', []):
        snap = row.get('snapshot') or {}
        instances.append({'instance': len(instances) + 1, 'sandboxed': bool(row.get('box')),
            'status': row.get('status'), 'observation_error': bool(row.get('error')),
            'pause':pause_status(row.get('pause')),
            'bridge_health': {k:v for k,v in (row.get('bridge_health') or {}).items()
                if k in ('phase','step','ageSeconds')},
            'bridge_performance': {k:v for k,v in (row.get('bridge_performance') or {}).items()
                if k in ('scanMs','lastScanMs','nativeCalls','cacheHits') and isinstance(v,(int,float))},
            'effective_scan_interval': row.get('effective_scan_interval'),
            'box_retry':{k:v for k,v in row.get('box_retry',{}).items() if k in ('attempts','delay','next_at') and type(v) in (int,float) and math.isfinite(v)},
            'worker_retry':{k:v for k,v in row.get('worker_retry',{}).items() if k in ('attempts','delay','next_at') and type(v) in (int,float) and math.isfinite(v)},
            'box_performance':{k:v for k,v in row.get('box_performance',{}).items() if k in ('scanMs','interval') and isinstance(v,(int,float))},
            'maintenance': {k:v for k,v in (row.get('maintenance') or {}).items() if k in ('active','since','attempts','retry_at')},
            'unavailable_planning_sections': sorted(set(snap.get('planningUnavailable') or {}) &
                {'characters','boxes','workshop','sorting','runes','pets','achievements','equipment','mail','tower','auxiliary','progression','recovery'}),
            'loaded': snap.get('loaded'), 'stage': snap.get('stage'),
            'growth': {**{k:row.get('growth',{}).get(k) for k in ('frontier','since','retry_pending','frontier_return_pending','entry_result_pending')},
                'phase':row.get('growth',{}).get('phase') if row.get('growth',{}).get('phase') in ('push','farm','endgame') else None,
                'retry_trigger':row.get('growth',{}).get('retry_trigger') if row.get('growth',{}).get('retry_trigger') in ('party_growth','retry_interval') else None},
            'snapshot_age_seconds': max(0,state.get('now',0)-snap['at']/1000) if isinstance(snap.get('at'),(int,float)) else None,
            'battle_result': {k: (snap.get('combat',{}).get('current') or {}).get(k)
                for k in ('sequence','level','difficulty','result','elapsed')},
            'pending_transitions': [{k:p.get(k) for k in ('kind','mode','level','difficulty','since')}
                for p in row.get('pending_transitions',[])],
            'characters': [{k: c.get(k) for k in ('id', 'level', 'points')} for c in snap.get('characters', [])],
            'squad': snap.get('squad'), 'battle_readiness': snap.get('battleReadiness'),
            'battle_recovery': row.get('battle_recovery'), 'record': snap.get('record'),
            'connection': snap.get('connection'), 'sync': snap.get('sync'),
            'workshop_pending': [{k:p.get(k) for k in ('kind','since')} for p in row.get('workshop_pending',[])
                if p.get('kind') in ('combine','forge','refine','decompose')],
            'storage_pending': [{k:p.get(k) for k in ('kind','since')} for p in row.get('storage_pending',[])
                if p.get('kind') in ('deposit','withdraw')],
            'workshop_receipt_persistence':row.get('workshop_receipt_persistence') if row.get('workshop_receipt_persistence') in ('available','unavailable') else None,
            'mail_settlement': {k:v for k,v in row.get('mail_settlement',{}).items() if k in ('pending','remaining','since')},
            'mail_observer': {k:v for k,v in snap.get('mail',{}).get('claims',{}).items() if k in ('available','readError')},
            'bridge_source_hash': snap.get('bridgeSourceHash') or row.get('bridge_source_hash'),
            'inventory': {k:snap.get('inventory',{}).get(k) for k in ('count','capacity')},
            'boxes': {k:snap.get('boxes',{}).get(k) for k in ('counts','total','freeSlots')},
            'box_status': {**{k:row.get('box_status',{}).get(k) for k in ('total','freeSlots')},
                'reason':safe_reason(row.get('box_status',{}).get('reason'))},
            'item_input_holding':snap.get('itemInputHolding'), 'cube_busy':snap.get('cubeBusy'),
            'manual_panel_open':snap.get('manualPanelOpen'), 'box_panel_blocked':'box' in snap.get('manualBlockedKinds',[]),
            'modal_blocked':bool(snap.get('automationBlocked')),
            'storage': {k:snap.get('storage',{}).get(k) for k in ('count','capacity','safeItems','tradable','pressure')},
            'storage_tabs': [{k:t.get(k) for k in ('id','open','count','capacity')} for t in snap.get('storage',{}).get('tabs',[])],
            'inventory_flow': {k:snap.get('inventoryFlow',{}).get(k) for k in ('movable','consumable','protectedMaterials','blockedTransfers','reservedEquipment','storageFull','staging','swapping','blocked','waitingConditions','recipeReserved')},
            'combining': {k:snap.get('combining',{}).get(k) for k in ('groups','ready','warehousePending','needSpace','warehouseMaterials','waitingGroups','status')},
            'refinement_material_synthesis': {k:snap.get('combining',{}).get('refinementMaterials',{}).get(k) for k in ('status','available','inventory','warehouse','storageEnabled','protected','reservedForSynthesis','reservedForEquipment','groups','ready','warehousePending','lockedRecipes')},
            'recycling': {k:snap.get('recycling',{}).get(k) for k in ('reservedEquipment','obsolete','inventory','storage','planned','pressureCleanup','nativeCapacity','batchLimit','socketedAllowed','locked','socketedRetained','highGradeRetained','retireTier')},
            'forging': {k:snap.get('forging',{}).get(k) for k in ('status','cubeLevel','tier','recipe','part','priority','ready','minLevel','maxLevel','source','sourceKnown','retainedParts','alternatives')},
            'refining': {k:snap.get('refining',{}).get(k) for k in ('status','targets','planned','ready','warehousePending','reservedMaterials','availableMaterials','protectedMaterials')},
            'rune_planning': snap.get('runes',{}).get('planning'),
            'skill_planning': [{k:c.get(k) for k in ('id','points','skillPlanning')} for c in snap.get('characters',[])],
            'forge_materials': [{k:m.get(k) for k in ('id','required','available','inventory','protected','source','firstStage','firstFreeStage','fusionSteps')} for m in snap.get('forging',{}).get('materials',[])],
            'fusion_waiting': [{k:m.get(k) for k in ('category','minTier','maxTier','grade','available','required')} for m in snap.get('combining',{}).get('nearest',[])],
            'feature_confirmations': {k: v.get('confirmed', 0) for k, v in row.get('feature_evidence', {}).items() if k in KINDS},
            'feature_status': {k: feature_status(v) for k,v in row.get('feature_evidence',{}).items() if k in KINDS},
            'recent_operations': [{'at':e.get('at'),'kind':e['action']['kind'],
                'status':e.get('status') if e.get('status') in STATUSES else None,
                'reason':safe_reason((e.get('result') or {}).get('reason')),
                'step':(e.get('result') or {}).get('step') if (e.get('result') or {}).get('step') in ('native_ready','configure','reserve','execute') else None}
                for e in state.get('events',[]) if e.get('instance')==row.get('id') and e.get('action',{}).get('kind') in KINDS][-12:]})
    config = state.get('config', {})
    journal=state.get('event_log') or {}
    safe_journal={k:journal[k] for k in ('buffered','dropped','attempts','retry_in_seconds')
                  if type(journal.get(k)) is int and journal[k]>=0}
    safe_journal['status']=journal.get('status') if journal.get('status') in ('available','draining','retrying') else None
    return {'version': VERSION, 'captured_at': state.get('now'), 'running': config.get('running'),'event_log':safe_journal,
            'modules': config.get('modules'), 'parameters': config.get('strategy'), 'instances': instances,
            'note': '诊断仅含运行状态、角色编号和策略参数；不含账号、昵称、存档、文件路径或控制令牌。'}
