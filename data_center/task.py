from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from click import prompt
from magic_jam import JamRAG, FeishuDoc, JamMySQL
from .models import VIDOData, Task, VIDOHistory
from magic_jam import FeishuMsg
from .data_hook import *
from .schema import *
from .jira_notify import *
from .rc_lock_reminder import get_enabled_reminders
import json
import copy
# from crew.crew import VidoCrew
from agent.exec_task import exec_task
from magic_jam import JamConfig
my_sql = JamMySQL()
my_sql.table_create()
jam_config = JamConfig().config
app_name = jam_config["feishu_bot"]["name"]
app_id = jam_config["feishu_bot"]["app_id"]
tasklist_guid = jam_config["feishu_bot"]["tasklist_guid"]
feishu_msg = FeishuMsg()
chat_id = "oc_e0606fd321e5b6401b9a30d6f7b8b3fb"
# chat_id = "oc_1de315452d722197017e7c3db2944834"
notify_tasks_list = []
task_card = {
    "open_id": "",
    "chat_id": "",
    "msg_type": "interactive",
    "card": {  
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "style": {
                "text_size": {
                    "normal_v2": {
                        "default": "normal",
                        "pc": "normal",
                        "mobile": "heading"
                    }
                }
            }
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                
            ]
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": ""
            },
            "subtitle": {
                "tag": "plain_text",
                "content": ""
            },
            "template": "blue",
            "padding": "12px 12px 12px 12px"
        }
    }
}
card = {
    "schema": "2.0",
    "config": {
        "update_multi": True,
        "style": {
            "text_size": {
                "normal_v2": {
                    "default": "normal",
                    "pc": "normal",
                    "mobile": "heading"
                }
            }
        }
    },
    "body": {
        "direction": "vertical",
        "padding": "12px 12px 12px 12px",
        "elements": [
            {
                "tag": "markdown",
                "content": "",
                "text_align": "left",
                "text_size": "normal_v2",
                "margin": "0px 0px 0px 0px"
            },
            {
                "tag": "hr",
                "margin": "0px 0px 0px 0px"
            },
            {
                "tag": "column_set",
                "horizontal_spacing": "8px",
                "horizontal_align": "left",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "以上内容由AI生成,仅供参考。",
                                    "text_size": "normal_v2",
                                    "text_align": "left",
                                    "text_color": "grey"
                                },
                                "icon": {
                                    "tag": "standard_icon",
                                    "token": "robot_outlined",
                                    "color": "grey"
                                },
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "vertical_align": "top",
                        "weight": 1
                    },
                    {
                        "tag": "column",
                        "width": "auto",
                        "elements": [
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "赞"
                                },
                                "type": "primary",
                                "width": "default",
                                "size": "medium",
                                "icon": {
                                    "tag": "standard_icon",
                                    "token": "thumbsup_outlined"
                                },
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "type": "helpful",
                                            "id": 0
                                        }
                                    }
                                ],
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "padding": "0px 4px 0px 4px",
                        "direction": "vertical",
                        "horizontal_spacing": "8px",
                        "vertical_spacing": "8px",
                        "horizontal_align": "right",
                        "vertical_align": "center",
                        "margin": "0px 0px 0px 0px"
                    },
                    {
                        "tag": "column",
                        "width": "auto",
                        "elements": [
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "踩"
                                },
                                "type": "danger",
                                "width": "default",
                                "size": "medium",
                                "icon": {
                                    "tag": "standard_icon",
                                    "token": "thumbdown_outlined"
                                },
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "type": "harmful",
                                            "id": 0
                                        }
                                    }
                                ],
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "padding": "0px 0px 0px 4px",
                        "direction": "vertical",
                        "horizontal_spacing": "8px",
                        "vertical_spacing": "8px",
                        "horizontal_align": "right",
                        "vertical_align": "center",
                        "margin": "0px 0px 0px 0px"
                    }
                ],
                "margin": "0px 0px 0px 0px"
            }
        ]
    }
}
async def task_reminder():
    group_list = feishu_msg.get_all_group_list()
    chat_ids = [item["chat_id"] for item in group_list]
    all_section_list = feishu_msg.get_task_section_list(tasklist_guid)
    need_send_groups = []
    for this_section in all_section_list:
        if this_section["name"].split("(")[-1].split(")")[0] in chat_ids:
            need_send_groups.append({
                "chat_id": this_section["name"].split("(")[-1].split(")")[0],
                "section_guid": this_section["guid"]
            })
    for this_group in need_send_groups:
        this_all_task = []
        section_tasks_all = feishu_msg.get_section_tasks(this_group["section_guid"])
        for section_tasks in section_tasks_all:
            if section_tasks["completed_at"] == "0":
                owner_id = None
                for item in section_tasks.get("members",[]):
                    if item["type"] == "user" and item["role"] == "assignee":
                        owner_id = item["id"]
                        break
                end_time = None
                if "due" in section_tasks:
                    end_time = (int(section_tasks["due"]["timestamp"])/1000)
                    end_time = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
                this_all_task.append({
                    "summary": section_tasks["summary"],
                    "user_id": owner_id,
                    "end_time": end_time
                })
        if this_all_task:
            inputs = {"app_name": app_name, "this_all_task": json.dumps(this_all_task, ensure_ascii=False, indent=2)}
            ret = exec_task("TaskReminderTask", **inputs)
            card["body"]["elements"][0]["content"] = ret["response"]
            save_id = JamMySQL().insert(VIDOHistory, prompt=ret["user_prompt"], sys_prompt=ret["sys_prompt"], answer=ret["response"], group_id=this_group["chat_id"]).id
            card["body"]["elements"][2]["columns"][1]["elements"][0]["behaviors"][0]["value"]["id"] = save_id
            card["body"]["elements"][2]["columns"][2]["elements"][0]["behaviors"][0]["value"]["id"] = save_id
            card_id = feishu_msg.create_card_ins(card)
            feishu_msg.send_msg("chat_id", this_group["chat_id"], json.dumps({"type":"card","data":{"card_id":card_id}}), msg_type="interactive")
    # crew = VidoCrew()
    # vido_agent = crew.vido_agent()
    # task_reminder_task = crew.task_reminder()
    # inputs = {"app_name": app_name, "chat_id": chat_id}
    # vido_agent.interpolate_inputs(inputs)
    # task_reminder_task.interpolate_inputs_and_add_conversation_history(inputs)
    # ret = vido_agent.execute_task(task_reminder_task)
    # ret = exec_task("TaskReminderTask", **inputs)
    # print(ret)
    # feishu_msg.send_msg("chat_id", chat_id, json.dumps({"text":ret}, ensure_ascii=False))
    

async def check_timeout_task():
    print("check_timeout_task")
    status_map = {
        0: "进行中",
        1: "已完成",
        2: "已取消",
        3: "已超时"
    }
    # db = next(get_db())
    notify_l = {}
    # tasks = db.query(Task).filter(Task.status == 0).all()
    tasks = my_sql.query(Task, status=0)
    # print(tasks)
    for item in tasks:
        if item.end_time and item.end_time < datetime.now() and item.end_time + timedelta(minutes=10) > datetime.now():
            if item.id not in notify_tasks_list:
                notify_tasks_list.append(item.id)
                if item.group_id:
                    if item.group_id not in notify_l:
                        notify_l[item.group_id] = []
                    notify_l[item.group_id].append({
                        "content": item.content,
                        "end_time": item.end_time,
                        "owner_id": item.owner_id,
                        "task_id": item.id,
                        "status": item.status
                    })
                    # item.status = 3
                    my_sql.update(Task, where={"id": item.id}, status=3)
    send_card = {}
    # print(notify_l)
    for key, value in notify_l.items():
        send_card[key] = {}
        for item in value:
            if item["owner_id"] not in send_card[key]:
                send_card[key][item["owner_id"]] = []
            send_card[key][item["owner_id"]].append(item)
        # body_msg = "以下任务已超时，请及时处理：\n"
        # i = 1
        # for item in value:
        #     body_msg += f"任务{i}： {item['content']}， 任务ID： {item['task_id']}， 截止时间： {item['end_time']}， 负责人： <at user_id=\"{item['owner_id']}\"></at>\n"
        #     i += 1
        
        # bot.send_msg("chat_id", key, body_msg)
    # print(send_card)
    for group_id, item in send_card.items():
        for owner_id, value in item.items():
            i = 1
            send_c_msg = copy.deepcopy(task_card)
            send_c_msg["open_id"] = owner_id
            send_c_msg["chat_id"] = group_id
            send_c_msg["card"]["header"]["title"]["content"] = f"以下任务已超时，请及时处理"
            for item in value:
                send_c_msg["card"]["body"]["elements"].append({
                        "tag": "column_set",
                        "columns": [
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "markdown",
                                        "content": f"任务{i}： {item['content']}， 任务ID： {item['task_id']}， 截止时间： {item['end_time']}",
                                        "text_align": "left",
                                        "text_size": "normal_v2",
                                        "margin": "0px 0px 0px 0px"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 3
                            },
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "select_static",
                                        "placeholder": {
                                        "tag": "plain_text",
                                        "content": status_map[item["status"]]
                                        },
                                        "behaviors": [
                                            {
                                                "type": "callback",
                                                "value": {
                                                "type": "change_status",
                                                "id": item["task_id"]
                                                }
                                            }
                                        ],
                                        "options": [
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "进行中"
                                                },
                                                "value": "1"
                                            },
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "已完成"
                                                },
                                                "value": "2"
                                            },
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "已取消"
                                                },
                                                "value": "3"
                                            },
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "已超时"
                                                },
                                                "value": "4"
                                            }
                                        ],
                                        "type": "default",
                                        "width": "default"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 1
                            }
                        ]
                    })
                i += 1
            feishu_msg.send_one_card_msg(card_body=send_c_msg)

async def timeout_task_notify():
    print("timeout_task_notify")
    status_map = {
        0: "进行中",
        1: "已完成",
        2: "已取消",
        3: "已超时"
    }
    db = next(my_sql.get_db())
    notify_l = {}
    tasks = db.query(Task).filter(Task.status.in_([0, 3])).all()
    for item in tasks:
        if item.end_time and item.end_time < datetime.now():
            if item.group_id:
                if item.group_id not in notify_l:
                    notify_l[item.group_id] = []
                notify_l[item.group_id].append({
                    "content": item.content,
                    "end_time": item.end_time,
                    "owner_id": item.owner_id,
                    "task_id": item.id,
                    "status": item.status,
                })
    send_card = {}
    for key, value in notify_l.items():
        send_card[key] = {}
        for item in value:
            if item["owner_id"] not in send_card[key]:
                send_card[key][item["owner_id"]] = []
            send_card[key][item["owner_id"]].append(item)
        # body_msg = "以下任务已超时，请及时处理：\n"
        # i = 1
        # send_card = {}
        # for item in value:
        #     body_msg += f"任务{i}： {item['content']}， 任务ID： {item['task_id']}， 截止时间： {item['end_time']}， 负责人： <at user_id=\"{item['owner_id']}\"></at>\n"
        #     i += 1
        
        # bot.send_msg("chat_id", key, body_msg)
    for group_id, item1 in send_card.items():
        for owner_id, value in item1.items():
            i = 1
            send_c_msg = copy.deepcopy(task_card)
            send_c_msg["open_id"] = owner_id
            send_c_msg["chat_id"] = group_id
            send_c_msg["card"]["header"]["title"]["content"] = f"以下任务已超时，请及时处理"
            for item in value:
                send_c_msg["card"]["body"]["elements"].append({
                        "tag": "column_set",
                        "columns": [
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "markdown",
                                        "content": f"任务{i}： {item['content']}， 任务ID： {item['task_id']}， 截止时间： {item['end_time']}",
                                        "text_align": "left",
                                        "text_size": "normal_v2",
                                        "margin": "0px 0px 0px 0px"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 3
                            },
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "select_static",
                                        "placeholder": {
                                        "tag": "plain_text",
                                        "content": status_map[item["status"]]
                                        },
                                        "behaviors": [
                                            {
                                                "type": "callback",
                                                "value": {
                                                "type": "change_status",
                                                "id": item["task_id"]
                                                }
                                            }
                                        ],
                                        "options": [
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "进行中"
                                                },
                                                "value": "1"
                                            },
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "已完成"
                                                },
                                                "value": "2"
                                            },
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "已取消"
                                                },
                                                "value": "3"
                                            },
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "已超时"
                                                },
                                                "value": "4"
                                            }
                                        ],
                                        "type": "default",
                                        "width": "default"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 1
                            }
                        ]
                    })
                i += 1
            feishu_msg.send_one_card_msg(card_body=send_c_msg)

def get_all_link(data):
    ret = []
    for item in data:
        temp_dict = {
            "link": item["link"],
            "title": item["title"],
            "latest_modify_time": item["latest_modify_time"],
            "all_parent": []
        }
        ret.append(temp_dict)
        if item.get("child"):
            child_ret = get_all_link(item["child"])
            for iitem in child_ret:
                iitem["all_parent"].insert(0, item["title"])
                ret.append({
                    **iitem,
                    "parent": iitem.get("parent") or item["title"]
                })
    return ret

async def update_data_store():
    fmea_rag = JamRAG()
    #TODO 1 从mysql数据库中获取文档更新状态

    # doc = "https://nio.feishu.cn/sheets/SQ5ZsKTYdhvKY9tqcp5cQe2rnUy?sheet=UTsYZs"
    # feishu_doc = FeishuDoc()
    # doc_info = feishu_doc.get_doc_info(doc)
    # modify_data = doc_info[doc]["latest_modify_time"]
    # ret_data = my_sql.query(VIDOData, link=doc)
    # if not ret_data or ret_data[0].mark != modify_data:
    #     fmea_rag.pipeline2(doc, collection="vido", schema=fmea_doc_schema, save_type="kg", doc_hook=fmea_doc_hook)
    # if not ret_data:
    #     my_sql.insert(VIDOData, link=doc, mark=modify_data)
    # elif ret_data[0].mark != modify_data:
    #     my_sql.update(VIDOData, where={"link": doc}, mark=modify_data)  
    if app_name == "VIDO-AI":
        print("update wiki")
        doc_obj = FeishuDoc()
        fmea_rag = JamRAG()
        
        ret = doc_obj.get_wiki_file_list("7085249687280320513")
        file_list = []
        file_detail = get_all_link(ret)
        print(file_detail)
        for item in file_detail:
            if item["link"].startswith("https://nio.feishu.cn/docx/") and len(item["all_parent"])>1 and item["all_parent"][0] == "VPL - VAS Process Library" and item["all_parent"][1] in ["1. NT3流程合集", "2. NT2流程合集", "3. 组织级流程合集"]:
                file_list.append(item["link"])
        db = next(my_sql.get_db())
        query_data = db.query(VIDOData).filter(VIDOData.link.notin_(file_list))
        for item in query_data.all():
            fmea_rag.clear_data2("vido", item.link)
        query_data.delete()
        db.commit()
        for item in file_detail:
            if item["link"].startswith("https://nio.feishu.cn/docx/") and len(item["all_parent"])>1 and item["all_parent"][0] == "VPL - VAS Process Library" and item["all_parent"][1] in ["1. NT3流程合集", "2. NT2流程合集", "3. 组织级流程合集"]:
                try:
                    temp_query = my_sql.query(VIDOData, link=item["link"])
                    if not temp_query:
                        print("store ", item["link"], item["title"])
                        fmea_rag.pipeline2(item["link"], collection="vido", images=True)
                        my_sql.insert(VIDOData, link=item["link"], mark=item["latest_modify_time"], title=item["title"])
                    else:
                        if temp_query[0].mark != item["latest_modify_time"]:
                            print("store ", item["link"], item["title"])
                            fmea_rag.pipeline2(item["link"], collection="vido", images=True)
                            my_sql.update(VIDOData, where={"link": item["link"]}, mark=item["latest_modify_time"], title=item["title"])
                except Exception as e:
                    print("store ERROR ", item["link"], item["title"], e)
    if app_name == "数字KiKi":
        docs = [
            "https://nio.feishu.cn/wiki/SxXDwtXz5iiM2KkbRzUcXhUln3g"
        ]
        feishu_doc = FeishuDoc()
        for doc in docs:
            doc_info = feishu_doc.get_doc_info(doc)
            modify_data = doc_info["latest_modify_time"]
            ret_data = my_sql.query(VIDOData, link=doc)
            if not ret_data or ret_data[0].mark != modify_data:
                fmea_rag.pipeline2(doc, collection="vido", images=True)
            if not ret_data:
                my_sql.insert(VIDOData, link=doc, mark=modify_data)
            elif ret_data[0].mark != modify_data:
                my_sql.update(VIDOData, where={"link": doc}, mark=modify_data)  

async def sync_data_from_task_to_mysql():
    db = next(my_sql.get_db())
    tasks = db.query(Task).filter(Task.status.in_([0, 3])).all()
    for task in tasks:
        if not task.task_guid:
            continue
        feishu_task = feishu_msg.get_task_info(task.task_guid)
        if feishu_task is None:
            db.delete(task)
            db.commit()
            continue
        assignee = None
        for item in feishu_task["members"]:
            if item["role"] == "assignee":
                assignee = item["id"]
        if assignee != task.owner_id:
            task.owner_id = assignee
        if "due" in feishu_task:
            end_time = int(feishu_task["due"]["timestamp"])/1000
            end_time = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
            if end_time != task.end_time:
                task.end_time = end_time
        if feishu_task.get("completed_at") != "0":
            task.status = 1
            d_time = int(feishu_task["completed_at"])/1000
            task.done_time = datetime.fromtimestamp(d_time).strftime('%Y-%m-%d %H:%M:%S')
        db.commit()
        db.refresh(task)
    
async def task_jira():
    date = datetime.now().strftime("%Y/%-m/%-d")
    notify = JiraNotify(chat_id)
    timeline = notify.get_timeline()
    # timeline_triplets = notify.parse_timeline_to_triplets()
    planes = notify.get_planes()
    # plane_triplets = notify.parse_plane_to_triplets()

    #上传数据
    fmea_rag = JamRAG()
    doc = "https://nio.feishu.cn/sheets/PC1Xs0Mv4hmhlQt1N25cZcPOnrJ?sheet=OKbnoL"
    fmea_rag.pipeline2(doc, collection="vido", schema=None, save_type="mix", doc_hook=doc_hook_func, skip_row=["3:1120"], skip_col=["E:ZD"],first_row=1,is_json=True)
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
    

async def rc_lock_reminder_task():
    """
    RC锁仓提醒定时任务
    每分钟执行一次，检查当前时间是否匹配各群聊配置的提醒时间
    """
    from datetime import datetime
    
    # 获取所有启用的提醒配置
    reminders = get_enabled_reminders()
    
    if not reminders:
        return
    
    # 获取当前时间
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute
    
    notify = JiraNotify()
    
    for reminder in reminders:
        try:
            chat_id = reminder.get("chat_id")
            advance_days = reminder.get("advance_days", 2)
            filters = reminder.get("filters", {})
            
            # 获取配置的提醒时间（默认9:00）
            reminder_hour = reminder.get("reminder_hour", 9)
            reminder_minute = reminder.get("reminder_minute", 0)
            
            # 检查当前时间是否匹配配置的提醒时间
            if current_hour != reminder_hour or current_minute != reminder_minute:
                continue
            
            print(f"[RC锁仓提醒] {current_hour:02d}:{current_minute:02d} 检查群聊 {chat_id} 的锁仓提醒")
            
            # 获取即将开始的锁仓版本
            upcoming_locks = notify.get_upcoming_lock_versions(advance_days)
            
            if upcoming_locks:
                print(f"群聊 {chat_id} 有 {len(upcoming_locks)} 个即将锁仓的版本需要提醒")
                
                # 发送提醒
                result = notify.send_rc_lock_reminder(chat_id, upcoming_locks, filters, advance_days)
                print(f"发送结果: {result}")
            else:
                print(f"群聊 {chat_id} 没有即将锁仓的版本需要提醒")
                
        except Exception as e:
            print(f"处理群聊 {reminder.get('chat_id')} 的RC锁仓提醒时出错: {e}")


async def send_task_summary_to_group(chat_id):
    """
    发送任务汇总到指定群聊（手动触发）
    """
    try:
        # 获取该群聊对应的任务分组
        all_section_list = feishu_msg.get_task_section_list(tasklist_guid)
        section_guid = None
        for this_section in all_section_list:
            if this_section["name"].split("(")[-1].split(")")[0] == chat_id:
                section_guid = this_section["guid"]
                break
        
        if not section_guid:
            # 如果没有找到对应的任务分组，返回提示
            return False
        
        # 获取该分组的所有任务
        this_all_task = []
        section_tasks_all = feishu_msg.get_section_tasks(section_guid)
        for section_tasks in section_tasks_all:
            if section_tasks["completed_at"] == "0":
                owner_id = None
                for item in section_tasks.get("members",[]):
                    if item["type"] == "user" and item["role"] == "assignee":
                        owner_id = item["id"]
                        break
                end_time = None
                if "due" in section_tasks:
                    end_time = (int(section_tasks["due"]["timestamp"])/1000)
                    end_time = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
                this_all_task.append({
                    "summary": section_tasks["summary"],
                    "user_id": owner_id,
                    "end_time": end_time
                })
        
        if this_all_task:
            inputs = {"app_name": app_name, "this_all_task": json.dumps(this_all_task, ensure_ascii=False, indent=2)}
            ret = exec_task("TaskReminderTask", **inputs)
            card_copy = copy.deepcopy(card)
            card_copy["body"]["elements"][0]["content"] = ret["response"]
            save_id = JamMySQL().insert(VIDOHistory, prompt=ret["user_prompt"], sys_prompt=ret["sys_prompt"], answer=ret["response"], group_id=chat_id).id
            card_copy["body"]["elements"][2]["columns"][1]["elements"][0]["behaviors"][0]["value"]["id"] = save_id
            card_copy["body"]["elements"][2]["columns"][2]["elements"][0]["behaviors"][0]["value"]["id"] = save_id
            card_id = feishu_msg.create_card_ins(card_copy)
            feishu_msg.send_msg("chat_id", chat_id, json.dumps({"type":"card","data":{"card_id":card_id}}), msg_type="interactive")
            return True
        else:
            # 如果没有任务，发送提示消息
            feishu_msg.send_msg("chat_id", chat_id, "当前群聊暂无未完成任务", "text")
            return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"发送任务汇总到群聊 {chat_id} 时出错: {e}")
        return False

async def init_task():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(update_data_store, 'cron', hour=1, minute=0)
    # scheduler.add_job(task_reminder, 'cron', hour=16, minute=45)  # 已关闭定时执行，改为手动触发
    scheduler.add_job(timeout_task_notify, 'cron', hour=10, minute=0)
    scheduler.add_job(check_timeout_task, 'interval', minutes=5)
    scheduler.add_job(task_jira, 'cron', hour=17, minute=0)
    scheduler.add_job(sync_data_from_task_to_mysql, 'interval', minutes=30)
    scheduler.add_job(rc_lock_reminder_task, 'cron', minute='*')  # 每分钟检查一次RC锁仓提醒（根据各群聊配置的时间执行）
    # 启动调度器
    scheduler.start()