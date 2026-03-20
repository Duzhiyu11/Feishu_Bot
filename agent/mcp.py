from magic_jam import JamMCP
from magic_jam import FeishuMsg
from typing import List, Dict, Any, Optional
from data_center.models import Task
from magic_jam import JamMySQL, JamConfig
from datetime import datetime
from data_center.jira_notify import JiraNotify
mcp = JamMCP("My MCP Server")
mcp.run()

# 读取配置
jam_config = JamConfig().config
tasklist_guid = jam_config["feishu_bot"]["tasklist_guid"]

@mcp.mcp.tool
def get_current_time() -> str:
    """获取当前时间, 获取现在日期，获取现在时间，获取当前是星期几"""
    from datetime import datetime
    dt = datetime.now()
    weekday_map = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
    weekday = weekday_map[dt.weekday()]
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {weekday}"

@mcp.mcp.tool
def get_recent_tasks(group_id: str = None, owner_id: str = None, limit: int = 5) -> List[dict]:
    """
    获取最近创建的任务列表，用于识别用户补充时间信息时更新哪个任务（支持群聊和私聊）
    
    Args:
        group_id (str, optional): 群组ID，用于筛选特定群组的任务。默认为 None（私聊场景不传此参数）
        owner_id (str, optional): 任务负责人ID，用于筛选特定负责人的任务。默认为 None
        limit (int, optional): 返回最近N个任务。默认为 5
    
    Returns:
        List[dict]: 最近创建的任务列表，按ID倒序排列（ID越大越新）
    """
    db = next(JamMySQL().get_db())
    ret_task = []
    tasks = db.query(Task)
    if group_id != None:
        tasks = tasks.filter(Task.group_id == group_id)
    if owner_id != None:
        tasks = tasks.filter(Task.owner_id == owner_id)
    # 按ID倒序排列，获取最近的任务
    tasks = tasks.order_by(Task.id.desc()).limit(limit).all()
    for task in tasks:
        ret_task.append({
            "id": task.id,
            "content": task.content,
            "name": task.name,
            "group_id": task.group_id,
            "end_time": task.end_time.strftime('%Y-%m-%d %H:%M:%S') if task.end_time else None,
            "owner_id": task.owner_id,
            "status": task.status,
        })
    return ret_task

@mcp.mcp.tool
def get_task(group_id: str = None, status: int = None, owner_id: str = None, source: int = None) -> List[dict]:
    """
    获取任务列表，支持多种筛选条件（支持群聊和私聊）
    
    Args:
        group_id (str, optional): 群组ID，用于筛选特定群组的任务。默认为 None（私聊场景不传此参数）
        status (int, optional): 任务状态，用于筛选特定状态的任务。默认为 None
                                0: 进行中, 1: 已完成, 2: 已取消, 3: 已超时
        owner_id (str, optional): 任务负责人ID，用于筛选特定负责人的任务。默认为 None
        source (int, optional): 任务来源，用于筛选特定来源的任务。默认为 None
                                0: 群聊, 1: 会议纪要, 2: 私聊
    
    Returns:
        List[dict]: 任务列表，每个任务包含以下字段：
            - id (int): 任务唯一标识符
            - content (str): 任务内容描述
            - group_id (str): 所属群组ID（私聊任务为None）
            - end_time (datetime): 任务截止时间
            - done_time (datetime): 任务完成时间
            - status (int): 任务状态 (0: 进行中, 1: 已完成, 2: 已取消, 3: 已超时)
            - source (int): 任务来源 (0: 群聊, 1: 会议纪要, 2: 私聊)
            - created_by_id (str): 任务创建者ID
            - owner_id (str): 任务负责人ID
    """
    db = next(JamMySQL().get_db())
    ret_task = []
    tasks = db.query(Task)
    if group_id != None:
        tasks = tasks.filter(Task.group_id == group_id)
    if status != None:
        tasks = tasks.filter(Task.status == status)
    if owner_id != None:
        tasks = tasks.filter(Task.owner_id == owner_id)
    if source != None:
        tasks = tasks.filter(Task.source == source)
    for task in tasks:
        ret_task.append({
            "id": task.id,
            "content": task.content,
            "group_id": task.group_id,
            "end_time": task.end_time,
            "done_time": task.done_time,
            "status": task.status,
            "source": task.source,
            "created_by_id": task.created_by_id,
            "owner_id": task.owner_id,
        })
    return ret_task

@mcp.mcp.tool
def create_task(content: str, name: str = None, group_id: str = None, 
                end_time: str = None, status: int = 0, source: int = 0, 
                created_by_id: str = None, owner_id: str = None) -> dict:
    """
    创建新任务（支持群聊和私聊）
    
    Args:
        content (str): 任务内容描述，必填
        name (str, optional): 任务名称。默认为 None
        group_id (str, optional): 所属群组ID。默认为 None（私聊场景可不传）
        end_time (str, optional): 任务截止时间，格式: "YYYY-MM-DD HH:MM:SS"。默认为 None
        status (int, optional): 任务状态。默认为 0 (进行中)
                                0: 进行中, 1: 已完成, 2: 已取消, 3: 已超时
        source (int, optional): 任务来源。默认为 0 (群聊)
                                0: 群聊, 1: 会议纪要, 2: 私聊（当group_id为空时自动设置为2）
        created_by_id (str, optional): 任务创建者ID。默认为 None
        owner_id (str, optional): 任务负责人ID。默认为 None（私聊场景下默认为created_by_id）
    
    Returns:
        dict: 创建成功的任务信息，包含任务ID和所有字段
    """
    db = next(JamMySQL().get_db())
    try:
        # 处理时间字符串转换
        end_time_obj = None
        if not end_time:
            # 如果未指定截止时间，默认设置为当天18:00
            today = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
            end_time_obj = today
            end_time = today.strftime("%Y-%m-%d %H:%M:%S")
        else:
            try:
                end_time_obj = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("时间格式错误，请使用 'YYYY-MM-DD HH:MM:SS' 格式")
        
        # 私聊场景处理：如果没有group_id，则认为是私聊
        is_private_chat = not group_id
        if is_private_chat:
            source = 2  # 私聊
        
        # 如果没有指定owner_id，默认使用created_by_id（群聊和私聊都适用）
        if not owner_id:
            if created_by_id:
                owner_id = created_by_id
            else:
                # 如果没有提供owner_id和created_by_id，提示需要传入用户ID
                raise ValueError("创建任务时，必须提供created_by_id参数（当前用户ID）作为任务负责人")
        
        feishu_msg = FeishuMsg()
        section_guid = None
        
        # 只有在群聊场景下才创建section
        if group_id:
            group_info = feishu_msg.get_group_info(group_id)
            if not group_info:
                raise ValueError(f"群组ID {group_id} 不存在")
            section_list = feishu_msg.get_task_section_list(tasklist_guid)
            for item in section_list:
                if item["name"].split("(")[-1].split(")")[0] == group_id:
                    section_guid = item["guid"]
                    break
            else:
                section_guid = feishu_msg.new_task_section(f"{group_info['name']}({group_id})", tasklist_guid)["guid"]
        
        if not name:
            name1 = content
        else:
            name1 = name
        
        # 创建飞书任务（私聊场景下section_guid为None）
        task_guid = feishu_msg.new_feishu_task(name1, description=content, assignee=[owner_id], end_time=str(int(end_time_obj.timestamp()*1000)),tasklist_guid=tasklist_guid, section_guid=section_guid)
            
        # 创建新任务
        new_task = Task(
            content=content,
            name=name,
            group_id=group_id,
            end_time=end_time_obj,
            status=status,
            source=source,
            created_by_id=created_by_id,
            owner_id=owner_id,
            task_guid=task_guid,
        )
        
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        
        return {
            "id": new_task.id,
            "content": new_task.content,
            "name": new_task.name,
            "group_id": new_task.group_id,
            "end_time": new_task.end_time,
            "done_time": new_task.done_time,
            "status": new_task.status,
            "source": new_task.source,
            "created_by_id": new_task.created_by_id,
            "owner_id": new_task.owner_id,
        }
    finally:
        db.close()

@mcp.mcp.tool
def update_task(task_id: int, end_time: str = None, done_time: str = None, 
                status: int = None, owner_id: str = None) -> dict:
    """
    修改任务信息
    
    Args:
        task_id (int): 任务ID，必填
        end_time (str, optional): 任务截止时间，格式: "YYYY-MM-DD HH:MM:SS"。默认为 None
        done_time (str, optional): 任务完成时间，格式: "YYYY-MM-DD HH:MM:SS"。默认为 None
        status (int, optional): 任务状态。默认为 None
                                0: 进行中, 1: 已完成, 2: 已取消, 3: 已超时
        owner_id (str, optional): 任务负责人ID。默认为 None
    
    Returns:
        dict: 修改后的任务信息
    """
    db = next(JamMySQL().get_db())
    try:
        # 查找任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise ValueError(f"任务ID {task_id} 不存在")
        
        # 更新字段
        if end_time is not None:
            try:
                task.end_time = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("end_time 时间格式错误，请使用 'YYYY-MM-DD HH:MM:SS' 格式")
        
        if done_time is not None:
            try:
                task.done_time = datetime.strptime(done_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("done_time 时间格式错误，请使用 'YYYY-MM-DD HH:MM:SS' 格式")
        if status == 1:
            if not done_time:
                task.done_time = datetime.strptime(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")

        if status is not None:
            task.status = status
        
        if owner_id is not None:
            task.owner_id = owner_id
        if task.task_guid:
            feishu_msg = FeishuMsg()
            this_task_info = feishu_msg.get_task_info(task.task_guid)
            if this_task_info is None:
                print(f"任务ID {task.task_guid} 不存在")
                db.delete(task)
                db.commit()
                return {
                }
            assignee = []
            if owner_id:
                mem_ids = []
                for item in this_task_info["members"]:
                    if item["role"] == "assignee":
                        mem_ids.append(item["id"])
                if mem_ids == [owner_id]:
                    assignee = []
                else:
                    assignee = [owner_id]
            if task.done_time:
                completed_time = str(int(task.done_time.timestamp()*1000))
            else:
                completed_time = None
            if task.end_time:
                end1_time = str(int(task.end_time.timestamp()*1000))
            else:
                end1_time = None
            feishu_msg.update_feishu_task(task.task_guid, assignee=assignee, completed_time=completed_time, end_time=end1_time)
        
        db.commit()
        db.refresh(task)
        
        return {
            "id": task.id,
            "content": task.content,
            "name": task.name,
            "group_id": task.group_id,
            "end_time": task.end_time,
            "done_time": task.done_time,
            "status": task.status,
            "source": task.source,
            "created_by_id": task.created_by_id,
            "owner_id": task.owner_id,
        }
    finally:
        db.close()

@mcp.mcp.tool
def delete_task(task_id: int) -> dict:
    """
    删除任务
    
    Args:
        task_id (int): 要删除的任务ID，必填
    
    Returns:
        dict: 删除操作结果，包含成功状态和消息
    """
    db = next(JamMySQL().get_db())
    try:
        # 查找任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise ValueError(f"任务ID {task_id} 不存在")
        
        if task.task_guid:
            feishu_msg = FeishuMsg()
            feishu_msg.del_task(task.task_guid)
        
        # 删除任务
        db.delete(task)
        db.commit()
        
        return {
            "success": True,
            "message": f"任务ID {task_id} 删除成功",
            "deleted_task_id": task_id
        }
    finally:
        db.close()

@mcp.mcp.tool
def get_jira_issues_link(issue_type: str = None, issue_status: list = [], fix_version: str = None, bu_team: str = None, assignee: str = None, reporter: str = None) -> str:
    """
    根据指定条件查询Jira问题，并返回对应问题的查看链接
    
    Args:
        issue_type (str, optional): 问题类型，可选值为: Bug, Epic, Development 。默认为 None，可不填
        issue_status (list, optional): 问题状态，可选值为: Open, Done, Discard, Closed, In Progress 中的一个或多个。默认为 []，可不填
        fix_version (str, optional): 版本，格式为：Vxx, Vxx_Zone, Vxx_VDF。比如：V35, V35_Zone, V35_VDF。默认为 None，可不填
        bu_team (str, optional): 业务团队，可选值为：Motion X, Motion Y&VMC, Motion Z, Body, Seat, Lighting, Smart Key, Cross/IVC, HVAC, HV/LV, NT2.5/FY, PTFS, BFSS, COMP, SEIO。默认为 None，可不填
        assignee (str, optional): issue/问题 负责人(传入的为用户id)，如 "ou_0000000000000000000000"。默认为 None，可不填
        reporter (str, optional): issue/问题 创建人(传入的为用户id)，如 "ou_0000000000000000000000"。默认为 None，可不填
    
    Returns:
        str: 符合条件的Jira问题链接，格式为 "https://jira.nioint.com/issues/?jql=project = nt3vims and xxx"
    """
    ret_str = "https://jira.nioint.com/issues/?jql=project = nt3vims "
    if issue_type:
        ret_str += f"and type = {issue_type} "
    if issue_status:
        ret_str += f"and status in ({', '.join([f'{status}' for status in issue_status])}) "
    if fix_version:
        ret_str += f"and fixVersion ~ '{fix_version}*' "
    if bu_team:
        ret_str += f"and 'Related BU Team' = '{bu_team}' "
    if assignee or reporter:
        feishu_msg = FeishuMsg()
    try:
        if assignee:
            ret = feishu_msg.get_user_info(assignee)["user_id"]
            ret_str += f"and assignee = '{ret}' "
        if reporter:
            ret = feishu_msg.get_user_info(reporter)["user_id"]
            ret_str += f"and reporter = '{ret}' "
    except Exception as e:
        print(f"获取用户ID失败: {e}")
    print(ret_str)
    return ret_str.replace(" ", "%20")


@mcp.mcp.tool
def query_rc_lock_info(chat_id: str = None,
                       open_id: str = None,
                       assignee: str = None,
                       related_bu_team: str = None,
                       summary: str = None,
                       issuetype: str = None,
                       status: str = None,
                       priority: str = None,
                       project: str = None,
                       only_current: bool = False) -> Dict[str, Any]:
    """
    查询RC锁仓信息，从飞书文档获取锁仓版本信息，并根据约束条件查询JIRA票据，返回结果卡片到群聊或私聊
    
    使用场景：用户在群聊或私聊中说"查询RC锁仓信息"、"查询锁仓任务"等相关关键词时调用此工具
    
    Args:
        chat_id (str, optional): 群聊ID，用于发送查询结果卡片到群聊。如果提供open_id则忽略此参数
        open_id (str, optional): 用户open_id，用于私聊场景发送卡片。如果提供则发送到私聊
        assignee (str, optional): 经办人/指派人的飞书用户ID（如 ou_xxx）或JIRA用户名。默认为 None，查询全部
        related_bu_team (str, optional): 关联业务单元团队，可选值：Motion X, Motion Y&VMC, Motion Z, Body, Seat, Lighting, Smart Key, Cross/IVC, HVAC, HV/LV, NT2.5/FY, PTFS, BFSS, COMP, SEIO。默认为 None，查询全部
        summary (str, optional): 摘要/标题关键词，模糊匹配。默认为 None，查询全部
        issuetype (str, optional): 问题类型，可选值：development, bug, "External Bug", "Quick Bug", "Cal Dev"。多个类型用逗号分隔，如 "development, Cal Dev"。默认为 None，查询全部
        status (str, optional): 状态，可选值：Open, Done, Discard, "In Progress", Closed, verify, monitoring。多个状态用逗号分隔，如 "Open, In Progress"。默认为 None，查询全部
        priority (str, optional): 优先级，如 P0, P1, P2, P3。默认为 None，查询全部
        project (str, optional): 项目，默认为 nt3vims
        only_current (bool, optional): 是否只查询当前日期在锁仓范围内的版本。默认False查询所有锁仓版本
    
    Returns:
        Dict[str, Any]: 包含以下字段：
            - success (bool): 是否成功
            - message (str): 结果消息
            - count (int): 查询到的票据数量
            - jql_links (list): JQL查询链接列表
    
    Example:
        # 群聊：查询所有RC锁仓信息（所有锁仓版本）
        query_rc_lock_info(chat_id="oc_xxx")
        
        # 私聊：查询所有RC锁仓信息
        query_rc_lock_info(open_id="ou_xxx")
        
        # 只查询当前正在锁仓的版本
        query_rc_lock_info(chat_id="oc_xxx", only_current=True)
        
        # 查询Lighting团队的development类型Open状态的票
        query_rc_lock_info(chat_id="oc_xxx", related_bu_team="Lighting", issuetype="development", status="Open")
    """
    try:
        # 确定发送目标：优先使用open_id（私聊），否则使用chat_id（群聊）
        # 智能判断：如果chat_id以ou_开头，实际上是open_id格式，自动转换
        if chat_id and chat_id.startswith("ou_"):
            # chat_id实际上是open_id格式，转换为open_id
            open_id = chat_id
            chat_id = None
        
        target_id = open_id if open_id else chat_id
        target_type = "open_id" if open_id else "chat_id"
        
        if not target_id:
            return {
                "success": False,
                "message": "必须提供chat_id或open_id参数",
                "count": 0,
                "jql_links": []
            }
        
        # 使用chat_id创建JiraNotify实例（如果私聊则使用默认值）
        notify = JiraNotify(chat_id or "oc_e0606fd321e5b6401b9a30d6f7b8b3fb")
        
        # 调用查询方法
        result = notify.query_rc_lock_info(
            assignee=assignee,
            related_bu_team=related_bu_team,
            summary=summary,
            issuetype=issuetype,
            status=status,
            priority=priority,
            project=project,
            only_current=only_current
        )
        
        # 如果有卡片数据，发送到目标（群聊或私聊）
        if result.get("card") and target_id:
            try:
                if target_type == "open_id":
                    # 私聊场景：直接发送消息
                    notify.feishu_msg.send_msg("open_id", target_id, result["card"], "interactive")
                else:
                    # 群聊场景：使用send_rc_lock_card方法
                    notify.send_rc_lock_card(target_id, result["card"])
                
                return {
                    "success": True,
                    "message": result["message"],
                    "count": len(result.get("data", [])),
                    "jql_links": result.get("jql_links", [])
                }
            except Exception as e:
                print(f"发送RC锁仓卡片失败: {e}")
                return {
                    "success": False,
                    "message": f"查询成功但发送卡片失败: {str(e)}",
                    "count": len(result.get("data", [])),
                    "jql_links": result.get("jql_links", [])
                }
        elif result.get("jql_links"):
            # 没有数据但有JQL链接，返回链接供用户查看
            return {
                "success": True,
                "message": result["message"],
                "count": 0,
                "jql_links": result.get("jql_links", [])
            }
        else:
            return {
                "success": False,
                "message": result.get("message", "查询失败"),
                "count": 0,
                "jql_links": []
            }
    except Exception as e:
        print(f"查询RC锁仓信息失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"查询失败: {str(e)}",
            "count": 0,
            "jql_links": []
        }


@mcp.mcp.tool
def set_rc_lock_reminder(chat_id: str,
                         advance_days: int = 2,
                         related_bu_team: str = None,
                         issuetype: str = None,
                         status: str = None,
                         assignee: str = None,
                         priority: str = None,
                         project: str = None,
                         reminder_hour: int = 9,
                         reminder_minute: int = 0) -> Dict[str, Any]:

    """
    设置RC锁仓提醒，每天在指定时间检查是否有即将开始的锁仓版本。
    设置成功后会立即查询设定时间内的锁仓信息并以卡片形式发送到群聊。
    
    Args:
        chat_id (str): 群聊ID，必填
        advance_days (int, optional): 提前几天提醒，默认2天
        related_bu_team (str, optional): 关联业务单元团队过滤
        issuetype (str, optional): 问题类型过滤（如 development, bug, "Cal Dev"）
        status (str, optional): 状态过滤（如 Open, Done, "In Progress"）
        assignee (str, optional): 经办人过滤
        priority (str, optional): 优先级过滤
        project (str, optional): 项目过滤
        reminder_hour (int, optional): 提醒时间（小时），0-23，默认9点
        reminder_minute (int, optional): 提醒时间（分钟），0-59，默认0分
    
    Returns:
        Dict[str, Any]: 设置结果
    
    Example:
        # 设置Lighting团队的锁仓提醒，提前2天，每天早上9点提醒
        set_rc_lock_reminder(chat_id="oc_xxx", related_bu_team="Lighting", issuetype="development, Cal Dev", status="Open")
        
        # 设置提前3天的提醒，每天早上10点提醒
        set_rc_lock_reminder(chat_id="oc_xxx", advance_days=3, reminder_hour=10, reminder_minute=0)
        
        # 设置上午10点30分的提醒
        set_rc_lock_reminder(chat_id="oc_xxx", reminder_hour=10, reminder_minute=30)
    """
    from data_center.rc_lock_reminder import set_rc_lock_reminder as _set_reminder
    from data_center.jira_notify import JiraNotify
    
    # 1. 保存提醒配置
    result = _set_reminder(
        chat_id=chat_id,
        advance_days=advance_days,
        related_bu_team=related_bu_team,
        issuetype=issuetype,
        status=status,
        assignee=assignee,
        priority=priority,
        project=project,
        enabled=True,
        reminder_hour=reminder_hour,
        reminder_minute=reminder_minute
    )
    
    # 2. 立即查询并发送当天到7天内的锁仓信息（使用和查询锁仓相同的表格样式）
    if result.get("success"):
        try:
            notify = JiraNotify(chat_id)
            
            # 获取当天到7天内的锁仓版本（用于立即展示）
            lock_versions = notify.get_lock_versions_in_range(start_days=0, end_days=7)
            
            if lock_versions:
                # 使用 query_rc_lock_info_for_upcoming 查询锁仓版本的JIRA票据并发送表格卡片
                query_result = notify.query_rc_lock_info_for_upcoming(
                    upcoming_locks=lock_versions,
                    assignee=assignee,
                    related_bu_team=related_bu_team,
                    summary=None,
                    issuetype=issuetype,
                    status=status,
                    priority=priority,
                    project=project,
                    advance_days=advance_days,
                    time_range_text="7天内"
                )
                
                # 发送多个卡片（每个版本一个）
                cards = query_result.get("cards", [])
                print(f"[set_rc_lock_reminder] 查询结果：cards数量={len(cards)}, data数量={len(query_result.get('data', []))}")
                if cards:
                    sent_count = 0
                    for i, card in enumerate(cards):
                        print(f"[set_rc_lock_reminder] 正在发送第 {i+1} 个卡片...")
                        if notify.send_rc_lock_card(chat_id, card):
                            sent_count += 1
                            print(f"[set_rc_lock_reminder] 第 {i+1} 个卡片发送成功")
                        else:
                            print(f"[set_rc_lock_reminder] 第 {i+1} 个卡片发送失败")
                    
                    result["upcoming_locks"] = len(lock_versions)
                    result["card_sent"] = sent_count > 0
                    result["jira_count"] = len(query_result.get("data", []))
                    result["cards_sent"] = sent_count
                    result["message"] += f"，发现{len(lock_versions)}个锁仓版本（当天到7天内），已发送{sent_count}个版本的详细任务列表（共{result['jira_count']}条）"
                else:
                    print(f"[set_rc_lock_reminder] 没有卡片需要发送（cards为空）")
                    result["upcoming_locks"] = len(lock_versions)
                    result["card_sent"] = False
                    result["message"] += f"，发现{len(lock_versions)}个锁仓版本（当天到7天内），但未找到符合条件的JIRA票据"
            else:
                result["upcoming_locks"] = 0
                result["card_sent"] = False
                result["message"] += f"，当天到7天内暂无锁仓版本"
        except Exception as e:
            print(f"查询即将锁仓版本失败: {e}")
            import traceback
            traceback.print_exc()
            result["upcoming_locks"] = 0
            result["card_sent"] = False
    
    return result


@mcp.mcp.tool
def delete_rc_lock_reminder(chat_id: str) -> Dict[str, Any]:
    """
    删除RC锁仓提醒
    
    Args:
        chat_id (str): 群聊ID，必填
    
    Returns:
        Dict[str, Any]: 删除结果
    
    Example:
        delete_rc_lock_reminder(chat_id="oc_xxx")
    """
    from data_center.rc_lock_reminder import delete_rc_lock_reminder as _delete_reminder
    
    return _delete_reminder(chat_id)


@mcp.mcp.tool
def get_rc_lock_reminder(chat_id: str) -> Dict[str, Any]:
    """
    查看当前群聊的RC锁仓提醒配置
    
    Args:
        chat_id (str): 群聊ID，必填
    
    Returns:
        Dict[str, Any]: 提醒配置信息
    
    Example:
        get_rc_lock_reminder(chat_id="oc_xxx")
    """
    from data_center.rc_lock_reminder import get_rc_lock_reminder as _get_reminder
    
    reminder = _get_reminder(chat_id)
    
    if reminder:
        return {
            "success": True,
            "message": "找到RC锁仓提醒配置",
            "reminder": reminder
        }
    else:
        return {
            "success": False,
            "message": "该群聊未设置RC锁仓提醒"
        }


@mcp.mcp.tool
def query_assignee_tasks(chat_id: str = None,
                         open_id: str = None,
                         assignee: str = None,
                         task_type: str = None,
                         status: str = None,
                         project: str = "nt3vims",
                         created_after: str = None,
                         jira_user_id: str = None,
                         version: str = None,
                         related_bu_team: str = None,
                         query_all: bool = False) -> Dict[str, Any]:
    """
    查询任务票清单,查询jira问题票开发票，查询开发票清单，支持按经办人、类型、状态、时间、版本、Related BU Team过滤
    
    Args:
        chat_id (str, optional): 群聊ID，用于发送卡片到群聊。如果提供open_id则忽略此参数
        open_id (str, optional): 用户open_id，用于私聊场景发送卡片。如果提供则发送到私聊
        assignee (str, optional): 经办人JIRA用户名或飞书open_id。如果不提供，在私聊场景下使用open_id,如果用户未明确指明哪个用户的票据，则不传该参数
        jira_user_id (str, optional): JIRA用户名（如果assignee是open_id格式，且已知JIRA用户名，可直接提供此参数避免调用get_user_info）
        task_type (str, optional): 任务类型，支持多种类型用逗号分隔：
            - "问题" 或 "bug": Bug, Int Bug, Quick Bug, External Bug
            - "任务" 或 "开发" 或 "development": Development, Epic, Design, Task
            - "测试" 或 "test": HIL Test, AO Test
            - 可同时查询多种，如 "问题,测试,开发"
            - 不填则查询全部类型
        status (str, optional): 状态过滤，支持的状态包括（多个用逗号分隔）：
            - Open: 待处理
            - Analysis: 分析中
            - Solution: 解决方案中
            - "In Progress": 进行中
            - Done: 已完成
            - Closed: 已关闭
            - Resolved: 已解决
            - Discard: 已废弃
            - "To Do": 待办
            - "In Review": 评审中
            - Reopened: 已重新打开
            默认为 "Open,Analysis,Solution"（只显示待处理、分析中、解决方案中的任务）
            示例：status="Open" 或 status="Open,In Progress"
        created_after (str, optional): 创建时间起始过滤，格式 "YYYY-MM-DD"
            示例：created_after="2025-10-01" 表示查询2025年10月1日之后创建的任务
        project (str, optional): 项目，默认 nt3vims
        version (str, optional): 版本过滤，如 "v31", "v32", "V31", "V32"， "ZONE", "VDF", "BL1000", "RL100"等
            示例：version="V32" 或 version="V32 ZONE" 或 version="BL1000" 或 version="VDF RL100"
        related_bu_team (str, optional): Related BU Team过滤，如 "BFSS", "Lighting", "Body", "Seat"等, 支持BU列表为：Motion X，Motion Y，Motion Z，Motion VMC，Body，Seat，Lighting，Smart Key，HVAC，HV/LV，PT-NIO BU，PT-ONVO BU，PT-FY BU，PT-ToolChain BU，PT-TS BU，NT2.5/FY，Cross/IVC，PTFS，BFSS，COMP，SEIO
            示例：related_bu_team="BFSS" 或 related_bu_team="Lighting"
        query_all (bool, optional): 是否查询所有经办人的任务票。如果为True，则不添加assignee条件，查询所有经办人的任务票
            示例：query_all=True 表示查询所有经办人的任务票（不限制经办人）
    
    Returns:
        Dict[str, Any]: 查询结果，包含卡片数据
    
    Example:
        # 查询某人的问题票
        query_assignee_tasks(chat_id="oc_xxx", assignee="jie.ni", task_type="问题")
        
        # 查询某人2025年10月后的问题票
        query_assignee_tasks(chat_id="oc_xxx", assignee="jie.ni", task_type="问题", created_after="2025-10-01")
        
        # 查询v31版本的任务票
        query_assignee_tasks(chat_id="oc_xxx", version="v31", task_type="问题,开发,测试")
        
        # 查询BFSS团队的任务票
        query_assignee_tasks(chat_id="oc_xxx", related_bu_team="BFSS", task_type="问题")
        
        # 查询v32版本BFSS团队的问题票
        query_assignee_tasks(chat_id="oc_xxx", version="v32", related_bu_team="BFSS", task_type="问题")
        
        # 查询所有v31版本BFSS团队的问题票（不限制经办人）
        query_assignee_tasks(chat_id="oc_xxx", version="v31", related_bu_team="BFSS", task_type="问题", query_all=True)
        
        # 查询某人v31版本的任务票
        query_assignee_tasks(chat_id="oc_xxx", assignee="jie.ni", version="v31", task_type="问题,开发,测试")
        
        # 私聊：查询当前用户的任务票
        query_assignee_tasks(open_id="ou_xxx", task_type="问题,测试,开发")
        
        # 查询2025年10月之后的任务票
        query_assignee_tasks(chat_id="oc_xxx", assignee="jie.ni", created_after="2025-10")
        
        # 查询2025年10月15日之后的任务票
        query_assignee_tasks(chat_id="oc_xxx", assignee="jie.ni", created_after="2025-10-15")
    """
    import re
    
    def validate_open_id(open_id_str: str) -> bool:
        """验证open_id格式是否正确"""
        if not open_id_str:
            return False
        # open_id格式：ou_开头，后面是32位十六进制字符
        pattern = r'^ou_[a-f0-9]{32}$'
        return bool(re.match(pattern, open_id_str))
    
    try:
        # 确定发送目标：优先使用open_id（私聊），否则使用chat_id（群聊）
        # 智能判断：如果chat_id以ou_开头，实际上是open_id格式，自动转换
        if chat_id and chat_id.startswith("ou_"):
            # chat_id实际上是open_id格式，转换为open_id
            if validate_open_id(chat_id):
                open_id = chat_id
                chat_id = None
            else:
                return {
                    "success": False,
                    "message": f"chat_id格式错误（不是有效的open_id格式）: {chat_id}",
                    "count": 0,
                    "jql_link": ""
                }
        
        # 验证open_id格式
        if open_id and not validate_open_id(open_id):
            return {
                "success": False,
                "message": f"open_id格式错误（应为ou_开头+32位十六进制）: {open_id}",
                "count": 0,
                "jql_link": ""
            }
        
        target_id = open_id if open_id else chat_id
        target_type = "open_id" if open_id else "chat_id"
        
        # 如果用户明确说"查询所有"（query_all=True），不自动添加assignee
        # 如果没有提供assignee，且不是"查询所有"，在私聊场景下使用open_id
        if not assignee and open_id and not query_all:
            assignee = open_id
        
        # 验证assignee格式（如果是open_id格式）
        if assignee and assignee.startswith("ou_"):
            if not validate_open_id(assignee):
                return {
                    "success": False,
                    "message": f"assignee格式错误（open_id应为ou_开头+32位十六进制）: {assignee}",
                    "count": 0,
                    "jql_link": ""
                }
        
        # assignee现在是可选的，如果不提供则查询所有经办人的任务票
        
        if not target_id:
            return {
                "success": False,
                "message": "必须提供chat_id或open_id参数",
                "count": 0,
                "jql_link": ""
            }
        
        print(f"[query_assignee_tasks] 开始查询: {target_type}={target_id}, assignee={assignee}, task_type={task_type}, created_after={created_after}, version={version}, related_bu_team={related_bu_team}, query_all={query_all}")
        
        # 使用默认chat_id创建JiraNotify实例（实际发送时会使用target_id）
        notify = JiraNotify(chat_id or "oc_e0606fd321e5b6401b9a30d6f7b8b3fb")
        
        # 如果query_all=True，不传assignee参数（查询所有经办人）
        result = notify.query_assignee_tasks(
            assignee=assignee if not query_all else None,
            task_type=task_type,
            status=status,
            project=project,
            created_after=created_after,
            jira_user_id=jira_user_id,
            version=version,
            related_bu_team=related_bu_team
        )
        
        print(f"[query_assignee_tasks] 查询结果: success={result.get('success')}, count={len(result.get('data', []))}, has_card={result.get('card') is not None}")
        
        # 如果有卡片数据，发送到目标（群聊或私聊）
        if result.get("card") and target_id:
            print(f"[query_assignee_tasks] 发送卡片到{target_type}: {target_id}")
            try:
                send_success = notify.feishu_msg.send_msg(target_type, target_id, result["card"], "interactive")
                if send_success:
                    print(f"[query_assignee_tasks] 卡片发送成功")
                    return {
                        "success": True,
                        "message": result["message"],
                        "count": len(result.get("data", [])),
                        "jql_link": result.get("jql_link", "")
                    }
                else:
                    print(f"[query_assignee_tasks] 卡片发送失败")
                    return {
                        "success": False,
                        "message": "卡片发送失败，请稍后重试",
                        "count": len(result.get("data", [])),
                        "jql_link": result.get("jql_link", "")
                    }
            except Exception as e:
                print(f"[query_assignee_tasks] 卡片发送异常: {e}")
                return {
                    "success": False,
                    "message": f"卡片发送失败: {str(e)}",
                    "count": len(result.get("data", [])),
                    "jql_link": result.get("jql_link", "")
                }
        else:
            print(f"[query_assignee_tasks] 无卡片数据: {result.get('message')}")
            return {
                "success": result.get("success", False),
                "message": result.get("message", "查询失败"),
                "count": 0,
                "jql_link": result.get("jql_link", "")
            }
    except Exception as e:
        print(f"查询经办人任务失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"查询失败: {str(e)}",
            "count": 0
        }
