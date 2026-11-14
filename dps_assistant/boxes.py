"""Explain box eligibility without changing reservations or native game state."""
import math

BOX_REASONS=frozenset(('box_reading','box_empty','box_ready','box_queued','box_paused','box_disabled',
    'inventory_full','item_drag_active','manual_panel_conflict','native_modal_active','trade_panel_active',
    'native_offline','native_sync_blocked','native_sync_backlog','box_result_unconfirmed',
    'box_retry_wait','native_box_rejected','native_box_waiting'))


def box_status(scan,config,state,ranked,now):
    snap=scan.get('snapshot') or {}
    boxes=snap.get('boxes') or {}
    result={k:boxes.get(k) for k in ('total','freeSlots')}
    candidates=[a for a in scan.get('actions',[]) if a['kind']=='box']
    if not config.get('running',True):reason='box_paused'
    elif not config.get('modules',{}).get('box',False):reason='box_disabled'
    elif boxes.get('total') is None:reason='box_reading'
    elif boxes['total']==0:reason='box_empty'
    elif snap.get('itemInputHolding'):reason='item_drag_active'
    elif snap.get('automationBlocked'):reason='native_modal_active'
    elif snap.get('trading'):reason='trade_panel_active'
    elif 'box' in snap.get('manualBlockedKinds',[]):reason='manual_panel_conflict'
    elif snap.get('sync',{}).get('blocked'):reason='native_sync_blocked'
    elif snap.get('connection',{}).get('online') is False or snap.get('connection',{}).get('loggedIn') is False or snap.get('connection',{}).get('trustBlocked'):reason='native_offline'
    elif snap.get('sync',{}).get('backlogged') or snap.get('sync',{}).get('queue',0)>100:reason='native_sync_backlog'
    elif boxes.get('freeSlots',0)<=0:reason='inventory_full'
    elif state.get('box_pending'):reason='box_result_unconfirmed'
    elif state.get('box_retry_at',0)>now:reason='native_box_rejected'
    elif any(a['kind']=='box' for a in ranked):reason='box_ready' if ranked[0]['kind']=='box' else 'box_queued'
    elif candidates and all(a['key'] in state.get('uncertain',{}) for a in candidates):reason='box_result_unconfirmed'
    elif candidates and (state.get('kind_cooldowns',{}).get('box',0)>now or all(
            a['key'] in state.get('uncertain',{}) or state.get('cooldowns',{}).get(a['key'],0)>now for a in candidates)):
        reason='native_box_rejected' if state.get('features',{}).get('box',{}).get('last_status')=='rejected' else 'box_retry_wait'
    else:reason='native_box_waiting'
    return {**result,'reason':reason}


def settle_legacy_boxes(state,record):
    """Only a native record change releases an old single-open reservation."""
    for key in list(state.get('uncertain',{})):
        if not key.startswith('box:'):continue
        try:before=int(key.rsplit(':',1)[1])
        except (ValueError,IndexError):continue
        if isinstance(record,int) and record>before:state['uncertain'].pop(key)


def apply_box_receipt(state,receipt,now):
    """Credit actual boxes once, independently of finished batch operation counts."""
    pending=state.get('box_pending')
    if not pending or not receipt or receipt.get('requestId')!=pending['request_id']:return None
    opened=receipt.get('openedCount');status=receipt.get('status')
    if type(opened) is not int or not 0<=opened<=8 or status not in ('confirmed','pending','rejected','waiting'):return None
    credited=pending.get('credited',0)
    if opened<credited:return None
    delta=opened-credited;pending['credited']=opened
    feature=state.setdefault('features',{}).setdefault('box',{'confirmed':0})
    feature.update(opened=feature.get('opened',0)+delta,last_status=status,last_at=now,last_reason=receipt.get('reason'))
    if status!='pending':
        state.pop('box_pending',None)
        if opened:
            state['confirmed']=state.get('confirmed',0)+1
            feature['confirmed']=feature.get('confirmed',0)+1
        if receipt.get('stopReason')=='native_box_rejected' or status=='rejected':state['box_retry_at']=now+5
    return {'delta':delta,'opened':opened,'status':status}


def box_process_identity(identity):
    """Retain only exact lifetime and environment; no paths or account in the stamp."""
    if not isinstance(identity, dict):return None
    pid,created,box=(identity.get(k) for k in ('pid','created','box'))
    if (type(pid) is not int or pid<=0 or type(created) not in (int,float)
            or not math.isfinite(created) or created<=0 or not isinstance(box,str)):
        return None
    return {'pid':pid,'created':created,'box':box}


def retire_ended_box_batch(state,current,now,lifetime_status):
    """Retire an unknowable old execution, never credit it or replay its request.

    A new game's own native queue may be drained independently once the exact old
    process is proven gone. A helper reconnect in the same game cannot do this.
    """
    pending=state.get('box_pending')
    if not isinstance(pending,dict):return None
    origin=box_process_identity(pending.get('process'));current=box_process_identity(current)
    if not origin or not current or origin['box']!=current['box']:return None
    if origin['pid']==current['pid'] and abs(origin['created']-current['created'])<=.001:return None
    if lifetime_status(origin)!='absent':return None
    archived={**pending,'reason':'origin_process_ended','retired_at':now}
    state['box_unresolved']=(state.get('box_unresolved') or [])[-31:]+[archived]
    state['box_unresolved_count']=state.get('box_unresolved_count',0)+1
    state.pop('box_pending')
    return archived
