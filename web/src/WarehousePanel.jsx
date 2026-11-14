import React from 'react';
import {pauseMessage} from './runtime-status.mjs';
import {boxStatusMessage} from './box-status.mjs';
import {HardDrives,ShieldCheck,Stack} from '@phosphor-icons/react';

export default function WarehousePanel({instance,config={}}){
 const s=instance?.snapshot,storage=s?.storage,flow=s?.inventoryFlow,fusion=s?.combining,recycling=s?.recycling,forge=s?.forging;
 const parts={1:'主武器',2:'副武器',3:'头盔',4:'护甲',5:'手套',6:'靴子',7:'饰品'};
 const sourceText=!forge?.sourceKnown?'':forge.source==='drop'?'按当前可刷材料筹备':forge.source==='fusion_ready'||forge.source==='fusion'?'材料可经合成随机获得，不保证一次产出':forge.source==='future'?'材料主要来自后续关卡或尚未开放的合成':'';
 const forgeText=!forge?'正在读取制作条件':forge.status==='disabled'?'自动制作已关闭':forge.status==='no_need'?'当前可用配方没有需要补充的装备':`${parts[forge.part]||'装备'} · 优先级 ${forge.priority??'待检查'}${forge.minLevel?` · ${forge.minLevel}～${forge.maxLevel}级配方`:''}：${forge.ready?'材料齐全，等待制作':forge.status==='storage_pending'?'材料齐全，先取出仓库材料':'等待配方材料'}`;
 const nearest=fusion?.nearest?.[0],fusionText=fusion?.status==='disabled'?'自动合成已关闭':fusion?.groups?`已匹配 ${fusion.groups} 组，${fusion.ready} 组可执行`:(nearest?`材料尚未凑齐：最近一组 ${nearest.available} / ${nearest.required} 件，同品质并符合配方等级范围后自动合成`:'暂无可合成的闲置材料');
 return <section className="panel workshop" aria-label="物品与多页仓库"><div className="section-title"><div><h2>物品与仓库</h2><p>保留升级装备，按制作 → 合成 → 分解处理，最后按游戏规则排序。</p></div><HardDrives size={21}/></div>
  <div className="workshop-stats"><div><Stack size={19}/><span>背包</span><strong>{s?.inventory.count??'待'}<small> / {s?.inventory.capacity??'待'}</small></strong></div><div><HardDrives size={19}/><span>所有已解锁仓库</span><strong>{storage?.count??'待'}<small> / {storage?.capacity??'待'}</small></strong></div><div><ShieldCheck size={19}/><span>保留的升级装备</span><strong>{recycling?.reservedEquipment??'待'}<small> 件</small></strong></div></div>
  {storage?.tabs&&<div className="warehouse-pages" aria-label="仓库分页">{storage.tabs.filter(t=>t.open).map(t=><div key={t.id} className={t.count>=t.capacity?'warehouse-page full':'warehouse-page'}><span>第 {t.id+1} 页</span><strong>{t.count??'待读取'} <small>/ {t.capacity??'待读取'}</small></strong><small>{t.count>=t.capacity?'已满，安排取料与整理':'已纳入自动整理'}</small></div>)}</div>}
  <div className="warehouse-explanation"><h3>现在为什么处理或等待</h3><p role="status">{!s?'连接游戏后显示每页占用和处理原因。':s.manualPanelOpen?'游戏窗口已保留；工坊与切场等待关闭，不冲突的开箱与成长继续。':flow?.blocked?'背包和仓库暂时没有可用的安全交换组合，等待配方、装备或容量变化。':forge?.ready?'制作材料已齐全，优先安排制作。':forge?.status==='storage_pending'?'制作材料已齐全，先取出仓库材料。':fusion?.needSpace?'背包需要先腾出取料空位，随后继续合成。':fusion?.warehousePending?`${fusion.warehousePending} 组合成材料位于仓库，正在安排取出。`:fusion?.ready?`${fusion.ready} 组材料已就绪，优先安排合成。`:recycling?.obsolete?`可回收闲置装备 ${recycling.obsolete} 件，完整配方和升级装备已经排除。`:'当前没有可执行的物品操作，继续检查掉落、配方和装备需求。'}</p>
   <p aria-label="自动宝箱状态"><b>自动宝箱：</b>{pauseMessage(instance,config)||boxStatusMessage(instance?.box_status)}。</p>
   <p aria-label="自动制作状态"><b>自动制作：</b>{forgeText}。{sourceText&&<span>{sourceText}。当前有效部位共用材料按一份配方保留，余量继续合成。</span>}{forge?.materials?.length>0&&<span> 材料进度 {forge.materials.map((m,i)=>`${i+1}：${m.available}/${m.required}${m.protected?`（另有 ${m.protected} 件受保护）`:''}`).join('；')}。</span>}</p>
   <p aria-label="自动合成状态"><b>自动合成：</b>{fusionText}。</p>
   <p aria-label="旧装备处理状态"><b>旧装备：</b>可回收 {recycling?.obsolete??0} 件；暂留高品质 {recycling?.highGradeRetained??0} 件；锁定 {recycling?.locked??0} 件。{recycling?.socketedAllowed?'已允许旧装备连同镶嵌回收，镶嵌不返还。':`带镶嵌暂留 ${recycling?.socketedRetained??0} 件，需开启回收授权。`}</p>
   <div className="warehouse-details"><span>已匹配配方 <b>{fusion?.groups??0} 组</b></span><span>配方保留材料 <b>{flow?.recipeReserved??0} 件</b></span><span>受消费保护 <b>{flow?.protectedMaterials??0} 件</b></span><span>系统排序 <b>{instance?.feature_evidence?.sort?.confirmed??0} 次确认</b></span></div>
  </div><p className="field-help">可交易装备可以换装与转仓，交易属性保持。锁定装备可无损存取，不参与合成、分解或镶嵌，穿在身上时不替换。未确认、登记和配方保留物品不回收；带镶嵌旧装备按回收开关处理。</p>
 </section>;
}
