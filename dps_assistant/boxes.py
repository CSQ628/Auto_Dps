"""Explain box eligibility without changing reservations or native game state."""
import math

BOX_REASONS=frozenset(('box_reading','box_empty','box_ready','box_queued','box_paused','box_disabled',
    'inventory_full','inventory_reserved_slots','box_category_disabled','item_drag_active','manual_panel_conflict','native_modal_active','trade_panel_active',
    'native_offline','native_sync_blocked','native_sync_backlog','box_result_unconfirmed',
    'box_retry_wait','native_box_rejected','native_box_waiting','native_request_not_started','box_connection_retry','inventory_relief'))


BOX_WAIT_MESSAGES={
 'inventory_full':'背包已满，等待存仓、合成、回收或扩容',
 'inventory_reserved_slots':'已达到背包空位预留',
 'inventory_relief':'正在自动整理背包，按锻造、合成、分解顺序处理并联动存仓，腾位后继续开箱',
 'box_category_disabled':'待开宝箱的品质分类已关闭',
 'item_drag_active':'正在拖拽物品',
 'manual_panel_conflict':'当前窗口与开箱冲突',
 'native_modal_active':'等待游戏确认窗口关闭',
 'trade_panel_active':'交易窗口正在使用',
 'native_offline':'等待游戏登录与网络恢复',
 'native_sync_blocked':'等待游戏恢复奖励结算',
 'native_sync_backlog':'等待游戏完成同步',
 'box_result_unconfirmed':'正在核对上次开箱回执，随后封存未明结果并接续当前队列',
 'box_retry_wait':'等待重试间隔',
 'native_box_rejected':'游戏暂未接受开箱',
 'native_request_not_started':'上次请求在执行前已取消，等待自动重试',
 'box_connection_retry':'开箱连接暂不可用，等待自动重试',
 'native_box_waiting':'等待原生开箱条件就绪',
}

def box_status(scan,config,state,ranked,now):
    snap=scan.get('snapshot') or {}
    boxes=snap.get('boxes') or {}
    result={k:boxes.get(k) for k in ('total','freeSlots')}
    candidates=[a for a in scan.get('actions',[]) if a['kind']=='box']
    if not config.get('running',True):reason='box_paused'
    elif not config.get('modules',{}).get('box',False):reason='box_disabled'
    elif boxes.get('total') is None:reason='box_reading'
    elif state.get('box_pending'):reason='box_result_unconfirmed'
    elif boxes['total']==0:reason='box_empty'
    elif snap.get('itemInputHolding'):reason='item_drag_active'
    elif snap.get('automationBlocked'):reason='native_modal_active'
    elif snap.get('trading'):reason='trade_panel_active'
    elif 'box' in snap.get('manualBlockedKinds',[]):reason='manual_panel_conflict'
    elif snap.get('sync',{}).get('blocked'):reason='native_sync_blocked'
    elif snap.get('connection',{}).get('online') is False or snap.get('connection',{}).get('loggedIn') is False or snap.get('connection',{}).get('trustBlocked'):reason='native_offline'
    elif snap.get('sync',{}).get('backlogged') or snap.get('sync',{}).get('queue',0)>100:reason='native_sync_backlog'
    elif boxes.get('freeSlots',0)<=0:reason='inventory_full'
    elif boxes.get('relief',{}).get('active') and not boxes['relief'].get('blocked'):reason='inventory_relief'
    elif state.get('box_pending'):reason='box_result_unconfirmed'
    elif boxes.get('openableSlots',1)<=0:reason='inventory_reserved_slots'
    elif len(boxes.get('enabledGrades',[]))==3 and len(boxes.get('counts',[]))==3 and not any(n>0 and enabled for n,enabled in zip(boxes['counts'],boxes['enabledGrades'])):reason='box_category_disabled'
    elif state.get('box_retry_at',0)>now:reason='native_request_not_started' if state.get('features',{}).get('box',{}).get('last_reason')=='native_request_not_started' else 'native_box_rejected'
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
        if receipt.get('stopReason')=='native_box_rejected' or status in ('rejected','waiting'):state['box_retry_at']=now+5
    return {'delta':delta,'opened':opened,'status':status}


def box_process_identity(identity):
    """Retain only exact lifetime and environment; no paths or account in the stamp."""
    if not isinstance(identity, dict):return None
    pid,created,box=(identity.get(k) for k in ('pid','created','box'))
    if (type(pid) is not int or pid<=0 or type(created) not in (int,float)
            or not math.isfinite(created) or created<=0 or not isinstance(box,str)):
        return None
    return {'pid':pid,'created':created,'box':box}


def archive_sealed_box_request(state,receipt,account,now):
    """Release a sealed command, retaining its unknown outcome and prior credit.

    Called only with the response of the authenticated current bridge. A native
    main-thread fence has closed this exact request ID against late execution.
    No elapsed time or queue change alone is accepted and nothing is credited.
    """
    from .box_receipts import valid_receipt
    pending=state.get('box_pending')
    if not pending or not valid_receipt(receipt) or receipt['status']!='unresolved':return None
    if receipt['requestId']!=pending.get('request_id') or receipt['account']!=account:return None
    archived={**pending,'reason':'box_request_sealed','retired_at':now,'fence':receipt['sealed']}
    state['box_unresolved']=(state.get('box_unresolved') or [])[-31:]+[archived]
    state['box_unresolved_count']=state.get('box_unresolved_count',0)+1
    state.pop('box_pending')
    return archived


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
