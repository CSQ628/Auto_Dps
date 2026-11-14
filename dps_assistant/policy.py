import json
import math
import time
from .parameters import strategy, high_farm_minimum
from .tuning import CATEGORIES, operation_allowed
from .transitions import entry_conflicts, stage_transition
from .mail import mail_pending
from .equipment_stability import prepare as prepare_equipment, describe as describe_equipment
from .workshop_receipts import KINDS as NATIVE_RECEIPT_KINDS

WORKSHOP_CONSUMPTION = frozenset(('combine', 'forge', 'refine', 'decompose'))

MODULES={
 'box':('自动宝箱','优先清理宝箱，联动背包扩容和换装'),
 'equipment':('上阵英雄智能换装','仅为当前上阵的三个英雄逐槽评分，联合背包与仓库分配装备'),
 'active':('主动技能','学习与升级，自动填充可用技能槽'),
 'passive':('被动成长','按当前等级和前置分配技能点'),
 'rune':('符文规划','扩容、编队、经验与收益优先，接续战斗加成'),
 'unlock':('角色解锁','满足原生条件后解锁并补齐编队'),
 'pet_unlock':('宠物培养','解锁永久小队加成，自动模式保留玩家跟随选择'),
 'progress':('主线与练级','成长后自动挑战Boss，仅按原生关卡要求使用已确认入场券'),
 'combine':('方块合成（含精炼材料）','按原生配方合成装备、饰品、精炼材料与制作材料，完整材料批次优先于镶嵌'),
 'decompose':('淘汰装备回收','先保留上阵英雄升级装备与配方材料，再联动背包和仓库回收淘汰装备'),
 'storage':('仓库调度','自动存仓，按装备、配方和镶嵌需求取用仓库物品'),
 'forge':('装备锻造','优先制作成长装备，缺料时接续合成和回收，联合仓库筹备材料'),
 'refine':('装备精炼（镶嵌）','装饰、宝石和纹章先保留完整合成批次，再用余量填装备空插槽；已有效果不自动清除'),
 'mail':('邮件与离线收益','处理邮件附件与已结算的离线收益面板'),
 'tower':('无限塔挑战','只在主线推进空档挑战；刷经验期间不切入塔层'),
 'ui_cleanup':('无人值守接续','默认自动收起背包和成长窗口，可关闭自动收起，交易面板保持等待'),
}

def module_for(kind):return {'formation':'unlock','pet_equip':'pet_unlock','skill_equip':'active','skill_refund':'active','passive_refund':'passive','skill_unequip':'active','deposit':'storage','withdraw':'storage','sort':'ui_cleanup','mail_open':'mail','mail_claim':'mail','mail_close':'mail','offline_close':'mail','tower_return':'progress','battle_recover':'ui_cleanup'}.get(kind,kind)

def affordable(action,snapshot,config):
    cost=action.get('cost')
    if not cost:return True
    amount=cost.get('amount');goods=cost.get('goods')
    if not isinstance(amount,(int,float)) or not 0<=amount<float('inf'):return False
    if goods==201:return amount<=max(0,snapshot['currencies']['soul']-config['soul_reserve'])
    if goods==202 and action['kind']=='rune' and action.get('permanent') and config.get('permanent_runes',True):
        return amount<=max(0,snapshot['currencies'].get('premium',0)-config.get('premium_reserve',0))
    return False

def arranged_characters(snapshot):
    characters = snapshot.get('characters', [])
    if isinstance(snapshot.get('squad'), (list, tuple)):
        active = {n for n in snapshot['squad'] if type(n) is int and n > 0}
        characters = [c for c in characters if c['id'] in active]
    return sorted(characters, key=lambda c: str(c['id']))


def _online_rune_level(snapshot):
    runes = snapshot.get('runes', {})
    values = [runes.get(key) for key in ('learned', 'onlineLearned', 'offlineLearned')]
    if (runes.get('progressKnown') is True
            and all(type(value) is int and value >= 0 for value in values)
            and values[0] == values[1] + values[2]):
        return values[1]
    return None


def _battle_rune_nodes(snapshot):
    scope = snapshot.get('runes', {}).get('battleScope')
    if (not isinstance(scope, dict) or type(scope.get('schema')) is not int
            or scope['schema'] != 1 or scope.get('policy') != 'online_without_storage_capacity'
            or _online_rune_level(snapshot) is None):
        return None
    signature = scope.get('signature')
    if not isinstance(signature, str) or not 2 <= len(signature) <= 65536:
        return None
    try:
        nodes = json.loads(signature)
    except (ValueError, RecursionError):
        return None
    if not isinstance(nodes, list) or len(nodes) > 1024:
        return None
    ids = set()
    for pair in nodes:
        if (not isinstance(pair, list) or len(pair) != 2
                or type(pair[0]) is not int or not 0 < pair[0] <= 2**53 - 1
                or type(pair[1]) is not int or not 0 <= pair[1] <= 2**53 - 1
                or pair[0] in ids):
            return None
        ids.add(pair[0])
    return tuple(sorted((pair[0], pair[1]) for pair in nodes))


def _rune_strength_scope(snapshot):
    if _battle_rune_nodes(snapshot) is not None:
        return 'battle_nodes_v1'
    return 'online' if _online_rune_level(snapshot) is not None else 'legacy'


def _party_equipment_effects(snapshot):
    # Native revisions contain only item identity and socket effects, not transient
    # server confirmations, locks, current health or container positions.
    items = [item for character in arranged_characters(snapshot) for item in character.get('equipment', [])]
    if not items:
        return None
    effects = {}
    for item in items:
        revision = item.get('revision')
        if not isinstance(revision, str) or not 2 <= len(revision) <= 65536:
            return None
        try:
            value = json.loads(revision)
        except (ValueError, RecursionError):
            return None
        if (not isinstance(value, list) or len(value) != 3 or value[0] != item.get('uid')
                or not isinstance(value[0], str) or not value[0]
                or type(value[1]) is not int or value[1] <= 0 or value[1] != item.get('id')
                or not isinstance(value[2], list) or len(value[2]) > 256
                or type(item.get('sockets')) is not int or len(value[2]) != item['sockets']):
            return None
        sockets = []
        for socket in value[2]:
            if (not isinstance(socket, dict)
                    or any(type(socket.get(key)) is not int or socket[key] < minimum
                           for key, minimum in [('index', 0), ('id', 1), ('ability', 0)])
                    or type(socket.get('value')) not in (int, float)
                    or not -1e308 <= socket['value'] <= 1e308):
                return None
            sockets.append((socket['index'], socket['id'], socket['ability'], socket['value']))
        # Different attachment categories can legitimately share index zero.
        effects[item['uid']] = ('socket_effects_v1', value[1], tuple(sorted(sockets)))
    return effects


def _equipment_strength_scope(snapshot):
    return 'socket_effects_v1' if _party_equipment_effects(snapshot) is not None else 'legacy'


def progression_baseline(snapshot):
    return {'progress_strength': progression_signature(snapshot),
            'rune_strength_scope': _rune_strength_scope(snapshot),
            'equipment_strength_scope': _equipment_strength_scope(snapshot)}


def _rebase_online_baseline(entry, snapshot, allow_missing=False):
    # Upgrade the representation once, preserving retry and settlement clocks.
    # A temporarily missing detailed scope uses the verified online fallback.
    scope = _rune_strength_scope(snapshot)
    if (entry and (allow_missing or entry.get('progress_strength') is not None)
            and ((entry.get('rune_strength_scope') != scope and scope != 'legacy')
                 or entry.get('equipment_strength_scope', 'legacy') != _equipment_strength_scope(snapshot))):
        entry.update(progression_baseline(snapshot))


def _party_signature(snapshot, pet):
    effects = _party_equipment_effects(snapshot)
    characters = tuple((c['id'], c.get('level'),
                        tuple(sorted(((e.get('slot'), e.get('uid'), e.get('sockets'))
                                      + ((effects[e['uid']],) if effects is not None else ())
                                      for e in c.get('equipment', [])), key=lambda e: (str(e[0]), str(e[1])))),
                        tuple(sorted(((p.get('kind'), p.get('skill'), p.get('level'))
                                      for p in c.get('skills', [])), key=lambda p: (str(p[0]), str(p[1]), str(p[2])))),
                        tuple(c.get('activeLoadout', []))) for c in arranged_characters(snapshot))
    online = _online_rune_level(snapshot)
    nodes = _battle_rune_nodes(snapshot)
    rune_level = (('battle_nodes_v1', nodes) if nodes is not None else
                  online if online is not None else snapshot.get('runes', {}).get('learned'))
    return str((snapshot.get('record', {}).get('maxCleared'), rune_level,
                pet, tuple(snapshot.get('squad') or []), characters))


def _owned_pet_effects(snapshot):
    pets = snapshot.get('pets', {})
    effects = pets.get('ownedEffects')
    if isinstance(effects, list):
        return tuple(sorted(((p.get('id'), p.get('ability'), p.get('factor')) for p in effects), key=str))
    # Legacy snapshots report only the count. Following never changes the bonuses.
    return pets.get('unlocked')


def planning_strength_available(snapshot):
    unavailable = snapshot.get('planningUnavailable') or {}
    return not any(section in unavailable for section in
                   ('characters', 'workshop', 'runes', 'pets', 'equipment', 'progression'))


def strength_signature(snapshot):
    return _party_signature(snapshot, _owned_pet_effects(snapshot))


def progression_signature(snapshot):
    return _party_signature(snapshot, _owned_pet_effects(snapshot))


def main_story_complete(snapshot):
    frontier=snapshot.get('record',{}).get('maxCleared')
    maximum=snapshot.get('catalogue',{}).get('normalMax')
    return type(frontier) is int and type(maximum) is int and maximum>0 and frontier>=maximum


def farm_retry_waiting(snapshot, growth, now, options):
    stage = snapshot.get('stage', {})
    level, frontier = stage.get('level'), snapshot.get('record', {}).get('maxCleared')
    if not (stage.get('category') == 0 and stage.get('repeat') is True
            and type(level) is int and type(frontier) is int and 0 < level <= frontier):
        return False
    current = snapshot.get('combat', {}).get('current') or {}
    elapsed = current.get('elapsed')
    matching = (snapshot.get('combat', {}).get('available') is True
                and current.get('level') == level and current.get('difficulty') == stage.get('difficulty'))
    boundary = matching and (current.get('result') in ('Cleared', 'Failed')
               or current.get('result') == 'InProgress' and type(elapsed) in (int, float)
               and math.isfinite(elapsed) and 0 <= elapsed <= 10)
    requested = growth.get('retry_requested_at', growth.get('since', now))
    return not boundary and now - requested < options['farm_retry_finish_seconds']


def active_frontier_battle(snapshot):
    stage = snapshot.get('stage', {})
    raw = snapshot.get('combat') or {}
    current = raw.get('current') or {}
    frontier = snapshot.get('record', {}).get('maxCleared')
    level, difficulty, sequence, elapsed = (stage.get('level'), stage.get('difficulty'),
                                            current.get('sequence'), current.get('elapsed'))
    if (stage.get('category') != 0 or stage.get('running') is not True or raw.get('available') is not True
            or type(frontier) is not int or frontier < 0 or type(level) is not int or level <= frontier
            or type(difficulty) is not int or difficulty < 0 or type(sequence) is not int or sequence < 0
            or current.get('result') != 'InProgress' or current.get('level') != level
            or current.get('difficulty') != difficulty or type(elapsed) not in (int, float)
            or not math.isfinite(elapsed) or elapsed < 0):
        return None
    # Repeat may have been inherited from an entrance guard just before native auto-advance.
    return {'level': level, 'difficulty': difficulty, 'sequence': sequence, 'elapsed': elapsed}


def observe_frontier_return(snapshot, state, now, options):
    growth = state.get('growth', {})
    battle = active_frontier_battle(snapshot) if growth.get('phase') == 'farm' else None
    if battle is None:
        growth.pop('frontier_return', None)
        return None
    marker = {k: battle[k] for k in ('level', 'difficulty', 'sequence')}
    marker['session'] = state.get('battle_observation', {}).get('session')
    previous = growth.get('frontier_return') or {}
    since = previous.get('since')
    if (any(previous.get(k) != value for k, value in marker.items())
            or type(since) not in (int, float) or not math.isfinite(since) or since > now):
        previous = {**marker, 'since': now}
        growth['frontier_return'] = previous
    waited = now - previous['since']
    return {'waiting': waited < options['farm_retry_finish_seconds'], 'battle': battle, 'waited': waited}


def skill_repair_authorized(config, repair):
    options=strategy(config)
    modules=(config or {}).get('modules',{})
    controls=repair.get('controls',{'passive':True})
    return bool(controls.get('passive') and modules.get('passive') is not False and options['allow_passive_refund'] and options['passive_learn'] and options['passive_upgrade']
                or controls.get('active') and modules.get('active') is not False and options['allow_active_refund'] and options['active_learn'] and options['active_upgrade'])


def skill_repair_pending(snapshot, config=None):
    options=strategy(config)
    for character in arranged_characters(snapshot):
        repair=character.get('skillPlanning',{}).get('repair') or {}
        if not skill_repair_authorized(config,repair):
            continue
        # A native refusal has no refund to execute; it must not hold new challenges forever.
        if repair.get('reason')=='native_refund_blocked' and not repair.get('refund'):
            continue
        if repair.get('excess',0)>0 or (repair.get('reason')=='fill_target'
                and character.get('points',0)>options['skill_point_reserve']):
            return True
    return False


def observe_growth(snapshot,state,now,config=None):
    options=strategy(config)
    record=snapshot.get('record',{});frontier=record.get('maxCleared',0);deaths=record.get('deaths',0)
    if not planning_strength_available(snapshot):
        growth = state.get('growth') or {'phase': 'push', 'frontier': frontier, 'since': now, 'deaths': deaths}
        return {k: growth[k] for k in ('phase', 'frontier', 'since', 'deaths')} | {
            'retry_pending': False, 'retry_trigger': None, 'gate': None, 'skill_repair_pending': False,
            'frontier_return_pending': False, 'observation_available': False,
            'reason': '部分成长数据暂不可用，保留原有规划；当前战斗与其他独立模块继续。'}
    strength=progression_signature(snapshot)
    repairing=skill_repair_pending(snapshot,config)
    growth=state.setdefault('growth',{'phase':'push','frontier':frontier,'since':now,'deaths':deaths})
    if frontier>growth['frontier'] or deaths<growth['deaths']:
        growth.update(phase='push',frontier=frontier,since=now,deaths=deaths)
        growth.pop('retry_requested_at', None)
        growth.pop('retry_trigger', None)
    if main_story_complete(snapshot):
        if growth['phase']!='endgame':growth.update(phase='endgame',frontier=frontier,since=now,deaths=deaths)
    elif growth['phase']=='endgame':
        growth.update(phase='push',frontier=frontier,since=now,deaths=deaths)
    if 'progress_strength' not in growth:
        # Old baselines included contextual pets and reserve heroes. Rebase once,
        # preserve the farming clock, and discard any retry based on that old comparison.
        growth.update(progression_baseline(snapshot))
        growth.pop('strength', None)
        if growth['phase']=='farm':
            growth.pop('retry_requested_at', None)
            growth.pop('retry_trigger', None)
    _rebase_online_baseline(growth, snapshot)
    stage = snapshot.get('stage', {})
    entry_waiting = (stage.get('category') == 0 and type(stage.get('level')) is int and stage['level'] <= frontier
        and any(key not in state.get('pending_results', {})
                and entry.get('action', {}).get('kind') == 'progress'
                and entry['action'].get('phase') == 'travel'
                and entry['action'].get('level') == frontier + 1
                for key, entry in state.get('entry_uncertainty', {}).items()))
    if snapshot.get('stage',{}).get('category',0)==0 and growth['phase']!='endgame':
        failures=sum(item.get('category')==0 and item.get('result')=='Failed' and item.get('level',0)>frontier and item.get('observed',0)>=growth['since'] for item in state.get('battle_observation',{}).get('outcomes',[]))
        native_available=snapshot.get('combat',{}).get('available') is True
        failed_push=failures>=options['push_failure_limit'] or (not native_available and deaths-growth['deaths']>=options['fallback_death_limit'])
        gate=snapshot.get('progression',{}).get('gate')
        if growth['phase']=='push' and (gate or entry_waiting or now-growth['since']>=options['push_wait_seconds'] and failed_push):
            growth.update(phase='farm',since=now,deaths=deaths,**progression_baseline(snapshot))
            growth.pop('retry_requested_at', None)
            growth.pop('retry_trigger', None)
        elif growth['phase']=='farm':
            if gate or repairing or entry_waiting:
                growth.pop('retry_requested_at', None)
                growth.pop('retry_trigger', None)
            elif now-growth['since']>=options['farm_min_seconds'] and (growth.get('progress_strength')!=strength or now-growth['since']>=options['farm_retry_seconds']):
                growth.setdefault('retry_trigger', 'party_growth' if growth.get('progress_strength')!=strength else 'retry_interval')
                growth.setdefault('retry_requested_at', now)
                if not farm_retry_waiting(snapshot, growth, now, options):
                    growth.update(phase='push',since=now,deaths=deaths)
    frontier_return = observe_frontier_return(snapshot, state, now, options)
    endgame_reason='主线已通关，持续练级、装备与技能养成'
    if (config or {}).get('modules',{}).get('tower'):endgame_reason+='，在战斗结束后接续无限塔'
    retry_pending = (growth['phase'] != 'endgame' and 'retry_requested_at' in growth
                     and farm_retry_waiting(snapshot, growth, now, options))
    return {key:growth[key] for key in ('phase','frontier','since','deaths')}|{'retry_pending': retry_pending, 'retry_trigger':growth.get('retry_trigger'), 'reason':{'farm':'重复失败，先积累等级与战力','endgame':endgame_reason}.get(growth['phase'],{'party_growth':'上阵队伍或永久成长发生变化，重新评估主线','retry_interval':'练级重试间隔已到，重新评估主线'}.get(growth.get('retry_trigger'),'接续主线，同时检查队伍成长')),
            'gate':snapshot.get('progression',{}).get('gate'),'skill_repair_pending':repairing,
            'entry_result_pending':entry_waiting,
            'frontier_return_pending':bool(frontier_return and frontier_return['waiting'])} | ({'reason':'正在重配上阵天赋，继续当前战斗与其他成长，完成后再评估新挑战。'} if repairing else {}) | ({'reason': '已满足主线重试条件，等待本场练级结算或下一轮开场；超时后接续重试。'} if retry_pending else {}) | ({'reason':'已进入未通关前沿，等待本场结算后再返回练级，其他成长继续。'} if frontier_return and frontier_return['waiting'] else {}) | ({'reason':'Boss入场结果尚未确认，保留防重复提交记录；继续免费练级、经验比较与其他成长。'} if entry_waiting else {})

def equipment_growth_signature(snapshot):
    without_gear = {**snapshot, 'characters': [{**c, 'equipment': []} for c in snapshot.get('characters', [])]}
    return progression_signature(without_gear)


def equipment_planning_status(scan, state):
    return describe_equipment(scan, state, equipment_growth_signature(scan['snapshot']))


def equipment_ready(action,state,now,config=None):
    options=strategy(config)
    # Keep the user-configured dwell and retired-item cooldown in addition to
    # confirmed-loadout history; native scoring still validates every swap.
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
    if scan.get('runtime',{}).get('maintenance',{}).get('active') or scan['snapshot'].get('automationBlocked'):return []
    if scan['snapshot'].get('sync',{}).get('blocked'):return []
    backlogged=scan['snapshot'].get('sync',{}).get('queue',0)>100
    offline=scan['snapshot'].get('connection',{}).get('online') is False
    available=[]
    transitioning=any(stage_transition(p.get('action',{})) for p in state.get('pending_results',{}).values())
    claiming=mail_pending(state)
    repairing=skill_repair_pending(scan['snapshot'],config)
    equipment_growth=equipment_growth_signature(scan['snapshot'])
    equipment_pending=any(p.get('action',{}).get('kind')=='equipment' for p in state.get('pending_results',{}).values())
    frontier_return=observe_frontier_return(scan['snapshot'],state,now,options)
    workshop_pending=[p['action'] for p in state.get('pending_results',{}).values()
                      if p.get('action',{}).get('kind') in NATIVE_RECEIPT_KINDS]
    workshop_items={uid for p in workshop_pending for uid in [*p.get('allowed',[]),p.get('uid'),p.get('swapUid')] if uid}
    for a in scan['actions']:
        touched={uid for uid in [*a.get('allowed',[]),a.get('uid'),a.get('swapUid'),a.get('previousUid')] if uid}
        if workshop_items.intersection(touched) or workshop_pending and a['kind']=='sort':continue
        if not planning_strength_available(scan['snapshot']) and (a['kind'] in ('equipment', 'tower')
                or a['kind']=='progress' and (a.get('mode') in ('push','boss')
                    or a.get('mode')=='farm' and a.get('phase')=='travel')
                or a['kind']=='battle_recover' and a.get('mode')=='stage'
                    and a.get('level')!=scan['snapshot'].get('stage',{}).get('level')):continue
        if not operation_allowed(a,options):continue
        if a['kind']=='box' and (state.get('box_pending') or any(k.startswith('box:') for k in state.get('uncertain',{}))):continue
        if claiming and a['kind']=='mail_claim':continue
        if a['kind'] in scan['snapshot'].get('manualBlockedKinds',[]):continue
        # Free recovery must remain available while reward mutations wait for native sync.
        # The bridge recomputes the no-ticket prerequisite before it accepts this flag.
        if (backlogged or offline) and not (a.get('freeEntry') is True and
                (a['kind'] in ('tower_return','battle_recover') or a['kind']=='progress' and a.get('mode') in ('guard','farm'))):continue
        if not config['modules'].get(module_for(a['kind']),False) and a['kind']!='tower_return' and not(a['kind']=='progress' and a.get('mode')=='guard' and not a.get('requiresProgress')):continue
        readiness=scan['snapshot'].get('battleReadiness',{})
        if readiness.get('known') and (not readiness.get('charactersInitialized') or readiness.get('expected',0)==0 or readiness.get('missing')) and (a['kind']=='tower' or a['kind']=='progress' and a.get('mode') not in ('guard',)):continue
        if transitioning and (a['kind'] in ('tower','tower_return','battle_recover','formation') or a['kind']=='progress'):continue
        if a['kind']=='battle_recover':
            recovery=state.get('battle_recovery',{})
            wait=options['stage_stall_wait_seconds'] if recovery.get('reason')=='stalled_end' else options['battle_recovery_wait_seconds']
            if not recovery.get('eligible') or now-recovery.get('since',now)<wait or now-recovery.get('last_attempt',0)<options['battle_recovery_retry_seconds']:continue
            if a.get('mode')!=('sync' if recovery.get('attempts',0)==0 and recovery.get('reason')!='stalled_end' else 'stage'):continue
        if state.get('cooldowns',{}).get(a['key'],0)>now:continue
        if a['key'] in state.get('uncertain',{}):continue
        if entry_conflicts(a,state):continue
        if a['kind']=='equipment':
            if equipment_pending or not equipment_ready(a,state,now,config):continue
            a,reason=prepare_equipment(a,scan['snapshot'],state,equipment_growth)
            if reason:continue
        if state.get('kind_cooldowns',{}).get(a['kind'],0)>now:continue
        if a['kind']=='equipment' and not a.get('empty') and a.get('gain',0)*100<options['equipment_min_gain_percent']:continue
        if repairing and (a['kind']=='tower' or a['kind']=='progress' and a.get('mode') in ('push','boss')):continue
        if a['kind']=='progress':
            phase=state.get('growth',{}).get('phase','push')
            if a.get('mode')=='farm' and (phase not in ('farm','endgame') or a.get('level',0)<high_farm_minimum(scan['snapshot'],options)):continue
            if a.get('mode')=='farm' and a.get('phase')=='travel' and frontier_return and frontier_return['waiting']:continue
            route=state.get('farm_route')
            if a.get('mode')=='farm' and route is not None and (a.get('level'),a.get('difficulty'))!=(route.get('level'),route.get('difficulty')):continue
            if a.get('mode') in ('push','boss') and phase in ('farm','endgame'):continue
            # Dispatch may be delayed by other growth actions after the phase changed.
            # Recheck the live farming round before leaving it for the frontier.
            if a.get('mode') in ('push','boss') and a.get('phase')=='travel' and 'retry_requested_at' in state.get('growth',{}) and farm_retry_waiting(scan['snapshot'],state.get('growth',{}),now,options):continue
        if a['kind']=='tower':
            stage=scan['snapshot'].get('stage',{})
            growth=state.get('growth',{})
            record=scan['snapshot'].get('record',{})
            catalogue=scan['snapshot'].get('catalogue',{})
            normal_max=catalogue.get('normalMax')
            if (not isinstance(record.get('maxCleared'),int) or isinstance(record.get('maxCleared'),bool)
                    or not isinstance(normal_max,int) or isinstance(normal_max,bool) or normal_max<=0
                    or record['maxCleared']<normal_max):continue
            if growth.get('phase')=='farm':continue
            if stage.get('category')!=0 or stage.get('running') is not False or stage.get('ending') is not True:continue
            if (growth.get('phase')=='push' and isinstance(stage.get('level'),int)
                    and isinstance(scan['snapshot'].get('record',{}).get('maxCleared'),int)
                    and stage['level']>scan['snapshot']['record']['maxCleared']):continue
            if state.get('tower_turn',{}).get('waiting'):continue
            previous=state.get('tower_attempt',{})
            _rebase_online_baseline(previous, scan['snapshot'], allow_missing=True)
            record=scan['snapshot'].get('record',{})
            changed=previous.get('progress_strength') is not None and previous['progress_strength']!=progression_signature(scan['snapshot'])
            if previous and previous.get('progress_strength') is None:
                changed=any(f.get('last_status')=='confirmed' and f.get('last_at',0)>previous.get('at',0)
                            for kind,f in state.get('features',{}).items() if kind in ('equipment','rune','active','passive','pet_unlock','formation'))
            if previous.get('level')==a['level'] and record.get('maxStage',0)<=previous.get('max_stage',0) and not changed and options['tower_require_growth']:continue
            if previous and now-previous.get('at',0)<options['tower_retry_seconds']:continue
        if not affordable(a,scan['snapshot'],config):continue
        a=dict(a)
        if a['kind']=='progress' and a.get('mode')=='farm' and a.get('phase')=='travel' and frontier_return:
            a['frontierReturn']={**frontier_return['battle'],'waited':frontier_return['waited']}
        if a['kind']=='tower':a['priority']=79
        available.append(a)
    # A tower may use an ended battle window after the main story is complete.
    # Keep its low growth priority, but do not leave that window to change farming maps.
    if state.get('growth',{}).get('phase')=='endgame' and any(a['kind']=='tower' for a in available):
        available=[a for a in available if not (a['kind']=='progress' and a.get('mode')=='farm')]
    # Spend attachments only after an eligible replacement for that exact slot.
    # Disabled/cooling-down/rejected equipment plans must not suppress refinement.
    replacements = {(a.get('id'), a.get('slot')) for a in available if a['kind']=='equipment'}
    pending_targets = {p.get('action',{}).get('previousUid')
                       for p in state.get('pending_results',{}).values()
                       if p.get('action',{}).get('kind')=='equipment'}
    available = [a for a in available if not (a['kind']=='refine' and
                 ((a.get('id'), a.get('slot')) in replacements or a.get('uid') in pending_targets))]
    # Forge > combine > recycle, after eligibility, budget and cooldown filters.
    def workshop_order(action):
        kind=action.get('purpose') if action['kind']=='withdraw' else action['kind']
        return {'forge':0,'combine':1,'decompose':2,'recycle':2}.get(kind)
    stages=[stage for a in available if (stage:=workshop_order(a)) is not None]
    if stages:
        first=min(stages)
        available=[a for a in available if workshop_order(a) in (None,first)]
    # A category preference covers both its synthesis and its warehouse recalls.
    # Apply it after eligibility checks, so disabled, pending or unaffordable work
    # cannot reserve a turn. Equal preferences preserve the existing action order.
    def synthesis_priority(action):
        if not (action['kind']=='combine' or action['kind']=='withdraw' and action.get('purpose')=='combine'):
            return None
        category=action.get('category')
        if type(category) is not int or not 0<=category<len(CATEGORIES):
            return None
        return options['combine_'+CATEGORIES[category][0]+'_priority']
    preferences=[value for action in available if (value:=synthesis_priority(action)) is not None]
    if preferences:
        preferred=min(preferences)
        available=[action for action in available if synthesis_priority(action) in (None,preferred)]
    useful_work={'box','equipment','combine','decompose','forge','refine','deposit','withdraw','active','passive','passive_refund','skill_refund','skill_equip','skill_unequip'}
    if any(a['kind'] in useful_work for a in available):
        available=[a for a in available if a['kind']!='sort']
    else:
        for a in available:
            if a['kind']=='sort':a['priority']=108
    # Resolve equal priority in favor of a proven gear upgrade before opening more boxes.
    # Rotate within equipment only; old timestamps must never demote all heroes below boxes.
    def rank(a):
        last=state.get('last_module',{}).get(module_for(a['kind']),state.get('scheduling_started',now))
        # A capped bonus can permanently starve priority-60 growth behind priority-99
        # loot. Keep accruing time since this module's last service. Urgent actions
        # remain a separate leading rank; eligibility and workshop order apply above.
        aging=max(0,now-last)/15 if a['priority']<110 else 0
        # Pure offline benefit stays last even after a long wait. An Offline node
        # opening an online route is a minimum prerequisite, not fallback spending.
        fallback=a['kind']=='rune' and (a.get('offlineFallback') is True or
            str(a.get('header','')).startswith('Offline') and a.get('offlineFallback') is not False)
        return (a['priority']>=110,not fallback,a['priority']+aging,a['kind']=='equipment',
                -state.get('last_equipment',{}).get(str(a.get('id')),0) if a['kind']=='equipment' else 0,a.get('gain',0),-a.get('cost',{}).get('amount',0))
    return sorted(available,key=rank,reverse=True)

def choose(scan,config,state,now=None):
    actions=ranked_actions(scan,config,state,now)
    return actions[0] if actions else None
