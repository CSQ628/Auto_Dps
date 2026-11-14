export function refinementStatusMessage(state){
 if(!state)return '正在读取精炼材料和装备插槽';
 if(state.status==='disabled')return '自动精炼已关闭，精炼材料仍按合成开关处理';
 if(state.status==='no_target')return '暂无可精炼的上阵装备';
 if(state.status==='ready')return `已安排 ${state.planned} 次精炼，${state.ready} 次材料就绪；可执行的同槽换装先完成`;
 if(state.status==='storage_pending')return `${state.warehousePending} 次精炼需先取出仓库材料，背包满时联动安全腾位`;
 return `暂无匹配的安全材料或空插槽，可用材料 ${state.availableMaterials??0} 件${state.protectedMaterials?`，另有 ${state.protectedMaterials} 件受保护`:''}`;
}

export function refinementMaterialStatusMessage(state){
 if(!state)return '正在读取精炼材料合成配方';
 if(state.status==='disabled')return '自动合成已关闭，精炼材料不自动合成';
 if(state.status==='ready')return `已匹配 ${state.groups} 组，${state.ready} 组材料就绪；完整配方已保留，不被镶嵌占用`;
 if(state.status==='storage_pending')return `${state.warehousePending} 组需取出仓库材料，背包满时先安排安全腾位`;
 if(state.status==='native_locked')return '材料对应配方尚未达到原生方块等级要求，解锁后自动重算';
 const nearest=state.nearest?.[0];
 const supply=nearest?`最近一组同品质材料 ${nearest.available} / ${nearest.required} 件`:'暂无满足配方的安全闲置精炼材料';
 return `${supply}${state.protected?`；另有 ${state.protected} 件受保护`:''}${state.storageEnabled===false&&state.warehouse?`；仓库 ${state.warehouse} 件未参与，仓库模块已关闭`:''}`;
}
