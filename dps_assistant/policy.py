import time
from .parameters import strategy
from .transitions import entry_conflicts

MODULES={
 'box':('自动宝箱','优先清理宝箱，联动背包扩容和换装'),
 'equipment':('三角色智能换装','按角色逐槽计算原生整套评分，联合背包与仓库分配装备'),
 'active':('主动技能','学习与升级，自动填充可用技能槽'),
 'passive':('被动成长','按当前等级和前置分配技能点'),
 'rune':('符文规划','扩容、编队、经验与收益优先，接续战斗加成'),
 'unlock':('角色解锁','满足原生条件后解锁并补齐编队'),
 'pet_unlock':('宠物培养','解锁并装备可用宠物'),
 'progress':('主线与练级','成长后自动挑战Boss，仅按原生关卡要求使用已确认入场券'),
 'combine':('方块合成','原生配方合成闲置材料，释放背包并接续换装'),
 'decompose':('淘汰装备回收','先保留三个角色的升级装备与合成材料，再联动背包和仓库回收淘汰装备'),
 'storage':('仓库调度','自动存仓，按装备、配方和镶嵌需求取用仓库物品'),
 'forge':('装备锻造','读取原生锻造配方，联合仓库筹备非交易材料'),
 'refine':('装备镶嵌','为非交易装备填充可用镶嵌槽，自动筹备材料'),
 'mail':('邮件与离线收益','处理邮件附件与已结算的离线收益面板'),
 'tower':('无限塔挑战','条件满足后挑战塔层，仅使用非交易入场道具'),
 'ui_cleanup':('无人值守接续','默认保留手动面板，可设置无人值守收起，交易面板保持等待'),
}

def module_for(kind):return {'formation':'unlock','pet_equip':'pet_unlock','skill_equip':'active','skill_refund':'active','skill_unequip':'active','deposit':'storage','withdraw':'storage','mail_open':'mail','mail_claim':'mail','mail_close':'mail','offline_close':'mail','tower_return':'progress','battle_recover':'ui_cleanup'}.get(kind,kind)

def affordable(action,snapshot,config):
    cost=action.get('cost')
    if not cost:return True
    amount=cost.get('amount');goods=cost.get('goods')
    if not isinstance(amount,(int,float)) or not 0<=amount<float('inf'):return False
    if goods==201:return amount<=max(0,snapshot['currencies']['soul']-config['soul_reserve'])
    if goods==202 and action['kind']=='rune' and action.get('permanent') and config.get('permanent_runes',True):
        return amount<=max(0,snapshot['currencies'].get('premium',0)-config.get('premium_reserve',2))
    return False

def strength_signature(snapshot):
    return str((snapshot.get('record',{}).get('maxCleared'),snapshot.get('runes',{}).get('learned'),
        snapshot.get('pets',{}).get('equipped'),tuple(snapshot.get('squad',[])),
        tuple((c['id'],c.get('level'),tuple((e.get('slot'),e.get('uid'),e.get('sockets')) for e in c.get('equipment',[])),
               tuple((p.get('skill'),p.get('level')) for p in c.get('skills',[])),tuple(c.get('activeLoadout',[]))) for c in snapshot.get('characters',[]))))

def observe_growth(snapshot,state,now,config=None):
    options=strategy(config)
    record=snapshot.get('record',{});frontier=record.get('maxCleared',0);deaths=record.get('deaths',0)
    strength=strength_signature(snapshot)
    growth=state.setdefault('growth',{'phase':'push','frontier':frontier,'since':now,'deaths':deaths})
    if frontier>growth['frontier'] or deaths<growth['deaths']:
        growth.update(phase='push',frontier=frontier,since=now,deaths=deaths)
    if snapshot.get('stage',{}).get('category',0)==0:
        failures=sum(item.get('category')==0 and item.get('result')=='Failed' and item.get('level',0)>frontier and item.get('observed',0)>=growth['since'] for item in state.get('battle_observation',{}).get('outcomes',[]))
        native_available=snapshot.get('combat',{}).get('available') is True
        failed_push=failures>=options['push_failure_limit'] or (not native_available and deaths-growth['deaths']>=options['fallback_death_limit'])
        if growth['phase']=='push' and now-growth['since']>=options['push_wait_seconds'] and failed_push:
            growth.update(phase='farm',since=now,deaths=deaths,strength=strength)
        elif growth['phase']=='farm' and now-growth['since']>=options['farm_min_seconds'] and (growth.get('strength')!=strength or now-growth['since']>=options['farm_retry_seconds']):
            growth.update(phase='push',since=now,deaths=deaths)
    return {key:growth[key] for key in ('phase','frontier','since','deaths')}|{'reason':'重复失败，先积累等级与战力' if growth['phase']=='farm' else '成长完成后接续主线',
            'gate':snapshot.get('progression',{}).get('gate')}

def equipment_ready(action,state,now,config=None):
    options=strategy(config)
    # Scores include temporary battle effects. Hold an occupied slot briefly and
    # avoid returning to recently discarded UIDs; native scoring still validates every swap.
    previous=action.get('previousUid')
    if not previous:return True
    hold=state.get('equipment_holds',{}).get(str(action['id'])+':'+str(action['slot']),{})
    if hold.get('uid')!=previous:return True
    retired_at=hold.get('retired_at',{}).get(action['uid'])
    expires=retired_at+options['equipment_return_seconds'] if retired_at is not None else hold.get('retired',{}).get(action['uid'],0)
    return now-hold.get('at',0)>=options['equipment_hold_seconds'] and expires<=now


def ranked_actions(scan,config,state,now=None):
    now=time.time() if now is None else now
    options=strategy(config)
    if not config['running'] or not scan['snapshot']['loaded']:return []
    if scan['snapshot'].get('automationBlocked'):return []
    if scan['snapshot'].get('sync',{}).get('blocked'):return []
    backlogged=scan['snapshot'].get('sync',{}).get('queue',0)>100
    offline=scan['snapshot'].get('connection',{}).get('online') is False
    available=[]
    for a in scan['actions']:
        # Free recovery must remain available while reward mutations wait for native sync.
        # The bridge recomputes the no-ticket prerequisite before it accepts this flag.
        if (backlogged or offline) and not (a.get('freeEntry') is True and
                (a['kind'] in ('tower_return','battle_recover') or a['kind']=='progress' and a.get('mode') in ('guard','farm'))):continue
        if not config['modules'].get(module_for(a['kind']),False) and not(a['kind']=='progress' and a.get('mode')=='guard'):continue
        readiness=scan['snapshot'].get('battleReadiness',{})
        if readiness.get('known') and (not readiness.get('charactersInitialized') or readiness.get('expected',0)==0 or readiness.get('missing')) and (a['kind']=='tower' or a['kind']=='progress' and a.get('mode') not in ('guard',)):continue
        transitioning=any(p.get('action',{}).get('kind') in ('tower','tower_return','battle_recover') or p.get('action',{}).get('kind')=='progress' and p['action'].get('phase')=='travel' for p in state.get('pending_results',{}).values())
        if transitioning and (a['kind'] in ('tower','tower_return','battle_recover','formation') or a['kind']=='progress'):continue
        if a['kind']=='battle_recover':
            recovery=state.get('battle_recovery',{})
            wait=options['stage_stall_wait_seconds'] if recovery.get('reason')=='stalled_end' else options['battle_recovery_wait_seconds']
            if not recovery.get('eligible') or now-recovery.get('since',now)<wait or now-recovery.get('last_attempt',0)<options['battle_recovery_retry_seconds']:continue
            if a.get('mode')!=('sync' if recovery.get('attempts',0)==0 and recovery.get('reason')!='stalled_end' else 'stage'):continue
        if state.get('cooldowns',{}).get(a['key'],0)>now:continue
        if a['key'] in state.get('uncertain',{}):continue
        if entry_conflicts(a,state):continue
        if a['kind']=='equipment' and not equipment_ready(a,state,now,config):continue
        if state.get('kind_cooldowns',{}).get(a['kind'],0)>now:continue
        if a['kind']=='equipment' and not a.get('empty') and a.get('gain',0)*100<options['equipment_min_gain_percent']:continue
        if a['kind']=='progress':
            phase=state.get('growth',{}).get('phase','push')
            if a.get('mode')=='farm' and phase!='farm':continue
            route=state.get('farm_route')
            if a.get('mode')=='farm' and route is not None and (a.get('level'),a.get('difficulty'))!=(route.get('level'),route.get('difficulty')):continue
            if a.get('mode') in ('push','boss') and phase=='farm':continue
        if a['kind']=='tower' and state.get('growth',{}).get('phase')=='farm' and now-state['growth'].get('since',now)<options['tower_farm_wait_seconds']:continue
        if a['kind']=='tower':
            if state.get('tower_turn',{}).get('waiting'):continue
            previous=state.get('tower_attempt',{})
            record=scan['snapshot'].get('record',{})
            changed=previous.get('strength') is not None and previous['strength']!=strength_signature(scan['snapshot'])
            if previous and previous.get('strength') is None:
                changed=any(f.get('last_status')=='confirmed' and f.get('last_at',0)>previous.get('at',0)
                            for kind,f in state.get('features',{}).items() if kind in ('equipment','rune','active','passive','pet_equip'))
            if previous.get('level')==a['level'] and record.get('maxStage',0)<=previous.get('max_stage',0) and not changed and options['tower_require_growth']:continue
            if previous and now-previous.get('at',0)<options['tower_retry_seconds']:continue
        if not affordable(a,scan['snapshot'],config):continue
        a=dict(a)
        # A bounded, native-approved tower attempt must get a turn between boss/farm cycles.
        if a['kind']=='tower':a['priority']=max(a['priority'],109)
        available.append(a)
    # Resolve equal priority in favor of a proven gear upgrade before opening more boxes.
    # Rotate within equipment only; old timestamps must never demote all heroes below boxes.
    def rank(a):
        last=state.get('last_module',{}).get(module_for(a['kind']),state.get('scheduling_started',now))
        aging=min(24,max(0,now-last)/15) if a['priority']<110 else 0
        return (a['priority']>=110,a['priority']+aging,a['kind']=='equipment',
                -state.get('last_equipment',{}).get(str(a.get('id')),0) if a['kind']=='equipment' else 0,a.get('gain',0),-a.get('cost',{}).get('amount',0))
    return sorted(available,key=rank,reverse=True)

def choose(scan,config,state,now=None):
    actions=ranked_actions(scan,config,state,now)
    return actions[0] if actions else None
