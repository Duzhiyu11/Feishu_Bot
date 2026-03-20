"""
群聊提醒配置管理模块
用于存储和管理各群聊的提醒时间配置
使用 JSON 配置文件，不依赖数据库
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "group_reminder_config.json")

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

def set_group_reminder(group_id: str,
                      reminder_hour: int = 17,
                      reminder_minute: int = 0,
                      enabled: bool = True) -> Dict[str, Any]:
    """
    设置群聊提醒配置
    
    Args:
        group_id: 群聊ID
        reminder_hour: 提醒小时，默认17点
        reminder_minute: 提醒分钟，默认0分
        enabled: 是否启用
    
    Returns:
        设置结果
    """
    config = load_config()
    
    reminder = {
        "group_id": group_id,
        "reminder_hour": reminder_hour,
        "reminder_minute": reminder_minute,
        "enabled": enabled,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    config["reminders"][group_id] = reminder
    save_config(config)
    
    return {
        "success": True,
        "message": f"已设置群聊提醒，将在每天{reminder_hour:02d}:{reminder_minute:02d}发送提醒",
        "reminder": reminder
    }

def get_group_reminder(group_id: str) -> Optional[Dict[str, Any]]:
    """
    获取指定群聊的提醒配置
    
    Args:
        group_id: 群聊ID
    
    Returns:
        提醒配置，如果不存在则返回None
    """
    config = load_config()
    return config["reminders"].get(group_id)

def delete_group_reminder(group_id: str) -> Dict[str, Any]:
    """
    删除群聊提醒配置
    
    Args:
        group_id: 群聊ID
    
    Returns:
        删除结果
    """
    config = load_config()
    
    if group_id in config["reminders"]:
        del config["reminders"][group_id]
        save_config(config)
        return {
            "success": True,
            "message": "已删除群聊提醒配置"
        }
    else:
        return {
            "success": False,
            "message": "未找到该群聊的提醒配置"
        }

def list_all_reminders() -> List[Dict[str, Any]]:
    """
    获取所有群聊提醒配置
    
    Returns:
        所有提醒配置列表
    """
    config = load_config()
    return list(config["reminders"].values())

def get_enabled_reminders() -> List[Dict[str, Any]]:
    """
    获取所有启用的群聊提醒配置
    
    Returns:
        启用的提醒配置列表
    """
    config = load_config()
    return [r for r in config["reminders"].values() if r.get("enabled", True)]

def get_reminder_time(group_id: str) -> tuple[int, int]:
    """
    获取群聊的提醒时间
    
    Args:
        group_id: 群聊ID
    
    Returns:
        (hour, minute) 元组，如果不存在则返回默认值 (17, 0)
    """
    reminder = get_group_reminder(group_id)
    if reminder and reminder.get("enabled", True):
        return (reminder.get("reminder_hour", 17), reminder.get("reminder_minute", 0))
    return (17, 0)  # 默认值
