const messages={
 box_reading:'正在读取宝箱与背包状态',box_empty:'暂无待开宝箱',box_ready:'每秒检查，有箱连续开启',box_queued:'快速开箱继续，其他成长独立轮换',
 box_paused:'自动远征已暂停',box_disabled:'自动宝箱已关闭',inventory_reserved_slots:'已达到自定义背包空位预留，其他成长继续',box_category_disabled:'待开宝箱所属分类已关闭',inventory_full:'背包已满，正在联动锻造、合成、分解与存仓',
 item_drag_active:'正在拖拽物品，放下后继续开箱',manual_panel_conflict:'当前窗口与开箱冲突，关闭窗口后恢复',
 native_modal_active:'等待确认窗口关闭；若开启了查看窗口时暂停，请先关闭查看窗口',trade_panel_active:'交易窗口正在使用，关闭后继续开箱',
 native_offline:'游戏离线，连接恢复后继续开箱',native_sync_blocked:'等待游戏恢复奖励结算',native_sync_backlog:'等待游戏完成同步',
 native_request_not_started:'上次请求在执行前已取消，将自动重试',box_connection_retry:'开箱连接暂不可用，正在自动重试；其他成长继续',
 box_result_unconfirmed:'正在恢复自动开箱，其他功能继续运行',box_retry_wait:'等待本次开箱重试间隔',
 inventory_relief:'正在自动整理：锻造 > 合成 > 分解，联动存仓，腾位后继续开箱',
 native_box_rejected:'游戏未接受上次开箱，保留箱子并稍后重试',native_box_waiting:'正在重新检查原生开箱条件',
};
export function boxStatusMessage(value){
 const message=messages[value?.reason]||messages.box_reading;
 return Number.isFinite(value?.total)?`待开 ${value.total} 个 · 背包空位 ${value.freeSlots??'待读取'} 格；${message}`:message;
}
