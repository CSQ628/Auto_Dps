"""One source of defaults, validation and editable strategy descriptions."""
import copy
import math

GROUPS = [('general','运行与重试'),('growth','主线与练级'),('tower','无限塔'),('equipment','装备策略'),
          ('skills','技能成长'),('runes','符文与预算'),('pets','宠物策略'),('workshop','工坊与仓库')]

def number(key,label,default,group,minimum,maximum,unit='',scope='strategy',step=1,hint=''):
    return dict(key=key,label=label,default=default,group=group,min=minimum,max=maximum,unit=unit,
                scope=scope,type='number',step=step,hint=hint)
def switch(key,label,default,group,hint='',scope='strategy',inverted=False):
    return dict(key=key,label=label,default=default,group=group,scope=scope,type='boolean',hint=hint,inverted=inverted)
def choice(key,label,default,group,options,hint=''):
    return dict(key=key,label=label,default=default,group=group,scope='strategy',type='choice',
                options=[dict(value=v,label=t) for v,t in options],hint=hint)

PARAMETERS = [
 switch('preserve_open_panels','自动关闭背包和成长窗口',False,'general','默认开启，自动收起背包、仓库、英雄、技能树和刻印窗口。关闭后保留窗口，不冲突的开箱与成长继续。拖拽物品、方块留有材料、交易与确认弹窗不会自动收起。',inverted=True),
 switch('pause_on_manual_panels','查看游戏窗口时暂停全部操作',False,'general','默认关闭：例如查看仓库时，技能和符文仍可成长，仓库物品和切场会等待。开启后，查看任一成长窗口都会暂停全部提交，关闭窗口自动恢复。'),
 number('interval','巡检间隔',2.0,'general',1,60,'秒','root',.5,'各实例独立成长巡检；开箱另按约 1 秒轻量检查。'),
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
 number('farm_retry_finish_seconds','主线与练级切换的结算等待',180,'growth',30,600,'秒',hint='重试主线前等练级结算或下一轮开场；已经进入未通关前沿时，返回练级前等本场结算。最长等待此时长，避免战斗或统计停滞；返回练级的超时许可只适用同一场战斗。'),
 number('farm_level_offset','高级图比较间隔',0,'growth',0,20,'关',hint='0 或 1 比较相邻高级图，2 表示每隔一关比较；始终从最高免费已通关图开始，不加入低级地图。'),
 number('farm_candidate_count','当前章节候选关数',10,'growth',1,10,'关',hint='默认覆盖当前章节全部 10 个关卡；候选范围以最高已通关关卡所在章节为界，不会扩展到旧章节。'),
 number('farm_failure_limit','有效失败样本数',2,'growth',1,20,'次',hint='失败次数不会直接触发降图；失败地图需达到此结算数并完成最少观测时长，才能按游戏原生经验收益参与比较。无有效样本达到试打上限后轮测本章其他地图。'),
 switch('adaptive_farming','按实测经验选择练级点',True,'growth','在免费已通关候选中比较；编队战力变化后重新观测，不延长主线重试周期。'),
 number('farm_sample_seconds','每个练级点最少有效观测',90,'growth',30,600,'秒',hint='还需完整战斗结算：通关一次，或失败结算达到失败样本阈值；经验收益取游戏原生角色经验累计。暂停、切场、离线和观测中断不计入。'),
 number('farm_probe_seconds','单图无有效结算的试打上限',240,'growth',60,1800,'秒',hint='同一战力下有效观察达到此时长仍无可比较样本时，轮测本章其他免费图。成长后重新采样，但同一次试打累计最多为此值与最少观测时长较大者的两倍；暂停、离线和切场时间不计入。'),
 number('farm_recheck_seconds','练级实测结果有效期',900,'growth',120,7200,'秒',hint='超时或编队战力变化后重新采样。'),
 number('farm_switch_gain_percent','实测练级点切换收益',10,'growth',0,100,'%',hint='候选比较完成后，经验收益超过此比例才切换，避免反复来回。'),
 number('tower_retry_seconds','同层挑战间隔',300,'tower',30,7200,'秒'),
 switch('tower_require_growth','同层失败后等待战力变化',True,'tower','主线、等级、装备、技能或符文变化后再尝试。'),
 number('equipment_hold_seconds','已占用装备槽保持',60,'equipment',0,1800,'秒'),
 number('equipment_return_seconds','淘汰装备禁止回切',300,'equipment',0,7200,'秒',hint='按淘汰时间应用当前设置。'),
 number('equipment_min_gain_percent','换装最低评分收益',0,'equipment',0,100,'%',step=.1,hint='以同一次原生整套评分比较，空槽优先补齐。'),
 number('skill_point_reserve','每名角色保留技能点',0,'skills',0,100,'点'),
 switch('recommended_actives','使用职业推荐主动组合',True,'skills','关闭后保留已装备组合，仅补空槽并升级。'),
 switch('allow_passive_refund','允许纠正被动天赋分配',True,'skills','从末端逐点撤销偏离职业目标的分支，原生退款确认后重新投入；关闭则保留已有分配。'),
 switch('allow_active_refund','允许重配主动技能点',True,'skills','回收未装配主动与核心主动的超额升级点；所选技能至少保留1级，再与被动统一分配。'),
 number('soul_reserve','灵魂保留预算',0,'runes',0,1000000000000,'','root'),
 switch('permanent_runes','允许水晶投资永久符文',True,'runes','仅用于原生永久符文。','root'),
 number('premium_reserve','水晶保留预算',0,'runes',0,1000000000000,'','root'),
 choice('rune_priority','符文投资偏好','growth','runes',[('growth','成长优先'),('balanced','均衡成长'),('combat','战斗优先')]),
 choice('pet_mode','跟随宠物偏好','auto','pets',[('auto','保留当前，空缺时补齐'),('growth','收益主题外观'),('combat','战斗主题外观'),('keep','完全保留，不自动选择')]),
 number('inventory_pressure_percent','背包整理触发占用',80,'workshop',40,100,'%',hint='联动存仓、合成和扩容优先级。'),
 number('storage_pressure_percent','仓库整理触发占用',80,'workshop',40,100,'%',hint='统计所有已解锁仓库页；达到阈值就安排取料合成与回收，不等完全满仓。'),
 switch('recycle_socketed_equipment','允许回收旧装备及其镶嵌',False,'workshop','仅回收没有任一上阵英雄升级用途、未被配方保留且符合品质和档位规则的装备；镶嵌会随装备消耗，不返还。锁定、交易、登记和未确认装备始终保护。'),
 switch('recycle_pressure_cleanup','空间紧张时回收闲置装备',True,'workshop','先制作、再合成，最后回收不提升任一上阵英雄、未保留且未用于完整配方的当前档及低档装备；可交易、锁定物品始终保护；带镶嵌装备需另行开启上方回收授权。'),
 number('recycle_pressure_max_grade','空间紧张时回收品质上限',4,'workshop',1,4,'级',hint='1=Common（普通）、2=Uncommon、3=Rare（稀有）、4=Unique。默认允许回收到 Unique；5=Epic 及以上不自动分解。只回收无换装价值且未被完整配方保留的装备。'),
 switch('auto_sort_items','物品操作后系统排序',True,'workshop','制作、合成、分解、换装与存取结束后，使用游戏系统排序整理背包和所有已解锁仓库页；保留分页和当前选中页。'),
 number('sort_cooldown_seconds','同一背包或仓库页排序间隔',30,'workshop',5,300,'秒',hint='内容或位置没有变化时不重复排序，整理期间不抢占取料合成。'),
 number('forge_priority_main_weapon','主武器打造优先级',1,'workshop',1,7,'',hint='数字越小越优先；同级按可制作档位和装备需求选择，缺料时继续处理其他可制作部位。'),
 number('forge_priority_sub_weapon','副武器打造优先级',1,'workshop',1,7,'',hint='数字越小越优先；同级按可制作档位和装备需求选择，缺料时继续处理其他可制作部位。'),
 number('forge_priority_helmet','头盔打造优先级',1,'workshop',1,7,'',hint='数字越小越优先；同级按可制作档位和装备需求选择，缺料时继续处理其他可制作部位。'),
 number('forge_priority_armor','护甲打造优先级',1,'workshop',1,7,'',hint='数字越小越优先；同级按可制作档位和装备需求选择，缺料时继续处理其他可制作部位。'),
 number('forge_priority_gloves','手套打造优先级',1,'workshop',1,7,'',hint='数字越小越优先；同级按可制作档位和装备需求选择，缺料时继续处理其他可制作部位。'),
 number('forge_priority_boots','靴子打造优先级',1,'workshop',1,7,'',hint='数字越小越优先；同级按可制作档位和装备需求选择，缺料时继续处理其他可制作部位。'),
 number('forge_priority_accessory','饰品打造优先级',1,'workshop',1,7,'',hint='数字越小越优先；同级按可制作档位和装备需求选择，缺料时继续处理其他可制作部位。'),
 number('recycle_batch','单次回收淘汰装备上限',12,'workshop',1,12,'件'),
 number('recycle_normal_tier_gap','普通装备回收落后档数',1,'workshop',1,10,'档'),
 number('recycle_rare_tier_gap','较高品质装备回收落后档数',2,'workshop',1,10,'档'),
]

# Examples are exposed by the same schema used to validate and save parameters.
PARAMETER_HELP = {'interval': '建议保持 2 秒：控制完整成长巡检的基础间隔，原生扫描负担较高时会自动延长。开箱独立约每秒轻量检查，不必为开箱调低此值。', 'auto_launch': '开启后，主游戏或已记住的沙盒退出时会尝试重新启动。只想管理当前运行的游戏时可关闭；手动指定目录用于主游戏启动。', 'launch_retry_seconds': '例如 120 秒：游戏暂未打开时，两次启动尝试至少相隔 2 分钟，避免反复启动。', 'action_retry_seconds': '例如 30 秒：原生条件未满足、暂时不能执行的同一动作等 30 秒再试，其他可执行成长继续。', 'action_cooldown_seconds': '例如 5 秒：同一动作刚执行后至少等 5 秒再检查是否可重复，避免连续提交。', 'push_wait_seconds': '例如 180 秒：挑战开始后至少观察 3 分钟；失败次数也达到下方阈值才转去练级。不是每关固定等待 3 分钟。', 'push_failure_limit': '例如 2 次：主线确认失败两次且观察时长已到，才转去练级。切场中止和塔战失败不算。', 'fallback_death_limit': '仅在游戏没有提供战斗结算统计时使用。例如累计 6 次角色死亡后，再结合观察时长判断是否需要练级。', 'farm_min_seconds': '例如 180 秒：转去练级后至少打 3 分钟，避免刚换装备就立即来回切换。', 'farm_retry_seconds': '例如 600 秒：没有新成长也会在练级 10 分钟后安排重试主线；仍需满足最短练级时间，并等待本场结算或下一轮开场，最长等待时间由下方参数控制。', 'farm_level_offset': '默认 0，与 1 一样比较相邻高级图；设为 2 则从最高免费图起隔一关取样。仅在最新章节与高级范围内比较，不再为了测试收益返回低级图。', 'farm_switch_gain_percent': '例如 10%：候选练级点的实测经验每分钟至少高 10% 才切换，避免小幅波动导致来回跑。', 'tower_retry_seconds': '例如 300 秒：同层两次挑战至少相隔 5 分钟；开启下方开关时，还需要观察到战力变化。', 'tower_farm_wait_seconds': '例如 180 秒：刚转去练级后的前 3 分钟先练级，之后再评估是否挑战无限塔。设置 0 可取消这段等待。', 'equipment_hold_seconds': '例如 60 秒：已穿上的装备至少保留 1 分钟才考虑替换，避免战斗临时增益导致频繁换装。空槽仍优先补齐。', 'equipment_return_seconds': '例如 300 秒：刚换下的同一件装备，5 分钟内不再穿回，避免两件装备反复互换。', 'equipment_min_gain_percent': '例如 5%：替换已有装备时，游戏原生整套评分至少提高 5%。默认 0 接受正收益；空槽优先补齐。', 'skill_point_reserve': '例如 2：每个角色都留下 2 点不自动使用，其余点数继续学习。默认 0 表示尽量用于成长。', 'recommended_actives': '开启后按职业机制和当前解锁等级调整主动技能；关闭后保留你已装配的组合，只补空槽和升级。', 'allow_active_refund': '开启后回收未装配主动，并将所选核心主动的超额升级点与被动统一重配；核心技能至少保留1级。关闭后保留主动旧投入。', 'soul_reserve': '例如 1000：购买符文后至少还剩 1000 灵魂。各账号分别计算，不会共用资源。', 'permanent_runes': '开启后允许花水晶购买游戏原生永久符文，仍遵守水晶保留数量；关闭后仅评估灵魂可购买的成长。', 'premium_reserve': '默认 0：不预留水晶，满足原生前置即可投资。设为其他值后按该值保留；关闭上方开关可完全禁止水晶消费。', 'rune_priority': '按原生前置最低1级开路，再结合当前等级、容量压力、技能触发、下一点增益和路径成本排序。成长优先偏向经验与收益，战斗优先偏向输出和生存；上阵满级后降低经验优先级。灵魂与灵魂石分别遵守保留量，在线收益优先；离线收益只作最低优先级兜底，在线路线所需离线前置仅投入最低等级。', 'pet_mode': '所有已拥有宠物的加成都同时生效，跟随只改变显示。自动模式保留当前有效跟随，空缺时补齐；旧收益/战斗选项只作固定外观偏好，不随关卡切换。完全保留时不选择跟随，仍可自动解锁。', 'inventory_pressure_percent': '例如 46 格背包、设置 80%：达到 37 格就提高整理优先级，优先制作和取料，再合成与回收；不会等到 46 格全满。', 'storage_pressure_percent': '例如两页共 98 格、设置 80%：占用达到 79 格即安排取料合成与回收。只统计已解锁页，按每页接收规则寻找空位。', 'recycle_batch': '例如 12：这是单次上限，还会按原生方块容量分批；方块只有 9 格时每次最多处理 9 件，剩余下次继续。只剩 3 件符合条件时只处理 3 件。交易、锁定和配方保留物品不作为材料；带镶嵌旧装备按回收授权开关处理。', 'recycle_normal_tier_gap': '例如当前可用装备是 5 档、设置 1：常规回收可考虑 4 档及更早的普通闲置装备。换装候选和完整合成配方继续保留。', 'recycle_rare_tier_gap': '例如当前 5 档、设置 2：较高品质的常规回收只考虑 3 档及更早装备，给它们更多保留空间。空间紧张回收另受开关与品质上限控制。'}
PARAMETER_HELP.update({'farm_level_offset': '例如最高已通关 38，设置 1：从当前章节内的最高免费关开始，绝不跳回旧章节。偏移 2 表示每隔一关取样。', 'farm_candidate_count': '默认 10：覆盖当前章节内可用的所有关卡；按实测经验效率选择，最高已通章节和难度固定，失败降档也不会越界。'})
PARAMETER_HELP.pop('tower_farm_wait_seconds', None)
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
    if config.get('_tower_default_off_schema')!=1:
        result['modules']={**(result.get('modules') or {}),'tower':False}
        result['_tower_default_off_schema']=1
    result['strategy']=copy.deepcopy(DEFAULT_STRATEGY)
    for spec in PARAMETERS:
        source=config if spec['scope']=='root' else config.get('strategy',{})
        try:value=validate_value(spec,source.get(spec['key'],spec['default']))
        except (ValueError,TypeError,AttributeError):value=spec['default']
        if spec['key']=='preserve_open_panels' and config.get('_panel_auto_close_schema')!=1:
            value=False
        schema_version=config.get('_strategy_schema_version',0)
        legacy_strategy=config.get('strategy') or {}
        if spec['scope']=='strategy' and spec['key']=='farm_candidate_count' and (not isinstance(schema_version,int) or schema_version<1):
            if legacy_strategy.get('farm_candidate_count')==5 and legacy_strategy.get('farm_level_offset')==1:
                value=spec['default']
        target=result if spec['scope']=='root' else result['strategy'];target[spec['key']]=value
    result['_panel_auto_close_schema']=1
    result['_strategy_schema_version']=1
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


def high_farm_minimum(snapshot, options):
    frontier = snapshot.get('record', {}).get('maxCleared', 0)
    band = snapshot.get('progression', {}).get('farmBand', {})
    chapter_start = (frontier - 1) // 10 * 10 + 1 if type(frontier) is int and frontier > 0 else 1
    highest = band.get('maxLevel')
    anchor = highest if type(highest) is int and 0 < highest <= frontier else frontier
    if band.get('policy') == 'chapter_exp_efficiency' and type(band.get('minLevel')) is int:
        return max(chapter_start, band['minLevel'])
    minimum = max(chapter_start, anchor - options.get('farm_candidate_count', 5) + 1)
    return max(minimum, band['minLevel']) if type(band.get('minLevel')) is int else minimum
