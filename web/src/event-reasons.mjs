const reasons={
 inventory_full:'背包暂无空位，等待安全腾位',storage_full:'已开放仓库暂无空位，等待安全整理',storage_source_changed:'物品所在容器已变化，重新规划存取',
 storage_swap_changed:'交换物品状态已变化，重新检查仓库取料',protected_or_missing_item:'物品受保护或已移动，重新检查',
 user_item_operation:'正在进行物品操作，等待操作结束',user_popup_open:'游戏面板尚未关闭，等待面板处理完成',
 view_not_ready:'等待游戏工坊界面就绪',cube_in_use:'工坊正在使用中，稍后重试',native_cube_busy:'等待原生工坊执行或同步结束',
 native_tier_not_ready:'配方阶级尚未就绪，稍后重新检查',native_material_not_reserved:'原生工坊未接收材料，稍后重新检查',
 autofill_contains_protected_material:'选中材料包含受保护物品，已取消本次分解或合成',native_recipe_not_ready:'材料已预留，等待原生配方条件满足',
 native_preparation_failed:'工坊准备未完成，已停止本次提交并稍后重试',native_cleanup_incomplete:'结果已核验，部分界面清理未完成，后续操作将重新检查',
 protected_or_missing_material:'材料状态已变化，重新检查背包',tower_repeat_not_disabled:'等待原生重复挑战开关关闭',
};
const steps={native_ready:'原生就绪检查',configure:'界面配置',reserve:'材料预留',execute:'执行提交'};
export function eventReason(event){
 const reason=event?.result?.reason;if(!reason)return '';
 const label=reasons[reason]||'原生条件暂未满足，等待下一次检查';
 const step=steps[event.result.step];return step?`${label}（${step}）`:label;
}
