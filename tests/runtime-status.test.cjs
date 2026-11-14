const test=require('node:test'),assert=require('node:assert/strict');
test('maintenance countdown describes pending retry without claiming recovery',async()=>{
 const {maintenanceMessage}=await import('../web/src/runtime-status.mjs');
 const row={maintenance:{active:true,retry_at:400}},config={running:true,auto_launch:true,instances:{}};
 assert.match(maintenanceMessage(row,config,100),/5 分 0 秒后重试/);
 assert.match(maintenanceMessage(row,config,401),/等待下一次登录检查/);
 assert.match(maintenanceMessage(row,{...config,running:false},100),/已暂停/);
 assert.match(maintenanceMessage(row,{...config,auto_launch:false},100),/自动启动已关闭/);
 assert.equal(maintenanceMessage({status:'running'},config,100),'');
});

test('pause text distinguishes manual, global, old unknown and confirmed trade damage',async()=>{
 const {pauseMessage}=await import('../web/src/runtime-status.mjs');
 const row={identity:'host:a'},config={running:true,instances:{'host:a':false}};
 assert.match(pauseMessage(row,config),/旧版未记录原因/);
 assert.match(pauseMessage({...row,pause:{reason:'manual_instance_pause'}},config),/手动暂停/);
 assert.match(pauseMessage({...row,pause:{reason:'protected_item_changed'}},config),/旧版物品保护/);
 assert.match(pauseMessage(row,{...config,running:false}),/全部远征/);
 assert.equal(pauseMessage(row,{running:true,instances:{}}),'');
 assert.equal(pauseMessage({...row,status:'paused',pause:{reason:'legacy_instance_pause'}},{running:true,instances:{'host:a':true}}),'');
});
