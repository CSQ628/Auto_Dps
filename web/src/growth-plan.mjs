export function skillStatus(c){
 const p=c?.skillPlanning;if(!p)return '';
 if(p.repair?.excess>0)return p.repair.refund?`正在纠正${p.repair.refund.kind==='active'?'主动升级':'被动'}：逐点回收 ${p.repair.refund.skill}，剩余 ${p.repair.excess} 点后重新投入`:'天赋纠错等待原生退款条件，主线重试与其他成长继续';
 if(p.repair?.reason==='skill_catalogue_invalid')return '技能目录校验未通过，保留已有分配并继续其他成长';
 if(!p.next)return c.points<=p.pointReserve?'技能点已用完或已达到保留量，升级后继续职业路线':'当前已开放技能暂无可投入目标';
 const reasons={core_unlock:'补齐核心主动',core_upgrade:'提升核心主动',role_passive:'提升职业被动',passive_prerequisite:'投入职业被动前置'};
 return `${reasons[p.next.reason]||'技能规划'} · ${p.next.skill}`;
}
export function runePlanStatus(p){
 if(!p)return '正在读取刻印前置与预算。';
 if(p.next?.offlineFallback)return `刻印兜底：离线收益目标 ${p.next.target}，仅在其他可执行成长之后投入。在线路线：${runePlanStatus({waiting:p.onlineWaiting})}`;
 if(p.next)return `刻印计划：${p.next.reason==='minimum_prerequisite'?'投入最低前置，接续在线目标':'按当前收益与成本提升'} ${p.next.target}。离线收益最低优先级。`;
 const w=p.waiting||{};
 if(w.reason==='premium_reserve')return `刻印等待灵魂石：下个可用节点需要 ${w.minimumPremium} 颗，扣除保留量后可用 ${w.premiumSpendable} 颗。可在参数设置调整保留量，当前设置保持。`;
 if(w.reason==='soul_reserve')return `刻印等待灵魂预算：下个可用节点需要 ${w.minimumSoul}，扣除保留量后可用 ${w.soulSpendable}。`;
 if(w.reason==='premium_disabled')return '在线刻印等待灵魂石节点；自动使用灵魂石已关闭，其他可执行成长继续。';
 if(w.reason==='premium_missing')return `刻印等待灵魂石：下个可用节点需要 ${w.minimumPremium} 颗，当前可用 ${w.premiumSpendable} 颗。`;
 if(w.reason==='soul_missing')return `刻印等待灵魂：下个可用节点需要 ${w.minimumSoul}，当前可用 ${w.soulSpendable}。`;
 if(w.reason==='runes_complete')return '该范围刻印已完成；其他可执行成长继续。';
 if(w.reason==='online_complete')return '在线刻印已完成，继续评估最低优先级离线收益。';
 return '刻印等待原生前置或货币条件，其他可执行成长继续。';
}
