"""
RC锁仓提醒配置管理模块
用于存储和管理各群聊的RC锁仓提醒配置
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "rc_lock_reminder_config.json")

def load_config() -> Dict[str, Any]:
    """加载配置文件"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"reminders": {}}

def save_config(config: Dict[str, Any]):
    """保存配置文件"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def set_rc_lock_reminder(chat_id: str, 
                         advance_days: int = 2,
                         related_bu_team: str = None,
                         issuetype: str = None,
                         status: str = None,
                         assignee: str = None,
                         priority: str = None,
                         project: str = None,
                         enabled: bool = True,
                         reminder_hour: int = 9,
                         reminder_minute: int = 0) -> Dict[str, Any]:
    """
    设置RC锁仓提醒
    
    Args:
        chat_id: 群聊ID
        advance_days: 提前几天提醒，默认2天
        related_bu_team: 关联业务单元团队过滤
        issuetype: 问题类型过滤
        status: 状态过滤
        assignee: 经办人过滤
        priority: 优先级过滤
        project: 项目过滤
        enabled: 是否启用
        reminder_hour: 提醒时间（小时），默认9点
        reminder_minute: 提醒时间（分钟），默认0分
    
    Returns:
        设置结果
    """
    config = load_config()
    
    # 验证时间参数
    if not (0 <= reminder_hour <= 23):
        return {
            "success": False,
            "message": "提醒时间小时数必须在0-23之间"
        }
    if not (0 <= reminder_minute <= 59):
        return {
            "success": False,
            "message": "提醒时间分钟数必须在0-59之间"
        }
    
    # 如果已存在配置，保留创建时间，否则设置创建时间
    existing_reminder = config["reminders"].get(chat_id)
    created_at = existing_reminder.get("created_at") if existing_reminder else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    reminder = {
        "chat_id": chat_id,
        "advance_days": advance_days,
        "filters": {
            "related_bu_team": related_bu_team,
            "issuetype": issuetype,
            "status": status,
            "assignee": assignee,
            "priority": priority,
            "project": project
        },
        "enabled": enabled,
        "reminder_hour": reminder_hour,
        "reminder_minute": reminder_minute,
        "created_at": created_at,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    config["reminders"][chat_id] = reminder
    save_config(config)
    
    return {
        "success": True,
        "message": f"已设置RC锁仓提醒，将在每天{reminder_hour:02d}:{reminder_minute:02d}检查，锁仓前{advance_days}天发送提醒",
        "reminder": reminder
    }

def get_rc_lock_reminder(chat_id: str) -> Optional[Dict[str, Any]]:
    """
    获取指定群聊的RC锁仓提醒配置
    
    Args:
        chat_id: 群聊ID
    
    Returns:
        提醒配置，如果不存在则返回None
    """
    config = load_config()
    return config["reminders"].get(chat_id)

def delete_rc_lock_reminder(chat_id: str) -> Dict[str, Any]:
    """
    删除RC锁仓提醒
    
    Args:
        chat_id: 群聊ID
    
    Returns:
        删除结果
    """
    config = load_config()
    
    if chat_id in config["reminders"]:
        del config["reminders"][chat_id]
        save_config(config)
        return {
            "success": True,
            "message": "已删除RC锁仓提醒"
        }
    else:
        return {
            "success": False,
            "message": "未找到该群聊的RC锁仓提醒配置"
        }

def list_all_reminders() -> List[Dict[str, Any]]:
    """
    获取所有RC锁仓提醒配置
    
    Returns:
        所有提醒配置列表
    """
    config = load_config()
    return list(config["reminders"].values())

def get_enabled_reminders() -> List[Dict[str, Any]]:
    """
    获取所有启用的RC锁仓提醒配置
    
    Returns:
        启用的提醒配置列表（兼容旧配置，自动添加默认提醒时间）
    """
    config = load_config()
    reminders = []
    for r in config["reminders"].values():
        if r.get("enabled", True):
            # 兼容旧配置：如果没有设置提醒时间，使用默认值9:00
            if "reminder_hour" not in r:
                r["reminder_hour"] = 9
            if "reminder_minute" not in r:
                r["reminder_minute"] = 0
            reminders.append(r)
    return reminders
