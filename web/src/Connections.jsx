import React,{useEffect,useRef,useState} from 'react';
import {Button,Dialog,DialogSurface,DialogBody,DialogTitle,DialogContent,DialogActions,Input,Dropdown,Option} from '@fluentui/react-components';
import {ArrowsClockwise,Link} from '@phosphor-icons/react';

export default function Connections({csrf,onClose,onBound}){
 const [data,setData]=useState(null),[path,setPath]=useState(''),[selected,setSelected]=useState(''),[pid,setPid]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
 const feedback=useRef(null);
 useEffect(()=>{if(!busy&&(error||message))feedback.current?.focus({preventScroll:true});},[busy,error,message]);
 async function scan(signal){
  setBusy(true);setError('');
  try{
   const response=await fetch('/api/connections',{signal});const result=await response.json();
   if(!response.ok)throw Error(result.error||'未能读取游戏信息');
   setData(result);setPath(value=>value||result.selected_path||result.games[0]?.path||'');
  }catch(e){if(e.name!=='AbortError')setError(e.message);}finally{if(!signal?.aborted)setBusy(false);}
 }
 useEffect(()=>{const controller=new AbortController();scan(controller.signal);return()=>controller.abort();},[]);
 async function bind(value){
  setBusy(true);setError('');setMessage('');
  try{
   const response=await fetch('/api/bind',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(value)});
   const result=await response.json();if(!response.ok)throw Error(result.error||'连接失败，请重试');
   setMessage(result.message);onBound?.(result);
  }catch(e){setError(e.message);}finally{setBusy(false);}
 }
 const process=data?.processes.find(p=>String(p.pid)===selected);
 return <Dialog open onOpenChange={(_,d)=>{if(!d.open&&!busy)onClose();}}><DialogSurface className="connection-dialog"><DialogBody>
  <DialogTitle>自定义多个连接</DialogTitle><DialogContent>
   <p className="dialog-description">自动连接始终开启。可以指定游戏目录，或逐个绑定正在运行的普通与沙盒实例；绑定后保留此窗口，可继续添加其他连接。</p>
   <div className="connection-toolbar"><span>{data?`找到 ${data.processes.length} 个运行实例`:'正在检测游戏进程和安装目录'}</span><Button icon={<ArrowsClockwise size={16}/>} disabled={busy} onClick={()=>scan()}>重新扫描</Button></div>
   <section className="connection-section"><h3>绑定运行中的游戏</h3>
    <label htmlFor="connection-process">选择实例</label>
    <Dropdown id="connection-process" aria-label="选择运行中的游戏实例" placeholder="选择一个游戏进程" value={process?`${process.box||'主实例'} · PID ${process.pid}`:''} selectedOptions={process?[String(process.pid)]:[]} disabled={busy} onOptionSelect={(_,d)=>{setSelected(d.optionValue);setPid('');}}>
     {data?.processes.map(p=><Option key={p.pid} value={String(p.pid)} text={`${p.box||'主实例'} · PID ${p.pid}`}><div className="process-option"><strong>{p.box||'主实例'} · PID {p.pid}</strong><small>{p.exe}</small></div></Option>)}
    </Dropdown>
    <label htmlFor="connection-pid">或填写游戏 PID</label><div className="connection-input-row"><Input id="connection-pid" aria-label="手动填写游戏 PID" placeholder="在任务管理器的“详细信息”中查看" value={pid} disabled={busy} onChange={(_,d)=>{setPid(d.value);setSelected('');}}/><Button appearance="primary" icon={<Link size={16}/>} disabled={busy||(!process&&!/^\d+$/.test(pid))} onClick={()=>bind(process?{pid:process.pid,created:process.created}:{pid:Number(pid)})}>绑定实例</Button></div>
    <p className="field-help">只会接入经过验证的 DPS.exe；同一账号已有控制实例时，其他实例保持观察。</p>
   </section>
   <section className="connection-section"><h3>指定游戏安装目录</h3>
    {data?.games.length>0&&<Dropdown aria-label="已检测到的游戏目录" placeholder="使用检测到的目录" onOptionSelect={(_,d)=>setPath(d.optionValue)}>{data.games.map(p=><Option key={p.path} value={p.path} text={p.path}><div className="process-option"><strong>{p.source}</strong><small>{p.path}</small></div></Option>)}</Dropdown>}
    <label htmlFor="connection-path">游戏目录或 DPS.exe 完整路径</label><Input id="connection-path" aria-label="游戏目录或 DPS.exe 完整路径" value={path} onChange={(_,d)=>setPath(d.value)} disabled={busy} placeholder="例如：D:\SteamLibrary\steamapps\common\DPS Desktop Pension Squad"/>
    <p className="field-help">目录会保存在本机。自动启动使用这个目录；已连接的游戏继续运行。</p><Button disabled={busy||!path.trim()} onClick={()=>bind({path})}>保存游戏目录</Button>
   </section>
   {error&&<p ref={feedback} tabIndex={-1} className="form-error" role="alert">{error}</p>}{message&&<p ref={feedback} tabIndex={-1} className="form-success" role="status">{message}</p>}
  </DialogContent><DialogActions><Button disabled={busy} onClick={onClose}>完成</Button></DialogActions>
 </DialogBody></DialogSurface></Dialog>;
}
