const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(){
 const item={isNull:()=>false,get_Uid:()=>'old',get_ConfigID:()=>2010101,get_Count:()=>1,get_Kind:()=>2,get_Config:()=>({Tradable:false,Grade:1,Tier:1}),get_IsLocked:()=>false,get_IsServerConfirmed:()=>true,get_Sockets:()=>[]};
 const inventory={items:[item],get_Has(){return this.items;}},selected=[],calls=[];let include=true;
 const cube={get_IsEmpty:()=>!selected.length,get_Has:()=>selected,CanReserveMore:()=>!selected.length};
 const popup={OnClickClose:()=>calls.push('close')};
 const view={CanStartExecute:()=>true,get_SelectedTier:()=>1,get_IncludeStorageToggle:()=>({get_isOn:()=>include,set_isOn:x=>{include=x;calls.push('storage');}}),
  SetSelectedTier:()=>{throw Error('decompose_has_no_dropdown');},RebuildRules:()=>calls.push('rules'),get_CanExecute:()=>!!selected.length,
  TryExecute:()=>{calls.push('execute');inventory.items=[];return true;},ReleaseAll:()=>{calls.push('release');selected.length=0;}};
 const im={get_Inventory:()=>inventory,get_Cube:()=>cube,get_Input:()=>({get_IsHolding:()=>false}),IsInUse:()=>false,IsEquipped:()=>false,FindRegistrations:()=>[],TryMoveToCube:p=>{selected.push(p);return true;}};
 const c={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],ref:x=>x,call:(o,n,a=[])=>o[n](...a),single:n=>n==='DG.UI.PopupLayoutHandler'?{get_AnyPopupOpen:()=>false}:n==='DG.Manager.CurrencyManager'?{Get:()=>0}:im};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nsceneObject=n=>n.endsWith("CubePopup")?testPopup:testView;activateCubeView=()=>testPopup;globalThis.run=cubeAction;',c);c.testView=view;c.testPopup=popup;
 return {view,popup,inventory,selected,calls,get include(){return include;},run:()=>c.run({kind:'decompose',tier:2,maxGrade:1,allowed:['old']})};
}
test('decomposition accepts a native view without a tier dropdown',()=>{
 const f=fixture(),r=f.run();assert.equal(r.status,'confirmed');assert.equal(r.consumed[0].count,1);assert.equal(f.include,true);
});
test('native busy state never opens the popup, releases reservations or consumes items',()=>{
 const f=fixture();f.view.CanStartExecute=()=>false;
 assert.equal(f.run().reason,'native_cube_busy');assert.deepEqual(f.calls,[]);assert.equal(f.inventory.items.length,1);
});
test('a cleanup exception preserves proven consumption and still restores the other settings',()=>{
 const f=fixture();f.view.ReleaseAll=()=>{throw Error('release_failed');};
 const r=f.run();assert.equal(r.status,'confirmed');assert.equal(r.reason,'native_cleanup_incomplete');assert.equal(r.cleanupIssues[0],'release');assert.equal(f.include,true);assert.ok(f.calls.includes('close'));
});
test('preparation and execution failures remain distinct even when popup cleanup also fails',()=>{
 let f=fixture();f.popup.OnClickClose=()=>{throw Error('close_failed');};f.view.RebuildRules=()=>{throw Error('sensitive_path');};
 let r=f.run();assert.equal(r.status,'waiting');assert.equal(r.reason,'native_preparation_failed');assert.equal(r.step,'configure');assert.equal(f.inventory.items.length,1);assert.equal(f.include,true);assert.ok(!JSON.stringify(r).includes('sensitive_path'));
 f=fixture();f.view.TryExecute=()=>{f.inventory.items=[];throw Error('response_lost');};f.popup.OnClickClose=()=>{throw Error('close_failed');};
 assert.throws(()=>f.run(),/response_lost/);assert.equal(f.include,true);assert.equal(f.selected.length,0);
});
test('empty reservation releases the view and provides the real waiting reason',()=>{
 const f=fixture();f.view.get_CanExecute=()=>false;
 const r=f.run();assert.equal(r.reason,'native_recipe_not_ready');assert.equal(f.selected.length,0);assert.equal(f.inventory.items.length,1);
});
