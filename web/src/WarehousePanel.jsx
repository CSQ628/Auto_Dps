import React from 'react';
import {HardDrives,ShieldCheck,Stack} from '@phosphor-icons/react';

export default function WarehousePanel({instance}){
 const s=instance?.snapshot,storage=s?.storage,flow=s?.inventoryFlow,fusion=s?.combining,recycling=s?.recycling;
 return <section className="panel workshop" aria-label="物品与多页仓库"><div className="section-title"><div><h2>物品与仓库</h2><p>保留升级装备，优先合成，再回收闲置装备，最后按游戏规则排序。</p></div><HardDrives size={21}/></div>
  <div className="workshop-stats"><div><Stack size={19}/><span>背包</span><strong>{s?.inventory.count??'待'}<small> / {s?.inventory.capacity??'待'}</small></strong></div><div><HardDrives size={19}/><span>所有已解锁仓库</span><strong>{storage?.count??'待'}<small> / {storage?.capacity??'待'}</small></strong></div><div><ShieldCheck size={19}/><span>保留的升级装备</span><strong>{recycling?.reservedEquipment??'待'}<small> 件</small></strong></div></div>
  {storage?.tabs&&<div className="warehouse-pages" aria-label="仓库分页">{storage.tabs.filter(t=>t.open).map(t=><div key={t.id} className={t.count>=t.capacity?'warehouse-page full':'warehouse-page'}><span>第 {t.id+1} 页</span><strong>{t.count??'待读取'} <small>/ {t.capacity??'待读取'}</small></strong><small>{t.count>=t.capacity?'已满，安排取料与整理':'已纳入自动整理'}</small></div>)}</div>}
  <div className="warehouse-explanation"><h3>现在为什么处理或等待</h3><p role="status">{!s?'连接游戏后显示每页占用和处理原因。':s.manualPanelOpen?'你正在查看游戏窗口，物品与切场操作等待关闭；不冲突的成长继续。':flow?.blocked?'背包和仓库暂时没有可用的安全交换组合，等待配方、装备或容量变化。':fusion?.needSpace?'背包需要先腾出取料空位，随后继续合成。':fusion?.warehousePending?`${fusion.warehousePending} 组合成材料位于仓库，正在安排取出。`:fusion?.ready?`${fusion.ready} 组材料已就绪，优先安排合成。`:recycling?.obsolete?`可回收闲置装备 ${recycling.obsolete} 件，完整配方和升级装备已经排除。`:'当前没有可执行的物品操作，继续检查掉落、配方和装备需求。'}</p>
   <div className="warehouse-details"><span>已匹配配方 <b>{fusion?.groups??0} 组</b></span><span>配方保留材料 <b>{flow?.recipeReserved??0} 件</b></span><span>受消费保护 <b>{flow?.protectedMaterials??0} 件</b></span><span>系统排序 <b>{instance?.feature_evidence?.sort?.confirmed??0} 次确认</b></span></div>
  </div><p className="field-help">可交易装备可以换装与转仓，交易属性保持。锁定、已镶嵌、未确认和配方所需物品不会作为闲置材料回收。</p>
 </section>;
}
