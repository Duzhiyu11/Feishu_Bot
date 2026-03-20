from magic_jam import JamRAG, FeishuDoc, JamMySQL, JiraTool, FeishuMsg, JamLLM
from magic_jam.parser.feishu_parser import FeishuDocParser
from typing import Dict, List, Any, Optional
import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote


class JiraNotify:
    """Jira通知类，用于获取Jira信息并发送飞书通知"""

    def __init__(self, chat_id: str = "oc_e0606fd321e5b6401b9a30d6f7b8b3fb"):
        self.chat_id = chat_id
        self.feishu_msg = FeishuMsg()
        self.feishu_doc = FeishuDoc()
        self.jira_tool = JiraTool()
        self.feishu_parser = FeishuDocParser()
        self.jam_llm = JamLLM()
        self._assignee_cache = {}  # 缓存Assignee显示名，避免重复调用JIRA API

    # -----------------------节点交付物相关----------------------------

    def _extract_version_timeline(self, data: List[List[Any]]) -> Dict[str, Dict[str, str]]:
        result = {}
        if not data or len(data) < 2:
            return result
        headers = data[0]
        stage_mapping = {}
        all_stages = []
        for i, header in enumerate(headers):
            if header and isinstance(header, str):
                if header.startswith('G'):
                    stage_name = header.split('(')[0] if '(' in header else header
                    stage_mapping[i] = stage_name
                    if stage_name not in all_stages:
                        all_stages.append(stage_name)

        current_version = None
        for row in data[1:]:
            if not row or len(row) < 2:
                continue

            first_col = row[0] if row[0] else ""

            # 检查是否是版本分隔行（如 "V34(待开始)" 整行都是同样的值）
            if first_col and isinstance(first_col, str) and '(' in first_col and first_col.startswith('V'):
                # 这是版本分隔行，提取版本号
                version_match = first_col.split('(')[0].strip()
                if version_match.startswith('V') and len(version_match) <= 4:
                    current_version = version_match
                    if current_version not in result:
                        result[current_version] = {stage: "" for stage in all_stages}
                continue

            # 检查是否是版本头行（第一列是纯版本号如 "V34"）
            # 使用第一列(Version)作为版本号
            if first_col and isinstance(first_col, str) and first_col.startswith('V') and len(first_col) <= 4:
                current_version = first_col
                if current_version not in result:
                    result[current_version] = {stage: "" for stage in all_stages}
                continue

            # 如果没有当前版本，跳过
            if not current_version:
                continue

            # 提取当前行的日期数据
            for col_idx, stage_name in stage_mapping.items():
                if col_idx < len(row):
                    time_value = row[col_idx]
                    if time_value and isinstance(time_value, str) and '/' in time_value:
                        # 只在没有值时设置（取第一个出现的日期）
                        if not result[current_version][stage_name]:
                            result[current_version][stage_name] = time_value

        return result

    def get_timeline(self) -> Dict[str, Dict[str, str]]:
        link = "https://nio.feishu.cn/sheets/PC1Xs0Mv4hmhlQt1N25cZcPOnrJ?sheet=KQGDKi"
        data = self.feishu_doc.parser_table(link=link, skip_row=["2:137"], skip_col=["L:V"], first_row=1, is_json=True)
        with open('timeline_raw.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        timeline = self._extract_version_timeline(data)
        with open('timeline.json', 'w', encoding='utf-8') as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        return timeline

    # -------------------------------项目计划表-----------------------

    @staticmethod
    def _parse_version_info(version_str: str) -> Dict[str, str]:
        """解析版本字符串，提取version, sw, rc信息
        
        支持的格式：
        - "V30 VDF RC01"
        - "V27 ALPS ZONE RC01"
        - "注意：受控版本，需先申请再合入！！！-V30 VDF RC12"
        """
        result = {"version": "", "sw": "", "rc": "", "full_name": ""}
        if not version_str:
            return result
        
        # 清理版本字符串，去掉前缀注释
        clean_str = version_str.split('\n')[0].strip()
        result["full_name"] = clean_str
        
        # 如果有前缀注释（如"注意：..."），尝试提取后面的版本信息
        if '-V' in clean_str:
            clean_str = clean_str.split('-V')[-1]
            clean_str = 'V' + clean_str
        
        # 尝试多种格式匹配
        # 格式1: V30 VDF RC01 或 V30 Zone RC01
        match = re.match(r'(V\d+)\s+(\w+)\s+(RC[\d.]+)', clean_str)
        if match:
            result["version"] = match.group(1)
            result["sw"] = match.group(2)
            result["rc"] = match.group(3)
            return result
        
        # 格式2: V27 ALPS ZONE RC01 (带多个空格分隔的SW名)
        match = re.match(r'(V\d+)\s+(.+?)\s+(RC[\d.]+)', clean_str)
        if match:
            result["version"] = match.group(1)
            result["sw"] = match.group(2).replace(' ', '_')  # 用下划线连接
            result["rc"] = match.group(3)
            return result
        
        # 格式3: 只有版本号 V30
        match = re.match(r'(V\d+)', clean_str)
        if match:
            result["version"] = match.group(1)
            # 尝试提取RC
            rc_match = re.search(r'(RC[\d.]+)', clean_str)
            if rc_match:
                result["rc"] = rc_match.group(1)
            # 尝试提取SW名
            sw_match = re.search(r'V\d+\s+(.+?)(?:\s+RC|\s*$)', clean_str)
            if sw_match:
                result["sw"] = sw_match.group(1).strip().replace(' ', '_')
        
        return result

    @staticmethod
    def _find_continuous_ranges(row: list, dates: list, years: list = None, start_col: int = 4) -> Dict[str, Dict[str, Any]]:
        """找出连续相同值的范围，返回每个值的起始和结束日期及列索引"""
        ranges = {}
        i = start_col
        while i < len(row):
            val = row[i]
            if val is not None and val != "":
                start_idx = i
                while i < len(row) and row[i] == val:
                    i += 1
                end_idx = i - 1

                def get_full_date(idx):
                    if idx >= len(dates):
                        return ""
                    date = dates[idx]
                    if years and idx < len(years) and years[idx]:
                        return f"{years[idx]}/{date}"
                    return date

                st = get_full_date(start_idx)
                et = get_full_date(end_idx)

                if val not in ranges:
                    ranges[val] = {"st": st, "et": et, "start_col": start_idx, "end_col": end_idx}
            else:
                i += 1
        return ranges

    @staticmethod
    def _ranges_overlap(range1: Dict, range2: Dict) -> bool:
        """检查两个列范围是否有交集"""
        return not (range1["end_col"] < range2["start_col"] or range2["end_col"] < range1["start_col"])
    def _parse_data(self, data: list) -> Dict[str, Any]:
        """解析data.json数据，转换为结构化格式"""
        if len(data) < 3:
            return {}

        years = data[0]
        dates = data[1]

        result = {}
        i = 2

        while i < len(data):
            row = data[i]
            if len(row) < 4 or row[1] is None:
                i += 1
                continue

            version_full = row[1]
            version_name = version_full.split('\n')[0].strip() if version_full else ""

            if not version_name:
                i += 1
                continue

            version_info = self._parse_version_info(version_name)

            if version_name not in result:
                result[version_name] = {
                    "version": version_info["version"],
                    "sw": version_info["sw"],
                    "rc": version_info["rc"],
                    "status": row[3] if len(row) > 3 else "",
                    "deliverables": row[2] if len(row) > 2 else "",
                    "plane": {}
                }

            plane_rows = []
            j = i
            while j < len(data) and len(data[j]) > 1 and data[j][1] == version_full:
                plane_rows.append(data[j])
                j += 1

            if plane_rows:
                # 从所有行中提取所有的ranges（包括plane和event）
                all_ranges = []
                for row_idx, prow in enumerate(plane_rows):
                    ranges = self._find_continuous_ranges(prow, dates, years)
                    all_ranges.append((row_idx, ranges))

                # 识别真正的plane：以V开头且包含数字的项
                plane_ranges = {}
                event_ranges_by_plane = {}

                for row_idx, ranges in all_ranges:
                    for name, info in ranges.items():
                        # 判断是否是plane：以V开头
                        if re.match(r'^V\d+', name):
                            if name not in plane_ranges:
                                plane_ranges[name] = info
                                event_ranges_by_plane[name] = []

                # 如果没有找到以V开头的plane，使用第一行的所有ranges作为plane（兼容旧逻辑）
                if not plane_ranges:
                    plane_ranges = all_ranges[0][1] if all_ranges else {}
                    for plane_name in plane_ranges:
                        event_ranges_by_plane[plane_name] = []

                # 收集所有event（不是plane的ranges）
                for row_idx, ranges in all_ranges:
                    for name, info in ranges.items():
                        if not re.match(r'^V\d+', name):
                            # 这是一个event，需要找到它属于哪个plane
                            for plane_name, plane_info in plane_ranges.items():
                                if self._ranges_overlap(plane_info, info):
                                    event_ranges_by_plane[plane_name].append((name, info))
                                    break

                # 构建最终结果
                for plane_name, plane_info in plane_ranges.items():
                    if plane_name not in result[version_name]["plane"]:
                        result[version_name]["plane"][plane_name] = {
                            "st": plane_info["st"],
                            "et": plane_info["et"],
                            "event": {}
                        }

                    # 添加该plane的所有events
                    for event_name, event_info in event_ranges_by_plane.get(plane_name, []):
                        if event_name not in result[version_name]["plane"][plane_name]["event"]:
                            result[version_name]["plane"][plane_name]["event"][event_name] = {
                                "st": event_info["st"],
                                "et": event_info["et"]
                            }

            i = j

        return result

    def get_planes(self) -> Dict[str, Any]:
        link = "https://nio.feishu.cn/sheets/PC1Xs0Mv4hmhlQt1N25cZcPOnrJ?sheet=OKbnoL"
        data = self.feishu_doc.parser_table(link=link, skip_row=["3:1120"], skip_col=["E:ZD"], first_row=1, is_json=True)
        with open('plane_raw.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        result = self._parse_data(data)
        with open('plane.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
    
    def get_planes_from_doc(self,data) -> Dict[str, Any]:
        # link = "https://nio.feishu.cn/sheets/PC1Xs0Mv4hmhlQt1N25cZcPOnrJ?sheet=OKbnoL"
        # data = self.feishu_doc.parser_table(link=link, skip_row=["3:1120"], skip_col=["E:ZD"], first_row=1, is_json=True)
        with open('plane_raw.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        result = self._parse_data(data)
        with open('plane.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
    def get_time(self, timeline: Dict, g: str, version: str, n: int) -> str:
        t = None
        for key, value in timeline.items():
            if key == version and g in value:
                t = value[g]
                break
        try:
            t = datetime.strptime(t, "%Y/%m/%d")
            t = t - timedelta(days=n)
            return t.strftime("%Y/%m/%d")
        except ValueError as e:
            print(f"日期格式错误: {e}")
            return None

    @staticmethod
    def _date_in_range(date: str, st: str, et: str) -> bool:
        """检查日期是否在范围内"""
        def parse_date(d: str) -> tuple:
            parts = d.split('/')
            if len(parts) == 3:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
            elif len(parts) == 2:
                return (0, int(parts[0]), int(parts[1]))
            return (0, 0, 0)

        d = parse_date(date)
        s = parse_date(st)
        e = parse_date(et)
        return s <= d <= e

    def get_plane_info(self, planes: Dict, date: str, status: str, event_name: str, sw: str = "") -> Dict[str, Any]:
        """根据时间、状态、事件名称查找匹配的plane信息"""
        results = {}

        for version_key, version_info in planes.items():
            # if version_info.get("status") != status:
            #     continue
            if sw != "" and sw != version_info.get("sw", ""):
                continue
            for plane_name, plane_info in version_info.get("plane", {}).items():
                for evt_name, evt_info in plane_info.get("event", {}).items():
                    # if event_name!= "" and event_name not in evt_name:
                    if evt_name.find(event_name) == -1:
                        continue
                    evt_st = evt_info.get("st", "")
                    evt_et = evt_info.get("et", "")
                    if evt_st and evt_et and self._date_in_range(date, evt_st, evt_et):
                        result_key = f"{version_key}-{plane_name}" if version_key != plane_name else version_key
                        results[result_key] = {
                            "version": version_info.get("version", ""),
                            "sw": version_info.get("sw", ""),
                            "rc": version_info.get("rc", ""),
                            "status": version_info.get("status", ""),
                            "deliverables": version_info.get("deliverables", ""),
                            "plane": {
                                plane_name: {
                                    "st": plane_info.get("st", ""),
                                    "et": plane_info.get("et", ""),
                                    "event": {
                                        evt_name: {
                                            "st": evt_st,
                                            "et": evt_et
                                        }
                                    }
                                }
                            }
                        }

        return results

    # -----------------------------Jira相关----------
    
    def check_time_time(self,check_time_str, start_time_str, end_time_str=None, 
                     cycle_days=None, format="%Y/%m/%d"):
        """
        检查时间是否在指定时间范围内，并可选择是否检查周期性条件
        
        Args:
            check_time_str: 要检查的时间字符串
            start_time_str: 开始时间字符串
            end_time_str: 结束时间字符串，可选
            cycle_days: 周期天数，例如3表示每3天，可选
            format: 时间格式，默认为"%Y/%m/%d"
        
        Returns:
            如果未指定cycle_days: 返回布尔值，表示是否在时间范围内
            如果指定了cycle_days: 返回元组(是否在时间范围内, 是否满足周期条件, 距离开始天数)
        """
        # 将字符串转换为datetime对象
        if start_time_str == None or check_time_str == None:
            return False
        check_time = datetime.strptime("2025/12/8", "%Y/%m/%d")
        check_time = datetime.strptime(check_time_str, format)
        start_time = datetime.strptime(start_time_str, format)
        
        # 1. 检查是否在时间范围内
        in_time_range = False
        
        if end_time_str is None:
            # 只有一个时间，判断是否在开始时间之后
            in_time_range = check_time >= start_time
            end_time = None
        else:
            end_time = datetime.strptime(end_time_str, format)
            in_time_range = start_time <= check_time <= end_time
        
        # 2. 如果未指定周期天数，直接返回时间范围判断结果
        if cycle_days is None:
            return in_time_range
        
        # 3. 如果指定了周期天数，检查是否满足周期性条件
        cycle_condition_met = False
        days_from_start = 0
        
        if in_time_range:
            # 计算检查时间与开始时间之间的天数差
            days_from_start = (check_time - start_time).days
            
            # 判断天数差是否能被周期整除
            if days_from_start % cycle_days == 0:
                cycle_condition_met = True
        
        return in_time_range and cycle_condition_met
        

    @staticmethod
    def _group_by_bu_team(jira_list: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """将Jira数组按照 Related BU Team 分类"""
        result = {}

        for item in jira_list:
            bu_teams = item.get("Related BU Team", [])
            if not bu_teams:
                bu_teams = ["Unknown"]
            for team in bu_teams:
                if team not in result:
                    result[team] = []
                result[team].append(item)

        return result

    def get_jira_info_fo_not_complete(self, version: str) -> Dict[str, List[Dict[str, Any]]]:
        jira_info = []
        jql = f'project = nt3vims and type= epic and status not in(discard,done) and fixVersion ~ "{version}*"'
        print(jql)
        fields = ["Assignee", "Related BU Team", "summary", "issuetype", "status", "priority", "project"]
        jira_info = self.jira_tool.search_issues(jql, fields)
        # jira_info = [item for item in jira_info if "In Progress" not in item.get("status", "")]
        jira_info = self._group_by_bu_team(jira_info)
        with open('jira_info_fo_not_complete.json', 'w', encoding='utf-8') as f:
            json.dump(jira_info, f, ensure_ascii=False, indent=4)
        return jira_info

    def get_jira_info_development_was_completed(self, planes: Dict,date,event_name) -> Dict[str, Dict]:
        result = {}
        print(json.dumps(planes, indent=4))
        for key, value in planes.items():
            version = value.get("version", "")
            sw = value.get("sw", "")
            rc = value.get("rc", "").upper()
            for plane_name, plane_info in value.get("plane", {}).items():
                for evt_name, evt_info in plane_info.get("event", {}).items():
                    if event_name in evt_name:
                        st = evt_info.get("st", "")
                        et = evt_info.get("et", "")
                        if self.check_time_time(date, st, et):
                            jql = f'project = nt3vims and type = development and "Model Hex" is not null and fixVersion ~ "{version}_{sw}*" and status not in(discard,done) AND "Planned RC" = {rc}'
                            print(jql)
                            fields = ["Planned RC", "Assignee", "Related BU Team", "summary", "issuetype", "status", "priority", "project"]
                            jira_info = self.jira_tool.search_issues(jql, fields)
                            jira_info = self._group_by_bu_team(jira_info)
                            result[key] = jira_info
        with open('jira_info_development_was_completed.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
        return result

    def get_jira_info_development_not_complete_bug(self, planes: Dict,date,event_name) -> Dict[str, Dict]:
        result = {}
        for key, value in planes.items():
            version = value.get("version", "")
            sw = value.get("sw", "")
            rc = value.get("rc", "").upper()
            for plane_name, plane_info in value.get("plane", {}).items():
                for evt_name, evt_info in plane_info.get("event", {}).items():
                    if event_name in evt_name:
                        st = evt_info.get("st", "")
                        et = evt_info.get("et", "")
                        if self.check_time_time(date, st, et):
                            jql = f'project = nt3vims AND type in (bug, "External Bug", "Quick Bug") AND status not in(discard,verify, monitoring,close) and fixVersion ~ "{version}_{sw}*" AND "Planned RC" = {rc} ORDER BY assignee ASC'
                            fields = ["Assignee", "Related BU Team", "summary", "issuetype", "status", "priority", "project"]
                            print(jql)
                            jira_info = self.jira_tool.search_issues(jql, fields)
                            jira_info = self._group_by_bu_team(jira_info)
                            result[key] = jira_info
        with open('jira_info_development_not_complete_bug.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
        return result

    def get_jira_info_development_not_complete_feature(self, planes: Dict,date,event_name,cycle_days=None) -> Dict[str, Dict]:
        result = {}
        date = datetime.now().strftime("%Y/%-m/%-d")
        for key, value in planes.items():
            version = value.get("version", "")
            sw = value.get("sw", "")
            rc = value.get("rc", "").upper()
            for plane_name, plane_info in value.get("plane", {}).items():
                for evt_name, evt_info in plane_info.get("event", {}).items():
                    if event_name in evt_name:
                        st = evt_info.get("st", "")
                        et = evt_info.get("et", "")
                        if self.check_time_time(date, st, et, cycle_days=cycle_days):
                            jql = f'project = nt3vims AND type = development AND status = Open AND fixVersion ~ "{version}_{sw}*" AND "Planned RC" = {rc} ORDER BY assignee ASC'
                            fields = ["Assignee", "Related BU Team", "summary", "issuetype", "status", "priority", "project"]
                            print(jql)
                            jira_info = self.jira_tool.search_issues(jql, fields)
                            jira_info = self._group_by_bu_team(jira_info)
                            result[key] = jira_info
        with open('jira_info_development_not_complete_feature.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
        return result
        

    def _get_assignee_display_name(self, assignee) -> str:
        """
        将JIRA Assignee转换为中文显示名
        
        Args:
            assignee: JIRA用户名（如 "jie.ni"）、User对象或None
            
        Returns:
            中文显示名，如果无法获取则返回原始值
        """
        if not assignee:
            return ""
        
        # 如果是User对象，直接获取displayName
        if hasattr(assignee, 'displayName') and assignee.displayName:
            return assignee.displayName
        elif hasattr(assignee, 'name') and assignee.name:
            return assignee.name
        
        # 转换为字符串用于缓存查找
        assignee_str = str(assignee) if assignee else ""
        if not assignee_str:
            return ""
        
        # 检查缓存
        if assignee_str in self._assignee_cache:
            return self._assignee_cache[assignee_str]
        
        # 如果是字符串，尝试通过JIRA API获取displayName
        try:
            # 尝试通过JIRA API获取用户信息
            user = self.jira_tool.jira.user(assignee_str)
            display_name = None
            if hasattr(user, 'displayName') and user.displayName:
                display_name = user.displayName
            elif hasattr(user, 'name') and user.name:
                display_name = user.name
            
            if display_name:
                # 缓存结果
                self._assignee_cache[assignee_str] = display_name
                return display_name
        except Exception as e:
            # 如果获取失败，返回原始值并缓存
            print(f"获取JIRA用户显示名失败 {assignee_str}: {e}")
            self._assignee_cache[assignee_str] = assignee_str
            return assignee_str
        
        # 如果无法获取，返回原始值并缓存
        self._assignee_cache[assignee_str] = assignee_str
        return assignee_str
    
    @staticmethod
    def _get_priority_color(priority: str) -> str:
        """获取优先级对应的颜色"""
        if "P0" in priority:
            return "red"
        elif "P1" in priority:
            return "orange"
        elif "P2" in priority:
            return "yellow"
        else:
            return "green"

    def _build_table_card(self, title: str, subtitle: str, rows: List[Dict]) -> Dict:
        """构建飞书表格卡片"""
        return {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "subtitle": {"tag": "plain_text", "content": subtitle},
                "template": "red",
                "padding": "12px 12px 12px 12px"
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": [{
                    "tag": "table",
                    "columns": [
                        {"data_type": "markdown", "name": "1", "display_name": "Issue", "horizontal_align": "left", "width": "auto"},
                        {"data_type": "text", "name": "2", "display_name": "Summary", "horizontal_align": "left", "width": "auto"},
                        {"data_type": "markdown", "name": "3", "display_name": "Priority", "horizontal_align": "left", "width": "auto"},
                        {"data_type": "text", "name": "4", "display_name": "Assignee", "horizontal_align": "left", "width": "auto"}
                    ],
                    "rows": rows,
                    "row_height": "low",
                    "header_style": {"background_style": "grey", "bold": True, "lines": 1},
                    "page_size": 10,
                    "margin": "0px 0px 0px 0px"
                }]
            }
        }

    def _build_rows(self, items: List[Dict]) -> List[Dict]:
        """构建表格行数据"""
        rows = []
        for item in items:
            key = item.get('key', '')
            summary = item.get('summary', '')
            priority = item.get('priority', '')
            assignee = item.get('Assignee', '')
            color = self._get_priority_color(priority)
            rows.append({
                "1": f"[{key}](https://jira.nioint.com/browse/{key})",
                "2": summary,
                "3": f"<font color='{color}'>{priority}</font>",
                "4": assignee
            })
        return rows

    def task_jira(self, data: Dict,title_str):
        """发送Jira通知卡片（单层数据）"""
        print("task_jira")
        for team, items in data.items():
            rows = self._build_rows(items)
            title = f"{title_str},您有{len(items)}张票需要流转，请及时关注"
            card_content = self._build_table_card(title, team, rows)
            self.feishu_msg.send_msg("chat_id", self.chat_id, card_content, "interactive")

    def task_jira2(self, data: Dict,title_str):
        """发送Jira通知卡片（双层数据：version -> team -> items）"""
        print("task_jira2")
        for version, data1 in data.items():
            for team, items in data1.items():
                rows = self._build_rows(items)
                title = f"{title_str},您有{len(items)}张票需要流转，请及时关注"
                subtitle = f"{team} {version}"
                card_content = self._build_table_card(title, subtitle, rows)
                self.feishu_msg.send_msg("chat_id", self.chat_id, card_content, "interactive")


    def parse_plane_to_triplets(self, plane_file: str = 'plane.json') -> Dict[str, Any]:
        """
        解析plane.json文件为三元组格式
        只提取MR和锁仓集成事件，MR映射到G2.5，锁仓集成映射到G2.6

        Args:
            plane_file: plane.json文件路径

        Returns:
            包含entities和relations的字典
        """
        # 读取plane.json文件
        with open(plane_file, 'r', encoding='utf-8') as f:
            planes = json.load(f)
        
        #预处理
        def replace_events(data):
            """替换event中的特定键"""
            if isinstance(data, dict):
                for key, value in data.items():
                    if key == "event" and isinstance(value, dict):
                        # 直接修改event字典
                        for k in list(value.keys()):
                            if "MR" in k:
                                value["MR"] = value.pop(k)
                            elif "锁仓集成" in k:
                                value["锁仓集成"] = value.pop(k)
                    else:
                        replace_events(value)
            elif isinstance(data, list):
                for item in data:
                    replace_events(item)
            return data
        planes = replace_events(planes)                

        # 事件名称映射到项目节点
        event_mapping = {
            "MR": "G2.5",
            "锁仓集成": "G2.6"
        }

        entities = []
        relations = []
        added_entities = set()  # 用于去重entity

        for version_key, version_info in planes.items():
            plane_dict = version_info.get("plane", {})

            for plane_name, plane_info in plane_dict.items():
                events = plane_info.get("event", {})

                # 检查是否有MR或锁仓集成事件
                has_valid_event = any(evt in event_mapping for evt in events.keys())
                if not has_valid_event:
                    continue

                for event_name, event_info in events.items():
                    # 只处理MR和锁仓集成事件
                    if event_name not in event_mapping:
                        continue

                    project_node = event_mapping[event_name]
                    st = event_info.get("st", "")
                    et = event_info.get("et", "")

                    if not st or not et:
                        continue

                    # 添加项目节点实体
                    node_entity_key = f"项目节点:{project_node}"
                    
                    if node_entity_key not in added_entities:
                        des_ = "项目节点"
                        if project_node.find("G2.5") != -1:
                            des_ = "项目节点, G2.5项目节点也称MR阶段"
                        if project_node.find("G2.6") != -1:
                            des_ = "项目节点, G2.6项目节点也称锁仓集成阶段"
                        entities.append({
                            "entity": project_node,
                            "type": "项目节点",
                            "description": des_ 
                        })
                        added_entities.add(node_entity_key)

                    # 组合版本项目名称：版本名 + 项目节点
                    version_project = f"{plane_name}项目版本, {project_node}项目节点"

                    # 添加版本项目实体
                    version_project_key = f"项目版本:{version_project}"
                    if version_project_key not in added_entities:
                        des_ = version_project
                        if version_project.find("G2.5") != -1:
                            des_ += ", G2.5项目节点也称MR阶段"
                        if version_project.find("G2.6") != -1:
                            des_ += ", G2.6项目节点也称锁仓集成阶段"
                        entities.append({
                            "entity": version_project,
                            "type": "项目版本及项目节点",
                            "description": des_
                        })
                        added_entities.add(version_project_key)

                    # 添加开始时间实体
                    st_entity_key = f"日期:{st}"
                    if st_entity_key not in added_entities:
                        entities.append({
                            "entity": st,
                            "type": "日期",
                            "description": "日期"
                        })
                        added_entities.add(st_entity_key)

                    # 添加截止时间实体
                    et_entity_key = f"日期:{et}"
                    if et_entity_key not in added_entities:
                        entities.append({
                            "entity": et,
                            "type": "日期",
                            "description": "日期"
                        })
                        added_entities.add(et_entity_key)

                    # 添加关系：项目节点 -> 版本 -> 版本项目
                    relations.append({
                        "head": project_node,
                        "head_type": "项目节点",
                        "relation": "版本",
                        "tail": version_project,
                        "tail_type": "项目版本及项目节点",
                        "description": f"{project_node} 包含版本 {version_project}"
                    })

                    # 添加关系：版本项目 -> 开始时间 -> 时间值
                    relations.append({
                        "head": version_project,
                        "head_type": "项目版本及项目节点",
                        "relation": "开始时间",
                        "tail": st,
                        "tail_type": "日期",
                        "description": f"{version_project} 的开始时间是 {st}"
                    })

                    # 添加关系：版本项目 -> 截止时间 -> 时间值
                    relations.append({
                        "head": version_project,
                        "head_type": "项目版本及项目节点",
                        "relation": "截止时间",
                        "tail": et,
                        "tail_type": "日期",
                        "description": f"{version_project} 的截止时间是 {et}"
                    })

        result = {
            "entities": entities,
            "relations": relations
        }

        # 保存结果
        with open('plane_triplets.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def parse_timeline_to_triplets(self, timeline_file: str = 'timeline.json') -> Dict[str, Any]:
        """
        解析timeline.json文件为三元组格式
        输入日期为截止时间，开始时间为截止时间前3天

        Args:
            timeline_file: timeline.json文件路径

        Returns:
            包含entities和relations的字典
        """
        from datetime import datetime, timedelta

        # 读取timeline.json文件
        with open(timeline_file, 'r', encoding='utf-8') as f:
            timeline = json.load(f)

        entities = []
        relations = []
        added_entities = set()  # 用于去重entity

        def calculate_start_date(end_date_str: str) -> str:
            """计算开始时间（截止时间前3天）"""
            try:
                end_date = datetime.strptime(end_date_str, "%Y/%m/%d")
            except ValueError:
                # 尝试不带前导零的格式
                parts = end_date_str.split('/')
                end_date = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
            start_date = end_date - timedelta(days=3)
            return f"{start_date.year}/{start_date.month}/{start_date.day}"

        for version, nodes in timeline.items():
            for node_name, end_date in nodes.items():
                # 跳过空日期
                if not end_date:
                    continue

                # 计算开始时间
                # start_date = calculate_start_date(end_date)

                # 组合版本项目名称：版本名 + 项目节点
                version_project = f"{version}项目版本,  {node_name}项目节点"

                # 添加项目节点实体
                node_entity_key = f"项目节点:{node_name}"
                if node_entity_key not in added_entities:
                    entities.append({
                        "entity": node_name,
                        "type": "项目节点",
                        "description": "项目节点"
                    })
                    added_entities.add(node_entity_key)

                # 添加版本项目实体
                version_project_key = f"项目版本:{version_project}"
                if version_project_key not in added_entities:
                    entities.append({
                        "entity": version_project,
                        "type": "项目版本及项目节点",
                        "description": "项目版本及项目节点"
                    })
                    added_entities.add(version_project_key)

                # 添加开始时间实体
                # st_entity_key = f"日期:{start_date}"
                # if st_entity_key not in added_entities:
                #     entities.append({
                #         "entity": start_date,
                #         "type": "日期",
                #         "description": "日期"
                #     })
                #     added_entities.add(st_entity_key)

                # 添加截止时间实体
                et_entity_key = f"日期:{end_date}"
                if et_entity_key not in added_entities:
                    entities.append({
                        "entity": end_date,
                        "type": "日期",
                        "description": "日期"
                    })
                    added_entities.add(et_entity_key)

                # 添加关系：项目节点 -> 版本 -> 版本项目
                relations.append({
                    "head": node_name,
                    "head_type": "项目节点",
                    "relation": "版本",
                    "tail": version_project,
                    "tail_type": "项目版本及项目节点",
                    "description": "项目版本及项目节点"
                })

                # 添加关系：版本项目 -> 开始时间 -> 时间值
                # relations.append({
                #     "head": version_project,
                #     "head_type": "版本项目",
                #     "relation": "开始时间",
                #     "tail": start_date,
                #     "tail_type": "日期",
                #     "description": "开始时间"
                # })

                # 添加关系：版本项目 -> 截止时间 -> 时间值
                relations.append({
                    "head": version_project,
                    "head_type": "项目版本及项目节点",
                    "relation": "截止时间",
                    "tail": end_date,
                    "tail_type": "日期",
                    "description": f"{version_project} 的截止时间是 {end_date}"
                })

        result = {
            "entities": entities,
            "relations": relations
        }

        # 保存结果
        with open('timeline_triplets.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def merge_triplets(self, plane_triplets: Dict[str, Any], timeline_triplets: Dict[str, Any]) -> Dict[str, Any]:
        """
        合并plane_triplets和timeline_triplets为一个三元组格式

        Args:
            plane_triplets: plane_triplets字典
            timeline_triplets: timeline_triplets字典

        Returns:
            合并后的三元组字典
        """
        entities = plane_triplets["entities"] + timeline_triplets["entities"]
        relations = plane_triplets["relations"] + timeline_triplets["relations"]
        result = {
            "entities": entities,
            "relations": relations
        }
        return result

    def _extract_version_from_plane_name(self, plane_name: str) -> Dict[str, str]:
        """
        从plane名称中提取版本信息
        
        Args:
            plane_name: plane名称，如 "V30 VDF RC12", "V31RC04" 等
        
        Returns:
            包含 version, sw, rc 的字典
        """
        result = {"version": "", "sw": "", "rc": ""}
        if not plane_name:
            return result
        
        # 尝试匹配格式: V30 VDF RC12
        match = re.match(r'(V\d+)\s+(\w+)\s+(RC[\d.]+)', plane_name)
        if match:
            result["version"] = match.group(1)
            result["sw"] = match.group(2)
            result["rc"] = match.group(3)
            return result
        
        # 尝试匹配格式: V31RC04 (版本号和RC连在一起)
        match = re.match(r'(V\d+)(RC[\d.]+)', plane_name)
        if match:
            result["version"] = match.group(1)
            result["rc"] = match.group(2)
            return result
        
        # 尝试单独匹配版本号和RC
        version_match = re.search(r'(V\d+)', plane_name)
        rc_match = re.search(r'(RC[\d.]+)', plane_name)
        sw_match = re.search(r'(VDF|Zone|ALPS)', plane_name, re.IGNORECASE)
        
        if version_match:
            result["version"] = version_match.group(1)
        if rc_match:
            result["rc"] = rc_match.group(1)
        if sw_match:
            result["sw"] = sw_match.group(1)
        
        return result

    def _get_all_lock_versions(self, planes: Dict) -> Dict[str, Any]:
        """获取所有包含锁仓事件的版本信息（不限制时间范围）"""
        results = {}
        
        for version_key, version_info in planes.items():
            for plane_name, plane_info_data in version_info.get("plane", {}).items():
                for evt_name, evt_info in plane_info_data.get("event", {}).items():
                    if "锁仓" in evt_name:
                        evt_st = evt_info.get("st", "")
                        evt_et = evt_info.get("et", "")
                        
                        result_key = f"{version_key}-{plane_name}" if version_key != plane_name else version_key
                        results[result_key] = {
                            "version": version_info.get("version", ""),
                            "sw": version_info.get("sw", ""),
                            "rc": version_info.get("rc", ""),
                            "status": version_info.get("status", ""),
                            "deliverables": version_info.get("deliverables", ""),
                            "plane": {
                                plane_name: {
                                    "st": plane_info_data.get("st", ""),
                                    "et": plane_info_data.get("et", ""),
                                    "event": {
                                        evt_name: {
                                            "st": evt_st,
                                            "et": evt_et
                                        }
                                    }
                                }
                            }
                        }
        
        return results

    def get_upcoming_lock_versions(self, advance_days: int = 2) -> List[Dict[str, Any]]:
        """
        获取即将开始的锁仓版本（指定天数后开始的锁仓）
        
        Args:
            advance_days: 提前几天提醒，默认2天
        
        Returns:
            即将开始锁仓的版本列表
        """
        planes = self.get_planes()
        all_lock_versions = self._get_all_lock_versions(planes)
        
        # 计算目标日期（advance_days天后）
        target_date = datetime.now() + timedelta(days=advance_days)
        target_date_str = target_date.strftime("%Y/%-m/%-d")
        
        upcoming_locks = []
        
        for key, value in all_lock_versions.items():
            for plane_name, plane_info in value.get("plane", {}).items():
                for evt_name, evt_info in plane_info.get("event", {}).items():
                    if "锁仓" in evt_name:
                        st = evt_info.get("st", "")
                        
                        # 检查锁仓开始时间是否是目标日期
                        if st == target_date_str:
                            # 提取版本信息
                            extracted = self._extract_version_from_plane_name(plane_name)
                            version = extracted.get("version", "") or value.get("version", "")
                            sw = extracted.get("sw", "") or value.get("sw", "")
                            rc = extracted.get("rc", "") or value.get("rc", "")
                            
                            upcoming_locks.append({
                                "version_key": key,
                                "plane_name": plane_name,
                                "version": version,
                                "sw": sw,
                                "rc": rc.upper() if rc else "",
                                "lock_start": st,
                                "lock_end": evt_info.get("et", ""),
                                "event_name": evt_name,
                                "status": value.get("status", "")
                            })
        
        return upcoming_locks

    def get_lock_versions_in_range(self, start_days: int = 0, end_days: int = 7) -> List[Dict[str, Any]]:
        """
        获取指定日期范围内的锁仓版本（用于设置提醒时立即查询）
        
        Args:
            start_days: 开始天数（0表示今天，1表示明天）
            end_days: 结束天数（7表示7天后）
        
        Returns:
            指定日期范围内开始锁仓的版本列表
        """
        planes = self.get_planes()
        all_lock_versions = self._get_all_lock_versions(planes)
        
        # 计算日期范围
        today = datetime.now()
        start_date = today + timedelta(days=start_days)
        end_date = today + timedelta(days=end_days)
        
        # 生成日期范围内的所有日期字符串
        date_range = []
        current_date = start_date
        while current_date <= end_date:
            date_range.append(current_date.strftime("%Y/%-m/%-d"))
            current_date += timedelta(days=1)
        
        lock_versions = []
        
        for key, value in all_lock_versions.items():
            for plane_name, plane_info in value.get("plane", {}).items():
                for evt_name, evt_info in plane_info.get("event", {}).items():
                    if "锁仓" in evt_name:
                        st = evt_info.get("st", "")
                        
                        # 检查锁仓开始时间是否在日期范围内
                        if st in date_range:
                            # 提取版本信息
                            extracted = self._extract_version_from_plane_name(plane_name)
                            version = extracted.get("version", "") or value.get("version", "")
                            sw = extracted.get("sw", "") or value.get("sw", "")
                            rc = extracted.get("rc", "") or value.get("rc", "")
                            
                            lock_versions.append({
                                "version_key": key,
                                "plane_name": plane_name,
                                "version": version,
                                "sw": sw,
                                "rc": rc.upper() if rc else "",
                                "lock_start": st,
                                "lock_end": evt_info.get("et", ""),
                                "event_name": evt_name,
                                "status": value.get("status", "")
                            })
        
        return lock_versions

    def query_rc_lock_info_for_upcoming(self,
                                        upcoming_locks: List[Dict],
                                        assignee: str = None,
                                        related_bu_team: str = None,
                                        summary: str = None,
                                        issuetype: str = None,
                                        status: str = None,
                                        priority: str = None,
                                        project: str = None,
                                        advance_days: int = 2,
                                        time_range_text: str = None) -> Dict[str, Any]:
        """
        查询即将锁仓版本的JIRA票据（用于设置提醒后立即展示）
        
        Args:
            upcoming_locks: 即将锁仓的版本列表
            其他参数同 query_rc_lock_info
        
        Returns:
            包含查询结果和卡片数据的字典，cards字段包含多个卡片（每个版本一个）
        """
        cards = []
        all_results = []
        jql_links = []
        
        for lock in upcoming_locks:
            version = lock.get("version", "")
            sw_raw = lock.get("sw", "")
            sw = sw_raw.upper() if sw_raw else ""  # 转换为大写，确保匹配 JIRA 中的格式（如 ZONE, VDF）
            rc = lock.get("rc", "").upper()
            st = lock.get("lock_start", "")
            et = lock.get("lock_end", "")
            plane_name = lock.get("plane_name", "")
            
            # 如果sw为空，尝试从plane_name重新提取
            if not sw and plane_name:
                extracted = self._extract_version_from_plane_name(plane_name)
                if not sw and extracted.get("sw"):
                    sw = extracted.get("sw", "").upper()
                    print(f"[query_rc_lock_info_for_upcoming] 从plane_name重新提取sw: {plane_name} -> sw={sw}")
            
            # 构建基础JQL
            jql_parts = [f'project = nt3vims']
            
            # 构建 fixVersion 条件
            if version and sw:
                # JIRA中的fixVersion格式是 "V32_ZONE RC05"（下划线格式）
                # 与其他查询函数保持一致，只使用下划线格式
                # sw 已转换为大写
                jql_parts.append(f'fixVersion ~ "{version}_{sw}*"')
            elif version:
                # 如果没有sw，使用更宽泛的匹配，但加上RC条件来限制范围
                if rc:
                    jql_parts.append(f'fixVersion ~ "{version}*"')
                else:
                    jql_parts.append(f'fixVersion ~ "{version}*"')
            
            # 添加 Planned RC 条件
            if rc:
                jql_parts.append(f'"Planned RC" = {rc}')
            
            # 添加约束条件
            if issuetype:
                types = [t.strip() for t in issuetype.split(',')]
                if len(types) > 1:
                    type_str = ', '.join([f'"{t}"' if ' ' in t else t for t in types])
                    jql_parts.append(f'type in ({type_str})')
                else:
                    jql_parts.append(f'type = "{issuetype}"' if ' ' in issuetype else f'type = {issuetype}')
            
            if status:
                statuses = [s.strip() for s in status.split(',')]
                if len(statuses) > 1:
                    status_str = ', '.join([f'"{s}"' if ' ' in s else s for s in statuses])
                    jql_parts.append(f'status in ({status_str})')
                else:
                    jql_parts.append(f'status = "{status}"' if ' ' in status else f'status = {status}')
            
            if related_bu_team:
                jql_parts.append(f'"Related BU Team" = "{related_bu_team}"')
            
            if assignee:
                jql_parts.append(f'assignee = "{assignee}"')
            
            if summary:
                jql_parts.append(f'summary ~ "{summary}"')
            
            if priority:
                jql_parts.append(f'priority = "{priority}"')
            
            if project:
                jql_parts[0] = f'project = {project}'
            
            # 检查是否有足够的条件
            if len(jql_parts) < 2:
                continue
            
            jql = ' AND '.join(jql_parts) + ' ORDER BY assignee ASC'
            print(f"[query_rc_lock_info_for_upcoming] 版本 {plane_name} (version={version}, sw={sw}, rc={rc})")
            print(f"[query_rc_lock_info_for_upcoming] 即将锁仓查询JQL: {jql}")
            
            # 构建JQL链接 - 使用urllib.parse.quote正确编码URL
            jql_encoded = quote(jql, safe='')
            jql_link = f"https://jira.nioint.com/issues/?jql={jql_encoded}"
            jql_link_info = {
                "version": plane_name,
                "rc": rc if rc else "N/A",
                "st": st,
                "et": et,
                "jql_link": jql_link
            }
            jql_links.append(jql_link_info)
            
            # 执行JIRA查询
            fields = ["Assignee", "Related BU Team", "summary", "issuetype", "status", "priority", "project"]
            version_issues = []
            try:
                jira_issues = self.jira_tool.search_issues(jql, fields)
                for issue in jira_issues:
                    issue["version_info"] = f"{plane_name} {rc}" if rc else plane_name
                    issue["st"] = st
                    issue["et"] = et
                version_issues = jira_issues
                all_results.extend(jira_issues)
                print(f"[query_rc_lock_info_for_upcoming] 版本 {plane_name} {rc} JIRA查询成功，返回 {len(version_issues)} 条结果")
            except Exception as e:
                print(f"[query_rc_lock_info_for_upcoming] 版本 {plane_name} {rc} JIRA查询失败: {e}")
                import traceback
                traceback.print_exc()
            
            # 如果有查询结果，为这个版本生成独立的卡片
            if version_issues:
                print(f"[query_rc_lock_info_for_upcoming] 版本 {plane_name} {rc} 查询到 {len(version_issues)} 条结果，生成卡片")
                card = self._build_rc_lock_card_for_reminder(
                    version_issues, 
                    [jql_link_info], 
                    advance_days, 
                    time_range_text=time_range_text
                )
                cards.append(card)
            else:
                print(f"[query_rc_lock_info_for_upcoming] 版本 {plane_name} {rc} 查询到 0 条结果，跳过生成卡片（JQL: {jql}）")
        
        print(f"[query_rc_lock_info_for_upcoming] 总共查询到 {len(all_results)} 条票据，生成了 {len(cards)} 个卡片")
        return {
            "success": True,
            "message": f"查询到 {len(all_results)} 条即将锁仓的相关票据，共 {len(cards)} 个版本",
            "data": all_results,
            "cards": cards,  # 多个卡片列表
            "card": cards[0] if cards else None,  # 保持向后兼容
            "jql_links": jql_links
        }

    def _extract_chinese_name(self, assignee) -> str:
        """
        从 Assignee 字段中提取中文名
        
        Args:
            assignee: Assignee 字段值，可能是多种格式：
                - 对象（有displayName属性）
                - "英文名(中文名)"
                - "英文名 中文名"
                - "中文名"
                - "英文名"
        
        Returns:
            中文名，如果没有找到中文名则返回原始值
        """
        if not assignee:
            return ""
        
        # 如果Assignee是对象，优先尝试获取displayName（通常包含中文名）
        if not isinstance(assignee, str):
            if hasattr(assignee, 'displayName'):
                assignee = assignee.displayName
            elif isinstance(assignee, dict):
                assignee = assignee.get('displayName', assignee.get('name', str(assignee)))
            else:
                assignee = str(assignee)
        
        assignee = str(assignee).strip()
        original_assignee = assignee
        
        # 方法1: 如果包含括号，提取括号内的内容
        if '(' in assignee and ')' in assignee:
            start = assignee.find('(')
            end = assignee.find(')')
            if start < end:
                chinese_name = assignee[start + 1:end].strip()
                # 如果提取的内容包含中文字符，返回它
                if any('\u4e00' <= char <= '\u9fff' for char in chinese_name):
                    return chinese_name
        
        # 方法2: 尝试匹配 "英文名 中文名" 格式（空格分隔，中文名在最后）
        # 使用正则表达式匹配：英文部分（可能包含空格）+ 中文部分
        # 匹配模式：英文部分（字母、空格、点、连字符）+ 一个或多个中文字符
        match = re.search(r'([A-Za-z\s\.\-]+)\s+([\u4e00-\u9fff]+)', assignee)
        if match:
            chinese_part = match.group(2)
            if chinese_part:
                return chinese_part
        
        # 方法3: 如果整个字符串包含中文字符，检查是否主要是中文
        chinese_chars = [char for char in assignee if '\u4e00' <= char <= '\u9fff']
        if chinese_chars:
            # 如果中文字符占比超过50%，或者字符串以中文开头，返回整个字符串
            chinese_ratio = len(chinese_chars) / len(assignee) if assignee else 0
            if chinese_ratio > 0.5 or assignee[0] in chinese_chars:
                return assignee
        
        # 方法4: 提取所有中文字符（如果存在）
        chinese_only = ''.join([char for char in assignee if '\u4e00' <= char <= '\u9fff'])
        if chinese_only:
            return chinese_only
        
        # 回退机制：如果没有找到中文名，返回原始值
        return original_assignee
    
    def _extract_version_prefix(self, version: str, rc: str) -> str:
        """
        提取版本的前部分，例如从 "V32 ZONE RC05-NIO 0180 G4 RC05" 提取 "V32 ZONE RC05"
        
        Args:
            version: 完整版本字符串，例如 "V32 ZONE RC05-NIO 0180 G4 RC05"
            rc: RC字符串，例如 "RC05"（可选，用于辅助判断）
        
        Returns:
            版本前部分，例如 "V32 ZONE RC05"
        """
        if not version:
            return ""
        
        # 优先按连字符分割，取第一部分（这是最常见的情况）
        if '-' in version:
            return version.split('-')[0].strip()
        
        # 如果没有连字符，尝试找到 RC 信息后的第一个空格或特殊字符
        if rc and rc in version:
            rc_index = version.find(rc)
            if rc_index != -1:
                # 找到 RC 结束位置
                end_pos = rc_index + len(rc)
                # 如果 RC 后面还有数字，继续包含（如 RC05）
                while end_pos < len(version) and version[end_pos].isdigit():
                    end_pos += 1
                # 检查后续字符，如果是空格或特殊字符则截断
                if end_pos < len(version):
                    next_char = version[end_pos]
                    if next_char in [' ', '-', '_']:
                        return version[:end_pos].strip()
        
        # 如果都没有，返回原版本
        return version.strip()

    def _build_rc_lock_card_for_reminder(self, issues: List[Dict], jql_links: List[Dict], advance_days: int, time_range_text: str = None) -> Dict:
        """
        构建RC锁仓提醒卡片（表格样式，和查询锁仓一致）
        
        Args:
            issues: JIRA票据列表
            jql_links: JQL链接列表
            advance_days: 提前天数
            time_range_text: 时间范围文本，如 "7天内" 或 "60天后"。如果不提供，则根据 advance_days 生成
        """
        # 构建表格行数据
        rows = []
        for issue in issues:
            key = issue.get('key', '')
            summary = issue.get('summary', '')
            issuetype = issue.get('issuetype', '')
            priority = issue.get('priority', '')
            assignee_raw = issue.get('Assignee', '')
            # 如果Assignee是对象，优先获取displayName
            if assignee_raw and not isinstance(assignee_raw, str):
                if hasattr(assignee_raw, 'displayName'):
                    assignee_raw = assignee_raw.displayName
                elif isinstance(assignee_raw, dict):
                    assignee_raw = assignee_raw.get('displayName', assignee_raw.get('name', str(assignee_raw)))
            # 提取中文名
            assignee = self._extract_chinese_name(assignee_raw)
            
            # 将Assignee转换为中文显示名
            assignee_display = self._get_assignee_display_name(assignee)
            
            color = self._get_priority_color(priority)
            
            rows.append({
                "key": f"[{key}](https://jira.nioint.com/browse/{key})",
                "issuetype": issuetype,
                "summary": summary[:50] + "..." if len(summary) > 50 else summary,
                "priority": [{"text": priority, "color": color}],
                "assignee": assignee
            })
        
        # 确定时间范围文本
        if time_range_text is None:
            time_range_text = f"{advance_days}天后"
        
        # 构建副标题
        jql_link = None
        if jql_links:
            first_link = jql_links[0]
            version = first_link.get('version', '')
            rc = first_link.get('rc', '')
            # 提取版本前部分
            version_prefix = self._extract_version_prefix(version, rc)
            subtitle = f"🔔 {time_range_text}锁仓 | 版本: {version_prefix}"
        else:
            subtitle = f"🔔 {time_range_text}锁仓"
        
        # 根据卡片中实际显示的 issues 构建查询链接
        # 使用 key in (KEY1, KEY2, ...) 的形式，确保能查询到所有显示的任务
        if issues:
            issue_keys = [issue.get('key', '') for issue in issues if issue.get('key')]
            if issue_keys:
                # 构建 JQL 查询：key in (KEY1, KEY2, ...)
                keys_str = ', '.join(issue_keys)
                jql = f'key in ({keys_str}) ORDER BY assignee ASC'
                jql_encoded = quote(jql, safe='')
                jql_link = f"https://jira.nioint.com/issues/?jql={jql_encoded}"
        
        # 构建 body elements
        body_elements = []
        
        # 如果有 JQL 链接，添加按钮
        if jql_link:
            body_elements.append({
                "tag": "column_set",
                "columns": [
                    {
                        "tag": "column",
                        "elements": [
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "任务详情"
                                },
                                "type": "default",
                                "width": "fill",
                                "behaviors": [
                                    {
                                        "type": "open_url",
                                        "default_url": jql_link,
                                        "pc_url": jql_link,
                                        "ios_url": jql_link,
                                        "android_url": jql_link
                                    }
                                ],
                                "element_id": "view_jql_button",
                                "margin": "0px 0px 8px 0px"
                            }
                        ],
                        "horizontal_align": "left",
                        "vertical_align": "top"
                    }
                ]
            })
        
        # 添加表格
        body_elements.append({
            "tag": "table",
            "element_id": "rc_lock_reminder_table",
            "columns": [
                {"data_type": "markdown", "display_name": "Key", "horizontal_align": "left", "name": "key", "width": "auto"},
                {"data_type": "text", "display_name": "IssueType", "horizontal_align": "left", "name": "issuetype", "width": "auto"},
                {"data_type": "text", "display_name": "Summary", "horizontal_align": "left", "name": "summary", "width": "auto"},
                {"data_type": "options", "display_name": "Priority", "horizontal_align": "left", "name": "priority", "width": "auto"},
                {"data_type": "text", "display_name": "Assignee", "horizontal_align": "left", "name": "assignee", "width": "auto"}
            ],
            "header_style": {"background_style": "none", "bold": True, "text_align": "left"},
            "margin": "0px",
            "page_size": 10,
            "row_height": "middle",
            "rows": rows
        })
        
        card = {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "icon": {
                    "tag": "standard_icon",
                    "token": "bell_outlined"
                },
                "padding": "12px 8px 12px 8px",
                "subtitle": {
                    "content": subtitle,
                    "tag": "plain_text"
                },
                "template": "orange",
                "title": {
                    "content": f"请及时流转任务（{time_range_text}）",
                    "tag": "plain_text"
                }
            },
            "body": {
                "direction": "vertical",
                "elements": body_elements
            }
        }
        
        return card

    def query_rc_lock_info(self, 
                          assignee: str = None,
                          related_bu_team: str = None,
                          summary: str = None,
                          issuetype: str = None,
                          status: str = None,
                          priority: str = None,
                          project: str = None,
                          only_current: bool = False) -> Dict[str, Any]:
        """
        查询RC锁仓信息，先从飞书文档获取锁仓信息，再根据约束条件到JIRA获取对应的票
        
        Args:
            assignee: 经办人/指派人
            related_bu_team: 关联业务单元团队
            summary: 摘要/标题（模糊匹配）
            issuetype: 问题类型/工单类型 (如 development, bug, "External Bug", "Quick Bug")
            status: 状态 (如 Open, Done, Discard, "In Progress")
            priority: 优先级
            project: 项目
            only_current: 是否只查询当前日期在锁仓范围内的版本，默认False查询所有锁仓版本
        
        Returns:
            包含查询结果和卡片数据的字典
        """
        date = datetime.now().strftime("%Y/%-m/%-d")
        
        # 1. 从飞书文档获取锁仓信息
        planes = self.get_planes()
        
        # 2. 获取锁仓版本信息
        if only_current:
            # 只获取当前日期在锁仓范围内的版本
            plane_info = self.get_plane_info(planes, date=date, status="In Progress", event_name="锁仓")
        else:
            # 获取所有锁仓版本（不限制时间范围）
            plane_info = self._get_all_lock_versions(planes)
        
        if not plane_info:
            return {
                "success": False,
                "message": "没有找到锁仓版本信息",
                "data": [],
                "card": None
            }
        
        # 3. 构建JQL查询并获取JIRA数据
        all_results = []
        jql_links = []
        
        for key, value in plane_info.items():
            # 先尝试从 value 中获取版本信息
            version = value.get("version", "")
            sw = value.get("sw", "")
            rc = value.get("rc", "").upper()
            
            for plane_name, plane_info_detail in value.get("plane", {}).items():
                # 如果 version/sw/rc 为空，尝试从 plane_name 中提取
                if not version or not rc:
                    extracted = self._extract_version_from_plane_name(plane_name)
                    if not version and extracted["version"]:
                        version = extracted["version"]
                    if not sw and extracted["sw"]:
                        sw = extracted["sw"]
                    if not rc and extracted["rc"]:
                        rc = extracted["rc"].upper()
                
                for evt_name, evt_info in plane_info_detail.get("event", {}).items():
                    if "锁仓" in evt_name:
                        st = evt_info.get("st", "")
                        et = evt_info.get("et", "")
                        
                        # 如果是only_current模式，需要检查时间范围；否则处理所有锁仓版本
                        if only_current and not self.check_time_time(date, st, et):
                            continue
                        
                        # 构建基础JQL
                        jql_parts = [f'project = nt3vims']
                        
                        # 构建 fixVersion 条件 - 需要确保有有效的版本信息
                        if version and sw:
                            # JIRA中的fixVersion格式是 "V32_ZONE RC05"（下划线格式）
                            # 与其他查询函数保持一致，只使用下划线格式
                            jql_parts.append(f'fixVersion ~ "{version}_{sw}*"')
                        elif version:
                            jql_parts.append(f'fixVersion ~ "{version}*"')
                        
                        # 添加 Planned RC 条件 - 需要确保 rc 不为空
                        if rc:
                            jql_parts.append(f'"Planned RC" = {rc}')
                        
                        # 添加约束条件
                        if issuetype:
                            # 支持多个issuetype用逗号分隔
                            types = [t.strip() for t in issuetype.split(',')]
                            if len(types) > 1:
                                type_str = ', '.join([f'"{t}"' if ' ' in t else t for t in types])
                                jql_parts.append(f'type in ({type_str})')
                            else:
                                jql_parts.append(f'type = "{issuetype}"' if ' ' in issuetype else f'type = {issuetype}')
                        
                        if status:
                            # 支持多个status用逗号分隔
                            statuses = [s.strip() for s in status.split(',')]
                            if len(statuses) > 1:
                                status_str = ', '.join([f'"{s}"' if ' ' in s else s for s in statuses])
                                jql_parts.append(f'status in ({status_str})')
                            else:
                                jql_parts.append(f'status = "{status}"' if ' ' in status else f'status = {status}')
                        
                        if related_bu_team:
                            # Related BU Team在JIRA中可能是多值字段，使用in操作符更安全
                            jql_parts.append(f'"Related BU Team" in ("{related_bu_team}")')
                        
                        if assignee:
                            # 尝试转换飞书ID到JIRA用户ID
                            try:
                                user_info = self.feishu_msg.get_user_info(assignee)
                                jira_user_id = user_info.get("user_id", assignee)
                                jql_parts.append(f'assignee = "{jira_user_id}"')
                            except:
                                jql_parts.append(f'assignee = "{assignee}"')
                        
                        if summary:
                            jql_parts.append(f'summary ~ "{summary}"')
                        
                        if priority:
                            jql_parts.append(f'priority = "{priority}"')
                        
                        if project:
                            jql_parts[0] = f'project = {project}'
                        
                        # 检查是否有足够的条件来构建有效的JQL
                        if len(jql_parts) < 2:
                            print(f"跳过无效的版本信息: {key} / {plane_name}")
                            continue
                        
                        jql = ' AND '.join(jql_parts) + ' ORDER BY assignee ASC'
                        print(f"RC锁仓查询JQL: {jql}")
                        
                        # 构建JQL链接 - 使用urllib.parse.quote正确编码URL
                        jql_encoded = quote(jql, safe='')
                        jql_link = f"https://jira.nioint.com/issues/?jql={jql_encoded}"
                        jql_links.append({
                            "version": f"{plane_name}",
                            "rc": rc if rc else "N/A",
                            "st": st,
                            "et": et,
                            "jql_link": jql_link
                        })
                        
                        # 执行JIRA查询
                        fields = ["Assignee", "Related BU Team", "summary", "issuetype", "status", "priority", "project"]
                        try:
                            jira_issues = self.jira_tool.search_issues(jql, fields)
                            for issue in jira_issues:
                                issue["version_info"] = f"{plane_name} {rc}" if rc else plane_name
                                issue["st"] = st
                                issue["et"] = et
                            all_results.extend(jira_issues)
                        except Exception as e:
                            print(f"JIRA查询失败: {e}")
        
        if not all_results:
            return {
                "success": True,
                "message": "未找到符合条件的JIRA票据",
                "data": [],
                "card": None,
                "jql_links": jql_links
            }
        
        # 4. 构建飞书卡片
        card = self._build_rc_lock_card(all_results, jql_links)
        
        return {
            "success": True,
            "message": f"查询到 {len(all_results)} 条RC锁仓相关票据",
            "data": all_results,
            "card": card,
            "jql_links": jql_links
        }

    def _build_rc_lock_card(self, issues: List[Dict], jql_links: List[Dict]) -> Dict:
        """
        构建RC锁仓信息的飞书卡片
        
        Args:
            issues: JIRA票据列表
            jql_links: JQL链接列表
        
        Returns:
            飞书卡片JSON
        """
        # 构建表格行数据
        rows = []
        for issue in issues:
            key = issue.get('key', '')
            summary = issue.get('summary', '')
            issuetype = issue.get('issuetype', '')
            priority = issue.get('priority', '')
            assignee_raw = issue.get('Assignee', '')
            # 如果Assignee是对象，优先获取displayName
            if assignee_raw and not isinstance(assignee_raw, str):
                if hasattr(assignee_raw, 'displayName'):
                    assignee_raw = assignee_raw.displayName
                elif isinstance(assignee_raw, dict):
                    assignee_raw = assignee_raw.get('displayName', assignee_raw.get('name', str(assignee_raw)))
            # 提取中文名
            assignee = self._extract_chinese_name(assignee_raw)
            related_bu = issue.get('Related BU Team', [])
            st = issue.get('st', '')
            et = issue.get('et', '')
            
            # 处理Related BU Team（可能是列表）
            if isinstance(related_bu, list):
                related_bu = ', '.join(related_bu) if related_bu else ''
            
            # 将Assignee转换为中文显示名
            assignee_display = self._get_assignee_display_name(assignee)
            
            # 获取优先级颜色
            color = self._get_priority_color(priority)
            
            rows.append({
                "key": f"[{key}](https://jira.nioint.com/browse/{key})",
                "issuetype": issuetype,
                "summary": summary[:50] + "..." if len(summary) > 50 else summary,
                "priority": [{"text": priority, "color": color}],
                "assignee": assignee_display
            })
        
        # 构建副标题
        jql_link = None
        if jql_links:
            first_link = jql_links[0]
            version = first_link.get('version', '')
            rc = first_link.get('rc', '')
            # 提取版本前部分，只显示 "V30 ZONE RC05" 而不是完整版本字符串
            version_prefix = self._extract_version_prefix(version, rc)
            jql_link = first_link.get('jql_link', '')
            subtitle = f"节点: 锁仓 | 版本: {version_prefix}"
        else:
            subtitle = "RC锁仓信息查询结果"
        
        # 构建 body elements
        body_elements = []
        
        # 如果有 JQL 链接，添加按钮
        if jql_link:
            body_elements.append({
                "tag": "column_set",
                "columns": [
                    {
                        "tag": "column",
                        "elements": [
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "任务详情"
                                },
                                "type": "default",
                                "width": "fill",
                                "behaviors": [
                                    {
                                        "type": "open_url",
                                        "default_url": jql_link,
                                        "pc_url": jql_link,
                                        "ios_url": jql_link,
                                        "android_url": jql_link
                                    }
                                ],
                                "element_id": "view_jql_button",
                                "margin": "0px 0px 8px 0px"
                            }
                        ],
                        "horizontal_align": "left",
                        "vertical_align": "top"
                    }
                ]
            })
        
        # 添加表格
        body_elements.append({
            "tag": "table",
            "element_id": "rc_lock_table",
            "columns": [
                {
                    "data_type": "markdown",
                    "display_name": "Key",
                    "horizontal_align": "left",
                    "name": "key",
                    "width": "auto"
                },
                {
                    "data_type": "text",
                    "display_name": "IssueType",
                    "horizontal_align": "left",
                    "name": "issuetype",
                    "width": "auto"
                },
                {
                    "data_type": "text",
                    "display_name": "Summary",
                    "horizontal_align": "left",
                    "name": "summary",
                    "width": "auto"
                },
                {
                    "data_type": "options",
                    "display_name": "Priority",
                    "horizontal_align": "left",
                    "name": "priority",
                    "width": "auto"
                },
                {
                    "data_type": "text",
                    "display_name": "Assignee",
                    "horizontal_align": "left",
                    "name": "assignee",
                    "width": "auto"
                },
                {
                    "data_type": "text",
                    "display_name": "Related BU Team",
                    "horizontal_align": "left",
                    "name": "related_bu",
                    "width": "auto"
                },
                {
                    "data_type": "text",
                    "display_name": "开始时间",
                    "horizontal_align": "left",
                    "name": "start_date",
                    "width": "auto"
                },
                {
                    "data_type": "text",
                    "display_name": "截止时间",
                    "horizontal_align": "left",
                    "name": "end_date",
                    "width": "auto"
                }
            ],
            "header_style": {
                "background_style": "none",
                "bold": True,
                "text_align": "left"
            },
            "margin": "0px",
            "page_size": 10,
            "row_height": "middle",
            "rows": rows
        })
        
        # 构建卡片
        card = {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "icon": {
                    "tag": "standard_icon",
                    "token": "task_outlined"
                },
                "padding": "12px 8px 12px 8px",
                "subtitle": {
                    "content": subtitle,
                    "tag": "plain_text"
                },
                "template": "blue",
                "title": {
                    "content": f"RC锁仓任务列表 (共{len(issues)}条)",
                    "tag": "plain_text"
                }
            },
            "body": {
                "direction": "vertical",
                "elements": body_elements
            }
        }
        
        # 如果有多个JQL链接，添加额外的按钮（第一个链接的按钮已经在 body_elements 中了）
        if len(jql_links) > 1:
            buttons_elements = []
            # 从第二个链接开始（第一个已经在 body_elements 中了）
            for link_info in jql_links[1:4]:  # 最多再显示3个按钮（总共4个）
                buttons_elements.append({
                    "elements": [
                        {
                            "behaviors": [
                                {
                                    "android_url": "",
                                    "default_url": link_info["jql_link"],
                                    "ios_url": "",
                                    "pc_url": "",
                                    "type": "open_url"
                                }
                            ],
                            "element_id": f"btn_{link_info['version']}_{link_info['rc']}".replace(" ", "_").replace(".", "_"),
                            "margin": "4px 0px 4px 0px",
                            "tag": "button",
                            "text": {
                                "content": f"查看 {link_info['version']} {link_info['rc']}",
                                "tag": "plain_text"
                            },
                            "type": "primary_filled" if link_info == jql_links[0] else "default",
                            "width": "fill"
                        }
                    ],
                    "horizontal_align": "left",
                    "tag": "column",
                    "vertical_align": "top",
                    "vertical_spacing": "8px",
                    "width": "auto"
                })
            
            if buttons_elements:
                card["body"]["elements"].append({
                    "columns": buttons_elements,
                    "flex_mode": "stretch",
                    "horizontal_align": "left",
                    "horizontal_spacing": "8px",
                    "margin": "8px 0px 0px 0px",
                    "tag": "column_set"
                })
        
        return card

    def find_field_info(self, field_name: str = "Found Version"):
        """
        查找JIRA字段信息，用于调试
        
        Args:
            field_name: 要查找的字段名
            
        Returns:
            字段信息字典
        """
        all_fields = self.jira_tool.get_all_fields()
        
        # 精确匹配
        for field in all_fields:
            if field.get("name") == field_name:
                return {
                    "found": True,
                    "name": field.get("name"),
                    "id": field.get("id"),
                    "type": field.get("type"),
                    "custom": field.get("custom", False),
                    "searchable": field.get("searchable", False),
                    "orderable": field.get("orderable", False),
                    "navigable": field.get("navigable", False),
                    "full_info": field
                }
        
        # 模糊匹配
        similar = []
        for field in all_fields:
            name = field.get("name", "")
            if field_name.lower() in name.lower() or name.lower() in field_name.lower():
                similar.append({
                    "name": name,
                    "id": field.get("id"),
                    "type": field.get("type")
                })
        
        return {
            "found": False,
            "similar_fields": similar
        }
    
    def get_all_jira_statuses(self, project: str = "nt3vims") -> List[str]:
        """
        获取JIRA项目中所有可用的状态
        
        Args:
            project: 项目名称，默认 nt3vims
        
        Returns:
            状态名称列表
        """
        try:
            # 获取项目所有问题类型的状态
            issue_types = self.jira_tool.jira.issue_types_for_project(project)
            all_statuses = set()
            
            for issue_type in issue_types:
                if hasattr(issue_type, 'statuses'):
                    for status in issue_type.statuses:
                        if hasattr(status, 'name'):
                            all_statuses.add(status.name)
            
            # 如果通过问题类型获取不到，尝试获取所有状态
            if not all_statuses:
                statuses = self.jira_tool.jira.statuses()
                all_statuses = {status.name for status in statuses if hasattr(status, 'name')}
            
            return sorted(list(all_statuses))
        except Exception as e:
            print(f"获取JIRA状态失败: {e}")
            # 返回已知的常用状态
            return ["Open", "In Progress", "Done", "Closed", "Resolved", "Discard", "To Do", "In Review", "Reopened"]

    def query_assignee_tasks(self,
                             assignee: str = None,
                             task_type: str = None,
                             status: str = None,
                             project: str = "nt3vims",
                             created_after: str = None,
                             jira_user_id: str = None,
                             version: str = None,
                             related_bu_team: str = None) -> Dict[str, Any]:
        """
        查询任务票清单，支持按经办人、类型、状态、时间、版本、Related BU Team过滤
        
        Args:
            assignee: 经办人（飞书用户ID或JIRA用户名），可选。如果不提供，则查询所有经办人的任务票
            task_type: 任务类型，可选值：问题/bug, 任务/开发/development, 测试/test，多个用逗号分隔
            status: 状态过滤，支持的状态包括（多个用逗号分隔）：
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
            created_after: 创建时间筛选，格式：YYYY-MM-DD 或 YYYY-MM（如 "2025-10-01" 或 "2025-10" 表示查询该日期/月份之后的任务）
            project: 项目，默认 nt3vims
            jira_user_id: JIRA用户名（如果assignee是open_id格式，且已知JIRA用户名，可直接提供此参数避免调用get_user_info）
            version: 版本过滤，如 "v31", "v32", "V31", "V32"等，支持模糊匹配（如 "v31" 会匹配 "V31_*" 格式的Found Version，如V31_Zone_RL232_BL0170_BL0172、V31_VDF_RC03等）
            related_bu_team: Related BU Team过滤，如 "BFSS", "Lighting", "Body", "Seat"等
        
        Returns:
            包含查询结果和卡片数据的字典
        """
        # 如果未指定status，默认只显示 Open, Analysis, Solution 状态的任务
        # if not status:
        #     status = "Open,Analysis,Solution"
        # 类型映射
        type_mapping = {
            "问题": ["Bug", "Int Bug", "Quick Bug", "External Bug"],
            "bug": ["Bug", "Int Bug", "Quick Bug", "External Bug"],
            "开发": ["Development", "Epic", "Design", "Task"],
            "任务": ["Development", "Epic", "Design", "Task"],
            "development": ["Development", "Epic", "Design", "Task"],
            "测试": ["HIL Test", "AO Test"],
            "test": ["HIL Test", "AO Test"],
        }
        
        # 构建JQL
        jql_parts = [f'project = {project}']
        
        # 添加经办人条件 - 尝试将飞书 open_id 转换为 JIRA user_id
        assignee_display_name = assignee if assignee else "全部"  # 默认显示原始值
        is_open_id_format = assignee.startswith("ou_") if assignee else False
        
        if assignee and is_open_id_format:
            # 验证open_id格式
            if not re.match(r'^ou_[a-f0-9]{32}$', assignee):
                return {
                    "success": False,
                    "message": f"open_id格式错误（应为ou_开头+32位十六进制）: {assignee}",
                    "data": [],
                    "card": None,
                    "jql_link": ""
                }
            
            # 如果已经提供了JIRA user_id，直接使用，避免调用get_user_info
            if jira_user_id:
                print(f"[query_assignee_tasks] 使用提供的JIRA user_id: {jira_user_id}")
                jql_parts.append(f'assignee = "{jira_user_id}"')
                assignee_display_name = jira_user_id
            else:
                # 如果没有提供JIRA user_id，尝试调用get_user_info获取
                try:
                    user_info = self.feishu_msg.get_user_info(assignee)
                    jira_user_id = user_info.get("user_id", assignee)
                    jql_parts.append(f'assignee = "{jira_user_id}"')
                    # 获取用户显示名称（中文+英文）
                    name = user_info.get("name", "")
                    en_name = user_info.get("en_name", "")
                    if name and en_name:
                        assignee_display_name = f"{name} {en_name}"
                    elif name:
                        assignee_display_name = name
                    elif en_name:
                        assignee_display_name = en_name
                except Exception as e:
                    # 如果转换失败，尝试降级处理：直接使用open_id作为JIRA用户名查询
                    error_msg = str(e)
                    error_lower = error_msg.lower()
                    
                    # 检查是否是权限错误或用户不存在错误
                    # 注意：get_user_info failed 通常表示权限问题或用户不存在
                    is_permission_error = (
                        "get_user_info failed" in error_lower or  # 飞书API调用失败，通常是权限问题
                        "no user authority" in error_lower or 
                        "not exist" in error_lower or 
                        "not a valid" in error_lower or
                        "41050" in error_msg or  # 飞书API权限错误码
                        "permission" in error_lower or
                        "forbidden" in error_lower or
                        "unauthorized" in error_lower
                    )
                    
                    if is_permission_error:
                        # 权限错误：返回友好的错误信息
                        print(f"无法获取用户信息（权限问题或用户不存在）: {assignee}")
                        print(f"错误详情: {error_msg}")
                        # 返回明确的权限错误信息，提示用户可能没有权限访问该用户信息
                        return {
                            "success": False,
                            "message": f"无法获取用户信息。可能的原因：1) 当前用户没有权限访问该用户（open_id: {assignee}）的信息；2) 该用户不存在或已离职。建议：如果该用户有JIRA账号，可以尝试使用JIRA用户名查询，或在群聊中查询（群聊中可能有更多权限）。",
                            "data": [],
                            "card": None,
                            "jql_link": ""
                        }
                    else:
                        # 其他错误：返回详细错误信息
                        print(f"获取用户JIRA ID失败: {e}")
                        return {
                            "success": False,
                            "message": f"获取用户JIRA ID失败: {error_msg}",
                            "data": [],
                            "card": None,
                            "jql_link": ""
                        }
        elif assignee:
            # 不是open_id格式，直接作为JIRA用户名使用
            jql_parts.append(f'assignee = "{assignee}"')
        # 如果assignee为空，则不添加经办人条件，查询所有经办人的任务票
        
        # 添加版本条件 - 使用Found Version字段
        if version:
            version_clean = version.strip().upper()
            # 如果版本号以V开头，直接使用；否则添加V前缀
            if not version_clean.startswith('V'):
                version_clean = 'V' + version_clean.lstrip('v')
            # JIRA中的Found Version格式是 "V31_Zone_RL232_BL0170_BL0172"（下划线格式），使用模糊匹配
            # 查询Found Version字段，匹配所有以V31开头的版本（如V31_Zone_RL232_BL0170_BL0172、V31_VDF_RC03等）
            # 注意：字段名是 "Found Version "（带尾随空格）
            all_versions = self.jira_tool.get_attr_values("versions", project_key="NT3VIMS")
            this_str = "("
            for iitem in all_versions:
                this_flag = True
                for this_i in version.split(" "):
                    for this_ii in this_i.split(","):
                        if this_ii.strip():
                            if iitem.lower().find(this_ii.strip().lower()) == -1:
                                this_flag = False
                if this_flag:
                    this_str += f'"{iitem}",'
            if this_str.endswith(","):
                this_str = this_str[:-1]
            this_str += ")"
            if this_str == "()":
                this_str = f'("{version}")'
            jql_parts.append(f'fixVersion in {this_str}')
            print(f"添加版本筛选: fixVersion in {this_str}")
        
        # 添加Related BU Team条件 - 复用RC锁仓中的逻辑
        if related_bu_team:
            # Related BU Team在JIRA中可能是多值字段，使用in操作符更安全
            # 与RC锁仓保持一致："Related BU Team" in ("{related_bu_team}")
            jql_parts.append(f'"Related BU Team" in ("{related_bu_team}")')
            print(f"添加Related BU Team筛选: {related_bu_team}")
        
        # 添加类型条件 - 支持多种类型
        if task_type:
            all_types = []
            # 分割多种类型（支持逗号、空格、顿号分隔）
            type_list = re.split(r'[,，、\s]+', task_type.strip())
            for t in type_list:
                t_lower = t.lower().strip()
                if t_lower and t_lower in type_mapping:
                    all_types.extend(type_mapping[t_lower])
                elif t_lower:
                    all_types.append(t)
            
            if all_types:
                # 去重
                all_types = list(dict.fromkeys(all_types))
                type_str = ', '.join([f'"{t}"' if ' ' in t else t for t in all_types])
                jql_parts.append(f'type in ({type_str})')
        
        # 添加状态条件
        if status:
            statuses = [s.strip() for s in status.split(',')]
            if len(statuses) > 1:
                status_str = ', '.join([f'"{s}"' if ' ' in s else s for s in statuses])
                jql_parts.append(f'status in ({status_str})')
            else:
                jql_parts.append(f'status = "{status}"' if ' ' in status else f'status = {status}')
        
        # 添加创建时间条件
        if created_after:
            try:
                # 解析时间格式：支持 YYYY-MM-DD 或 YYYY-MM
                created_after = created_after.strip()
                parts = created_after.split('-')
                
                if len(parts) == 2:
                    # YYYY-MM 格式，转换为该月第一天
                    year, month = parts
                    # 验证年月格式
                    if len(year) == 4 and len(month) == 2 and year.isdigit() and month.isdigit():
                        date_str = f"{year}-{month}-01"
                    else:
                        raise ValueError(f"无效的时间格式: {created_after}")
                elif len(parts) == 3:
                    # YYYY-MM-DD 格式
                    year, month, day = parts
                    # 验证日期格式
                    if len(year) == 4 and len(month) == 2 and len(day) == 2 and \
                       year.isdigit() and month.isdigit() and day.isdigit():
                        date_str = created_after
                    else:
                        raise ValueError(f"无效的时间格式: {created_after}")
                else:
                    raise ValueError(f"无效的时间格式: {created_after}")
                
                # 转换为JIRA日期格式（YYYY-MM-DD）
                jql_parts.append(f'created >= "{date_str}"')
                print(f"添加创建时间筛选: created >= {date_str}")
            except Exception as e:
                print(f"解析创建时间失败: {e}, 忽略时间筛选条件")
        
        jql = ' AND '.join(jql_parts) + ' ORDER BY created DESC'
        print(f"经办人任务查询JQL: {jql}")
        
        # 构建JQL链接 - 使用urllib.parse.quote正确编码URL
        jql_encoded = quote(jql, safe='')
        jql_link = f"https://jira.nioint.com/issues/?jql={jql_encoded}"
        
        # 执行JIRA查询
        fields = ["Assignee", "Related BU Team", "summary", "issuetype", "status", "priority", "project", "created", "Found Version "]
        try:
            jira_issues = self.jira_tool.search_issues(jql, fields)
        except Exception as e:
            print(f"JIRA查询失败: {e}")
            return {
                "success": False,
                "message": f"查询失败: {str(e)}",
                "data": [],
                "card": None,
                "jql_link": jql_link
            }
        
        # 排除不需要显示的状态（在代码中过滤，而不是在JQL中排除）
        excluded_statuses = {
            "Duplicate", "RC Duplicate", "Closed", "Resolved", "Done", "Validated", "Verify",
            "Hold", "Fixed", "Cancelled", "Rejected", "Frozen", "Pause",
            "Draft", "Validate", "Engineering Review Complete", "Decision",
            "Verified", "Validation", "Close w/o Action-RootCause",
            "Close w/o Action-Solution", "Close w/o Action-Implementat",
            "Denied", "In Validation", "Discard", "Close"
        }
        
        # 过滤掉排除的状态
        filtered_issues = []
        for issue in jira_issues:
            issue_status = issue.get('status', '')
            if issue_status not in excluded_statuses:
                filtered_issues.append(issue)
        
        # 按创建时间倒序排序（越新的越前）
        def get_created_time(issue):
            created = issue.get('created', '')
            if created:
                try:
                    # JIRA时间格式: 2026-01-25T10:30:00.000+0800
                    # 解析时间字符串
                    if 'T' in created:
                        time_str = created.split('+')[0].split('.')[0]  # 去掉时区和毫秒
                        return datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%S')
                    return datetime.min
                except:
                    return datetime.min
            return datetime.min
        
        filtered_issues.sort(key=get_created_time, reverse=True)
        
        if not filtered_issues:
            return {
                "success": True,
                "message": "未找到符合条件的JIRA票据",
                "data": [],
                "card": None,
                "jql_link": jql_link
            }
        
        # 构建卡片
        card = self._build_assignee_tasks_card(filtered_issues, assignee_display_name, task_type, jql_link, version, related_bu_team)
        
        return {
            "success": True,
            "message": f"查询到 {len(filtered_issues)} 条任务票",
            "data": filtered_issues,
            "card": card,
            "jql_link": jql_link
        }

    def _build_assignee_tasks_card(self, issues: List[Dict], assignee_display_name: str, task_type: str, jql_link: str, version: str = None, related_bu_team: str = None) -> Dict:
        """
        构建经办人任务票清单卡片
        
        Args:
            assignee_display_name: 经办人显示名称（中文+英文）
            task_type: 任务类型
            jql_link: JQL查询链接
            version: 版本号（可选）
            related_bu_team: Related BU Team（可选）
        """
        # 限制显示条数，避免卡片数据过大导致渲染失败
        MAX_DISPLAY_ROWS = 50
        total_count = len(issues)
        display_issues = issues[:MAX_DISPLAY_ROWS]
        
        # 构建表格行数据
        rows = []
        for issue in display_issues:
            key = issue.get('key', '')
            summary = issue.get('summary', '')
            issuetype = issue.get('issuetype', '')
            priority = issue.get('priority', '')
            assignee_name = issue.get('Assignee', '')
            
            color = self._get_priority_color(priority)
            
            rows.append({
                "key": f"[{key}](https://jira.nioint.com/browse/{key})",
                "issuetype": issuetype,
                "summary": summary[:50] + "..." if len(summary) > 50 else summary,
                "priority": [{"text": priority, "color": color}],
                "assignee": assignee_name
            })
        
        # 任务类型描述
        type_desc = task_type if task_type else "全部"
        
        # 构建副标题内容
        subtitle_parts = []
        if assignee_display_name and assignee_display_name != "全部":
            subtitle_parts.append(f"经办人: {assignee_display_name}")
        subtitle_parts.append(f"类型: {type_desc}")
        
        # 添加版本信息（如果有）
        if version:
            version_clean = version.strip().upper()
            if not version_clean.startswith('V'):
                version_clean = 'V' + version_clean.lstrip('v')
            subtitle_parts.append(f"版本: {version_clean}")
        
        # 添加Related BU Team信息（如果有）
        if related_bu_team:
            subtitle_parts.append(f"Related BU Team: {related_bu_team}")
        
        subtitle_content = " | ".join(subtitle_parts)
        
        # 标题显示总数和显示数
        if total_count > MAX_DISPLAY_ROWS:
            title_content = f"任务票清单 (显示前{MAX_DISPLAY_ROWS}条，共{total_count}条)"
        else:
            title_content = f"任务票清单 (共{total_count}条)"
        
        card = {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "icon": {
                    "tag": "standard_icon",
                    "token": "task_outlined"
                },
                "padding": "12px 8px 12px 8px",
                "subtitle": {
                    "content": subtitle_content,
                    "tag": "lark_md"
                },
                "template": "blue",
                "title": {
                    "content": title_content,
                    "tag": "plain_text"
                }
            },
            "body": {
                "direction": "vertical",
                "elements": [
                    {
                        "tag": "column_set",
                        "columns": [
                            {
                                "tag": "column",
                                "elements": [
                                    {
                                        "tag": "button",
                                        "text": {
                                            "tag": "plain_text",
                                            "content": "任务详情"
                                        },
                                        "type": "default",
                                        "width": "fill",
                                        "behaviors": [
                                            {
                                                "type": "open_url",
                                                "default_url": jql_link,
                                                "pc_url": jql_link,
                                                "ios_url": jql_link,
                                                "android_url": jql_link
                                            }
                                        ],
                                        "element_id": "view_jql_button",
                                        "margin": "0px 0px 8px 0px"
                                    }
                                ],
                                "horizontal_align": "left",
                                "vertical_align": "top"
                            }
                        ],
                        "margin": "0px 0px 8px 0px"
                    },
                    {
                        "tag": "table",
                        "element_id": "assignee_tasks_table",
                        "columns": [
                            {"data_type": "markdown", "display_name": "Key", "horizontal_align": "left", "name": "key", "width": "auto"},
                            {"data_type": "text", "display_name": "IssueType", "horizontal_align": "left", "name": "issuetype", "width": "auto"},
                            {"data_type": "text", "display_name": "Summary", "horizontal_align": "left", "name": "summary", "width": "auto"},
                            {"data_type": "options", "display_name": "Priority", "horizontal_align": "left", "name": "priority", "width": "auto"},
                            {"data_type": "text", "display_name": "Assignee", "horizontal_align": "left", "name": "assignee", "width": "auto"}
                        ],
                        "header_style": {"background_style": "none", "bold": True, "text_align": "left"},
                        "margin": "0px",
                        "page_size": 10,
                        "row_height": "middle",
                        "rows": rows
                    }
                ]
            }
        }
        
        return card

    def send_rc_lock_reminder(self, chat_id: str, upcoming_locks: List[Dict], filters: Dict, advance_days: int = 2) -> Dict[str, Any]:
        """
        发送RC锁仓提醒到群聊（使用详细任务列表卡片）
        
        Args:
            chat_id: 群聊ID
            upcoming_locks: 即将开始的锁仓版本列表
            filters: 过滤条件
            advance_days: 提前天数
        
        Returns:
            发送结果
        """
        if not upcoming_locks:
            return {"success": False, "message": "没有即将开始的锁仓版本"}
        
        # 查询即将锁仓版本的JIRA票据（使用和设置提醒后立即展示相同的逻辑）
        query_result = self.query_rc_lock_info_for_upcoming(
            upcoming_locks=upcoming_locks,
            assignee=filters.get("assignee"),
            related_bu_team=filters.get("related_bu_team"),
            summary=filters.get("summary"),
            issuetype=filters.get("issuetype"),
            status=filters.get("status"),
            priority=filters.get("priority"),
            project=filters.get("project"),
            advance_days=advance_days
        )
        
        # 发送多个卡片（每个版本一个，只发送有查询结果的版本）
        cards = query_result.get("cards", [])
        try:
            sent_count = 0
            for card in cards:
                if self.send_rc_lock_card(chat_id, card):
                    sent_count += 1
            
            jira_count = len(query_result.get("data", []))
            return {
                "success": True, 
                "message": f"已发送{sent_count}个锁仓提醒（共{len(upcoming_locks)}个版本），共{jira_count}条任务"
            }
        except Exception as e:
            print(f"发送RC锁仓提醒失败: {e}")
            return {"success": False, "message": f"发送失败: {str(e)}"}

    def _build_rc_lock_reminder_card(self, upcoming_locks: List[Dict], filters: Dict, advance_days: int) -> Dict:
        """
        【已废弃】构建RC锁仓提醒卡片
        已统一使用 _build_rc_lock_card_for_reminder 方法（橙色表格样式）
        保留此方法仅用于向后兼容，不再被调用
        
        Args:
            upcoming_locks: 即将开始的锁仓版本列表
            filters: 过滤条件
            advance_days: 提前天数
        
        Returns:
            飞书卡片JSON
        """
        # 构建过滤条件描述
        filter_desc_parts = []
        if filters.get("related_bu_team"):
            filter_desc_parts.append(f"Related BU Team: {filters['related_bu_team']}")
        if filters.get("issuetype"):
            filter_desc_parts.append(f"IssueType: {filters['issuetype']}")
        if filters.get("status"):
            filter_desc_parts.append(f"Status: {filters['status']}")
        if filters.get("assignee"):
            filter_desc_parts.append(f"Assignee: {filters['assignee']}")
        if filters.get("priority"):
            filter_desc_parts.append(f"Priority: {filters['priority']}")
        
        filter_desc = " | ".join(filter_desc_parts) if filter_desc_parts else "无特定过滤条件"
        
        # 构建版本列表内容
        version_content = ""
        for lock in upcoming_locks:
            version_info = f"{lock['plane_name']}"
            if lock.get("rc"):
                version_info += f" ({lock['rc']})"
            version_content += f"• **{version_info}**\n"
            version_content += f"  锁仓时间: {lock['lock_start']} ~ {lock['lock_end']}\n"
            version_content += f"  事件: {lock['event_name']}\n\n"
        
        card = {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "icon": {
                    "tag": "standard_icon",
                    "token": "bell_outlined"
                },
                "padding": "12px 8px 12px 8px",
                "subtitle": {
                    "content": f"过滤条件: {filter_desc}",
                    "tag": "plain_text"
                },
                "template": "orange",
                "title": {
                    "content": f"🔔 RC锁仓提醒 - {advance_days}天后开始锁仓，请及时流转任务",
                    "tag": "plain_text"
                }
            },
            "body": {
                "direction": "vertical",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"以下版本将在 **{advance_days}天后** 开始锁仓，请提前处理相关任务：\n\n{version_content}",
                        "text_align": "left"
                    },
                    {
                        "tag": "hr"
                    },
                    {
                        "tag": "div",
                        "text": {
                            "tag": "plain_text",
                            "content": "💡 提示：可以使用 \"查询RC锁仓\" 命令查看详细的任务列表"
                        }
                    }
                ]
            }
        }
        
        return card

    def send_rc_lock_card(self, chat_id: str, card: Dict) -> bool:
        """
        发送RC锁仓信息卡片到群聊
        
        Args:
            chat_id: 群聊ID
            card: 卡片数据
            
        Returns:
            是否发送成功
        """
        try:
            result = self.feishu_msg.send_msg("chat_id", chat_id, card, "interactive")
            print(f"[send_rc_lock_card] 发送结果: {result}")
            return True
        except Exception as e:
            print(f"[send_rc_lock_card] 发送失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_video_title(self, video_url: str) -> Optional[str]:
        """
        获取视频标题
        
        Args:
            video_url: 视频链接
        
        Returns:
            视频标题，如果失败返回None
        """
        try:
            import re
            import requests
            
            # YouTube视频标题
            if "youtube.com" in video_url or "youtu.be" in video_url:
                # 使用YouTube oEmbed API（不需要API密钥）
                # 匹配YouTube视频ID
                video_id_match = re.search(r'(?:v=|shorts/|youtu\.be/)([a-zA-Z0-9_-]{11})', video_url)
                if video_id_match:
                    video_id = video_id_match.group(1)
                    try:
                        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                        response = requests.get(oembed_url, timeout=5)
                        if response.status_code == 200:
                            data = response.json()
                            return data.get("title", None)
                    except Exception as e:
                        print(f"[_get_video_title] YouTube API调用失败: {e}")
                return None
            
            # Bilibili视频标题
            elif "bilibili.com" in video_url or "b23.tv" in video_url:
                # 匹配BV号
                bvid_match = re.search(r'(BV[a-zA-Z0-9]{10})', video_url, re.IGNORECASE)
                if bvid_match:
                    bvid = bvid_match.group(1).upper()
                    try:
                        # Bilibili API（不需要登录）
                        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
                        response = requests.get(api_url, timeout=5)
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("code") == 0 and data.get("data"):
                                return data["data"].get("title", None)
                    except Exception as e:
                        print(f"[_get_video_title] Bilibili API调用失败: {e}")
                return None
            
            # 其他视频网站可以在这里扩展
            return None
        except Exception as e:
            print(f"[_get_video_title] 获取视频标题失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _get_video_thumbnail(self, video_url: str) -> Optional[str]:
        """
        获取视频封面图片URL
        
        Args:
            video_url: 视频链接
        
        Returns:
            封面图片URL，如果失败返回None
        """
        try:
            import re
            # Bilibili视频封面
            if "bilibili.com" in video_url or "b23.tv" in video_url:
                # Bilibili视频封面格式：https://i0.hdslb.com/bfs/archive/{bvid}.jpg
                # 匹配BV号（BV后面跟10位字母数字组合）
                bvid_match = re.search(r'(BV[a-zA-Z0-9]{10})', video_url, re.IGNORECASE)
                if bvid_match:
                    bvid = bvid_match.group(1).upper()  # 统一转为大写
                    # Bilibili封面图片URL格式
                    return f"https://i0.hdslb.com/bfs/archive/{bvid}.jpg"
                # 如果是短链接b23.tv，可能需要先解析，这里先返回None
                # 后续可以通过API获取：https://api.bilibili.com/x/web-interface/view?bvid={bvid}
                return None
            
            # YouTube视频封面
            elif "youtube.com" in video_url or "youtu.be" in video_url:
                # YouTube视频封面格式：https://img.youtube.com/vi/{video_id}/maxresdefault.jpg
                # 匹配YouTube视频ID（11位字符）
                # 支持格式：
                # - youtube.com/watch?v=VIDEO_ID
                # - youtube.com/shorts/VIDEO_ID
                # - youtu.be/VIDEO_ID
                video_id_match = re.search(r'(?:v=|shorts/|youtu\.be/)([a-zA-Z0-9_-]{11})', video_url)
                if video_id_match:
                    video_id = video_id_match.group(1)
                    return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                return None
            
            # 腾讯视频封面
            elif "v.qq.com" in video_url:
                # 腾讯视频封面需要通过API获取，这里返回None，后续可以通过其他方式获取
                # 可以尝试从URL中提取vid，然后使用：https://vpic.video.qq.com/{vid}.jpg
                vid_match = re.search(r'vid=([a-zA-Z0-9]+)', video_url)
                if vid_match:
                    vid = vid_match.group(1)
                    return f"https://vpic.video.qq.com/{vid}.jpg"
                return None
            
            # 其他视频网站可以在这里扩展
            return None
        except Exception as e:
            print(f"[_get_video_thumbnail] 获取视频封面失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _is_video_link(self, url: str) -> bool:
        """
        判断链接是否为视频链接
        
        Args:
            url: 链接URL
        
        Returns:
            是否为视频链接
        """
        video_domains = [
            "bilibili.com", "b23.tv",
            "youtube.com", "youtu.be",
            "v.qq.com", "iqiyi.com",
            "youku.com", "acfun.cn",
            "douyin.com", "tiktok.com"
        ]
        return any(domain in url for domain in video_domains)
    
    def _is_feishu_link(self, url: str) -> bool:
        """
        判断链接是否为飞书链接
        
        Args:
            url: 链接URL
        
        Returns:
            是否为飞书链接
        """
        return "nio.feishu.cn" in url

    def generate_article_card(self, article_url: str) -> Optional[Dict]:
        """
        根据文章链接生成推送卡片
        
        Args:
            article_url: 文章链接（如飞书wiki/docx链接或视频链接）
        
        Returns:
            卡片字典，如果失败返回None
        """
        try:
            # 清理URL：去除末尾的标点符号（如右括号、句号等）
            # 这些标点可能是用户输入时误加的
            original_url = article_url
            cleaned_url = article_url.rstrip('.,;:!?)\\]}）')
            
            # 调试信息：如果URL被清理了，打印日志
            if original_url != cleaned_url:
                print(f"[generate_article_card] URL清理: '{original_url}' -> '{cleaned_url}'")
            
            # 判断链接类型
            is_video = self._is_video_link(cleaned_url)
            is_feishu = self._is_feishu_link(cleaned_url)
            
            # 使用清理后的URL（确保后续所有代码都使用清理后的URL）
            article_url = cleaned_url
            
            # 1. 获取文章标题
            # 规范化链接（去掉查询参数）用于匹配
            normalized_url = article_url.split("?")[0] if "?" in article_url else article_url
            
            # 1. 获取文章标题
            title = "文章标题"  # 默认标题
            
            # 如果是视频链接，获取视频标题
            if is_video:
                # 尝试获取视频真实标题
                video_title = self._get_video_title(article_url)
                if video_title:
                    title = video_title
                    print(f"[generate_article_card] 成功获取视频标题: {title}")
                else:
                    # 如果无法获取标题，使用默认值
                    if "bilibili.com" in article_url:
                        title = "B站视频"
                    elif "youtube.com" in article_url or "youtu.be" in article_url:
                        title = "YouTube视频"
                    elif "v.qq.com" in article_url:
                        title = "腾讯视频"
                    else:
                        title = "视频"
                    print(f"[generate_article_card] 无法获取视频标题，使用默认值: {title}")
            
            # 如果是飞书链接，获取文档信息
            if is_feishu:
                try:
                    # get_doc_info返回的是单个文档信息字典（包含title, owner_id等字段）
                    # 注意：如果ret_dict为空或key不存在，会抛出KeyError
                    doc_info_result = self.feishu_doc.get_doc_info(article_url)
                    print(f"[generate_article_card] get_doc_info返回类型: {type(doc_info_result)}")
                    
                    if isinstance(doc_info_result, dict) and doc_info_result:
                        # 检查是否包含title字段（单个文档信息）
                        if "title" in doc_info_result:
                            title = doc_info_result.get("title", "文章标题")
                            print(f"[generate_article_card] 成功获取标题: {title}")
                        else:
                            # 可能是包含链接作为key的字典（虽然get_doc_info通常不返回这种格式）
                            # 尝试查找匹配的链接
                            if normalized_url in doc_info_result:
                                title = doc_info_result[normalized_url].get("title", "文章标题")
                                print(f"[generate_article_card] 从规范化链接获取标题: {title}")
                            elif article_url in doc_info_result:
                                title = doc_info_result[article_url].get("title", "文章标题")
                                print(f"[generate_article_card] 从原始链接获取标题: {title}")
                            else:
                                print(f"[generate_article_card] 文档信息中不包含title字段，使用默认标题")
                    else:
                        print(f"[generate_article_card] get_doc_info返回无效值: {doc_info_result}")
                except KeyError as e:
                    # 如果ret_dict为空，ret_dict[key]会报KeyError
                    # 这通常意味着API调用失败或文档不存在/无权限
                    print(f"[generate_article_card] KeyError - 文档可能不存在或无权限访问: {e}")
                    print(f"[generate_article_card] 链接: {article_url}")
                    import traceback
                    traceback.print_exc()
                    # 即使无法获取标题，也继续生成卡片（使用默认标题）
                except Exception as e:
                    print(f"[generate_article_card] 获取文档信息异常: {e}")
                    print(f"[generate_article_card] 链接: {article_url}")
                    import traceback
                    traceback.print_exc()
                    # 即使无法获取标题，也继续生成卡片（使用默认标题）
            
            # 即使无法获取标题，也继续生成卡片
            print(f"[generate_article_card] 使用标题: {title}")
            
            # 2. 获取文章内容
            content = None
            if is_feishu:
                # 飞书链接：获取文档内容
                try:
                    if "nio.feishu.cn/wiki/" in article_url:
                        content = self.feishu_parser.parser_wiki(article_url)
                    elif "nio.feishu.cn/docx/" in article_url:
                        content = self.feishu_parser.parser_doc(article_url)
                    elif "nio.feishu.cn/sheets/" in article_url:
                        # 表格类型，可以获取表格内容（返回JSON格式，需要转换为字符串）
                        table_data = self.feishu_parser.parser_table(article_url, is_json=True)
                        if isinstance(table_data, (list, dict)):
                            content = json.dumps(table_data, ensure_ascii=False, indent=2)
                        else:
                            content = str(table_data)
                    
                    # 如果content是None或空字符串，尝试使用doc_info中的信息
                    if not content:
                        print(f"[generate_article_card] 无法获取文章内容，尝试使用文档信息: {article_url}")
                        # 如果无法获取内容，至少使用标题作为总结
                        content = f"文章标题：{title}"
                except Exception as e:
                    print(f"[generate_article_card] 获取文章内容失败: {e}")
                    import traceback
                    traceback.print_exc()
                    # 如果获取内容失败，使用标题作为总结
                    content = f"文章标题：{title}"
            elif is_video:
                # 视频链接：使用链接本身作为内容，让LLM总结
                content = f"视频链接：{article_url}\n视频标题：{title}"
                print(f"[generate_article_card] 视频链接，使用URL: {article_url}")
            
            if not content:
                print(f"[generate_article_card] 无法获取文章内容: {article_url}")
                return None
            
            # 3. 生成AI总结
            # 确保content是字符串类型
            if not isinstance(content, str):
                content = str(content)
            
            # 限制内容长度避免token过多
            content_preview = content[:5000] if len(content) > 5000 else content
            
            if is_video:
                summary_prompt = f"""请根据以下视频链接信息，生成一个简洁的视频介绍，要求：
1. 介绍要简洁明了，控制在200字以内
2. 可以推测视频可能的内容和主题
3. 使用中文输出

视频信息：
{content_preview}
"""
            else:
                summary_prompt = f"""请总结以下文章的主要内容，要求：
1. 总结要简洁明了，控制在200字以内
2. 突出文章的核心观点和关键信息
3. 使用中文输出

文章内容：
{content_preview}
"""
            
            messages = [{"role": "user", "content": summary_prompt}]
            summary_result = self.jam_llm.invoke(messages)
            
            # 处理返回结果
            if isinstance(summary_result, tuple):
                # 如果返回的是元组，取第二个元素（content）
                summary = summary_result[1] if len(summary_result) > 1 else str(summary_result[0])
            else:
                summary = str(summary_result)
            
            # 如果summary为空或太短，使用默认值
            if not summary or len(summary.strip()) < 10:
                if is_video:
                    summary = "视频内容介绍生成中，请查看视频链接了解详细信息。"
                else:
                    summary = "文章内容总结生成中，请查看原文链接了解详细信息。"
            
            # 4. 构建卡片元素列表
            card_elements = [
                {
                    "tag": "markdown",
                    "content": summary,
                    "text_align": "left",
                    "text_size": "normal",
                    "margin": "0px 0px 0px 0px"
                }
            ]
            
            # 添加分隔线和原文链接按钮
            card_elements.extend([
                {
                    "tag": "hr",
                    "margin": "0px 0px 0px 0px"
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "原文链接" if not is_video else "视频链接"
                    },
                    "type": "primary_filled",
                    "width": "fill",
                    "size": "medium",
                    "icon": {
                        "tag": "standard_icon",
                        "token": "ai-common_colorful"
                    },
                    "behaviors": [
                        {
                            "type": "open_url",
                            "default_url": article_url,  # 使用清理后的URL
                            "pc_url": article_url,
                            "ios_url": article_url,
                            "android_url": article_url
                        }
                    ],
                    "margin": "4px 0px 4px 0px"
                },
            ])
            
            # 5. 构建卡片
            card = {
                "schema": "2.0",
                "config": {
                    "update_multi": True
                },
                "body": {
                    "direction": "vertical",
                    "elements": card_elements + [
                        {
                            "tag": "hr",
                            "margin": "0px 0px 0px 0px"
                        },
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "机器人使用说明"
                            },
                            "type": "default",
                            "width": "fill",
                            "size": "medium",
                            "icon": {
                                "tag": "standard_icon",
                                "token": "file-text_outlined"
                            },
                            "behaviors": [
                                {
                                    "type": "open_url",
                                    "default_url": "https://nio.feishu.cn/docx/T1pId9HKKoy25YxkVEkcbQE9n2c",
                                    "pc_url": "https://nio.feishu.cn/docx/T1pId9HKKoy25YxkVEkcbQE9n2c",
                                    "ios_url": "https://nio.feishu.cn/docx/T1pId9HKKoy25YxkVEkcbQE9n2c",
                                    "android_url": "https://nio.feishu.cn/docx/T1pId9HKKoy25YxkVEkcbQE9n2c"
                                }
                            ],
                            "margin": "4px 0px 4px 0px"
                        }
                    ]
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    },
                    "subtitle": {
                        "tag": "plain_text",
                        "content": ""
                    },
                    "template": "blue",
                    "padding": "12px 12px 12px 12px"
                }
            }
            
            return card
            
        except Exception as e:
            print(f"[generate_article_card] 生成卡片失败: {e}")
            import traceback
            traceback.print_exc()
            return None

def doc_hook_func(data):
    notify = JiraNotify()
    notify.get_timeline()
    notify.get_planes()
    plane_triplets = notify.parse_plane_to_triplets()
    timeline_triplets = notify.parse_timeline_to_triplets()
    triplets = notify.merge_triplets(plane_triplets, timeline_triplets)
    return triplets
    
        


if __name__ == '__main__':
    date = datetime.now().strftime("%Y/%-m/%-d")
    notify = JiraNotify()
    timeline = notify.get_timeline()
    # timeline_triplets = notify.parse_timeline_to_triplets()
    planes = notify.get_planes()
    # plane_triplets = notify.parse_plane_to_triplets()

    #上传数据
    fmea_rag = JamRAG()
    doc = "https://nio.feishu.cn/sheets/PC1Xs0Mv4hmhlQt1N25cZcPOnrJ?sheet=OKbnoL"
    fmea_rag.pipeline(doc, collection="plane", schema=None, save_type="mix", doc_hook=doc_hook_func, skip_row=["3:1120"], skip_col=["E:ZD"],first_row=1,is_json=True)
    # ret = fmea_rag.search("VDF G2.5 V31RC04 开始截止时间 涉及版本，时间等一定要准确", collection="plane")
    # print(ret)
    # ret = fmea_rag.search("今天 G2.5有哪些相关版本项目", collection="plane")
    # print(ret)
    
    
    # FO未完成的任务
    print("=================FO未完成的任务=====================")
    for k,v in timeline.items():
        version = k
        if "G2" in v:
            st = notify.get_time(timeline, "G2", version, 3)
            et = notify.get_time(timeline, "G2", version, 0)
            if notify.check_time_time(date, st, et):
                data = notify.get_jira_info_fo_not_complete(version)
                notify.task_jira(data,f"FO未完成的任务 G2{version}")
    
    # 已开发完成任务
    # G2.6
    print("=================G2.6已开发完成任务==================")
    plane_info = notify.get_plane_info(planes, date=date, status="In Progress", event_name="锁仓")
    data = notify.get_jira_info_development_was_completed(plane_info,date, event_name="锁仓")
    #print(data)
    notify.task_jira2(data,"G2.6已开发完成任务")

    # 开发未完成的bug
    # bug票时间满足就行
    print("=================开发未完成的bug======================")
    plane_info = notify.get_plane_info(planes, date=date, status="In Progress", event_name="锁仓")
    data = notify.get_jira_info_development_not_complete_bug(plane_info,date, event_name="锁仓")
    #print(data)
    notify.task_jira2(data,"开发未完成的bug")

    # 开发未完成的feature
    # G2.5每周
    print("=================G2.5每周开发未完成的feature====================")
    plane_info = notify.get_plane_info(planes, date=date, status="In Progress", event_name="MR")
    data = notify.get_jira_info_development_not_complete_feature(plane_info,date, event_name="MR",cycle_days=7)
    #print(data)
    notify.task_jira2(data,"G2.5开发未完成的任务")

    # G2.6每天
    print("=================G2.6每天开发未完成的feature=====================")
    plane_info = notify.get_plane_info(planes, date=date, status="In Progress", event_name="锁仓")
    data = notify.get_jira_info_development_not_complete_feature(plane_info,date, event_name="锁仓")
    #print(data)
    notify.task_jira2(data,"G2.6开发未完成的任务")