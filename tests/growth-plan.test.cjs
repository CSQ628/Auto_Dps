const test=require('node:test'),assert=require('node:assert/strict');
test('engraving UI distinguishes a stone reserve gate from an unaffordable soul node or completion',async()=>{
 const {runePlanStatus,skillStatus}=await import('../web/src/growth-plan.mjs');
 const text=runePlanStatus({waiting:{reason:'premium_reserve',minimumPremium:8,premiumSpendable:7}});
 assert.match(text,/需要 8 颗/);assert.match(text,/可用 7 颗/);assert.ok(!text.includes('已完成'));
 assert.match(runePlanStatus({next:{target:5,reason:'minimum_prerequisite'}}),/最低前置/);
 assert.match(runePlanStatus({waiting:{reason:'online_complete'}}),/最低优先级离线收益/);
 assert.match(skillStatus({points:0,skillPlanning:{pointReserve:0}}),/升级后继续/);
});
