"""One source of defaults, validation and editable strategy descriptions."""
import copy
import math

GROUPS = [('general','运行与重试'),('growth','主线与练级'),('tower','无限塔'),('equipment','装备策略'),
          ('skills','技能成长'),('runes','符文与预算'),('pets','宠物策略'),('workshop','工坊与仓库')]

def number(key,label,default,group,minimum,maximum,unit='',scope='strategy',step=1,hint=''):
    return dict(key=key,label=label,default=default,group=group,min=minimum,max=maximum,unit=unit,
                scope=scope,type='number',step=step,hint=hint)
def switch(key,label,default,group,hint='',scope='strategy'):
    return dict(key=key,label=label,default=default,group=group,scope=scope,type='boolean',hint=hint)
def choice(key,label,default,group,options,hint=''):
    return dict(key=key,label=label,default=default,group=group,scope='strategy',type='choice',
                options=[dict(value=v,label=t) for v,t in options],hint=hint)

PARAMETERS = [
 switch('preserve_open_panels','保留手动打开的背包等面板',True,'general','开启后不自动关闭你正在查看的背包、仓库、英雄和符文窗口；助手继续不冲突的成长。关闭后允许无人值守收起这些窗口。'),
 switch('pause_on_manual_panels','查看游戏窗口时暂停全部操作',False,'general','默认关闭：例如查看仓库时，技能和符文仍可成长，仓库物品和切场会等待。开启后，查看任一成长窗口都会暂停全部提交，关闭窗口自动恢复。'),
 number('interval','巡检间隔',2.0,'general',1,60,'秒','root',.5,'各实例独立巡检。'),
 switch('auto_launch','自动启动缺失的游戏实例',True,'general','接续主实例与已识别的沙盒实例。','root'),
 number('launch_retry_seconds','游戏启动重试间隔',120,'general',30,3600,'秒'),
 number('action_retry_seconds','条件未满足后重试',30,'general',5,300,'秒'),
 number('action_cooldown_seconds','同一已执行动作的等待',5,'general',1,60,'秒'),
 number('battle_recovery_wait_seconds','空战场持续多久后恢复',30,'general',10,300,'秒',hint='编队有已拥有角色、但战场模型全缺失时才触发；正常死亡和切场继续等待原生流程。'),
 number('battle_recovery_retry_seconds','空战场恢复重试间隔',90,'general',30,600,'秒',hint='先重新同步原生编队，仍未恢复才重新进入当前免费关卡。'),
 number('stage_stall_wait_seconds','结算后停滞多久再接续',90,'general',30,600,'秒',hint='无待生成敌人、切场序号和波次持续不变才恢复；确认已通关后可接续下一免费关卡。'),
 number('stage_transition_wait_seconds','切场确认最长等待',120,'general',30,600,'秒',hint='等待期间不提交其他切场。超时后不把提交算成功，也不自动重放收费入场。'),
 number('push_wait_seconds','推进阶段最短观察',180,'growth',30,3600,'秒',hint='达到失败阈值后仍先完成此观察时长。'),
 number('push_failure_limit','主线失败后转练级',2,'growth',1,20,'次',hint='只统计已确认归属的未通关主线失败。'),
 number('fallback_death_limit','统计不可用时死亡阈值',6,'growth',1,60,'次'),
 number('farm_min_seconds','每轮练级最短时长',180,'growth',30,3600,'秒'),
 number('farm_retry_seconds','无新成长时重试主线',600,'growth',30,7200,'秒',hint='同时受每轮练级最短时长限制。'),
 number('farm_level_offset','练级关卡落后已通前沿',1,'growth',1,20,'关',hint='以此位置附近最高的免费可重复关卡为练级主目标。'),
 number('farm_failure_limit','练级关失败后自动降档',2,'growth',1,20,'次',hint='只统计实际观察到的主线重复练级失败，塔战和切场中止不计入。'),
 number('farm_candidate_count','备用练级关卡数',5,'growth',1,20,'关',hint='含主目标；失败后逐档选择更低的免费已通关关卡，等级或前沿提升后重新评估。'),
 switch('adaptive_farming','按实测经验选择练级点',True,'growth','在免费已通关候选中比较；编队战力变化后重新观测，不延长主线重试周期。'),
 number('farm_sample_seconds','每个练级点最少有效观测',90,'growth',30,600,'秒',hint='还需至少一次该关的原生通关确认；暂停、切场、离线和观测中断不计入。'),
 number('farm_recheck_seconds','练级实测结果有效期',900,'growth',120,7200,'秒',hint='超时或编队战力变化后重新采样。'),
 number('farm_switch_gain_percent','实测练级点切换收益',10,'growth',0,100,'%',hint='候选比较完成后，经验收益超过此比例才切换，避免反复来回。'),
 number('tower_retry_seconds','同层挑战间隔',300,'tower',30,7200,'秒'),
 number('tower_farm_wait_seconds','开始练级后暂缓塔挑战',180,'tower',0,3600,'秒'),
 switch('tower_require_growth','同层失败后等待战力变化',True,'tower','主线、等级、装备、技能或符文变化后再尝试。'),
 number('equipment_hold_seconds','已占用装备槽保持',60,'equipment',0,1800,'秒'),
 number('equipment_return_seconds','淘汰装备禁止回切',300,'equipment',0,7200,'秒',hint='按淘汰时间应用当前设置。'),
 number('equipment_min_gain_percent','换装最低评分收益',0,'equipment',0,100,'%',step=.1,hint='以同一次原生整套评分比较，空槽优先补齐。'),
 number('skill_point_reserve','每名角色保留技能点',0,'skills',0,100,'点'),
 switch('recommended_actives','使用职业推荐主动组合',True,'skills','关闭后保留已装备组合，仅补空槽并升级。'),
 switch('allow_active_refund','允许回收未使用主动技能点',True,'skills','供新解锁推荐技能与被动成长使用。'),
 number('soul_reserve','灵魂保留预算',0,'runes',0,1000000000000,'','root'),
 switch('permanent_runes','允许水晶投资永久符文',True,'runes','仅用于原生永久符文。','root'),
 number('premium_reserve','水晶保留预算',2,'runes',0,1000000000000,'','root'),
 choice('rune_priority','符文投资偏好','growth','runes',[('growth','成长优先'),('balanced','均衡成长'),('combat','战斗优先')]),
 choice('pet_mode','宠物切换偏好','auto','pets',[('auto','随练级与推进切换'),('growth','优先收益与经验'),('combat','优先战斗'),('keep','保留当前宠物')]),
 number('inventory_pressure_percent','背包整理触发占用',80,'workshop',40,100,'%',hint='联动存仓、合成和扩容优先级。'),
 number('storage_pressure_percent','仓库整理触发占用',80,'workshop',40,100,'%',hint='统计所有已解锁仓库页；达到阈值就安排取料合成与回收，不等完全满仓。'),
 switch('recycle_pressure_cleanup','空间紧张时回收闲置装备',True,'workshop','先合成，再回收不提升任一角色、未保留且未用于完整配方的当前档及低档装备；可交易、带镶嵌、锁定物品继续保护。'),
 number('recycle_pressure_max_grade','空间紧张时回收品质上限',4,'workshop',1,4,'级',hint='1=Common（普通）、2=Uncommon、3=Rare（稀有）、4=Unique。默认允许回收到 Unique；5=Epic 及以上始终保留。只回收无换装价值且未被完整配方保留的装备。'),
 switch('auto_sort_items','物品操作后系统排序',True,'workshop','合成、分解、换装与存取结束后，使用游戏系统排序整理背包和所有已解锁仓库页；保留分页和当前选中页。'),
 number('sort_cooldown_seconds','同一背包或仓库页排序间隔',30,'workshop',5,300,'秒',hint='内容或位置没有变化时不重复排序，整理期间不抢占取料合成。'),
 number('recycle_batch','单次回收淘汰装备上限',12,'workshop',1,12,'件'),
 number('recycle_normal_tier_gap','普通装备回收落后档数',1,'workshop',1,10,'档'),
 number('recycle_rare_tier_gap','较高品质装备回收落后档数',2,'workshop',1,10,'档'),
]

# Examples are exposed by the same schema used to validate and save parameters.
PARAMETER_HELP = {'interval': '建议保持 2 秒：每个实例约每 2 秒检查一次，只执行当前允许的动作。数值越小检查越频繁，电脑负担也越高。', 'auto_launch': '开启后，主游戏或已记住的沙盒退出时会尝试重新启动。只想管理当前运行的游戏时可关闭；手动指定目录用于主游戏启动。', 'launch_retry_seconds': '例如 120 秒：游戏暂未打开时，两次启动尝试至少相隔 2 分钟，避免反复启动。', 'action_retry_seconds': '例如 30 秒：原生条件未满足、暂时不能执行的同一动作等 30 秒再试，其他可执行成长继续。', 'action_cooldown_seconds': '例如 5 秒：同一动作刚执行后至少等 5 秒再检查是否可重复，避免连续提交。', 'push_wait_seconds': '例如 180 秒：挑战开始后至少观察 3 分钟；失败次数也达到下方阈值才转去练级。不是每关固定等待 3 分钟。', 'push_failure_limit': '例如 2 次：主线确认失败两次且观察时长已到，才转去练级。切场中止和塔战失败不算。', 'fallback_death_limit': '仅在游戏没有提供战斗结算统计时使用。例如累计 6 次角色死亡后，再结合观察时长判断是否需要练级。', 'farm_min_seconds': '例如 180 秒：转去练级后至少打 3 分钟，避免刚换装备就立即来回切换。', 'farm_retry_seconds': '例如 600 秒：没有新成长也会在练级 10 分钟后重新挑战主线；仍需满足最短练级时间。', 'farm_level_offset': '例如最高已通关 30、设置 1：从 29 关附近选择免费可重复关卡。失败后会继续降低，收费关卡不会用来练级。', 'farm_switch_gain_percent': '例如 10%：候选练级点的实测经验每分钟至少高 10% 才切换，避免小幅波动导致来回跑。', 'tower_retry_seconds': '例如 300 秒：同层两次挑战至少相隔 5 分钟；开启下方开关时，还需要观察到战力变化。', 'tower_farm_wait_seconds': '例如 180 秒：刚转去练级后的前 3 分钟先练级，之后再评估是否挑战无限塔。设置 0 可取消这段等待。', 'equipment_hold_seconds': '例如 60 秒：已穿上的装备至少保留 1 分钟才考虑替换，避免战斗临时增益导致频繁换装。空槽仍优先补齐。', 'equipment_return_seconds': '例如 300 秒：刚换下的同一件装备，5 分钟内不再穿回，避免两件装备反复互换。', 'equipment_min_gain_percent': '例如 5%：替换已有装备时，游戏原生整套评分至少提高 5%。默认 0 接受正收益；空槽优先补齐。', 'skill_point_reserve': '例如 2：每个角色都留下 2 点不自动使用，其余点数继续学习。默认 0 表示尽量用于成长。', 'recommended_actives': '开启后按职业机制和当前解锁等级调整主动技能；关闭后保留你已装配的组合，只补空槽和升级。', 'allow_active_refund': '开启后可回收不再使用的主动技能点，供新推荐主动和被动使用；关闭后保留原投入。', 'soul_reserve': '例如 1000：购买符文后至少还剩 1000 灵魂。各账号分别计算，不会共用资源。', 'permanent_runes': '开启后允许花水晶购买游戏原生永久符文，仍遵守水晶保留数量；关闭后仅评估灵魂可购买的成长。', 'premium_reserve': '例如 2：购买永久符文后至少留下 2 水晶。想全部自行支配水晶，可关闭上方开关。', 'rune_priority': '成长优先偏向编队、背包、经验和收益；战斗优先偏向攻击与生存；均衡兼顾两者。都先满足游戏原生前置。', 'pet_mode': '自动会在练级时偏向经验收益、推进时偏向战斗。选择保留当前宠物后不会自动切换，已满足条件的宠物仍可解锁。', 'inventory_pressure_percent': '例如 46 格背包、设置 80%：达到 37 格就提高整理优先级，先合成、再存取与回收；不会等到 46 格全满。', 'storage_pressure_percent': '例如两页共 98 格、设置 80%：占用达到 79 格即安排取料合成与回收。只统计已解锁页，按每页接收规则寻找空位。', 'recycle_batch': '例如 12：每次最多分解 12 件已判定淘汰的装备；只剩 3 件符合条件时只处理 3 件。交易、锁定、镶嵌和配方保留物品不作为材料。', 'recycle_normal_tier_gap': '例如当前可用装备是 5 档、设置 1：常规回收可考虑 4 档及更早的普通闲置装备。换装候选和完整合成配方继续保留。', 'recycle_rare_tier_gap': '例如当前 5 档、设置 2：较高品质的常规回收只考虑 3 档及更早装备，给它们更多保留空间。空间紧张回收另受开关与品质上限控制。'}
for parameter in PARAMETERS:
    if parameter["key"] in PARAMETER_HELP:parameter["hint"]=PARAMETER_HELP[parameter["key"]]

DEFAULT_STRATEGY = {p['key']:p['default'] for p in PARAMETERS if p['scope']=='strategy'}
BY_KEY = {(p['scope'],p['key']):p for p in PARAMETERS}

def validate_value(spec,value):
    kind=spec['type']
    if kind=='boolean':
        if not isinstance(value,bool): raise ValueError(spec['label']+'需要开关值')
    elif kind=='number':
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(spec['label']+'需要有效数字')
        if not spec['min']<=value<=spec['max'] or (spec['step']==1 and value!=int(value)):
            raise ValueError(spec['label']+'超出可用范围')
        if spec['step']==1: value=int(value)
    elif value not in [p['value'] for p in spec['options']]:
        raise ValueError(spec['label']+'选项无效')
    return value

def normalize_config(config):
    result=copy.deepcopy(config)
    result['strategy']=copy.deepcopy(DEFAULT_STRATEGY)
    for spec in PARAMETERS:
        source=config if spec['scope']=='root' else config.get('strategy',{})
        try:value=validate_value(spec,source.get(spec['key'],spec['default']))
        except (ValueError,TypeError,AttributeError):value=spec['default']
        target=result if spec['scope']=='root' else result['strategy'];target[spec['key']]=value
    return result

def apply_patch(config,patch):
    if not isinstance(patch,dict):raise ValueError('参数必须是对象')
    result=copy.deepcopy(config)
    for key,value in patch.items():
        if key=='strategy':
            if not isinstance(value,dict):raise ValueError('策略参数必须是对象')
            for name,new in value.items():
                spec=BY_KEY.get(('strategy',name))
                if not spec:raise ValueError('未知策略参数: '+name)
                result.setdefault('strategy',copy.deepcopy(DEFAULT_STRATEGY))[name]=validate_value(spec,new)
        elif ('root',key) in BY_KEY:result[key]=validate_value(BY_KEY[('root',key)],value)
        elif key=='running':
            if not isinstance(value,bool):raise ValueError('运行状态需要开关值')
            result[key]=value
        elif key in ('modules','instances'):
            if not isinstance(value,dict) or any(not isinstance(v,bool) for v in value.values()):raise ValueError('模块与实例状态需要开关值')
            for name,new in value.items():
                if key=='modules' and name not in result[key]:raise ValueError('未知模块: '+name)
                result[key][name]=new
        else:raise ValueError('未知设置: '+key)
    return result

def strategy(config=None):
    return {**DEFAULT_STRATEGY,**((config or {}).get('strategy') or {})}

def public_parameters():
    return {'groups':[dict(id=k,label=v) for k,v in GROUPS],'fields':copy.deepcopy(PARAMETERS)}
