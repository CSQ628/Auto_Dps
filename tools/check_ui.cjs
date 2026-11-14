const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.DPS_TEST_URL||'http://127.0.0.1:17861',output=process.env.DPS_TEST_OUTPUT||'runtime/release-ui';

(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],report={};
 page.on('pageerror',error=>errors.push(error.message));
 page.on('console',message=>{if(message.type()==='error'&&!message.text().includes('503 (Service Unavailable)')&&!message.text().includes('400 (Bad Request)'))errors.push(message.text());});
 const state=()=>page.evaluate(async()=>await (await fetch('/api/state')).json());
 const field=key=>page.locator(`[data-parameter="${key}"]`);
 const saved=async(key)=>{await field(key).locator('.parameter-save').getByText('已保存',{exact:true}).waitFor();};
 const persist=async(key,value,scope='strategy')=>{
  await page.waitForFunction(async({key,value,scope})=>{
   const s=await(await fetch('/api/state')).json();return (scope==='root'?s.config[key]:s.config.strategy[key])===value;
  },{key,value,scope});
 };
 const inspect=async(name)=>{
  await page.evaluate(()=>window.scrollTo(0,0));
  report[name]=await page.evaluate(()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth,
   overflow:[...document.querySelectorAll('.panel,.module,.parameter-row')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>e.className)}));
  await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});
  assert.ok(report[name].documentWidth<=report[name].width);assert.deepEqual(report[name].overflow,[]);
 };
 try{
  await page.goto(base);const dialog=page.getByRole('dialog'),agree=page.getByRole('button',{name:/我同意/});
  await dialog.waitFor();const started=Date.now();assert.ok(await agree.isDisabled());
  assert.ok((await dialog.innerText()).includes('本项目完全开源免费'));
  await page.keyboard.press('Escape');assert.ok(await dialog.isVisible());
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'notice-mobile.png')});
  await page.waitForFunction(()=>{const button=[...document.querySelectorAll('[role="dialog"] button')].find(e=>e.textContent==='我同意');return button&&!button.disabled;});
  report.consentDelayMs=Date.now()-started;assert.ok(report.consentDelayMs>=2700);
  await agree.click();await dialog.waitFor({state:'hidden'});assert.equal((await state()).preferences.noticeAccepted,true);
  await page.reload();await page.getByRole('heading',{name:'远征概览'}).waitFor();assert.equal(await dialog.count(),0);
  await page.setViewportSize({width:1440,height:1000});
  const picker=await page.locator('#current-instance').boundingBox();
  const connect=await page.getByRole('button',{name:'自定义多个连接',exact:true}).boundingBox();
  assert.ok(picker&&connect&&connect.x>=picker.x+picker.width,'custom connections button must sit to the right of the current-view picker');
  report.connectionButtonRightOfCurrentView=true;
  await page.getByRole('button',{name:'自动化策略',exact:true}).click();
  assert.equal(await page.locator('.module').count(),16);
  for(const details of await page.locator('.module-tuning').all())await details.locator('summary').click();
  for(const module of await page.locator('.module').all())assert.ok(await module.locator('[data-parameter]').count());
  assert.ok(await page.locator('.app-version').getByText('v'+(await state()).version,{exact:true}).isVisible());
  await inspect('modules-desktop');await page.setViewportSize({width:700,height:653});await inspect('modules-700');
  await page.setViewportSize({width:390,height:844});await inspect('modules-mobile');
  await page.getByRole('button',{name:'参数设置',exact:true}).click();
  await page.getByRole('heading',{name:'基础参数与策略'}).waitFor();assert.equal(await page.locator('[data-parameter]').count(),(await state()).parameters.fields.length);
  const initial=(await state()).config;
  const interval=page.getByRole('spinbutton',{name:'巡检间隔',exact:true});
  let finishFirst;
  const firstReturned=new Promise(resolve=>finishFirst=resolve);
  await page.route('**/api/config',async route=>{const response=await route.fetch();finishFirst();await new Promise(r=>setTimeout(r,1000));await route.fulfill({response});},{times:1});
  await interval.fill('3.5');await firstReturned;await interval.fill('4');
  await saved('interval');await persist('interval',4,'root');assert.equal(await interval.inputValue(),'4');
  await interval.fill(String(initial.interval));await saved('interval');await persist('interval',initial.interval,'root');
  const batch=page.getByRole('spinbutton',{name:'单次回收淘汰装备上限',exact:true});
  await page.route('**/api/config',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'模拟保存失败'})}),{times:1});
  await batch.fill('11');await field('recycle_batch').getByText('保存失败',{exact:true}).waitFor();assert.equal(await batch.inputValue(),'11');
  assert.equal((await state()).config.strategy.recycle_batch,initial.strategy.recycle_batch);
  await field('recycle_batch').getByRole('button',{name:'重试保存'}).click();await persist('recycle_batch',11);await saved('recycle_batch');
  await batch.fill('0');await field('recycle_batch').getByText(/请输入/).waitFor();assert.equal((await state()).config.strategy.recycle_batch,11);
  await page.locator('#parameter-group-workshop').getByRole('button',{name:'恢复本组默认值'}).click();
  await persist('recycle_batch',12);await page.waitForFunction(()=>document.querySelector('#parameter-recycle_batch').value==='12');
  const recommended=page.getByRole('switch',{name:'使用职业推荐主动组合',exact:true});await recommended.uncheck();await persist('recommended_actives',false);
  await page.getByRole('combobox',{name:'跟随宠物偏好'}).click();await page.getByRole('option',{name:'完全保留，不自动选择',exact:true}).click();await persist('pet_mode','keep');
  await page.reload();await page.getByRole('button',{name:'参数设置',exact:true}).click();await recommended.waitFor();assert.equal(await recommended.isChecked(),false);
  assert.equal(await page.getByRole('combobox',{name:'跟随宠物偏好'}).textContent(),'完全保留，不自动选择');
  await recommended.check();await persist('recommended_actives',true);
  await page.getByRole('combobox',{name:'跟随宠物偏好'}).click();await page.getByRole('option',{name:'保留当前，空缺时补齐',exact:true}).click();await persist('pet_mode','auto');
  await inspect('parameters-mobile');await page.setViewportSize({width:1440,height:1000});await inspect('parameters-desktop');

  for(const theme of ['深色界面','浅色界面']){
   await page.getByRole('combobox',{name:'界面主题',exact:true}).click();await page.getByRole('option',{name:theme,exact:true}).click();
   for(const width of [1440,700,390]){
    await page.setViewportSize({width,height:900});
    for(const name of ['远征概览','自动化策略','沙盒与实例','运行记录','参数设置']){
     await page.getByRole('button',{name,exact:true}).click();await page.getByRole('heading',{name,exact:true,level:1}).waitFor();await inspect(theme+'-'+name+'-'+width);
    }
   }
  }
  await page.getByRole('button',{name:'自定义多个连接',exact:true}).click();await dialog.waitFor();
  await page.getByRole('button',{name:'重新扫描',exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelector('.connection-toolbar')?.textContent.includes('找到'));
  await page.getByRole('textbox',{name:'手动填写游戏 PID'}).fill('1');await page.getByRole('button',{name:'绑定实例',exact:true}).click();
  await dialog.getByRole('alert').waitFor();report.invalidPidRejected=true;
  await inspect('connection-mobile');await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
  await page.setViewportSize({width:1440,height:1000});await page.getByRole('button',{name:'自定义多个连接',exact:true}).click();await dialog.waitFor();
  await page.waitForFunction(()=>document.querySelector('.connection-toolbar')?.textContent.includes('找到'));
  for(const pid of [22172,30952]){await page.getByRole('textbox',{name:'手动填写游戏 PID'}).fill(String(pid));await page.getByRole('button',{name:'绑定实例',exact:true}).click();await dialog.getByRole('status').waitFor();assert.ok(await dialog.isVisible());}
  const bound=(await state()).instances.filter(i=>i.binding==='manual');assert.equal(bound.length,2);report.multipleBindings=bound.length;
  await inspect('connection-desktop');await page.getByRole('button',{name:'完成',exact:true}).click();
  await page.getByRole('button',{name:'参数设置',exact:true}).click();
  const source=page.locator('.source-address a');assert.equal(await source.getAttribute('href'),'https://github.com/weixiao030/Auto_Dps');
  await page.getByRole('button',{name:'放大赞赏码'}).click();await dialog.waitFor();
  await page.waitForFunction(()=>{const image=document.querySelector('.appreciation-dialog img');return image?.complete&&image.naturalWidth>0;});
  await page.getByRole('button',{name:'关闭',exact:true}).click();
  report.rows=(await state()).parameters.fields.length;report.modules=(await state()).modules.length;report.preferences=(await state()).preferences;report.errors=errors;assert.deepEqual(errors,[]);
 }finally{fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({...report,errors},null,2));await browser.close();}
 console.log(JSON.stringify(report));
})().catch(error=>{console.error(error);process.exitCode=1;});
