const test=require('node:test'),assert=require('node:assert/strict');
test('waiting events show a useful Chinese reason without rendering raw native errors',async()=>{
 const {eventReason}=await import('../web/src/event-reasons.mjs');
 assert.match(eventReason({result:{reason:'native_material_not_reserved'}}),/未接收材料/);
 assert.match(eventReason({result:{reason:'native_preparation_failed',step:'reserve',error:'private-account'}}),/材料预留/);
 assert.match(eventReason({result:{reason:'forge_result_unconfirmed'}}),/避免重复消费/);
 assert.match(eventReason({result:{reason:'forge_result_unconfirmed'}}),/其他自动化继续/);
 for(const reason of ['combine_result_unconfirmed','decompose_result_unconfirmed']){
  assert.match(eventReason({result:{reason}}),/避免重复消费/);assert.match(eventReason({result:{reason}}),/其他自动化继续/);
 }
 assert.equal(eventReason({status:'waiting'}),'');
 assert.ok(!eventReason({result:{reason:'private-token',error:'private-account'}}).includes('private'));
});

test('warning and sorting-difference text never claims the instance was paused',async()=>{
 const {eventReason}=await import('../web/src/event-reasons.mjs');
 assert.match(eventReason({status:'warning',result:{reason:'tradable_state_changed'}}),/自动化继续运行/);
 assert.doesNotMatch(eventReason({result:{reason:'sort_conservation_failed'}}),/暂停/);
});
