export function pauseMessage(instance,config={}){
 if(config.running===false)return '全部远征已暂停，点击“开始自动远征”恢复';
 const disabled=config.instances?.[instance?.identity]===false,reason=instance?.pause?.reason;
 if(!disabled)return '';
 if(reason==='protected_item_changed')return '旧版物品保护曾暂停此实例；正在自动恢复；新版异常仅记录警告';
 if(reason==='manual_instance_pause')return '当前实例已手动暂停，可恢复当前实例';
 return '当前实例已暂停（旧版未记录原因），可恢复当前实例';
}

export function maintenanceMessage(instance,config,now=Date.now()/1000){
 if(!instance?.maintenance?.active)return '';
 if(!config.running||instance.status==='paused'||config.instances?.[instance.identity]===false)return '维护等待已暂停，恢复远征后继续重连';
 if(!config.auto_launch)return '服务器维护中，自动启动已关闭；手动打开游戏后自动检查恢复';
 const seconds=Math.max(0,Math.ceil((instance.maintenance.retry_at||now)-now));
 if(!seconds)return '服务器维护中，正在等待下一次登录检查';
 return `服务器维护中，约 ${Math.floor(seconds/60)} 分 ${seconds%60} 秒后重试；登录就绪后自动接续`;
}
