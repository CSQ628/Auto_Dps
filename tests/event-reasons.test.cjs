const test=require('node:test'),assert=require('node:assert/strict');
test('waiting events show a useful Chinese reason without rendering raw native errors',async()=>{
 const {eventReason}=await import('../web/src/event-reasons.mjs');
 assert.match(eventReason({result:{reason:'native_material_not_reserved'}}),/未接收材料/);
 assert.match(eventReason({result:{reason:'native_preparation_failed',step:'reserve',error:'private-account'}}),/材料预留/);
 assert.equal(eventReason({status:'waiting'}),'');
 assert.ok(!eventReason({result:{reason:'private-token',error:'private-account'}}).includes('private'));
});
