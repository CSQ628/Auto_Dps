from concurrent.futures import ThreadPoolExecutor
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import threading
import time
import zipfile
from .storage import DATA,atomic_json,load_json,event,recent_events
from .runtime import Bridge,discover,launch
from .policy import MODULES,choose,ranked_actions,module_for,strength_signature,observe_growth
from .completion import milestones
from .combat import observe_combat
from .platform_paths import VERSION
from .parameters import DEFAULT_STRATEGY,normalize_config,apply_patch,public_parameters,strategy

DEFAULT={'strategy':copy.deepcopy(DEFAULT_STRATEGY),'running':True,'interval':2.0,'soul_reserve':0,'premium_reserve':2,'permanent_runes':True,'auto_launch':True,'managed_boxes':[],'modules':{k:True for k in MODULES},'instances':{}}

class Engine:
    def __init__(self,start=True):
        self.lock=threading.RLock();self.submit_gate=threading.RLock();self.stopping=threading.Event()
        self.config=load_json(DATA/'config.json',copy.deepcopy(DEFAULT))
        self.config={**copy.deepcopy(DEFAULT),**self.config};self.config['modules']={**DEFAULT['modules'],**self.config.get('modules',{})};self.config=normalize_config(self.config)
        self.preferences=load_json(DATA/'preferences.json',{})
        self.preferences={'noticeAccepted':self.preferences.get('noticeAccepted') is True}
        self.durable=load_json(DATA/'scheduler.json',{});self.instances={};self.bridges={};self.jobs={}
        self.events=recent_events();self.started=time.time();self.pool=ThreadPoolExecutor(max_workers=8,thread_name_prefix='dps-instance')
        self.thread=threading.Thread(target=self.loop,daemon=True)
        if start:self.thread.start()
        atomic_json(DATA/'config.json',self.config)
    def record(self,instance,status,message,**details):
        row={'at':time.time(),'instance':instance,'status':status,'message':message,**details}
        with self.lock:self.events=(self.events+[row])[-200:]
        event(row)
    def save(self):
        with self.lock:atomic_json(DATA/'scheduler.json',self.durable)
    def record_equipment(self,state,action,now):
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
        for action_key,pending in list(state.get('pending_results',{}).items()):
            action=pending['action'];stage=snap.get('stage',{});kind=action['kind']
            confirmed=(kind=='tower' and stage.get('category')==1 and stage.get('level')==action['level'] and stage.get('running')) or (kind in ('tower_return','progress') and action.get('level') and stage.get('category')==0 and stage.get('level')==action['level'] and stage.get('running') and (kind!='progress' or action.get('phase')=='travel' or stage.get('repeat')==action.get('repeat')))
            if kind=='equipment':
                character=next((c for c in snap.get('characters',[]) if c['id']==action['id']),{})
                confirmed=any(p.get('slot')==action['slot'] and p['uid']==action['uid'] for p in character.get('equipment',[]))
            if not confirmed:continue
            state['pending_results'].pop(action_key);state['uncertain'].pop(action_key,None)
            state['confirmed']=state.get('confirmed',0)+1;row['confirmed']=state['confirmed']
            feature=state.setdefault('features',{}).setdefault(kind,{'confirmed':0})
            feature.update(confirmed=feature.get('confirmed',0)+1,last_status='confirmed',last_at=time.time(),last_reason=None)
            if kind=='equipment':self.record_equipment(state,action,time.time())
            self.record(key,'confirmed',action['label'],identity=row['identity'],action=action,result={'status':'confirmed','observed_stage':stage})
        row['feature_evidence']=copy.deepcopy(state.get('features',{}))
        row['equipment_evidence']=copy.deepcopy(state.get('equipment_by_character',{}))
    def update(self,value):
        with self.submit_gate,self.lock:
            updated=apply_patch(self.config,value)
            atomic_json(DATA/'config.json',updated);self.config=updated
        return self.config
    def loop(self):
        last_launch={}
        while not self.stopping.is_set():
            try:
                found=discover();live={str(p['pid']) for p in found}
                boxes={p['box'] for p in found}
                remembered=sorted(set(self.config['managed_boxes']) | {b for b in boxes if b})
                if remembered!=self.config['managed_boxes']:
                    with self.lock:self.config['managed_boxes']=remembered;atomic_json(DATA/'config.json',self.config)
                if self.config['auto_launch'] and self.config['running']:
                    for box in ['',*remembered]:
                        if box not in boxes and time.time()-last_launch.get(box,0)>strategy(self.config)['launch_retry_seconds']:
                            last_launch[box]=time.time();launch(box);self.record('system','submitted','启动 DPS · '+(box or '主实例'))
                for identity in found:
                    key=str(identity['pid'])
                    existing=self.bridges.get(key)
                    if existing and existing.identity['created']!=identity['created']:
                        # Do not reuse any job, session or snapshot from the old process lifetime.
                        existing.close();self.bridges.pop(key,None);self.instances.pop(key,None)
                        if key in self.jobs and not self.jobs[key].done():continue
                    with self.lock:
                        row=self.instances.setdefault(key,{'id':key,**identity,'name':'DPS · '+(identity['box'] or '主实例'),'status':'connecting','snapshot':None,'actions':[],'confirmed':0})
                    # Let Unity and Steam finish initial loading before attaching a native bridge.
                    if time.time()-identity['created']<15:continue
                    if key not in self.bridges:
                        self.bridges[key]=Bridge(identity);row['status']='connecting'
                    if key not in self.jobs or self.jobs[key].done():self.jobs[key]=self.pool.submit(self.tick,key)
                for key in list(self.bridges):
                    if key not in live:
                        self.bridges.pop(key).close()
                        with self.lock:self.instances[key]['status']='stopped'
                # Short-lived Steam/Unity launchers may disappear before receiving a bridge.
                with self.lock:
                    for key,row in self.instances.items():
                        if key not in live:row.update(status='stopped',actions=[])
            except Exception as e:self.record('system','error',str(e))
            self.stopping.wait(self.config['interval'])
    def tick(self,key):
        bridge=self.bridges[key];row=self.instances[key]
        try:
            scan=bridge.call('opportunities',strategy(self.config));snap=scan['snapshot']
            identity=(bridge.identity['box'] or 'host')+':'+snap['account']
            with self.lock:
                state=self.durable.setdefault(identity,{'cooldowns':{},'uncertain':{},'last_equipment':{}})
                row.update(snapshot=snap,actions=scan['actions'][:24],issues=scan['issues'],last_seen=time.time(),account=snap['account'],identity=identity,status='running' if self.config['running'] else 'paused',error=None,confirmed=state.get('confirmed',0),feature_evidence=copy.deepcopy(state.get('features',{})))
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
            if not self.config['instances'].get(identity,True):row['status']='paused';return
            self.observe_boss_clear(key,row,state,snap)
            self.observe_tower_clear(key,row,state,snap)
            self.settle_pending(key,row,state,snap)
            state.setdefault('scheduling_started',time.time())
            row['combat_analysis']=observe_combat(snap,state,str(bridge.identity['pid'])+':'+str(bridge.identity['created']),time.time())
            row['growth']=observe_growth(snap,state,time.time(),self.config)
            row['milestones']=milestones(snap,state.get('features',{}))
            row['actions']=ranked_actions(scan,self.config,state)[:24]
            # A fresh native scan invalidates completed state-specific keys; elapsed time alone never proves failure.
            current_keys={a['key'] for a in scan['actions']}
            for old_key in list(state['uncertain']):
                if old_key not in current_keys:state['uncertain'].pop(old_key)
            with self.submit_gate:
                action=choose(scan,self.config,state)
                if action is None or self.stopping.is_set() or not self.config['instances'].get(identity,True):return
                state['uncertain'][action['key']]=time.time();self.save()
                command={**action,'account':snap['account'],'soulReserve':self.config['soul_reserve'],'premiumReserve':self.config['premium_reserve'],'permanentRunes':self.config['permanent_runes'],'strategy':strategy(self.config)}
                if action['kind']=='progress' and action.get('mode')=='boss':
                    state['boss_attempt']={k:action[k] for k in ('level','ticket','ticketUid','ticketBefore')};self.save()
                if action['kind']=='tower':
                    state['tower_attempt']={'level':action['level'],'max_stage':snap['record']['maxStage'],'cleared_before':snap['record'].get('towerMaxCleared'),'strength':strength_signature(snap),'at':time.time()};self.save()
                result=bridge.call('execute',command)
            status=result['status'];now=time.time()
            if action['kind']=='progress' and action.get('mode')=='boss' and status not in ('pending','confirmed'):
                state.pop('boss_attempt',None)
            state['uncertain'].pop(action['key'],None)
            state['cooldowns'][action['key']]=now+(strategy(self.config)['action_retry_seconds'] if status in ('rejected','no_change','waiting') else strategy(self.config)['action_cooldown_seconds'])
            if action['kind']=='equipment':state['last_equipment'][str(action['id'])]=now
            state.setdefault('last_module',{})[module_for(action['kind'])]=now
            if status=='pending':state['uncertain'][action['key']]=now
            if status=='pending' and action['kind'] in ('tower','tower_return','equipment','progress'):state.setdefault('pending_results',{})[action['key']]={'action':action,'at':now}
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
            if result.get('protectedChanged'):
                self.update({'instances':{identity:False}})
                row.update(status='paused',error='可交易物品校验出现差异，已停止该实例提交')
            self.save();self.record(key,status,action['label'],identity=identity,box=bridge.identity['box'],action=action,result=result)
        except Exception as e:
            with self.lock:row.update(status='recovering',error=str(e))
            # Observation failure is not evidence that the bridge/game stopped.
            if row.get('last_error')!=str(e):self.record(key,'error',str(e));row['last_error']=str(e)
            # Restart an owned helper only after its process is authoritatively terminal.
            if bridge.process.poll() is not None:
                with self.lock:
                    if self.bridges.get(key) is bridge:
                        self.bridges.pop(key,None);bridge.close()
            elif ('10061' in str(e) or 'connection refused' in str(e).lower()) and time.time()-bridge.started>=30:
                # The helper can be transiently unavailable after an in-game scene reload.
                # Allow Sandboxie/Frida to finish initialization before replacing an unready helper.
                with self.lock:
                    if self.bridges.get(key) is bridge:
                        self.bridges.pop(key,None);bridge.close();row['status']='recovering'
    def accept_notice(self):
        with self.lock:
            updated={'noticeAccepted':True};atomic_json(DATA/'preferences.json',updated);self.preferences=updated
        return copy.deepcopy(updated)
    def public_state(self):
        with self.lock:return copy.deepcopy({'version':VERSION,'preferences':self.preferences,'started':self.started,'now':time.time(),'config':self.config,'parameters':public_parameters(),'modules':[{'id':k,'name':n,'description':d} for k,(n,d) in MODULES.items()],'instances':list(self.instances.values()),'events':self.events[-80:],'data_directory':str(DATA),'validation':{'graduated':False,'message':'成长链路正在实机验证，尚未完成全系统与毕业验收'}})
    def stop(self):
        self.stopping.set()
        if self.thread.is_alive():self.thread.join(timeout=5)
        self.pool.shutdown(wait=True,cancel_futures=True)
        for bridge in self.bridges.values():bridge.close()
        self.save()
