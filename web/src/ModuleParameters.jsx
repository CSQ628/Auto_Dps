import React,{useRef} from 'react';
import {Parameter} from './Parameters';

const keys={
 box:['inventory_pressure_percent','interval'],
 equipment:['equipment_hold_seconds','equipment_return_seconds','equipment_min_gain_percent'],
 active:['recommended_actives','allow_active_refund','skill_point_reserve'],
 passive:['skill_point_reserve'],rune:['rune_priority','soul_reserve','permanent_runes','premium_reserve'],
 unlock:['action_retry_seconds'],pet_unlock:['pet_mode'],
 progress:['push_wait_seconds','push_failure_limit','farm_min_seconds','farm_retry_seconds','farm_level_offset'],
 combine:['inventory_pressure_percent','action_cooldown_seconds'],
 decompose:['recycle_batch','recycle_normal_tier_gap','recycle_rare_tier_gap'],
 storage:['inventory_pressure_percent'],forge:['action_retry_seconds','action_cooldown_seconds'],
 refine:['action_retry_seconds','action_cooldown_seconds'],mail:['action_retry_seconds'],
 tower:['tower_retry_seconds','tower_farm_wait_seconds','tower_require_growth'],
 ui_cleanup:['action_retry_seconds','action_cooldown_seconds'],
};
export default function ModuleParameters({module,schema,config,update}){
 const controls=useRef(new Map());
 if(!schema)return null;
 const fields=(keys[module]||[]).map(key=>schema.fields.find(p=>p.key===key)).filter(Boolean);
 return <div className="module-tuning" aria-label="模块参数"><h4>参数 · 修改后自动保存</h4>{fields.map(spec=><Parameter key={spec.key} spec={spec} value={spec.scope==='root'?config[spec.key]:config.strategy?.[spec.key]} update={update} controls={controls} idPrefix={'module-'+module}/>)}</div>;
}
