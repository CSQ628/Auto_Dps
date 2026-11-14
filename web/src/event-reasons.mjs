const reasons={
 native_refund_blocked:'原生暂不允许天赋退款，继续主线重试与其他成长，稍后自动检查',
 skill_catalogue_invalid:'技能目录校验未通过，记录警告并继续其他自动化',
 frontier_battle_in_progress:'已进入未通关前沿，等本场结算后再返回练级；其他成长继续',
 box_receipt_store_unavailable:'回执保存暂未完成，其他自动化继续；未知结果不会重复消费',
 connection_recovered:'连接已自动恢复，继续自动化',automatic_pause_recovered:'旧版自动保护暂停已恢复，继续自动化',
 tradable_state_changed:'仅记录异常警告，主机与沙盒的自动化继续运行',
 native_box_rejected:'游戏未接受本次开箱，已保留箱子并稍后重试',box_result_unconfirmed:'开箱结果尚未确认，保留预约避免重复提交',box_queue_changed:'箱子数量已变化，重新检查',
 manual_panel_conflict:'当前手动窗口与此操作冲突，关闭窗口后恢复',sort_protected_stack:'此页有受保护的可堆叠物品，仅跳过本页排序；开箱与其他成长继续检查',sort_conservation_failed:'本次排序核对有差异，继续检查其他可执行操作',item_drag_active:'正在拖拽物品，放下后恢复',
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
