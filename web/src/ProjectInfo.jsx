// Support wording and author-provided assets adapted from IdleLegions-AutoAbyss.
// Reimplemented with Fluent UI for Auto_Dps. See THIRD_PARTY_NOTICES.md.
import React,{useEffect,useState} from 'react';
import {Button,Dialog,DialogSurface,DialogBody,DialogTitle,DialogContent,DialogActions,Popover,PopoverTrigger,PopoverSurface} from '@fluentui/react-components';
import {ArrowUpRight,Code,DownloadSimple,Heart} from '@phosphor-icons/react';

const repository='https://github.com/weixiao030/Auto_Dps';

function AppreciationDialog({open,onOpenChange}){
 return <Dialog open={open} onOpenChange={(_,d)=>onOpenChange(d.open)}><DialogSurface className="appreciation-dialog"><DialogBody><DialogTitle>作者赞赏码</DialogTitle><DialogContent><p>自愿支持，所有功能均可免费使用。</p><img src="/appreciation-original.jpg" alt="作者提供的完整微信赞赏码" width="1210" height="1210"/></DialogContent><DialogActions><a href="/appreciation-original.jpg" target="_blank" rel="noopener noreferrer">查看原图</a><Button onClick={()=>onOpenChange(false)}>关闭</Button></DialogActions></DialogBody></DialogSurface></Dialog>;
}

export function SidebarSupport(){
 const [expanded,setExpanded]=useState(false),[previewOpen,setPreviewOpen]=useState(false),[imageError,setImageError]=useState(false);
 function openOriginal(){setPreviewOpen(false);setExpanded(true);}
 return <div className="sidebar-support"><Popover open={previewOpen&&!expanded} onOpenChange={(_,d)=>setPreviewOpen(d.open)} openOnHover unstable_disableAutoFocus positioning={{position:'after',align:'bottom',offset:12,fallbackPositions:['below','above'],overflowBoundaryPadding:16}}>
  <PopoverTrigger disableButtonEnhancement><button type="button" className="sidebar-support-trigger" aria-label="赞赏作者，点击查看原图" aria-haspopup="dialog" onClick={openOriginal}>{imageError?<Heart size={24}/>:<img src="/appreciation-code.webp" alt="" width="36" height="36" onError={()=>setImageError(true)}/>}</button></PopoverTrigger>
  <PopoverSurface className="sidebar-support-preview"><button type="button" onClick={openOriginal} aria-label="查看赞赏码原图"><img src="/appreciation-code.webp" alt="作者微信赞赏码预览" width="220" height="220"/></button><p>自愿赞赏 · 点击查看原图</p></PopoverSurface>
 </Popover><AppreciationDialog open={expanded} onOpenChange={setExpanded}/></div>;
}

export function FirstRunNotice({accepted,csrf,onAccepted}){
 const [remaining,setRemaining]=useState(3),[saving,setSaving]=useState(false),[error,setError]=useState('');
 useEffect(()=>{
  if(accepted)return;
  const deadline=performance.now()+3000;setRemaining(3);
  const timer=setInterval(()=>setRemaining(Math.max(0,Math.ceil((deadline-performance.now())/1000))),100);
  return()=>clearInterval(timer);
 },[accepted]);
 async function agree(){
  if(remaining||saving)return;
  setSaving(true);setError('');
  try{
   const response=await fetch('/api/consent',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({accepted:true})});
   if(!response.ok)throw Error('未能保存同意记录，请重试。');
   onAccepted();
  }catch(e){setError(e.message);}finally{setSaving(false);}
 }
 return <Dialog open={!accepted} modalType="modal"><DialogSurface className="first-run-notice"><DialogBody><DialogTitle>使用前请阅读</DialogTitle><DialogContent>
  <p>本项目完全开源免费，地址:<a href={repository} target="_blank" rel="noopener noreferrer">{repository}</a>,仅供学习参考，使用该助手导致的任何问题包括但不限于封号等问题自行承担，本项目允许你自行修改等行为，但请不要用于付费商业用途，免费分发等行为无需找我要授权，如果修改后可以的话请署名和带上项目源地址谢谢！</p>
  {error&&<p role="alert">{error}</p>}
 </DialogContent><DialogActions><Button appearance="primary" disabled={remaining>0||saving} onClick={agree}>{saving?'正在保存…':remaining?`我同意（${remaining} 秒）`:'我同意'}</Button></DialogActions></DialogBody></DialogSurface></Dialog>;
}

export function ProjectSupport(){
 const [expanded,setExpanded]=useState(false),[imageError,setImageError]=useState(false);
 return <section className="panel project-support" aria-labelledby="support-title"><div className="project-info"><Code size={25}/><h2 id="support-title">免费开源，自愿赞赏。</h2>
  <p className="free-notice">该软件免费并开源，如果是付费购买请前往退款</p><div className="source-address"><span>开源地址:</span><a href={repository} target="_blank" rel="noopener noreferrer">{repository}<ArrowUpRight size={16}/></a></div>
  <p>喜欢这个小工具，可以自愿支持作者。感谢每一份反馈与支持。</p></div>
  <figure className="appreciation"><div className="appreciation-heading"><Heart size={18}/><h3>给作者一点鼓励</h3></div>
   {imageError?<p role="alert">赞赏码加载失败，请重新打开控制台。</p>:<button type="button" className="appreciation-preview" aria-label="放大赞赏码" onClick={()=>setExpanded(true)}><img src="/appreciation-code.webp" alt="作者提供的微信赞赏码，点击可查看原图" width="600" height="600" onError={()=>setImageError(true)}/></button>}
   <figcaption><p>无论是否打赏都不影响使用，全部免费,感谢板板支持</p><a href="/appreciation-original.jpg" download="DPS远征助手赞赏码.jpg"><DownloadSimple size={16}/>保存赞赏码</a></figcaption>
  </figure><AppreciationDialog open={expanded} onOpenChange={setExpanded}/>
 </section>;
}
