import React,{useRef} from 'react';
import {ParameterSections} from './Parameters';

export default function ModuleParameters({module,schema,config,update}){
 const controls=useRef(new Map());
 if(!schema)return null;
 const fields=schema.fields.filter(p=>p.modules?.includes(module));
 return <details className="module-tuning" aria-label="模块参数"><summary>展开设置与用途说明 · {fields.length} 项</summary><ParameterSections fields={fields} config={config} update={update} controls={controls} idPrefix={'module-'+module}/></details>;
}
