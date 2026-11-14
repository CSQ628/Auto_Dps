import React,{useEffect,useRef,useState} from 'react';
import {Button,Dropdown,Input,Option,Switch} from '@fluentui/react-components';
import {CheckCircle,SlidersHorizontal} from '@phosphor-icons/react';

export function Parameter({spec,value,update,controls,disabled,idPrefix="parameter"}){
 const [draft,setDraft]=useState(String(value??spec.default)),[status,setStatus]=useState('已保存');
 const timer=useRef(),dirty=useRef(false),pending=useRef(null),last=useRef(null),version=useRef(0),mounted=useRef(true),commitRef=useRef();
 useEffect(()=>{if(!dirty.current)setDraft(String(value??spec.default));},[value,spec.default]);
 async function commit(next,revision){
  if(revision!==version.current)return;
  clearTimeout(timer.current);pending.current=null;
  if(mounted.current)setStatus('保存中…');
  const ok=await update(spec.scope==='root'?{[spec.key]:next}:{strategy:{[spec.key]:next}});
  if(revision===version.current){dirty.current=!ok;if(mounted.current){setStatus(ok?'已保存':'保存失败');if(ok)setDraft(String(next));}}
 }
 commitRef.current=commit;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;clearTimeout(timer.current);if(pending.current!==null)commitRef.current(pending.current,version.current);};},[]);
 useEffect(()=>{const handle={group:spec.group,cancel(){clearTimeout(timer.current);version.current++;pending.current=null;last.current=null;dirty.current=false;setDraft(String(value??spec.default));setStatus('已保存');}};controls.current.set(spec.key,handle);return()=>controls.current.delete(spec.key);},[spec,value,controls]);
 function edit(text){
  const revision=++version.current;setDraft(text);dirty.current=true;clearTimeout(timer.current);pending.current=null;last.current=null;
  const number=Number(text);
  if(!text.trim()||!Number.isFinite(number)||number<spec.min||number>spec.max||(spec.step===1&&!Number.isInteger(number))){setStatus(`请输入 ${spec.min} 至 ${spec.max}${spec.step===1?' 的整数':''}`);return;}
  pending.current=number;last.current=number;setStatus('等待自动保存');timer.current=setTimeout(()=>commitRef.current(number,revision),700);
 }
 function select(next){const revision=++version.current;setDraft(String(next));dirty.current=true;last.current=next;commit(next,revision);}
 return <div className="parameter-row" data-parameter={spec.key}><div className="parameter-description"><label htmlFor={idPrefix+'-'+spec.key}>{spec.label}</label>{spec.hint&&<p>{spec.hint}</p>}<small>默认：{spec.type==='boolean'?((spec.inverted?!spec.default:spec.default)?'开启':'关闭'):spec.type==='choice'?spec.options.find(x=>x.value===spec.default)?.label:spec.default}{spec.unit?` ${spec.unit}`:''}{spec.type==='number'?` · 范围 ${spec.min}～${spec.max}${spec.unit}`:''}</small></div><div className="parameter-control">
 {spec.type==='number'?<Input disabled={disabled} id={idPrefix+'-'+spec.key} aria-label={spec.label} type="number" min={spec.min} max={spec.max} step={spec.step} value={draft} contentAfter={spec.unit||undefined} onChange={(_,d)=>edit(d.value)} onBlur={()=>{if(pending.current!==null)commitRef.current(pending.current,version.current);}}/>:spec.type==='boolean'?<Switch disabled={disabled} id={idPrefix+'-'+spec.key} aria-label={spec.label} checked={spec.inverted?draft!=='true':draft==='true'} onChange={(_,d)=>select(spec.inverted?!d.checked:d.checked)}/>:<Dropdown disabled={disabled} id={idPrefix+'-'+spec.key} aria-label={spec.label} value={spec.options.find(o=>o.value===draft)?.label||''} selectedOptions={[draft]} onOptionSelect={(_,d)=>select(d.optionValue)}>{spec.options.map(o=><Option key={o.value} value={o.value}>{o.label}</Option>)}</Dropdown>}
 <span className={'parameter-save '+(status==='已保存'?'saved':'')} role="status">{status==='已保存'&&<CheckCircle size={12}/>} {status}</span>{status==='保存失败'&&<Button appearance="subtle" size="small" onClick={()=>commit(last.current,version.current)}>重试保存</Button>}</div></div>;
}

export default function Parameters({schema,config,update,focus,dataDirectory}){
 const controls=useRef(new Map()),[resetting,setResetting]=useState('');
 useEffect(()=>{if(focus)document.getElementById('parameter-group-'+focus)?.scrollIntoView({block:'start',behavior:'smooth'});},[focus]);
 if(!schema)return <section className="panel"><h2>正在读取参数</h2></section>;
 async function reset(group){
  setResetting(group);for(const handle of controls.current.values())if(handle.group===group)handle.cancel();
  const patch={strategy:{}};for(const spec of schema.fields.filter(s=>s.group===group)){if(spec.scope==='root')patch[spec.key]=spec.default;else patch.strategy[spec.key]=spec.default;}
  await update(patch);setResetting('');
 }
 return <div className="settings-page"><section className="panel parameter-intro"><div><SlidersHorizontal size={23}/><h2>基础参数与策略</h2></div><p>这里显示当前生效值。修改后自动保存，后续巡检使用新设置；全部实例共用策略，各账号的资源与进度独立计算。</p><nav aria-label="参数分组">{schema.groups.map(g=><a key={g.id} href={'#parameter-group-'+g.id}>{g.label}</a>)}</nav></section>
 {schema.groups.map(group=><section className="panel parameter-group" id={'parameter-group-'+group.id} key={group.id}><div className="section-title"><h2>{group.label}</h2><Button disabled={!!resetting} appearance="subtle" size="small" onClick={()=>reset(group.id)}>恢复本组默认值</Button></div>{schema.fields.filter(s=>s.group===group.id).map(spec=><Parameter key={spec.key} spec={spec} value={spec.scope==='root'?config[spec.key]:config.strategy?.[spec.key]} update={update} controls={controls} disabled={resetting===group.id}/>)}</section>)}
 <section className="panel settings-path"><strong>配置、备份与日志</strong><code>{dataDirectory}</code><p>参数保存到本机配置，关闭页面或重启助手后继续沿用。</p></section></div>;
}
