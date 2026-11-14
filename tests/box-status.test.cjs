const test=require('node:test'),assert=require('node:assert/strict');
test('box feedback shows queue, free slots and the actual guard without private text',async()=>{
 const {boxStatusMessage}=await import('../web/src/box-status.mjs');
 assert.match(boxStatusMessage({total:13,freeSlots:8,reason:'box_ready'}),/待开 13 个.*空位 8 格.*每秒检查/);
 assert.match(boxStatusMessage({total:13,freeSlots:0,reason:'inventory_full'}),/背包已满/);
 assert.match(boxStatusMessage({reason:'box_result_unconfirmed'}),/避免重复/);
 assert.equal(boxStatusMessage({reason:'private-account'}),'正在读取宝箱与背包状态');
 assert.match(boxStatusMessage(),/读取/);
});
