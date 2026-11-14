const test=require('node:test'),assert=require('node:assert/strict');

test('default dashboard selection follows the highest progressed live account',async()=>{
 const {preferredInstance}=await import('../web/src/instance-selection.mjs');
 const low={id:'host',snapshot:{record:{maxCleared:29}}};
 const high={id:'sandbox',snapshot:{record:{maxCleared:39}}};
 assert.equal(preferredInstance([low,high]),high);
 assert.equal(preferredInstance([high,low]),high);
 assert.equal(preferredInstance([low,{id:'loading',snapshot:null}]),low);
});

test('native stage ids render with the game chapter and stage labels',async()=>{
 const {mapStageName}=await import('../web/src/instance-selection.mjs');
 assert.deepEqual([18,20,28,29,30,31,39,40].map(mapStageName),['2-8','2-10','3-8','3-9','3-10','4-1','4-9','4-10']);
 assert.equal(mapStageName(0),'—');
});
