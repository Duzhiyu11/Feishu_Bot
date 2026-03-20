"""
数据类定义（非数据库模型）
这些类仅用于数据传输和业务逻辑，不会创建数据库表
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class Meeting:
    """会议数据类（不创建数据库表，仅用于数据传输）"""
    title: str  # 会议标题
    description: Optional[str] = None  # 会议描述
    group_id: Optional[str] = None  # 群组ID
    start_time: Optional[datetime] = None  # 会议开始时间
    end_time: Optional[datetime] = None  # 会议结束时间
    attendees: Optional[List[Dict[str, Any]]] = None  # 参会人列表 [{"user_id": "ou_xxx", "user_name": "姓名"}]
    created_by_id: Optional[str] = None  # 创建人ID
    meeting_id: Optional[str] = None  # 飞书会议ID
    event_id: Optional[str] = None  # 飞书日历事件ID
    calendar_id: Optional[str] = None  # 日历ID
    is_regular: bool = False  # 是否例会
    regular_config: Optional[Dict[str, Any]] = None  # 例会配置 {"type": "weekly", "day_of_week": 1, "time": "14:00"}
    need_topic_reminder: bool = False  # 是否需要议题提醒
    topic_reminder_sent: bool = False  # 议题提醒是否已发送
    topics: Optional[List[Dict[str, Any]]] = None  # 会议议题列表 [{"topic": "议题内容", "owner": "负责人"}]
    status: int = 0  # 0:待开始, 1:进行中, 2:已结束, 3:已取消


@dataclass
class RCLockReminderActive:
    """RC锁仓提醒激活群组数据类（不创建数据库表，仅用于数据传输）"""
    group_id: str  # 群组ID
    created_at: Optional[datetime] = None  # 创建时间
