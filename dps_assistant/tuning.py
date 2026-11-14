"""Detailed operation controls and module metadata. Defaults preserve existing automation."""
import re

PARTS = [('main_weapon','主武器'),('sub_weapon','副武器'),('helmet','头盔'),
         ('armor','护甲'),('gloves','手套'),('boots','靴子'),('accessory','饰品')]
CATEGORIES = [('equipment','装备'),('accessory','饰品'),('refinement','精炼材料'),('craft','制作材料')]
BASE_MODULE_PARAMETERS = {
 'box':['inventory_pressure_percent','interval'],
 'equipment':['equipment_hold_seconds','equipment_return_seconds','equipment_min_gain_percent'],
 'active':['recommended_actives','allow_active_refund','skill_point_reserve'],
 'passive':['allow_passive_refund','skill_point_reserve'],
 'rune':['rune_priority','soul_reserve','permanent_runes','premium_reserve'],
 'unlock':['action_retry_seconds'], 'pet_unlock':['pet_mode'],
 'progress':['push_wait_seconds','push_failure_limit','fallback_death_limit','farm_min_seconds','farm_retry_seconds','farm_retry_finish_seconds','farm_level_offset','farm_candidate_count','farm_failure_limit','adaptive_farming','farm_sample_seconds','farm_probe_seconds','farm_recheck_seconds','farm_switch_gain_percent'],
 'combine':['inventory_pressure_percent','action_cooldown_seconds'],
 'decompose':['recycle_socketed_equipment','recycle_pressure_cleanup','recycle_pressure_max_grade','recycle_batch','recycle_normal_tier_gap','recycle_rare_tier_gap'],
 'storage':['inventory_pressure_percent','storage_pressure_percent','auto_sort_items','sort_cooldown_seconds'],
 'forge':['forge_priority_'+p for p,_ in PARTS]+['action_retry_seconds','action_cooldown_seconds'],
 'refine':['action_retry_seconds','action_cooldown_seconds'], 'mail':['action_retry_seconds'],
 'tower':['tower_retry_seconds','tower_require_growth'],
 'ui_cleanup':['preserve_open_panels','pause_on_manual_panels','auto_sort_items','sort_cooldown_seconds','battle_recovery_wait_seconds','battle_recovery_retry_seconds','stage_stall_wait_seconds','stage_transition_wait_seconds','action_retry_seconds','action_cooldown_seconds'],
}

def extra_parameters(number, switch, choice):
    result=[]
    def add(spec,module,section):
        result.append({**spec,'modules':[module],'section':section})
    def flag(key,label,module,group,section,hint=''):
        add(switch(key,label,True,group,hint or '默认开启，沿用现有行为；关闭仅停止此项自动操作。原生解锁和物品保护始终生效。'),module,section)
    def limit(key,label,module,group,section,maximum=100,unit='级'):
        add(number(key,label,0,group,0,maximum,unit,hint='0 表示不额外限制；始终受当前账号实时等级、原生配方、解锁条件和安全保护限制。最小值高于最大值时不安排此类操作。'),module,section)
    for grade,label in enumerate(['普通','高级','首领']):
        flag('box_grade_'+str(grade),'开启'+label+'宝箱','box','general','宝箱分类')
    add(number('box_batch_limit','单批最多开启宝箱',8,'general',1,8,'个',hint='单批仍受背包空位和主线程时间片限制；回执未确认时不会重复开箱。'),'box','宝箱节奏')
    add(number('box_free_slots','开箱后预留背包空位',0,'general',0,100,'格',hint='默认 0，沿用原行为；达到预留空位后停止开箱，仓储与其他成长继续。'),'box','宝箱节奏')
    for prefix,module,group,section in [('equipment','equipment','equipment','换装部位'),('forge','forge','workshop','锻造部位'),('refine','refine','workshop','镶嵌部位')]:
        for part,label in PARTS:
            flag(prefix+'_part_'+part,label,module,group,section)
    for key,label in [('equipment_fill_empty','补齐空装备槽'),('equipment_replace','替换已有装备'),('equipment_inventory','使用背包装备'),('equipment_storage','使用仓库装备')]:
        flag(key,label,'equipment','equipment','换装范围','关闭后仍保护已识别的升级装备，不会因此将它们当作合成或回收材料。')
    for category,label in CATEGORIES:
        section=label+'合成'
        flag('combine_'+category,'允许合成'+label,'combine','workshop',section)
        for bound,word in [('min','最低'),('max','最高')]:
            limit('combine_'+category+'_'+bound+'_grade',word+'材料品质','combine','workshop',section)
            limit('combine_'+category+'_'+bound+'_tier',word+'材料档位','combine','workshop',section,100,'档')
        add(number('combine_'+category+'_priority','分类处理优先级',1,'workshop',1,10,hint='数字越小越优先；相同优先级沿用原生配方档位与顺序。'),'combine',section)
    flag('combine_use_storage','合成取用仓库材料','combine','workshop','合成来源')
    flag('forge_use_storage','锻造取用仓库材料','forge','workshop','锻造范围')
    add(number('forge_tier_offset','锻造低于当前可用档数',0,'workshop',0,10,'档',hint='0 沿用实时可用档位；逐个账号与英雄计算，不固定某个角色等级。'),'forge','锻造范围')
    add(number('forge_min_need','锻造最低需求评分',0,'workshop',0,1000,hint='0 沿用原需求判断；提高后仅制作需求评分达到此值的配方，不为被排除配方预约材料。'),'forge','锻造范围')
    for kind,label in [('equipment','武器与防具'),('accessory','饰品')]:
        flag('recycle_'+kind,'回收'+label,'decompose','workshop','回收范围')
    flag('recycle_retired','按落后档位常规回收','decompose','workshop','回收范围')
    flag('recycle_use_storage','回收仓库淘汰装备','decompose','workshop','回收范围')
    add(number('recycle_min_grade','回收最低品质',1,'workshop',1,4,'级',hint='同时受常规品质规则与空间紧张时的品质上限约束；Epic 及以上始终保留。'),'decompose','回收范围')
    add(number('recycle_max_grade','回收最高品质',4,'workshop',1,4,'级',hint='仅进一步收紧现有回收范围，不扩大到 Epic 及以上。最低值高于最高值时不回收。'),'decompose','回收范围')
    flag('refine_use_storage','镶嵌取用仓库材料','refine','workshop','镶嵌材料')
    flag('refine_tradable_equipment','不朽及以下可交易装备补镶嵌','refine','workshop','镶嵌范围','允许给不朽及以下品质的已装备物品补空槽，优先品质高的装备；完整保留已有镶嵌与交易属性。锁定、未确认目标及可交易材料仍受保护。')
    for bound,word in [('min','最低'),('max','最高')]:
        limit('refine_'+bound+'_grade',word+'镶嵌材料品质','refine','workshop','镶嵌材料')
        limit('refine_'+bound+'_tier',word+'目标装备档位','refine','workshop','镶嵌范围',100,'档')
    add(choice('refine_material_order','镶嵌材料选择顺序','highest','workshop',[('highest','品质高优先（现有策略）'),('lowest','品质低优先')],'先保留已启用的完整合成批次，再从剩余材料中按原生插槽兼容性选择；不清空或覆盖已有镶嵌。'),'refine','镶嵌材料')
    for key,label in [('active_learn','学习新主动技能'),('active_upgrade','升级已学主动技能'),('active_equip','自动装配与替换主动技能'),('passive_learn','学习新被动节点'),('passive_upgrade','升级已有被动节点')]:
        flag(key,label,'active' if key.startswith('active') else 'passive','skills','学习与装配','仅从当前等级已解锁且原生允许的技能中选择；关闭学习或升级时，该类技能自动退款纠错也停止，避免退点后无法回填。')
    for group,label in [('growth','经验、灵魂与掉落'),('combat','战斗属性'),('capacity','背包、仓库与编队容量'),('utility','开箱、移动与便利'),('offline','离线收益')]:
        flag('rune_'+group,'投资'+label,'rune','runes','投资分类','关闭后不购买此类节点，其他路线若依赖尚未学会的此类前置，也不会绕过开关消费。')
    for key,label in [('rune_learn','学习新符文节点'),('rune_upgrade','升级已学符文')]:flag(key,label,'rune','runes','投资范围')
    limit('rune_max_level','单节点等级上限','rune','runes','投资范围',100000)
    limit('rune_soul_cost_limit','单次灵魂消费上限','rune','runes','消费限制',1000000000000,'')
    limit('rune_premium_cost_limit','单次水晶消费上限','rune','runes','消费限制',1000000000000,'')
    for key,label in [('unlock_characters','解锁符合条件的角色'),('formation_fill','使用已拥有角色补齐编队')]:flag(key,label,'unlock','skills','角色与编队')
    for key,label in [('pet_unlock_enabled','解锁符合条件的宠物'),('pet_follow_enabled','自动选择跟随外观')]:flag(key,label,'pet_unlock','pets','宠物操作')
    for key,label in [('storage_deposit','自动存仓腾位'),('storage_withdraw','按需求取用仓库材料'),('storage_swap','双满时交换物品腾位'),('storage_withdraw_forge','取用锻造材料'),('storage_withdraw_combine','取用合成材料'),('storage_withdraw_refine','取用镶嵌材料'),('storage_withdraw_recycle','取用待回收装备')]:flag(key,label,'storage','workshop','仓储操作')
    for key,label in [('sort_inventory','自动排序背包'),('sort_storage','自动排序已解锁仓库页')]:
        spec=switch(key,label,True,'workshop','同时受“物品操作后系统排序”总开关约束；不改变分页与玩家选中页。')
        result.append({**spec,'modules':['storage','ui_cleanup'],'section':'自动排序'})
    for key,label in [('mail_claim_enabled','自动读取并领取邮件附件'),('mail_close_enabled','自动收起已处理邮箱'),('offline_close_enabled','自动完成离线收益展示')]:flag(key,label,'mail','general','邮件与离线展示')
    for key,label in [('progress_push','发起新主线挑战'),('progress_farm','自动选择与切换练级关卡'),('progress_boss_tickets','使用入场券挑战主线 Boss')]:flag(key,label,'progress','growth','主线操作','影响助手发起的新操作；已开始战斗和游戏原生结算继续。免费入场保护仍生效，收费操作不会因等待超时而重放。')
    limit('progress_max_stage','主线挑战关卡上限','progress','growth','主线操作',100000,'关')
    flag('tower_tickets','允许使用原生入场券挑战塔层','tower','tower','塔挑战范围')
    limit('tower_max_level','塔挑战层数上限','tower','tower','塔挑战范围',100000,'层')
    for name,label in [('hero','英雄与装备窗口'),('skills','技能树'),('storage','仓库'),('cube','合成方块'),('runes','刻印窗口')]:flag('cleanup_'+name,'自动收起'+label,'ui_cleanup','general','窗口分类','同时受自动关闭窗口总开关约束；关闭后保留此窗口，只等待与该窗口冲突的自动操作。')
    for key,label in [('recovery_empty','恢复缺失的战场角色'),('recovery_stall','接续结算后停滞战场')]:flag(key,label,'ui_cleanup','general','无人值守恢复')
    for key,label in [('launch_main','自动启动主游戏实例'),('launch_sandbox','自动启动已识别沙盒实例')]:flag(key,label,'ui_cleanup','general','游戏启动','同时受“自动启动缺失的游戏实例”总开关与实例手动暂停设置约束。')
    return result


def operation_allowed(action, options):
    """A dispatch-time safeguard; the bridge also filters before reserving materials."""
    kind=action.get('kind')
    if kind=='box':return options.get('box_grade_'+str(action.get('grade',0)),False)
    if kind in ('unlock','formation','pet_unlock','pet_equip','mail_open','mail_claim','mail_close','offline_close','deposit'):
        return options[{'unlock':'unlock_characters','formation':'formation_fill','pet_unlock':'pet_unlock_enabled',
                        'pet_equip':'pet_follow_enabled','mail_open':'mail_claim_enabled','mail_claim':'mail_claim_enabled',
                        'mail_close':'mail_close_enabled','offline_close':'offline_close_enabled','deposit':'storage_deposit'}[kind]]
    if kind=='withdraw':
        purpose={'workshop':'refine','decompose':'recycle'}.get(action.get('purpose'),action.get('purpose'))
        if not (options['storage_withdraw'] and (not action.get('swapUid') or options['storage_swap']) and options.get('storage_withdraw_'+str(purpose),True) and options.get(str(purpose)+'_use_storage',True)):return False
        if purpose=='combine' and 'category' in action:return operation_allowed({**action,'kind':'combine'},options)
        if purpose=='forge' and 'part' in action:return operation_allowed({**action,'kind':'forge'},options)
        if purpose=='refine' and 'slot' in action:return operation_allowed({**action,'kind':'refine'},options)
        return True
    if kind=='sort':return options['auto_sort_items'] and options['sort_inventory' if action.get('place')=='inventory' else 'sort_storage']
    if kind in ('skill_equip','skill_unequip'):return options['active_equip']
    if kind in ('active','passive'):return options[kind+'_learn' if action.get('level',0)==0 else kind+'_upgrade']
    if kind in ('skill_refund','passive_refund'):
        prefix='active' if kind=='skill_refund' else 'passive'
        return options[prefix+'_learn'] and options[prefix+'_upgrade'] and options['allow_'+prefix+'_refund']
    if kind=='combine':
        category=action.get('category')
        if type(category) is not int or not 0<=category<4:return False
        key='combine_'+CATEGORIES[category][0]
        return options[key] and in_range(action.get('maxGrade'),options,key+'_min_grade',key+'_max_grade') and in_range(action.get('materialTier',action.get('tier')),options,key+'_min_tier',key+'_max_tier')
    if kind in ('equipment','refine','forge'):
        slot=action.get('part',1)-1 if kind=='forge' else action.get('slot',0)
        if type(slot) is not int or slot<0:return False
        part=PARTS[min(slot,6)][0]
        if not options[kind+'_part_'+part]:return False
        if kind=='refine' and action.get('allowTradableTarget') is True:
            if not options['refine_tradable_equipment'] or type(action.get('targetGrade')) is not int or not 1<=action['targetGrade']<=7:return False
        if kind=='equipment':return options['equipment_fill_empty' if action.get('empty') else 'equipment_replace'] and options['equipment_storage' if action.get('source')=='storage' else 'equipment_inventory']
    if kind=='decompose':return action.get('maxGrade',1)<=options['recycle_max_grade']
    if kind=='rune':
        header=action.get('header','')
        group=('offline' if header.startswith('Offline') else 'capacity' if re.search('InventorySlot|StorageTab|SquadSlot',header) else 'growth' if re.search('KillExpGain|KillGoods|NormalBoxDropRate|BossBoxDropRate',header) else 'utility' if re.search('Box|MoveSpeed|WaveSkip|ReviveHaste',header) else 'combat')
        level=action.get('level',0);cost=action.get('cost') or {};limit=options['rune_soul_cost_limit' if cost.get('goods')==201 else 'rune_premium_cost_limit']
        return options['rune_'+group] and options['rune_upgrade' if level>0 else 'rune_learn'] and (not options['rune_max_level'] or level<options['rune_max_level']) and (not limit or cost.get('amount',0)<=limit)
    if kind=='progress':
        mode=action.get('mode')
        if mode=='farm':return options['progress_farm']
        if mode in ('push','boss'):return options['progress_push'] and (mode!='boss' or options['progress_boss_tickets']) and (not options['progress_max_stage'] or action.get('level',0)<=options['progress_max_stage'])
    if kind=='tower':return (options['tower_tickets'] or action.get('ticket',0)<=0) and (not options['tower_max_level'] or action.get('level',0)<=options['tower_max_level'])
    if kind=='battle_recover':return options['recovery_stall' if action.get('reason')=='stalled_end' else 'recovery_empty']
    return True


def in_range(value,options,min_key,max_key):
    low,high=options[min_key],options[max_key]
    if not low and not high:return True
    return type(value) in (int,float) and (not low or value>=low) and (not high or value<=high)
