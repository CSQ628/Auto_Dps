const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const context={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],ref:x=>x,call:(o,n,a=[])=>o[n](...a)};
vm.createContext(context);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nglobalThis.subject={hasAttachmentSpace,materialReceipt};',context);
const {hasAttachmentSpace,materialReceipt}=context.subject;
test('compatible material is skipped when its actual socket type is full',()=>{
 const deco={ItemType:1},gem={ItemType:2};
 const material={get_AttachmentConfig:()=>deco};
 const equipment={get_EquipmentConfig:()=>({}),get_Sockets:()=>[{get_Config:()=>deco}]};
 const im={CanAttach:()=>true,GetSocketCount:(_,type)=>type===1?1:2};
 assert.equal(hasAttachmentSpace(im,equipment,material),false);
 equipment.get_Sockets=()=>[{get_Config:()=>gem}];assert.equal(hasAttachmentSpace(im,equipment,material),true);
 im.CanAttach=()=>false;assert.equal(hasAttachmentSpace(im,equipment,material),false);
});
test('partial stack consumption has a confirmed quantity even when its UID survives',()=>{
 const before=[{uid:'stack',id:1,count:20}],after=[{uid:'stack',id:1,count:11},{uid:'result',id:2,count:1}];
 const receipt=materialReceipt(before,after,Array.from({length:9},()=>before[0]));
 assert.equal(receipt.consumed.length,1);assert.equal(receipt.consumed[0].count,9);assert.equal(receipt.consumed[0].reserved,9);
 assert.equal(receipt.produced[0].id,2);assert.equal(receipt.produced[0].count,1);
});
test('reservation without a quantity change never claims consumption',()=>{
 const before=[{uid:'stack',count:9}];const receipt=materialReceipt(before,before,Array(9).fill(before[0]));
 assert.equal(receipt.consumed.length,0);assert.equal(receipt.produced.length,0);
});
test('switching from equipment to tier-zero materials refreshes native options and rules before consuming',()=>{
 const item=(uid,count,id=1)=>({uid,count,id,isNull:()=>false,get_Uid(){return this.uid;},get_ConfigID(){return this.id;},get_Count(){return this.count;},get_Kind:()=>16,get_Config:()=>({Tradable:false,Grade:1,Tier:0}),get_IsLocked:()=>false,get_IsServerConfirmed:()=>true,get_Sockets:()=>[]});
 const stack=item('stack',20),inventory={items:[stack],get_Has(){return this.items;}},selected=[];
 let category=0,tier=5,options=[1,2,3,4,5],ruleCategory=0,ruleTier=5,include=true,failPreparation=true;
 const cube={get_IsEmpty:()=>!selected.length,get_Has:()=>selected,CanReserveMore:p=>ruleCategory===2&&ruleTier===0&&selected.length<9};
 const view={get_SelectedTier:()=>tier,get_SelectedCategory:()=>category,get_IncludeStorageToggle:()=>({get_isOn:()=>include,set_isOn:x=>{include=x;}}),SetCategory:x=>{category=x;},RefreshLevelRangeOptions:()=>{options=category===2?[0]:[1,2,3,4,5];},SetSelectedTier:x=>{if(options.includes(x))tier=x;},RebuildRules:()=>{if(failPreparation)throw Error('view_not_ready');ruleCategory=category;ruleTier=tier;},get_CanExecute:()=>selected.length===9,TryExecute:()=>{stack.count-=selected.length;inventory.items.push(item('produced',1,2));return true;},ReleaseAll:()=>{selected.length=0;}};
 const im={get_Inventory:()=>inventory,get_Cube:()=>cube,get_Input:()=>({get_IsHolding:()=>false}),IsInUse:()=>false,IsEquipped:()=>false,FindRegistrations:()=>[],TryMoveToCube:p=>{if(!cube.CanReserveMore(p))return false;selected.push(p);return true;}};
 const c={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],ref:x=>x,call:(o,n,a=[])=>o[n](...a),single:n=>n==='DG.UI.PopupLayoutHandler'?{get_AnyPopupOpen:()=>false}:n==='DG.Manager.CurrencyManager'?{Get:()=>0}:im};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nsceneObject=()=>globalThis.testView;activateCubeView=()=>({OnClickClose(){}});globalThis.run=cubeAction;',c);c.testView=view;
 const cmd={kind:'combine',category:2,tier:0,maxGrade:1,allowed:['stack']};
 const waiting=c.run(cmd);assert.equal(waiting.status,'waiting');assert.equal(waiting.reason,'native_preparation_failed');
 assert.equal(stack.count,20);assert.equal(selected.length,0);assert.equal(category,0);assert.equal(tier,5);assert.equal(include,true);
 failPreparation=false;
 const result=c.run(cmd);
 assert.equal(result.status,'confirmed');assert.equal(result.consumed[0].count,9);assert.equal(stack.count,11);assert.equal(result.produced[0].id,2);
 assert.equal(category,0);assert.equal(tier,5);assert.equal(include,true);assert.equal(selected.length,0);
 view.TryExecute=()=>{stack.count-=selected.length;throw Error('response_lost_after_submission');};
 assert.throws(()=>c.run(cmd),/response_lost_after_submission/);assert.equal(stack.count,2);assert.equal(selected.length,0);assert.equal(include,true);
});

test('decomposition uses the base view lifecycle without assemble/refine-only methods',()=>{
 const item={isNull:()=>false,get_Uid:()=>'old',get_ConfigID:()=>2010101,get_Count:()=>1,get_Kind:()=>2,get_Config:()=>({Tradable:false,Grade:1,Tier:1}),get_IsLocked:()=>false,get_IsServerConfirmed:()=>true,get_Sockets:()=>[]};
 const inventory={items:[item],get_Has(){return this.items;}},selected=[];let tier=5,include=true,soul=100;
 const cube={get_IsEmpty:()=>!selected.length,get_Has:()=>selected,CanReserveMore:()=>selected.length===0};
 const view={get_SelectedTier:()=>tier,get_IncludeStorageToggle:()=>({get_isOn:()=>include,set_isOn:x=>{include=x;}}),SetSelectedTier:x=>{tier=x;},RebuildRules:()=>{},get_CanExecute:()=>selected.length===1,TryExecute:()=>{inventory.items=[];soul+=50;return true;},ReleaseAll:()=>{selected.length=0;}};
 const im={get_Inventory:()=>inventory,get_Cube:()=>cube,get_Input:()=>({get_IsHolding:()=>false}),IsInUse:()=>false,IsEquipped:()=>false,FindRegistrations:()=>[],TryMoveToCube:p=>{if(!cube.CanReserveMore(p))return false;selected.push(p);return true;}};
 const c={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],ref:x=>x,call:(o,n,a=[])=>o[n](...a),single:n=>n==='DG.UI.PopupLayoutHandler'?{get_AnyPopupOpen:()=>false}:n==='DG.Manager.CurrencyManager'?{Get:()=>soul}:im};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nsceneObject=()=>globalThis.testView;activateCubeView=()=>({OnClickClose(){}});globalThis.run=cubeAction;',c);c.testView=view;
 const result=c.run({kind:'decompose',tier:1,maxGrade:1,allowed:['old']});
 assert.equal(result.status,'confirmed');assert.equal(result.consumed[0].uid,'old');assert.equal(result.afterCount,0);
 assert.equal(result.soulAfter-result.soulBefore,50);assert.equal(tier,5);assert.equal(include,true);assert.equal(selected.length,0);
});
