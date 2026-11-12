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
 switch('preserve_open_panels','保留手动打开的背包等面板',True,'general','开启时保留背包、英雄、仓库、魔方和符文窗口，并暂停助手提交操作；手动关闭窗口后自动恢复。关闭后允许无人值守收起这些窗口。'),
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
 switch('recycle_pressure_cleanup','空间紧张时回收普通闲置装备',True,'workshop','背包达到整理阈值或仓库已满时，回收不提升任一角色、未保留且未用于配方的当前档及低档普通装备；可交易、带镶嵌、锁定物品继续保护。'),
 number('recycle_batch','单次回收淘汰装备上限',12,'workshop',1,12,'件'),
 number('recycle_normal_tier_gap','普通装备回收落后档数',1,'workshop',1,10,'档'),
 number('recycle_rare_tier_gap','较高品质装备回收落后档数',2,'workshop',1,10,'档'),
]
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
