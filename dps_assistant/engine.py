from concurrent.futures import ThreadPoolExecutor
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import threading
import time
import uuid
import zipfile
from .storage import DATA,atomic_json,load_json,event,recent_events
from .connections import game_executable,live_process,candidates
from .runtime import box_for,Bridge,BridgeStarting,BridgeFailure,BRIDGE_STARTUP_SECONDS,BRIDGE_LISTENER_SECONDS,transport_error,bridge_error_message,discover,launch,game_presence,process_identity_status,process_lifetime_status
from .policy import MODULES,choose,ranked_actions,module_for,progression_signature,progression_baseline,observe_growth,equipment_planning_status,skill_repair_authorized
from .completion import milestones
from .equipment_stability import record_confirmed as record_equipment_stability
from .boxes import box_status,settle_legacy_boxes,apply_box_receipt,box_process_identity,retire_ended_box_batch
from .pause import pause_info,PROTECTION_MESSAGE,automatic_pause_evidence
from .mail import settle_mail
from .combat import observe_combat
from .tower import observe_tower_turn, begin_tower_turn
from .training import observe_experience, observe_farming
from .performance import observe_scan_cost
from .recovery import observe_battle_readiness
from .transitions import paid_entry, stage_arrived, entry_cleared, stage_transition
from .platform_paths import VERSION
from .parameters import DEFAULT_STRATEGY,normalize_config,apply_patch,public_parameters,strategy

DEFAULT={'strategy':copy.deepcopy(DEFAULT_STRATEGY),'running':True,'interval':2.0,'soul_reserve':0,'premium_reserve':0,'permanent_runes':True,'auto_launch':True,'managed_boxes':[],'modules':{k:k!='tower' for k in MODULES},'instances':{}}

class Engine:
    def __init__(self,start=True):
        self.lock=threading.RLock();self.submit_gate=threading.RLock();self.stopping=threading.Event()
        self.config=load_json(DATA/'config.json',copy.deepcopy(DEFAULT))
        try:self.legacy_config_modified=(DATA/'config.json').stat().st_mtime
        except OSError:self.legacy_config_modified=0
        self.config={**copy.deepcopy(DEFAULT),**self.config};self.config['modules']={**DEFAULT['modules'],**self.config.get('modules',{})};self.config=normalize_config(self.config)
        self.preferences=load_json(DATA/'preferences.json',{})
        self.preferences={'noticeAccepted':self.preferences.get('noticeAccepted') is True}
        self.connection=load_json(DATA/'connection.json',{});self.manual_bindings={}
        self.durable=load_json(DATA/'scheduler.json',{});self.runtime_state=load_json(DATA/'runtime-state.json',{});self.instances={};self.bridges={};self.jobs={}
        self.events=recent_events();self.started=time.time();self.pool=ThreadPoolExecutor(max_workers=8,thread_name_prefix='dps-instance')
        self.thread=threading.Thread(target=self.loop,daemon=True)
        atomic_json(DATA/'config.json',self.config)
        self.recover_automatic_pauses()
        if start:self.thread.start()
    def record(self,instance,status,message,**details):
        row={'at':time.time(),'instance':instance,'status':status,'message':message,**details}
        with self.lock:self.events=(self.events+[row])[-200:]
        event(row)
    def save(self):
        with self.lock:atomic_json(DATA/'scheduler.json',self.durable)
    def record_equipment(self,state,action,now):
        record_equipment_stability(state,action)
        character=state.setdefault('equipment_by_character',{}).setdefault(str(action['id']),{'confirmed':0})
        character.update(confirmed=character['confirmed']+1,last_at=now,slot=action['slot'],uid=action['uid'])
        key=str(action['id'])+':'+str(action['slot'])
        holds=state.setdefault('equipment_holds',{});previous=holds.get(key,{})
        retired={uid:expiry for uid,expiry in previous.get('retired',{}).items() if expiry>now}
        if action.get('previousUid'):retired[action['previousUid']]=now+strategy(self.config)['equipment_return_seconds']
        retired=dict(sorted(retired.items(),key=lambda p:p[1],reverse=True)[:16])
        retired_at={uid:at for uid,at in previous.get('retired_at',{}).items() if uid in retired}
        if action.get('previousUid'):retired_at[action['previousUid']]=now
        holds[key]={'uid':action['uid'],'at':now,'retired':retired,'retired_at':retired_at}
    def observe_skill_repair_blocks(self,key,row,state,snapshot):
        blocked={}
        kinds={}
        characters=snapshot.get('characters',[])
        for character in characters:
            repair=character.get('skillPlanning',{}).get('repair') or {}
            if not skill_repair_authorized(self.config,repair):continue
            reason=repair.get('reason')
            if reason=='skill_catalogue_invalid' or reason=='native_refund_blocked' and not repair.get('refund'):
                blocked[str(character['id'])]=reason
                controls=repair.get('controls',{})
                active=repair.get('activeExcess',0)>0 or controls.get('active') and not controls.get('passive')
                kinds[str(character['id'])]='skill_refund' if active else 'passive_refund'
        previous=state.get('skill_repair_blocks',{})
        for character,reason in blocked.items():
            if previous.get(character)!=reason:
                detail='原生暂不允许退款' if reason=='native_refund_blocked' else '技能目录校验未通过'
                self.record(key,'warning','角色 '+character+' 天赋纠错受阻：'+detail+'；继续主线重试与其他成长',
                            identity=row['identity'],action={'kind':kinds[character],'id':int(character)},
                            result={'reason':reason,'automationContinues':True})
        if blocked:state['skill_repair_blocks']=blocked
        else:state.pop('skill_repair_blocks',None)
    def observe_tower_clear(self,key,row,state,snap):
        attempt=state.get('tower_attempt',{});before=attempt.get('cleared_before')
        if before is None or not before<attempt['level']<=snap.get('record',{}).get('towerMaxCleared',-1):return
        level=attempt['level'];state.setdefault('tower_clears',{})[str(level)]={'before':before,'after':snap['record']['towerMaxCleared']}
        state.pop('tower_attempt',None)
        for pending_key,pending in list(state.get('pending_results',{}).items()):
            if pending['action']['kind']=='tower' and pending['action']['level']==level:
                state['pending_results'].pop(pending_key);state.get('uncertain',{}).pop(pending_key,None)
        self.record(key,'confirmed','无限塔第 '+str(level)+' 层已通关',identity=row['identity'],
                    action={'kind':'tower_clear','level':level},result={'source':'native_clear_record','maxCleared':snap['record']['towerMaxCleared']})
        self.save()
    def observe_boss_clear(self,key,row,state,snap):
        attempt=state.get('boss_attempt')
        if not attempt or snap.get('record',{}).get('maxCleared',0)<attempt['level']:return
        held=next((p for p in snap.get('entryTickets',[]) if p['uid']==attempt['ticketUid']),None)
        result={'status':'confirmed','maxCleared':snap['record']['maxCleared'],'ticket':attempt['ticket'],
                'ticketUid':attempt['ticketUid'],'ticketBefore':attempt['ticketBefore'],
                'ticketAfter':(held['count'] if held else 0) if 'entryTickets' in snap else None,'source':'native_clear_record'}
        state.pop('boss_attempt',None);state.setdefault('boss_clears',{})[str(attempt['level'])]=result
        self.record(key,'confirmed','第 '+str(attempt['level'])+' 关Boss已通关，接续下一关',identity=row['identity'],
                    action={'kind':'boss_clear','key':'boss_clear:'+str(attempt['level']),'level':attempt['level']},result=result)
        self.save()
    def settle_pending(self,key,row,state,snap):
        for pending_key,pending in state.get('pending_results',{}).items():
            if paid_entry(pending['action']):
                state.setdefault('entry_uncertainty',{}).setdefault(pending_key,pending)
        for entry_key,entry in list(state.get('entry_uncertainty',{}).items()):
            if stage_arrived(entry['action'],snap) or entry_cleared(entry['action'],snap,entry.get('cleared_before')):
                state['entry_uncertainty'].pop(entry_key)
                state.get('uncertain',{}).pop(entry_key,None)
        for action_key,pending in list(state.get('pending_results',{}).items()):
            action=pending['action'];stage=snap.get('stage',{});kind=action['kind']
            settlement_result=None
            if kind=='mail_claim':
                settlement_result=settle_mail(pending,snap)
                if settlement_result is None:continue
                if settlement_result['status']=='no_change':
                    state['pending_results'].pop(action_key);state['uncertain'].pop(action_key,None)
                    feature=state.setdefault('features',{}).setdefault(kind,{'confirmed':0})
                    feature.update(last_status='no_change',last_at=time.time(),last_reason='native_mail_already_claimed')
                    self.record(key,'no_change','原生回执确认邮件已领取，解除等待',identity=row['identity'],action=action,result=settlement_result)
                    continue
            confirmed=(kind=='tower' and stage.get('category')==1 and stage.get('level')==action['level'] and stage.get('running')) or (kind in ('tower_return','progress') and action.get('level') and stage.get('category')==0 and stage.get('level')==action['level'] and stage.get('running') and (kind!='progress' or action.get('phase')=='travel' or stage.get('repeat')==action.get('repeat')))
            if kind=='mail_claim':confirmed=settlement_result is not None
            if stage_transition(action):
                confirmed=stage_arrived(action,snap) or entry_cleared(action,snap,pending.get('cleared_before'))
            if kind=='equipment':
                character=next((c for c in snap.get('characters',[]) if c['id']==action['id']),{})
                confirmed=any(p.get('slot')==action['slot'] and p['uid']==action['uid'] for p in character.get('equipment',[]))
                if (not confirmed and action.get('equipmentStability')
                        and time.time()-pending['at']>=max(30,strategy(self.config)['action_retry_seconds'])):
                    # Equipment swaps consume no currency. Release an unconfirmed request
                    # and replan from a fresh native scan; never replay its old context.
                    state['pending_results'].pop(action_key);state.get('uncertain',{}).pop(action_key,None)
                    self.record(key,'waiting','换装尚未确认，按当前原生装备重新评估',identity=row['identity'],
                                action=action,result={'status':'waiting','reason':'equipment_unconfirmed_replan'})
                    continue
            if kind=='battle_recover':
                ready=snap.get('battleReadiness',{})
                confirmed=stage_arrived(action,snap)
                if not confirmed and time.time()-pending['at']>=45:
                    state['pending_results'].pop(action_key);state['uncertain'].pop(action_key,None)
                    self.record(key,'waiting','战场恢复尚未确认，等待下一次原生恢复尝试',identity=row['identity'],action=action)
            readiness=snap.get('battleReadiness',{})
            if not stage_transition(action) and kind=='progress' and readiness.get('known') and (
                    not readiness.get('charactersInitialized') or readiness.get('missing') or stage.get('alivePlayers',0)<=0):confirmed=False
            transition=stage_transition(action) and kind!='battle_recover'
            if transition and not confirmed and time.time()-pending['at']>=strategy(self.config)['stage_transition_wait_seconds']:
                state['pending_results'].pop(action_key);state['uncertain'].pop(action_key,None)
                # A paid entry with an unknown result must never be automatically replayed.
                state.setdefault('cooldowns',{})[action_key]=time.time()+strategy(self.config)['stage_transition_wait_seconds']
                if paid_entry(action):
                    state.setdefault('uncertain',{})[action_key]=time.time()
                elif kind=='tower' and stage.get('category')==0:
                    state.pop('tower_turn',None);state.pop('tower_attempt',None)
                self.record(key,'waiting','切场确认超时，保留原生状态并停止重复提交',identity=row['identity'],action=action)
            if not confirmed:continue
            state['pending_results'].pop(action_key);state['uncertain'].pop(action_key,None)
            state['confirmed']=state.get('confirmed',0)+1;row['confirmed']=state['confirmed']
            feature=state.setdefault('features',{}).setdefault(kind,{'confirmed':0})
            feature.update(confirmed=feature.get('confirmed',0)+1,last_status='confirmed',last_at=time.time(),last_reason=None)
            if kind=='equipment':self.record_equipment(state,action,time.time())
            self.record(key,'confirmed',action['label'],identity=row['identity'],action=action,result=settlement_result or {'status':'confirmed','observed_stage':stage})
        row['feature_evidence']=copy.deepcopy(state.get('features',{}))
        row['equipment_evidence']=copy.deepcopy(state.get('equipment_by_character',{}))
        mails=[p for p in state.get('pending_results',{}).values() if p.get('action',{}).get('kind')=='mail_claim']
        row['mail_settlement']={'pending':len(mails),'remaining':sum(len(set(p['action'].get('ids',[]))-set(p.get('mail_results',{}))) for p in mails),
                                'since':min((p['at'] for p in mails),default=None)}
    def update(self,value):
        with self.submit_gate,self.lock:
            previous=self.config
            updated=apply_patch(self.config,value)
            for identity,enabled in value.get('instances',{}).items():
                updated.setdefault('_instance_run_intent',{})[identity]={'enabled':enabled,'at':time.time()}
            atomic_json(DATA/'config.json',updated);self.config=updated
            changed=False
            for identity,enabled in value.get('instances',{}).items():
                state=self.durable.setdefault(identity,{'cooldowns':{},'uncertain':{},'last_equipment':{}})
                if enabled:
                    was_paused=previous.get('instances',{}).get(identity,True) is False
                    changed=state.pop('pause',None) is not None or changed
                    if was_paused:
                        key=next((r['id'] for r in self.instances.values() if r.get('identity')==identity),'system')
                        self.record(key,'confirmed','已恢复当前实例，继续核对原生执行条件',identity=identity)
                else:
                    state['pause']={'reason':'manual_instance_pause','at':time.time()};changed=True
            if changed:self.save()
        return self.config
    def recover_automatic_pauses(self):
        with self.submit_gate,self.lock:
            if self.config.get('_pause_recovery_schema')==1:return
            recover=automatic_pause_evidence(self.config,self.durable,self.events,self.legacy_config_modified)
            updated=copy.deepcopy(self.config);updated['_pause_recovery_schema']=1
            for identity in recover:updated['instances'][identity]=True
            try:atomic_json(DATA/'config.json',updated)
            except OSError:
                if not getattr(self,'pause_migration_warning',False):
                    self.record('system','warning','旧版自动暂停恢复暂未保存，将继续自动重试')
                    self.pause_migration_warning=True
                return
            self.config=updated
            for identity,source in recover.items():
                state=self.durable.setdefault(identity,{})
                state.pop('pause',None)
                self.record('system','confirmed','已自动恢复旧版保护误停的实例',identity=identity,
                            result={'reason':'automatic_pause_recovered','source':source})
            if recover:self.save()

    def discovered_processes(self):
        """Keep known bindings on transient discovery/permission failures, never PID alone."""
        try:found=discover()
        except (OSError,RuntimeError):found=[]
        found_by_pid={str(p['pid']):p for p in found}
        with self.lock:
            manual=dict(self.manual_bindings)
            known={key:dict(bridge.identity) for key,bridge in self.bridges.items()}
            for key,row in self.instances.items():
                if all(k in row for k in ('pid','created','exe','box')):known.setdefault(key,{k:row[k] for k in ('pid','created','exe','box')})
            known.update(manual)
        for key,binding in known.items():
            detected=found_by_pid.get(key)
            if detected:
                if key in manual and abs(detected['created']-binding['created'])>.001:
                    with self.lock:self.manual_bindings.pop(key,None)
                continue
            status=process_identity_status(binding)
            if status=='absent':
                if key in manual:
                    with self.lock:self.manual_bindings.pop(key,None)
                continue
            found_by_pid[key]={**binding,'identity_waiting':status=='unknown'}
        return list(found_by_pid.values())

    def warn_for_trade(self,key,identity,action,result):
        # Post-action observations never change a user's run/pause switch.
        self.record(key,'warning','警告：检测到可交易物品数量或交易属性变化，自动化继续运行。',
                    identity=identity,action={'kind':action['kind']},
                    result={'reason':'tradable_state_changed','changed_count':len(result['tradeChanged'])})
    def connection_state(self):
        found=discover()
        with self.lock:return candidates(found,self.connection.get('game_path',''))
    def bind(self,value):
        if not isinstance(value,dict):raise ValueError('连接请求需要是对象')
        if set(value)=={'path'}:
            executable=game_executable(value['path'])
            with self.submit_gate,self.lock:
                connection={**self.connection,'game_path':executable}
                atomic_json(DATA/'connection.json',connection);self.connection=connection
            return {'status':'saved','path':executable,'message':'游戏目录已保存。自动启动使用此目录；运行中的游戏会继续自动接入。'}
        if set(value) not in ({'pid'},{'pid','created'}):raise ValueError('请选择一个运行中的实例，或填写游戏目录')
        identity=live_process(value['pid'],value.get('created'));identity['box']=box_for(identity['pid'])
        with self.submit_gate,self.lock:
            existing=self.instances.get(str(identity['pid']))
            if existing and existing['created']==identity['created']:
                if existing.get('identity'):
                    self.update({'instances':{existing['identity']:True}})
                existing['binding']='manual'
            self.manual_bindings[str(identity['pid'])]=identity
        return {'status':'connecting','pid':identity['pid'],'created':identity['created'],
                'message':'已绑定此游戏进程，正在读取账号与原生状态。同一账号仍只允许一个控制实例。'}
    def save_runtime(self):
        with self.lock:atomic_json(DATA/'runtime-state.json',self.runtime_state)
    def runtime_enabled(self,box,identity=None):
        identity=identity or self.runtime_state.get(box,{}).get('identity')
        if identity:return not pause_info(self.config,identity,self.durable.get(identity,{}))
        # Before login, preserve any explicitly paused account in this environment.
        prefix=(box or 'host')+':'
        return all(enabled for key,enabled in self.config['instances'].items() if key.startswith(prefix))
    def launch_missing(self,boxes,remembered,now=None):
        now=time.time() if now is None else now
        with self.submit_gate,self.lock:
            if not self.config['auto_launch'] or not self.config['running'] or self.stopping.is_set():return
            for box in ['',*remembered]:
                if box in boxes or not self.runtime_enabled(box):continue
                entry=self.runtime_state.setdefault(box,{})
                maintenance=entry.get('maintenance',{})
                retry=strategy(self.config)['launch_retry_seconds']
                if now-entry.get('last_launch',0)<retry or maintenance.get('retry_at',0)>now:continue
                presence=game_presence(box)
                if presence!='absent':
                    if entry.get('launch_wait')!=presence:
                        entry['launch_wait']=presence;self.save_runtime()
                        self.record('system','waiting','游戏仍在运行，等待重新接入' if presence=='present' else '暂时无法确认游戏是否退出，等待重新检查')
                    continue
                entry.pop('launch_wait',None)
                # Reserve before starting Steam/Sandboxie; restart or lost reply cannot duplicate it.
                entry['last_launch']=now
                if maintenance.get('active'):maintenance['retry_at']=now+max(300,retry)
                self.save_runtime()
                try:
                    if launch(box,self.connection.get('game_path')) is not None:self.record('system','submitted','启动 DPS · '+(box or '主实例'))
                except Exception as error:self.record('system','warning','自动启动暂未完成，将继续重试：'+str(error))
    def observe_runtime(self,bridge,row,scan):
        native=scan.get('runtime')
        if not native:return False # Compatibility with older read-only scan fixtures.
        box=bridge.identity['box'];session=str(bridge.identity['pid'])+':'+str(bridge.identity['created']);now=time.time()
        with self.lock:
            entry=self.runtime_state.setdefault(box,{})
            maintenance=native.get('maintenance',{})
            if maintenance.get('active') is True:
                hold=entry.setdefault('maintenance',{'active':True,'since':now,'attempts':0})
                if hold.get('session')!=session:
                    attempts=min(4,hold.get('attempts',0)+1)
                    delay=max(strategy(self.config)['launch_retry_seconds'],min(1800,300*2**(attempts-1)))
                    hold.update(active=True,attempts=attempts,session=session,retry_at=now+delay)
                    self.save_runtime();self.record(row['id'],'waiting','服务器维护中，暂停成长并按退避间隔重连')
            hold=entry.get('maintenance',{})
            connection=(scan.get('snapshot') or {}).get('connection',{})
            if hold and maintenance.get('known') is True and not maintenance.get('active') and native.get('ready') and connection.get('online') is True and connection.get('loggedIn') is True:
                entry.pop('maintenance');row.pop('maintenance',None);self.save_runtime()
                self.record(row['id'],'confirmed','服务器维护已解除，登录与存档就绪，接续自动成长')
                hold={}
            if not hold and native.get('ready'):return False
            enabled=self.config['running'] and self.runtime_enabled(box,row.get('identity'))
            message='服务器维护中，等待下一次自动重连' if hold else '等待游戏登录与存档加载'
            row.update(status=('maintenance' if hold else 'connecting') if enabled else 'paused',snapshot=None,actions=[],error=None,issues=[message],last_seen=now)
            for key in ('growth','combat_analysis','experience','farming','battle_recovery','milestones','pending_transitions'):row.pop(key,None)
            if hold:row['maintenance']={k:hold.get(k) for k in ('active','since','attempts','retry_at')}
        with self.submit_gate:
            with self.lock:
                should_exit=(hold and maintenance.get('active') is True and maintenance.get('canExit') is True and
                    self.config['running'] and self.runtime_enabled(box,row.get('identity')) and
                    self.config['modules'].get('ui_cleanup') and not self.stopping.is_set() and hold.get('exit_session')!=session)
                if should_exit:hold.update(exit_session=session,exit_at=now);self.save_runtime()
            if should_exit:
                try:
                    result=bridge.call('execute',{'kind':'maintenance_exit','strategy':self.bridge_options()})
                    self.record(row['id'],result['status'],'按游戏维护提示完成原生退出',action={'kind':'maintenance_exit'},result=result)
                except Exception:
                    # Exiting the game can destroy the bridge before its reply arrives.
                    self.record(row['id'],'waiting','维护退出已提交，等待进程结束；不重复确认')
        return True
    def loop(self):
        while not self.stopping.is_set():
            try:
                self.recover_automatic_pauses()
                found=self.discovered_processes();live={str(p['pid']) for p in found}
                boxes={p['box'] for p in found}
                remembered=sorted(set(self.config['managed_boxes']) | {b for b in boxes if b})
                if remembered!=self.config['managed_boxes']:
                    with self.lock:self.config['managed_boxes']=remembered;atomic_json(DATA/'config.json',self.config)
                self.launch_missing(boxes,remembered)
                for identity in found:
                    key=str(identity['pid'])
                    existing=self.bridges.get(key)
                    if existing and existing.identity['created']!=identity['created']:
                        if key in self.jobs and not self.jobs[key].done():continue
                        # Do not reuse any job, session or snapshot from the old process lifetime.
                        existing.close();self.bridges.pop(key,None);self.instances.pop(key,None)
                        if key in self.jobs and not self.jobs[key].done():continue
                    with self.lock:
                        row=self.instances.setdefault(key,{'id':key,**identity,'name':'DPS · '+(identity['box'] or '主实例'),'status':'connecting','snapshot':None,'actions':[],'confirmed':0})
                    if key in self.manual_bindings:row['binding']='manual'
                    if identity.get('identity_waiting'):
                        row.update(status='recovering',actions=[],issues=['暂时无法核验进程，保留连接并自动重试'])
                        continue
                    # Let Unity and Steam finish initial loading before attaching a native bridge.
                    if time.time()-identity['created']<15:continue
                    if key not in self.bridges:
                        if time.time()<row.get('bridge_retry_at',0):continue
                        try:self.bridges[key]=Bridge(identity)
                        except Exception as error:
                            row['bridge_failures']=min(5,row.get('bridge_failures',0)+1)
                            row['bridge_retry_at']=time.time()+min(30,2**row['bridge_failures'])
                            row.update(status='recovering',actions=[],error=bridge_error_message(error))
                            self.record(key,'warning','连接暂未建立，将自动重试')
                            continue
                        row['status']='connecting'
                        row.pop('native_next_scan_at',None)
                    if key not in self.jobs or self.jobs[key].done():self.jobs[key]=self.pool.submit(self.tick,key)
                for key in list(self.bridges):
                    if key not in live:
                        self.bridges.pop(key).close()
                        with self.lock:self.instances[key]['status']='stopped'
                # Short-lived Steam/Unity launchers may disappear before receiving a bridge.
                with self.lock:
                    for key,row in self.instances.items():
                        if key not in live:row.update(status='stopped',actions=[])
            except Exception as e:self.record('system','warning','自动连接暂未完成，将继续重试：'+str(e))
            self.stopping.wait(min(1.0,self.config['interval']))
    def observe_box_receipt_store(self,key,row,result):
        persistence=result.get('receiptPersistence')
        if persistence=='unavailable':
            if not row.get('box_receipt_warning'):
                self.record(key,'warning','开箱回执暂未写入持久存储，保留现有预约并继续核对',
                            result={'reason':'box_receipt_store_unavailable'})
            row['box_receipt_warning']=True
        elif persistence=='available':row.pop('box_receipt_warning',None)
    def tick_boxes(self,key):
        """One bounded loot batch per second, independent of expensive growth scans."""
        row=self.instances[key];bridge=self.bridges[key];now=time.time()
        if not row.get('box_fast_supported') or now<row.get('next_box_scan_at',0):return
        identity=row.get('identity');state=self.durable.get(identity)
        if not state or row.get('status') not in ('running','paused') or not isinstance(row.get('snapshot'),dict):return
        if state.get('backup',{}).get('status')!='created' or not Path(state['backup']['path']).is_file():return
        with self.submit_gate:
            if self.stopping.is_set() or not self.config['running'] or not self.config['modules'].get('box') or pause_info(self.config,identity,state):return
            if any(i is not row and i.get('account')==row.get('account') and i.get('status') not in ('stopped','duplicate') for i in self.instances.values()):return
            row['next_box_scan_at']=now+1
            pending=state.get('box_pending',{})
            try:
                scan=bridge.call('boxscan',{'strategy':self.bridge_options(),'requestId':pending.get('request_id')})
                self.observe_box_receipt_store(key,row,scan)
                snap=scan.get('snapshot')
                if not snap:
                    row['native_next_scan_at']=0
                    return
                if snap['account']!=row['account']:raise RuntimeError('account_changed')
                row['box_performance']={'scanMs':scan.get('scanMs'),'at':time.time(),'interval':1}
                # Do not freshen the full snapshot's sampling clock with partial data.
                row['snapshot']['boxes']=snap['boxes'];row['snapshot']['inventory']=snap['inventory']
                settled=apply_box_receipt(state,scan.get('receipt'),time.time())
                if settled:
                    row['confirmed']=state.get('confirmed',0);row['feature_evidence']=copy.deepcopy(state.get('features',{}))
                    self.save()
                    if settled['status']!='pending':
                        self.record(key,settled['status'],'连续开箱结果已确认 · '+str(settled['opened'])+' 个',identity=identity,
                                    action={'kind':'box','key':pending['request_id']},result=scan['receipt'])
                # A dead game's request cannot execute in this new lifetime. Keep
                # its outcome unknown, but do not block the current native queue.
                before_retirement={k:state[k] for k in ('box_pending','box_unresolved','box_unresolved_count') if k in state}
                archived=retire_ended_box_batch(state,bridge.identity,time.time(),process_lifetime_status)
                if archived:
                    try:self.save()
                    except Exception:
                        for name in ('box_pending','box_unresolved','box_unresolved_count'):state.pop(name,None)
                        state.update(before_retirement)
                        raise
                    self.record(key,'warning','旧游戏进程已结束，保留未确认开箱记录，接续当前游戏宝箱',identity=identity,
                                result={'reason':'box_origin_process_ended','credited':archived.get('credited',0),
                                        'request_id':archived['request_id']})
                settle_legacy_boxes(state,snap.get('record',{}).get('boxes'))
                ready=ranked_actions(scan,self.config,state)
                row['box_status']=box_status(scan,self.config,state,ready,time.time())
                if state.get('box_pending') or state.get('box_retry_at',0)>time.time() or not ready:return
                request_id='box-batch:'+uuid.uuid4().hex
                state['box_pending']={'request_id':request_id,'at':time.time(),'record_before':snap['record']['boxes'],'credited':0,
                                      'process':box_process_identity(bridge.identity)}
                try:self.save() # Native has not been called until this commit succeeds.
                except Exception:
                    state.pop('box_pending',None) # This request is proven unsent.
                    raise
                result=bridge.call('openboxes',{'requestId':request_id,'account':snap['account'],'strategy':self.bridge_options()})
                self.observe_box_receipt_store(key,row,result)
                settled=apply_box_receipt(state,result,time.time())
                row['confirmed']=state.get('confirmed',0);row['feature_evidence']=copy.deepcopy(state.get('features',{}))
                self.save()
                if settled:
                    self.record(key,settled['status'],'连续开箱 · 已确认 '+str(settled['opened'])+' 个',identity=identity,
                                action={'kind':'box','key':request_id},result=result)
                if state.get('box_pending'):row['box_status']={**row['box_status'],'reason':'box_result_unconfirmed'}
            except Exception as error:
                # Never replay openboxes after transport failure. A receipt on the
                # same game can settle it; only a proven ended origin may retire it.
                row['next_box_scan_at']=time.time()+5
                row['box_status']={**row.get('box_status',{}),'reason':'box_result_unconfirmed' if state.get('box_pending') else 'native_box_waiting'}
                if row.get('box_error')!=str(error):self.record(key,'waiting','开箱等待原生确认或连接恢复',reason=str(error));row['box_error']=str(error)
    def prepare_submission(self,state,action,snapshot,session,now):
        """Commit all pre-native bookkeeping together; a failed commit is unsent.

        The caller holds submit_gate. Never use this rollback after bridge.call:
        a lost native reply still represents a potentially executed operation.
        """
        fields=('uncertain','entry_uncertainty','pending_results','boss_attempt',
                'battle_recovery','tower_turn','tower_attempt')
        previous={name:copy.deepcopy(state[name]) for name in fields if name in state}
        try:
            state.setdefault('uncertain',{})[action['key']]=now
            if stage_transition(action):
                entry={'action':action,'at':now,'cleared_before':snapshot.get('record',{}).get(
                    'towerMaxCleared' if action['kind']=='tower' else 'maxCleared')}
                if paid_entry(action):state.setdefault('entry_uncertainty',{})[action['key']]=entry
                state.setdefault('pending_results',{})[action['key']]=entry
            if action['kind']=='equipment':
                state.setdefault('pending_results',{})[action['key']]={'action':action,'at':now}
            if action['kind']=='mail_claim':
                claims=snapshot.get('mail',{}).get('claims',{})
                state.setdefault('pending_results',{})[action['key']]={'action':action,'at':now,
                    'mail_observer':claims.get('observer'),'mail_sequence':claims.get('sequence',0)}
            if action['kind']=='progress' and action.get('mode')=='boss':
                state['boss_attempt']={k:action[k] for k in ('level','ticket','ticketUid','ticketBefore')}
            if action['kind']=='battle_recover':
                recovery=state['battle_recovery'];recovery.update(last_attempt=now,attempts=recovery.get('attempts',0)+1)
            if action['kind']=='tower':
                begin_tower_turn(snapshot,state,session,now)
                state['tower_attempt']={'level':action['level'],'max_stage':snapshot['record']['maxStage'],
                    'cleared_before':snapshot['record'].get('towerMaxCleared'),
                    **progression_baseline(snapshot),'at':now}
            self.save()
        except Exception:
            for name in fields:state.pop(name,None)
            state.update(previous)
            raise

    def tick(self,key):
        bridge=self.bridges[key];row=self.instances[key]
        try:
            self.tick_boxes(key)
            if time.time()<row.get('native_next_scan_at',0):return
            scan=bridge.call('opportunities',self.bridge_options())
            row['box_fast_supported']=scan.get('boxFastPath')==1
            if scan.get('bridgeSourceHash'):row['bridge_source_hash']=scan['bridgeSourceHash']
            if self.observe_runtime(bridge,row,scan):return
            snap=scan['snapshot']
            observe_scan_cost(row,snap.get('bridgePerformance'),self.config['interval'],time.time())
            identity=(bridge.identity['box'] or 'host')+':'+snap['account']
            with self.lock:
                entry=self.runtime_state.setdefault(bridge.identity['box'],{})
                if entry.get('identity')!=identity:entry['identity']=identity;self.save_runtime()
                state=self.durable.setdefault(identity,{'cooldowns':{},'uncertain':{},'last_equipment':{}})
                row.update(snapshot=snap,actions=scan['actions'][:24],issues=scan['issues'],last_seen=time.time(),account=snap['account'],identity=identity,status='running' if self.config['running'] else 'paused',error=None,confirmed=state.get('confirmed',0),feature_evidence=copy.deepcopy(state.get('features',{})))
                row['bridge_health']=getattr(bridge,'last_health',None)
                row.pop('bridge_retry_at',None);row.pop('bridge_failures',None)
                recovered_error=row.pop('last_error',None)
                if recovered_error:self.record(key,'confirmed','连接已自动恢复，接续自动化',identity=identity,result={'reason':'connection_recovered'})
                if any(i is not row and i.get('account')==snap['account'] and i.get('status') not in ('stopped','duplicate') for i in self.instances.values()):
                    row.update(status='duplicate',issues=['同一账号已有控制实例，当前实例仅观察']);return
            if state.get('backup',{}).get('status')!='created' or state['backup'].get('version')!=2 or not Path(state['backup']['path']).is_file():
                backup=bridge.call('backup')
                data=base64.b64decode(backup.pop('zip'))
                if backup['account']!=snap['account'] or hashlib.sha256(data).hexdigest()!=backup['sha256']:raise RuntimeError('backup_identity_or_digest_mismatch')
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if not archive.namelist() or archive.testzip():raise RuntimeError('backup_archive_corrupt')
                destination=DATA/'backups'/('save-'+identity.replace(':','-')+'-'+time.strftime('%Y%m%d-%H%M%S')+'.zip')
                destination.parent.mkdir(parents=True,exist_ok=True);temporary=destination.with_suffix('.tmp');temporary.write_bytes(data);temporary.replace(destination)
                state['backup']={'status':'created','version':2,'path':str(destination),**backup};self.save()
                self.record(key,'confirmed','已创建账号存档备份',identity=identity,files=backup['files'])
            if pause_info(self.config,identity,state):row['status']='paused';return
            # Older versions reserved free travel only by key. Rebuild its observation
            # record so an old lost response cannot keep this account stuck forever.
            for candidate in scan['actions']:
                reserved=state.get('uncertain',{}).get(candidate['key'])
                if reserved is not None and (stage_transition(candidate) or candidate['kind']=='mail_claim'):
                    state.setdefault('pending_results',{}).setdefault(candidate['key'],
                        {'action':candidate,'at':reserved,'cleared_before':None})
            self.observe_boss_clear(key,row,state,snap)
            self.observe_tower_clear(key,row,state,snap)
            self.settle_pending(key,row,state,snap)
            state.setdefault('scheduling_started',time.time())
            row['combat_analysis']=observe_combat(snap,state,str(bridge.identity['pid'])+':'+str(bridge.identity['created']),time.time())
            self.observe_skill_repair_blocks(key,row,state,snap)
            row['growth']=observe_growth(snap,state,time.time(),self.config)
            session=str(bridge.identity['pid'])+':'+str(bridge.identity['created'])
            row['tower_turn']=observe_tower_turn(snap,state,session,time.time())
            # Adaptive scan spacing is part of the sampling clock, per instance.
            observation_config={**self.config,'interval':row.get('effective_scan_interval',self.config['interval'])}
            row['experience']=observe_experience(snap,state,session,time.time(),observation_config)
            row['farming']=observe_farming(snap,state,session,time.time(),observation_config)
            row['battle_recovery']=observe_battle_readiness(snap,state,session,time.time())
            row['milestones']=milestones(snap,state.get('features',{}),self.config)
            transitions={**state.get('entry_uncertainty',{}),**state.get('pending_results',{})}
            row['pending_transitions']=[{'kind':p['action']['kind'],'mode':p['action'].get('mode'),
                'level':p['action'].get('level'),'difficulty':p['action'].get('difficulty',0),'since':p['at']}
                for p in transitions.values() if stage_transition(p['action'])]
            # A fresh native scan invalidates completed state-specific keys; elapsed time alone never proves failure.
            current_keys={a['key'] for a in scan['actions']}
            settle_legacy_boxes(state,snap.get('record',{}).get('boxes'))
            for old_key in list(state['uncertain']):
                if old_key.startswith('box:'):continue
                if old_key not in current_keys and old_key not in state.get('entry_uncertainty',{}) and state.get('pending_results',{}).get(old_key,{}).get('action',{}).get('kind')!='mail_claim':state['uncertain'].pop(old_key)
            # Boxes have their own bounded lane; the normal turn remains available
            # for skills, runes, equipment and workshop work even with endless loot.
            schedule_scan={**scan,'actions':[a for a in scan['actions'] if a['kind']!='box']} if row['box_fast_supported'] else scan
            row['equipment_stability']=equipment_planning_status(schedule_scan,state)
            ranked=ranked_actions(schedule_scan,self.config,state)
            row['actions']=ranked[:24]
            row['box_status']=box_status(scan,self.config,state,ranked,time.time())
            with self.submit_gate:
                action=choose(schedule_scan,self.config,state)
                if action is None or self.stopping.is_set() or pause_info(self.config,identity,state):
                    self.save();return
                command={**action,'account':snap['account'],'soulReserve':self.config['soul_reserve'],'premiumReserve':self.config['premium_reserve'],'permanentRunes':self.config['permanent_runes'],'strategy':self.bridge_options()}
                self.prepare_submission(state,action,snap,session,time.time())
                result=bridge.call('execute',command)
                if result.get('tradeChanged'):self.warn_for_trade(key,identity,action,result)
            observe_scan_cost(row,result.get('bridgePerformance'),self.config['interval'],time.time())
            status=result['status'];now=time.time()
            if action['kind']=='tower' and status in ('rejected','no_change','waiting','stale'):
                state.pop('tower_turn',None)
            if stage_transition(action) and status in ('confirmed','rejected','no_change','waiting','stale'):
                state.get('entry_uncertainty',{}).pop(action['key'],None)
                state.get('pending_results',{}).pop(action['key'],None)
            if action['kind'] in ('mail_claim','equipment') and status in ('confirmed','rejected','no_change','waiting','stale'):
                state.get('pending_results',{}).pop(action['key'],None)
            if action['kind']=='progress' and action.get('mode')=='boss' and status not in ('pending','confirmed'):
                state.pop('boss_attempt',None)
            state['uncertain'].pop(action['key'],None)
            state['cooldowns'][action['key']]=now+(strategy(self.config)['action_retry_seconds'] if status in ('rejected','no_change','waiting') else strategy(self.config)['action_cooldown_seconds'])
            if action['kind']=='equipment':state['last_equipment'][str(action['id'])]=now
            state.setdefault('last_module',{})[module_for(action['kind'])]=now
            if status=='pending':state['uncertain'][action['key']]=now
            if status=='pending' and action['kind'] in ('tower','tower_return','equipment','progress','battle_recover'):
                state.setdefault('pending_results',{}).setdefault(action['key'],{'action':action,'at':now})
            if status=='confirmed':state['confirmed']=state.get('confirmed',0)+1;row['confirmed']=state['confirmed']
            if status=='confirmed' and action['kind']=='equipment':self.record_equipment(state,action,now)
            feature=state.setdefault('features',{}).setdefault(action['kind'],{'confirmed':0})
            feature.update(last_status=status,last_at=now,last_reason=result.get('reason'))
            reason=result.get('reason')
            feature['same_waits']=feature.get('same_waits',0)+1 if status=='waiting' and feature.get('wait_reason')==reason else 1 if status=='waiting' else 0
            feature['wait_reason']=reason
            if feature['same_waits']>=3:
                state.setdefault('kind_cooldowns',{})[action['kind']]=now+60
                feature['same_waits']=0
            if status=='confirmed':feature['confirmed']+=1
            row['feature_evidence']=copy.deepcopy(state['features'])
            row['equipment_evidence']=copy.deepcopy(state.get('equipment_by_character',{}))
            self.save();self.record(key,status,action['label'],identity=identity,box=bridge.identity['box'],action=action,result=result)
        except BridgeStarting as e:
            # Readiness is a normal startup phase, not a failed native action.
            with self.lock:row.update(status='connecting',error=None,actions=[],issues=[str(e)],bridge_health=e.health)
        except Exception as e:
            hold=self.runtime_state.get(bridge.identity['box'],{}).get('maintenance',{})
            session=str(bridge.identity['pid'])+':'+str(bridge.identity['created'])
            if hold.get('exit_session')==session and (time.time()-hold.get('exit_at',0)<60 or hasattr(bridge,'valid') and not bridge.valid()):
                # Native shutdown after maintenance is expected; discovery removes the dead bridge.
                with self.lock:row.update(status='maintenance' if self.config['running'] and self.runtime_enabled(bridge.identity['box'],row.get('identity')) else 'paused',error=None,actions=[],snapshot=None)
                return
            health=e.health if isinstance(e,BridgeFailure) else None
            if health is None and hasattr(bridge,'health'):
                try:health=bridge.health(timeout=.5)
                except Exception:pass
            age=time.time()-bridge.started
            if health and health.get('phase')=='starting' and age<BRIDGE_STARTUP_SECONDS:
                with self.lock:row.update(status='connecting',error=None,actions=[],issues=[str(BridgeStarting(health))],bridge_health=health)
                return
            message=bridge_error_message(e)
            with self.lock:row.update(status='recovering',error=message,actions=[],bridge_health=health)
            # Observation failure is not evidence that the bridge/game stopped.
            if row.get('last_error')!=message:self.record(key,'warning',message+'；保持开关，自动重试');row['last_error']=message
            # Sandboxie's launcher may exit while its authenticated helper is still alive.
            healthy=health and health.get('phase')=='ready'
            failed=health and (health.get('phase')=='failed' or health.get('phase')=='starting' and age>=BRIDGE_STARTUP_SECONDS)
            if failed or not healthy and (bridge.process.poll() is not None or transport_error(e) and age>=BRIDGE_LISTENER_SECONDS):
                with self.lock:
                    if self.bridges.get(key) is bridge:
                        self.bridges.pop(key,None);bridge.close()
                        row['bridge_failures']=min(5,row.get('bridge_failures',0)+1)
                        row['bridge_retry_at']=time.time()+min(30,2**row['bridge_failures'])
    def bridge_options(self):
        return {**strategy(self.config),'modules':dict(self.config['modules']),
                'budget':{k:self.config[k] for k in ('soul_reserve','premium_reserve','permanent_runes')}}
    def accept_notice(self):
        with self.lock:
            updated={'noticeAccepted':True};atomic_json(DATA/'preferences.json',updated);self.preferences=updated
        return copy.deepcopy(updated)
    def maintenance_waiting(self):
        result=[]
        for box,entry in self.runtime_state.items():
            hold=entry.get('maintenance',{})
            if not hold.get('active') or any(row.get('box')==box and row.get('status')!='stopped' for row in self.instances.values()):continue
            enabled=self.config['running'] and self.runtime_enabled(box)
            result.append({'id':'maintenance:'+box,'pid':None,'box':box,'name':'DPS · '+(box or '主实例'),
                'identity':entry.get('identity'),'status':'maintenance' if enabled else 'paused','snapshot':None,'actions':[],
                'maintenance':{k:hold.get(k) for k in ('active','since','attempts','retry_at')},
                'issues':['服务器维护中，等待自动重连' if enabled else '维护等待已暂停，恢复远征后继续重连']})
        return result
    def public_state(self):
        with self.lock:
            instances=copy.deepcopy(list(self.instances.values())+self.maintenance_waiting())
            for row in instances:
                info=pause_info(self.config,row.get('identity'),self.durable.get(row.get('identity'),{}))
                row['pause']=info
                if info:
                    row['actions']=[]
                    if row['status'] in ('running','paused'):row['status']='paused'
                    if info['reason']=='protected_item_changed':row['error']=PROTECTION_MESSAGE
            return copy.deepcopy({'version':VERSION,'updates':self.updater.state() if getattr(self,'updater',None) else {'status':'unavailable'},'preferences':self.preferences,'started':self.started,'now':time.time(),'config':self.config,'parameters':public_parameters(),'modules':[{'id':k,'name':n,'description':d} for k,(n,d) in MODULES.items()],'instances':instances,'events':self.events[-80:],'data_directory':str(DATA),'validation':{'graduated':False,'message':'成长链路正在实机验证，尚未完成全系统与毕业验收'}})
    def stop(self):
        self.stopping.set()
        if self.thread.is_alive():self.thread.join(timeout=5)
        self.pool.shutdown(wait=True,cancel_futures=True)
        for bridge in self.bridges.values():bridge.close()
        self.save()
