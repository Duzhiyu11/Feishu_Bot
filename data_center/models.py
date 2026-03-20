from magic_jam import DBBase
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey, Text, ForeignKeyConstraint, func
from sqlalchemy.dialects.mysql import LONGTEXT

# 数据类已移至 data_classes.py，避免与数据库模型混淆
# 如需使用 Meeting 或 RCLockReminderActive，请从 data_center.data_classes 导入
class Task(DBBase):
    __tablename__ = "tasks"
    content = Column(LONGTEXT, nullable=False)
    name = Column(String(255), nullable=True)
    group_id = Column(String(255), nullable=True)
    end_time = Column(DateTime, nullable=True)
    done_time = Column(DateTime, nullable=True)
    status = Column(Integer, default=0, nullable=False)#进行中，已完成，已取消，已超时
    source = Column(Integer, default=0, nullable=False)#0:群聊, 1:会议纪要, 2:私聊
    created_by_id = Column(String(255), nullable=True)
    owner_id = Column(String(255), nullable=True)
    task_guid = Column(String(255), nullable=True)


class VIDOData(DBBase):
    __tablename__ = "vido_data"
    link = Column(String(200), nullable=False, unique=True)
    mark = Column(String(100), nullable=False)
    title = Column(String(200), nullable=True)


class VIDOHistory(DBBase):
    __tablename__ = "vido_history"
    query = Column(String(500), nullable=True)
    prompt = Column(LONGTEXT, nullable=True)
    sys_prompt = Column(LONGTEXT, nullable=True)
    answer = Column(LONGTEXT, nullable=True)
    user = Column(String(100), nullable=True)
    group_id = Column(String(255), nullable=True)
    helpful = Column(Integer, default=0, nullable=False)
    harmful = Column(Integer, default=0, nullable=False)


# class GroupReminderConfig(DBBase):
#     __tablename__ = "group_reminder_config"
#     group_id = Column(String(255), nullable=False, unique=True)
#     reminder_hour = Column(Integer, default=17, nullable=False)  # 默认17点
#     reminder_minute = Column(Integer, default=0, nullable=False)  # 默认0分
#     enabled = Column(Boolean, default=True, nullable=False)  # 是否启用