import json
import threading
import copy
import time
import requests
import random
from datetime import datetime
from magic_jam.parser.feishu_parser import FeishuDocParser
from magic_jam import JamConfig
from magic_jam import FeishuMsg
# from crew.crew import VidoCrew
from agent.exec_task import exec_task
from langfuse import get_client
from dotenv import load_dotenv
from openinference.instrumentation.crewai import CrewAIInstrumentor
from openinference.instrumentation.litellm import LiteLLMInstrumentor
from magic_jam import JamMySQL,JamRAG
from data_center.models import Task, VIDOHistory
from data_center.jira_notify import JiraNotify
from board_manager import BoardManager
from doc_manager import DocManager
from magic_jam import JiraTool
from magic_jam.llm.jam_llm import JamLLM
import re
import os

class Executor:
    def __init__(self):
        load_dotenv()
        self.jam_sql = JamMySQL()
        self.feishu_parser = FeishuDocParser()
        self.jam_config = JamConfig().config
        self.app_name = self.jam_config["feishu_bot"]["name"]
        self.app_id = self.jam_config["feishu_bot"]["app_id"]
        self.admin_list = self.jam_config["feishu_bot"].get("admin",[])
        self.msg_record = {}
        self.thread_lock = {}
        self.feishu_msg = FeishuMsg()
        self.help_harm_count = {}
        # crew = VidoCrew()
        # self.vido_agent = crew.vido_agent()
        # self.group_reply_task = crew.group_reply()
        # self.check_need_reply_task = crew.check_need_reply()
        # self.user_reply_task = crew.user_reply()
        self.group_reply_task = "GroupReplyTask"
        self.check_need_reply_task = "CheckNeedReplyTask"
        self.user_reply_task = "UserReplyTask"
        self.recv_msg_ids = []
        self.users = {}
        # 初始化画板管理器（不传json_dir，使用BoardManager的默认值，基于board_manager.py所在目录）
        self.board_manager = BoardManager(json_dir=None)
        # 初始化文档管理器（使用board_manager的json_dir的父目录，确保路径一致）
        magic_vido_dir = os.path.dirname(self.board_manager.json_dir)
        self.doc_manager = DocManager(base_dir=magic_vido_dir)
        # 加载VAS维测方法树数据
        vas_tree_path = os.path.join(magic_vido_dir, "doc", "vas_method_tree.json")
        if os.path.exists(vas_tree_path):
            with open(vas_tree_path, 'r', encoding='utf-8') as f:
                self.vas_method_tree = json.load(f)
        else:
            self.vas_method_tree = None
            print(f"警告: VAS维测方法树文件不存在: {vas_tree_path}")
        self.fmea_req = {}
        self.open_claw_flag = {}
        self.fmea_base_url = "http://localhost:8000"

    def get_knowledge(self, msg):
        i = 0
        while i <3:
            try:
                fmea_rag = JamRAG()
                ret = fmea_rag.retriever2(collection="vido", query=msg)
                return ret
            except Exception as e:
                print("get knowledge failed",e)
                i += 1
        return ""
        # try:
        #     ret_str = ""
        #     ret = self.feishu_parser.request_niogpt_application(msg, "0087cc794bac42cda96da5cc22fc8fa8")
        #     # print("get niogpt knowledge",ret)
        #     for item in json.loads(ret):
        #         if item.get("ext", {}).get("score") is None:
        #             continue
        #         if item.get("ext", {}).get("score") < 0.45:
        #             continue
        #         ret_str += item["text"]+"\n"
        #     # if ret_str == "":
        #     #     if json.loads(ret)[0].get("ext", {}).get("score") is None:
        #     #         if json.loads(ret)[0].get("ext", {}).get("score") >0.3:
        #     #             ret_str = json.loads(ret)[0]["text"]+"\n"
        #     # vector_store = QdrantVectorStore(
        #     #     client=self.local_rag.qdrant_client,
        #     #     collection_name="sf_table_test",
        #     #     embedding=self.local_rag.embedder
        #     # )
        #     # ret = vector_store.similarity_search_with_score(query=msg, k=3)
        #     # for item in ret:
        #     #     if item[1] < 0.45:
        #     #         continue
        #     #     ret_str += item[0].page_content+"\n"
        #     print("get niogpt knowledge1",ret_str)
        #     return ret_str
        # except Exception as e:
        #     print("get niogpt knowledge failed",e)
        #     return None

    def back_send_msg(self, user, msg_id, json_data, mentions_info=None):
            # 处理 mentions：将消息中的 @_user_1 等替换为用户名（用于后续的文档解析、画板查询等逻辑）
            
            if json_data["event"]["message"]["message_type"] != "image" and user in self.fmea_req:
                self.fmea_req.pop(user)
                self.feishu_msg.send_msg("open_id", user, "退出失效分析", "text")
            elif json_data["event"]["message"]["message_type"] == "image" and user in self.fmea_req:
                ## 失效分析
                print(self.fmea_req)
                func_name = self.fmea_req[user].get('function_name', '')
                func_desc = self.fmea_req[user].get('function_description', '')
                fusion_graph = self.fmea_req[user].get('fusion_spectrum', '')
                self.fmea_req.pop(user)
                image_path = self.feishu_msg.parser_msg_type("image", json_data["event"]["message"]["content"], msg_id, image=False)
                print(image_path)
                img_key = self.feishu_msg.upload_image(image_path)
                content = f"**正在生成该功能的失效模式中，预计需3~5分钟**\n**功能名称：** {func_name}\n**功能描述：** {func_desc}\n**融合图谱：** {fusion_graph.split(',')[-1]}\n**功能图片：**\n\n"
                this_card = {
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
                                "content": content,
                                "text_align": "left",
                                "text_size": "normal_v2",
                                "margin": "0px 0px 0px 0px"
                            },
                            {
                                "tag": "img",
                                "img_key": img_key,
                                "preview": True,
                                "transparent": False,
                                "scale_type": "fit_horizontal",
                                "margin": "0px 0px 0px 0px"
                            }
                        ]
                    }
                }
                card_id = self.feishu_msg.create_card_ins(this_card)
                ret = self.feishu_msg.send_msg("open_id", user, json.dumps({"type":"card","data":{"card_id":card_id}}), "interactive")
                this_msg_id= ret["message_id"]
                function_item = {
                    "flowId": 1001,
                    "functionName": func_name,
                    "functionDesc": func_desc,
                    "functionSource": "",
                    "designImageUrl": image_path,
                }
                # request 图片解析
                resp1 = requests.post(
                    f"{self.fmea_base_url}/kg-api/dfmea-fault-report/generate-image-analysis-result",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(function_item, ensure_ascii=False),
                )
                if resp1.status_code != 200:
                    print("generate-image-analysis-result failed", resp1.text)
                    self.feishu_msg.reply_msg(this_msg_id, "生成失效模式失败，"+str(resp1.text), "text")
                data1 = resp1.json()["data"]
                image_analysis_result = data1["imageAnalysisResults"]
                # request 生成失效模式
                resp2 = requests.post(
                    f"{self.fmea_base_url}/kg-api/dfmea-fault-report/generate-fault-mode",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "analysisContext": function_item,
                            "imageAnalysisResultItem": image_analysis_result,
                            "neo4j_config": [],
                        }
                    ),
                )
                if resp2.status_code != 200:
                    print("generate-fault-mode failed", resp2.text)
                    self.feishu_msg.reply_msg(this_msg_id, "生成失效模式失败，"+str(resp2.text), "text")
                data2 = resp2.json()["data"]
                pres = data2.get("globalDict", {})
                fault_modes = data2["faultReportFaultModeRes"]
                # fault_modes = [
                #     {
                #         "flowId": 1001,
                #         "ModeId": None,
                #         "faultModeId": 1,
                #         "faultType": "突然失效",
                #         "faultMode": "无法接收本地唤醒信号变化；无法满足唤醒条件；无法正常上电唤醒；无法识别本地唤醒源；无法记录本地唤醒源；无法接收网络唤醒信号；无法识别网络唤醒源；无法记录网络唤醒源；无法维持网络唤醒状态；无法维持网络休眠状态",
                #         "chainOfThoughtModel": "分析功能文本：(1)(3)描述了系统的唤醒功能，(2)(4)描述了唤醒源的识别与记录功能，(5)描述了网络状态的维持功能。这些功能都具有明确的'能/不能'二元状态特征。根据失效七原则中的'突然失效'类型，其适用于所有功能，通过在功能动词前加'无法'来推导失效模式。因此针对每个子功能分别应用：'无法接收本地唤醒信号变化'、'无法满足唤醒条件'、'无法正常上电唤醒'、'无法识别本地唤醒源'、'无法记录本地唤醒源'、'无法接收网络唤醒信号'、'无法识别网络唤醒源'、'无法记录网络唤醒源'、'无法维持网络唤醒状态'、'无法维持网络休眠状态'。",
                #         "modeRemark": None
                #     },
                #     {
                #         "flowId": 1001,
                #         "ModeId": None,
                #         "faultModeId": 2,
                #         "faultType": "随着时间变化",
                #         "faultMode": "NA",
                #         "chainOfThoughtModel": "虽然功能中包含'准确识别'这类隐含性能要求的描述，但核心功能（唤醒、识别、记录、状态维持）本质上都是离散状态切换（成功/失败）。根据失效七原则，'对于仅具有两种离散状态的功能，即使有相关性能指标，也不适用此类型'。此外，任务指令明确指出'仅有两个状态的功能不适用于...随时间变化'，且'涉及数值相关的功能或性能通常归类于处于较高或较低水平'。本功能无连续变化的性能参数（如识别精度随时间衰减），故不适用此失效类型。",
                #         "modeRemark": None
                #     },
                #     {
                #         "flowId": 1001,
                #         "ModeId": None,
                #         "faultModeId": 3,
                #         "faultType": "功能间歇",
                #         "faultMode": "间歇性无法接收本地唤醒信号；间歇性无法满足唤醒条件；间歇性无法正常上电唤醒；间歇性无法识别本地唤醒源；间歇性无法记录本地唤醒源；间歇性无法接收网络唤醒信号；间歇性无法识别网络唤醒源；间歇性无法记录网络唤醒源；间歇性无法维持网络唤醒状态；间歇性无法维持网络休眠状态",
                #         "chainOfThoughtModel": "功能文本描述的唤醒、识别、记录、状态维持等功能在实际运行中可能因信号干扰、电源波动、软件异常等原因出现不稳定性。根据失效七原则中的'功能间歇'类型，其适用于可能会出现不稳定的功能，使用'间歇性'等描述词。因此，将'突然失效'推导出的各个失效模式前加上'间歇性'，得到相应的间歇性失效模式，例如'间歇性无法正常上电唤醒'等。",
                #         "modeRemark": None
                #     },
                #     {
                #         "flowId": 1001,
                #         "ModeId": None,
                #         "faultModeId": 4,
                #         "faultType": "处于较高或较低水平",
                #         "faultMode": "NA",
                #         "chainOfThoughtModel": "功能文本主要描述的是状态转换和逻辑判断功能（如唤醒、识别、记录、维持状态），这些功能的成功与否是离散事件，不具备连续可量化的性能指标或阈值（如灵敏度、功率、输出电平的具体数值范围）。虽然有'准确识别'的表述，但这属于功能正确性的范畴，而非一个可量化水平的偏离。任务指令也强调'涉及数值相关的功能...归类于处于较高或较低水平'，本功能不符合此条件，故不适用此失效类型。",
                #         "modeRemark": None
                #     },
                #     {
                #         "flowId": 1001,
                #         "ModeId": None,
                #         "faultModeId": 5,
                #         "faultType": "非预期的执行",
                #         "faultMode": "非预期执行上电唤醒（无有效唤醒信号或条件不满足）；非预期识别本地唤醒源；非预期记录本地唤醒源；非预期识别网络唤醒源；非预期记录网络唤醒源；非预期改变网络唤醒状态；非预期改变网络休眠状态",
                #         "chainOfThoughtModel": "功能(1)(3)明确了唤醒需要特定信号和条件，功能(2)(4)明确了识别和记录应在唤醒后进行，功能(5)明确了状态维持应根据功能需求。因此，这些功能都有明确的执行前提和时机。根据失效七原则中的'非预期的执行'类型，当功能具有明确的执行时间时才适用，可使用'误执行'、'非预期执行'等表达。由此推导：在没有收到有效信号或不满足条件时发生唤醒为非预期执行；在不应进行识别或记录的时候进行了操作为非预期识别/记录；未按功能需求改变网络状态为非预期改变状态。",
                #         "modeRemark": None
                #     },
                #     {
                #         "flowId": 1001,
                #         "ModeId": None,
                #         "faultModeId": 6,
                #         "faultType": "卡在某一水平上",
                #         "faultMode": "NA",
                #         "chainOfThoughtModel": "功能文本描述的系统行为主要是事件驱动的状态跳转：从未唤醒到唤醒，识别源并记录，以及根据需求维持唤醒或休眠状态。这些都是离��的状态，而不是在一个连续范围内可调节的水平。例如，唤醒只有'醒'和'睡'两种状态，识别只有'识别到'和'未识别到'。根据失效七原则和任务指令中的明确规定：'仅有两个状态的功能不适用于‘卡在某一水平上’这一失效类型'，并且'当功能具有可调节的连续状态时才适用'。本功能均为离散状态，故不适用此失效类型。",
                #         "modeRemark": None
                #     },
                #     {
                #         "flowId": 1001,
                #         "ModeId": None,
                #         "faultModeId": 7,
                #         "faultType": "错误的方向",
                #         "faultMode": "NA",
                #         "chainOfThoughtModel": "功能文本描述的操作包括：接收信号、判断条件、上电唤醒、识别唤醒源、记录唤醒源、维持网络状态。这些操作本质上是条件的满足、状态的设置和信息的处理，不具有物理空间或逻辑上的方向性（如电机正反转、信号流向指定目标等）。根据失效七原则，'错误的方向'类型'当功能具有明确的方向性操��时才适用'。本功能不存在此类方向性操作，故不适用此失效类型。",
                #         "modeRemark": None
                #     }
                # ]
                # pres={}
                # image_analysis_result = ""
                f_mode_card = {
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
                                "tag": "column_set",
                                "horizontal_spacing": "8px",
                                "horizontal_align": "left",
                                "columns": [
                                    # {
                                    #     "tag": "column",
                                    #     "width": "weighted",
                                    #     "elements": [
                                    #         {
                                    #             "tag": "div",
                                    #             "text": {
                                    #                 "tag": "plain_text",
                                    #                 "content": "失效类型",
                                    #                 "text_size": "heading",
                                    #                 "text_align": "left",
                                    #                 "text_color": "default"
                                    #             },
                                    #             "icon": {
                                    #                 "tag": "standard_icon",
                                    #                 "token": "emoji_outlined",
                                    #                 "color": "grey"
                                    #             },
                                    #             "margin": "0px 0px 0px 0px"
                                    #         }
                                    #     ],
                                    #     "vertical_align": "top",
                                    #     "weight": 1
                                    # },
                                    {
                                        "tag": "column",
                                        "width": "weighted",
                                        "elements": [
                                            {
                                                "tag": "div",
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "失效模式",
                                                    "text_size": "heading",
                                                    "text_align": "left",
                                                    "text_color": "default"
                                                },
                                                "icon": {
                                                    "tag": "standard_icon",
                                                    "token": "emoji_outlined",
                                                    "color": "grey"
                                                },
                                                "margin": "0px 0px 0px 0px"
                                            }
                                        ],
                                        "vertical_align": "top",
                                        "weight": 2
                                    },
                                    {
                                        "tag": "column",
                                        "width": "weighted",
                                        "elements": [
                                            {
                                                "tag": "div",
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "操作",
                                                    "text_size": "heading",
                                                    "text_align": "left",
                                                    "text_color": "default",
                                                    "lines": 7
                                                },
                                                "icon": {
                                                    "tag": "standard_icon",
                                                    "token": "emoji_outlined",
                                                    "color": "grey"
                                                },
                                                "margin": "0px 0px 0px 0px"
                                            }
                                        ],
                                        "vertical_align": "top",
                                        "weight": 1
                                    }
                                ],
                                "margin": "0px 0px 0px 0px"
                            }
                        ]
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": "失效模式"
                        },
                        "subtitle": {
                            "tag": "plain_text",
                            "content": ""
                        },
                        "template": "blue",
                        "padding": "12px 12px 12px 12px"
                    }
                }
                for fault_mode in fault_modes:
                    temp_column_set = {
                        "tag": "column_set",
                        "horizontal_spacing": "8px",
                        "horizontal_align": "left",
                        "columns": [
                            # {
                            #     "tag": "column",
                            #     "width": "weighted",
                            #     "elements": [
                            #         {
                            #             "tag": "div",
                            #             "text": {
                            #                 "tag": "plain_text",
                            #                 "content": fault_mode["faultType"],
                            #                 "text_size": "normal_v2",
                            #                 "text_align": "left",
                            #                 "text_color": "default"
                            #             },
                            #             "margin": "0px 0px 0px 0px"
                            #         }
                            #     ],
                            #     "vertical_align": "top",
                            #     "weight": 1
                            # },
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "div",
                                        "text": {
                                            "tag": "plain_text",
                                            "content": fault_mode["faultMode"],
                                            "text_size": "normal_v2",
                                            "text_align": "left",
                                            "text_color": "default"
                                        },
                                        "margin": "0px 0px 0px 0px"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 2
                            }
                        ],
                        "margin": "0px 0px 0px 0px"
                    }
                    if fault_mode["faultMode"] == "NA":
                        temp_column_set["columns"].append({
                            "tag": "column",
                            "width": "weighted",
                            "elements": [
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "NA",
                                        "text_size": "heading",
                                        "text_align": "left",
                                        "text_color": "default",
                                        "lines": 7
                                    },
                                    "margin": "0px 0px 0px 0px"
                                }
                            ],
                            "vertical_align": "top",
                            "weight": 1
                        })
                    else:
                        temp_column_set["columns"].append({
                            "tag": "column",
                            "width": "weighted",
                            "elements": [
                                {
                                    "tag": "button",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "生成失效原因"
                                    },
                                    "type": "default",
                                    "width": "fill",
                                    "size": "medium",
                                    "margin": "0px 0px 0px 0px",
                                    "behaviors": [
                                        {
                                            "type": "callback",
                                            "value": {
                                                "type": "failure_reason",
                                                "resDict": json.dumps(pres, ensure_ascii=False),
                                                "analysisContext": json.dumps(function_item, ensure_ascii=False),
                                                "imageAnalysisResultItem": image_analysis_result,
                                                "faultReportFaultModeRes": json.dumps([fault_mode], ensure_ascii=False)
                                            }
                                        }
                                    ]
                                }
                            ],
                            "vertical_align": "top",
                            "weight": 1
                        })
                    f_mode_card["body"]["elements"].append(copy.deepcopy(temp_column_set))
                card_id = self.feishu_msg.create_card_ins(f_mode_card)
                self.feishu_msg.reply_msg(this_msg_id, json.dumps({"type":"card","data":{"card_id":card_id}}), "interactive")
                return
            if user in self.open_claw_flag:
                # print(json_data["event"]["message"]["message_type"])
                element_id = "id_"+str(int(time.time()*1000))
                save_id = JamMySQL().insert(VIDOHistory, user=user).id
                card_id = self.create_flow_card(element_id, save_id=save_id)
                self.feishu_msg.reply_msg(msg_id, json.dumps({"type":"card","data":{"card_id":card_id}}), msg_type="interactive")
                try:
                    send_msgs = self.feishu_msg.parser_msg_type(json_data["event"]["message"]["message_type"], json_data["event"]["message"]["content"], msg_id)
                    match = re.search(r'https://jira\.nioint\.com/browse/([A-Z0-9]+-\d+)', send_msgs)
                    jira_key = None
                    if match:
                        jira_key = match.group(1)
                    if jira_key:
                        # if not jira_key.upper().startswith("NT3VIMS"):
                        #     self.feishu_msg.send_msg("open_id", user, "仅支持对NT3VIMS的jira故障单进行分析!!", "text")
                        #     return
                        send_msgs += f"\n 该jira {jira_key} 信息如下: \n"
                        jira_tool = JiraTool()
                        issue_info = jira_tool.get_issue_info(jira_key, fields=["summary", "description", "attachment"], attachment_type=["image"])
                        send_msgs += f"- 故障标题: \n{issue_info.get('summary', '')}\n"
                        send_msgs += f"- 故障描述: \n{issue_info.get('description', '')}\n"
                        send_msgs += f"- 附件： \n"
                        jam_llm = JamLLM(model_type="multimodal")
                        # print(issue_info)
                        for attachment in issue_info.get("attachment", []):
                            send_msgs += f"{attachment.split('/')[-1]} 内容如下：\n"
                            resp = jam_llm.invoke_images(images=attachment)
                            send_msgs += f"{resp}\n\n"
                    i = 1
                    for attempt in range(3):
                        ret = self.llm_call("OpenClawTask", context=send_msgs, history_conversation=self.open_claw_flag[user], stream=True)
                        # self.feishu_msg.send_msg("open_id", user, ret["response"], "text")
                        if ret["response"]:
                            send_d = ""
                            temp_send = ""
                            current_time = time.time()
                            for cont in ret["response"]:
                                if cont == False:
                                    # 处理失败，重试
                                    break
                                if cont != None:
                                    temp_send += cont
                                    if time.time() - current_time > 2:
                                        send_d += temp_send
                                        self.update_flow_card(card_id, element_id, send_d, sequence=i)
                                        i += 1
                                        temp_send = ""
                                        current_time = time.time()
                            else:
                                if temp_send:
                                    send_d += temp_send
                                    self.update_flow_card(card_id, element_id, send_d, sequence=i)
                                    i += 1
                                self.open_claw_flag[user].append({"role": "user", "content": ret["user_prompt"]})
                                self.open_claw_flag[user].append({"role": "assistant", "content": send_d})
                                break
                            continue
                        else:
                            continue
                    else:
                        send_d = "服务器出了点问题(code:1007)，请联系<at id=ou_287877ad6ecdf314dfd669137365d995></at>"
                        self.update_flow_card(card_id, element_id, send_d, sequence=i)
                        i += 1
                    JamMySQL().update(VIDOHistory, where={"id":save_id}, query=send_msgs, prompt=ret["user_prompt"], sys_prompt=ret["sys_prompt"], answer=send_d)
                except Exception as e:
                    self.update_flow_card(card_id, element_id, "处理出错，"+str(e), sequence=i)
                    i += 1
                    print(e)
                self.update_card_config(card_id,sequence=i)
                if send_d.find("故障单分析完成") != -1:
                    self.feishu_msg.send_msg("open_id", user, "该故障单分析已完成，重新输入 故障分析 触发下一轮故障分析", "text")
                    self.open_claw_flag.pop(user)
                return
            if json_data["event"]["message"]["message_type"] != "text":
                return
            send_msgs = json.loads(json_data["event"]["message"]["content"])["text"]
            if send_msgs == "故障分析" and user not in self.open_claw_flag:
                self.open_claw_flag[user] = []
                self.feishu_msg.send_msg("open_id", user, "请输入您的故障分析需求，您可输入一个jira链接或者问题详情等信息", "text")
                return
            if mentions_info:
                for mention in mentions_info:
                    mention_key = mention.get("key", "")  # @_user_1
                    mention_name = mention.get("name", "")  # 用户名
                    # 替换消息中的 mention key 为用户名
                    if mention_key and mention_name:
                        send_msgs = send_msgs.replace(mention_key, "@" + mention_name)
            if send_msgs == "失效分析":
                this_card = {
                    "schema": "2.0",
                    "config": {
                        "update_multi": True
                    },
                    "body": {
                        "direction": "vertical",
                        "elements": [
                            {
                                "tag": "form",
                                "elements": [
                                    {
                                        "tag": "input",
                                        "placeholder": {
                                            "tag": "plain_text",
                                            "content": "请输入功能名称"
                                        },
                                        "default_value": "",
                                        "width": "fill",
                                        "label": {
                                            "tag": "plain_text",
                                            "content": "功能名称 "
                                        },
                                        "label_position": "top",
                                        "required": True,
                                        "name": "function_name",
                                        "element_id": "WQHrisCV4EIVf7pZ7JkG"
                                    },
                                    {
                                        "tag": "input",
                                        "placeholder": {
                                            "tag": "plain_text",
                                            "content": "请输入功能描述"
                                        },
                                        "default_value": "",
                                        "width": "fill",
                                        "label": {
                                            "tag": "plain_text",
                                            "content": "功能描述"
                                        },
                                        "label_position": "top",
                                        "name": "function_description",
                                        "element_id": "cqRmaBbkoG12D2RwRyPo"
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
                                                        "tag": "select_static",
                                                        "placeholder": {
                                                            "tag": "plain_text",
                                                            "content": "请选择融合图谱"
                                                        },
                                                        "options": [
                                                            {
                                                                "text": {
                                                                    "tag": "plain_text",
                                                                    "content": "无"
                                                                },
                                                                "value": "option1,无"
                                                            },
                                                            {
                                                                "text": {
                                                                    "tag": "plain_text",
                                                                    "content": "图谱选项1"
                                                                },
                                                                "value": "option2,图谱选项1"
                                                            },
                                                            {
                                                                "text": {
                                                                    "tag": "plain_text",
                                                                    "content": "图谱选项2"
                                                                },
                                                                "value": "option3,图谱选项2"
                                                            }
                                                        ],
                                                        "type": "default",
                                                        "width": "fill",
                                                        "name": "fusion_spectrum",
                                                        "element_id": "xMIx6nKnUJvNiswC1CZa"
                                                    }
                                                ],
                                                "vertical_spacing": "8px",
                                                "horizontal_align": "left",
                                                "vertical_align": "top",
                                                "weight": 1
                                            }
                                        ]
                                    },
                                    {
                                        "tag": "markdown",
                                        "content": "请到[FMEA系统](http://10.132.168.7/kg/kgN)生成所需功能的融合图谱",
                                        "text_align": "left",
                                        "text_size": "notation",
                                        "margin": "0px 0px 0px 0px",
                                        "icon": {
                                            "tag": "standard_icon",
                                            "token": "emoji_outlined",
                                            "color": "grey"
                                        }
                                    },
                                    {
                                        "tag": "column_set",
                                        "flex_mode": "flow",
                                        "horizontal_spacing": "8px",
                                        "horizontal_align": "left",
                                        "columns": [
                                            {
                                                "tag": "column",
                                                "width": "auto",
                                                "elements": [
                                                    {
                                                        "tag": "button",
                                                        "text": {
                                                            "tag": "plain_text",
                                                            "content": "提交"
                                                        },
                                                        "type": "primary_filled",
                                                        "width": "fill",
                                                        "form_action_type": "submit",
                                                        "name": "submit_button",
                                                        "margin": "4px 0px 4px 0px",
                                                        "element_id": "WznV52zjgCiS7X377IGa",
                                                        "behaviors": [
                                                            {
                                                                "type": "callback",
                                                                "value": {
                                                                    "type": "failure_analysis"
                                                                }
                                                            }
                                                        ]
                                                    }
                                                ],
                                                "vertical_spacing": "8px",
                                                "horizontal_align": "left",
                                                "vertical_align": "top"
                                            }
                                        ],
                                        "margin": "12px 0px 0px 0px"
                                    }
                                ],
                                "direction": "vertical",
                                "vertical_spacing": "12px",
                                "horizontal_align": "left",
                                "vertical_align": "top",
                                "padding": "12px 12px 12px 12px",
                                "margin": "0px 0px 0px 0px",
                                "name": "failure_report_form"
                            }
                        ]
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": "失效分析"
                        },
                        "subtitle": {
                            "tag": "plain_text",
                            "content": ""
                        },
                        "template": "blue",
                        "padding": "12px 8px 12px 8px"
                    }
                }
                card_id = self.feishu_msg.create_card_ins(this_card)
                self.feishu_msg.send_msg("open_id", user, json.dumps({"type":"card","data":{"card_id":card_id}}), "interactive")
                return
            print(send_msgs)
            if send_msgs == "推送管理" and user in self.admin_list:
                this_card = {
                    "schema": "2.0",
                    "config": {
                        "update_multi": True
                    },
                    "body": {
                        "direction": "vertical",
                        "padding": "12px 12px 12px 12px",
                        "elements": [
                            {
                                "tag": "form",
                                "elements": [
                                    {
                                        "tag": "input",
                                        "placeholder": {
                                            "tag": "plain_text",
                                            "content": "输入卡片id"
                                        },
                                        "default_value": "",
                                        "width": "default",
                                        "label": {
                                            "tag": "plain_text",
                                            "content": "卡片ID："
                                        },
                                        "name": "card_id",
                                        "margin": "0px 0px 0px 0px"
                                    },
                                    {
                                        "tag": "input",
                                        "placeholder": {
                                            "tag": "plain_text",
                                            "content": "输入部门名称"
                                        },
                                        "default_value": "",
                                        "width": "default",
                                        "label": {
                                            "tag": "plain_text",
                                            "content": "部门名称："
                                        },
                                        "name": "dep_name",
                                        "margin": "0px 0px 0px 0px"
                                    },
                                    {
                                        "tag": "input",
                                        "placeholder": {
                                            "tag": "plain_text",
                                            "content": "输入群组名称"
                                        },
                                        "default_value": "",
                                        "width": "default",
                                        "label": {
                                            "tag": "plain_text",
                                            "content": "群组名称："
                                        },
                                        "name": "group_name",
                                        "margin": "0px 0px 0px 0px"
                                    },
                                    {
                                        "tag": "input",
                                        "placeholder": {
                                            "tag": "plain_text",
                                            "content": "域账号，多人以逗号隔开"
                                        },
                                        "default_value": "",
                                        "width": "default",
                                        "label": {
                                            "tag": "plain_text",
                                            "content": "推送人员："
                                        },
                                        "name": "user_ids",
                                        "margin": "0px 0px 0px 0px"
                                    },
                                    {
                                        "tag": "select_static",
                                        "placeholder": {
                                            "tag": "plain_text",
                                            "content": "个人推送"
                                        },
                                        "options": [
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "个人推送"
                                                },
                                                "value": "1"
                                            },
                                            {
                                                "text": {
                                                    "tag": "plain_text",
                                                    "content": "推送至群组，仅写了群组名称生效"
                                                },
                                                "value": "2"
                                            }
                                        ],
                                        "type": "default",
                                        "width": "default",
                                        "initial_index": 1,
                                        "name": "push_type",
                                        "margin": "0px 0px 0px 0px"
                                    },
                                    {
                                        "tag": "input",
                                        "placeholder": {
                                            "tag": "plain_text",
                                            "content": "消息ID"
                                        },
                                        "default_value": "",
                                        "width": "default",
                                        "label": {
                                            "tag": "plain_text",
                                            "content": "推送消息的ID："
                                        },
                                        "name": "msg_id",
                                        "margin": "0px 0px 0px 0px"
                                    },
                                    {
                                        "tag": "column_set",
                                        "columns": [
                                            {
                                                "tag": "column",
                                                "width": "auto",
                                                "elements": [
                                                    {
                                                        "tag": "button",
                                                        "text": {
                                                            "tag": "plain_text",
                                                            "content": "预览"
                                                        },
                                                        "type": "primary",
                                                        "width": "default",
                                                        "behaviors": [
                                                            {
                                                                "type": "callback",
                                                                "value": {
                                                                    "type": "push_view"
                                                                }
                                                            }
                                                        ],
                                                        "form_action_type": "submit",
                                                        "name": "Button_mlhlugdj"
                                                    }
                                                ],
                                                "vertical_align": "top"
                                            },
                                            {
                                                "tag": "column",
                                                "width": "auto",
                                                "elements": [
                                                    {
                                                        "tag": "button",
                                                        "text": {
                                                            "tag": "plain_text",
                                                            "content": "提交"
                                                        },
                                                        "type": "danger_filled",
                                                        "width": "default",
                                                        "confirm": {
                                                            "title": {
                                                                "tag": "plain_text",
                                                                "content": "确认推送"
                                                            },
                                                            "text": {
                                                                "tag": "plain_text",
                                                                "content": "建议先预览然后再进行提交"
                                                            }
                                                        },
                                                        "behaviors": [
                                                            {
                                                                "type": "callback",
                                                                "value": {
                                                                    "type": "push_push"
                                                                }
                                                            }
                                                        ],
                                                        "form_action_type": "submit",
                                                        "name": "Button_mlhlugdk"
                                                    }
                                                ],
                                                "vertical_align": "top"
                                            },
                                            {
                                                "tag": "column",
                                                "width": "auto",
                                                "elements": [
                                                    {
                                                        "tag": "button",
                                                        "text": {
                                                            "tag": "plain_text",
                                                            "content": "查看推送状态"
                                                        },
                                                        "type": "primary_filled",
                                                        "width": "default",
                                                        "size": "medium",
                                                        "behaviors": [
                                                            {
                                                                "type": "callback",
                                                                "value": {
                                                                    "type": "push_status"
                                                                }
                                                            }
                                                        ],
                                                        "form_action_type": "submit",
                                                        "name": "Button_du2mjw3tth4",
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
                                                            "content": "推送撤回"
                                                        },
                                                        "type": "danger_filled",
                                                        "width": "default",
                                                        "size": "medium",
                                                        "confirm": {
                                                            "title": {
                                                                "tag": "plain_text",
                                                                "content": "确认测回推送"
                                                            },
                                                            "text": {
                                                                "tag": "plain_text",
                                                                "content": "请确实是否撤回推送"
                                                            }
                                                        },
                                                        "behaviors": [
                                                            {
                                                                "type": "callback",
                                                                "value": {
                                                                    "type": "push_recall"
                                                                }
                                                            }
                                                        ],
                                                        "form_action_type": "submit",
                                                        "name": "Button_du2mjw3tth5",
                                                        "margin": "0px 0px 0px 0px"
                                                    }
                                                ],
                                                "vertical_align": "top",
                                                "weight": 1
                                            }
                                        ]
                                    }
                                ],
                                "padding": "4px 0px 4px 0px",
                                "margin": "0px 0px 0px 0px",
                                "name": "Form_mlhlugdi"
                            }
                        ]
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": "推送管理"
                        },
                        "subtitle": {
                            "tag": "plain_text",
                            "content": ""
                        },
                        "template": "blue",
                        "padding": "12px 12px 12px 12px"
                    }
                }
                card_id = self.feishu_msg.create_card_ins(this_card)
                self.feishu_msg.send_msg("open_id", user, json.dumps({"type":"card","data":{"card_id":card_id}}), "interactive")
                return
            if send_msgs.startswith("发送卡片消息") and user in self.admin_list:
                card_id = send_msgs.split("发送卡片消息")[1].split(" ")[0].strip()
                print(card_id)
                target_users = []
                if mentions_info:
                    for mention in mentions_info:
                        # 排除机器人自己
                        if mention.get("id", {}).get("open_id") and mention.get("id", {}).get("open_id") != user:
                            open_id = mention["id"]["open_id"]
                            name = mention.get("name", "unknown")
                            target_users.append({"open_id": open_id, "name": name})
                
                if target_users:
                    # 如果有@的用户，私信发送给被@的用户
                    for target_user in target_users:
                        try:
                            self.feishu_msg.send_msg("open_id", target_user["open_id"], "{\"type\":\"template\",\"data\":{\"template_id\":\""+card_id+"\"}}", "interactive")
                            print(f"[generate_article_card] 成功发送文章卡片给@{target_user['name']}(私信)")
                        except Exception as e:
                            print(f"[generate_article_card] 发送卡片给@{target_user['name']}失败: {e}")
                    # 发送确认消息给当前用户
                    if len(target_users) == 1:
                        confirm_msg = f"已成功推送给 @{target_users[0]['name']}"
                    else:
                        names = "、".join([f"@{u['name']}" for u in target_users])
                        confirm_msg = f"已成功推送给 {names}"
                    self.feishu_msg.send_msg("open_id", user, confirm_msg, "text")
                else:
                    # 如果没有@的用户，发送给当前用户
                    self.feishu_msg.send_msg("open_id", user, "{\"type\":\"template\",\"data\":{\"template_id\":\""+card_id+"\"}}", "interactive")
                    print(f"[generate_article_card] 成功发送文章卡片(私聊)")
                # 发送卡片后，不再执行后续的LLM调用，直接返回
                return
            # 检测消息中是否包含文章链接和"推送"关键词
            # 飞书链接模式：只匹配合法的URL字符（字母、数字、下划线、横线、查询参数等），排除中文字符
            feishu_link_pattern = r'https?://nio\.feishu\.cn/(?:wiki|docx|sheets)/[a-zA-Z0-9_\-]+(?:\?[a-zA-Z0-9_\-=&%\.]*)?'
            # 视频链接模式：支持bilibili、youtube等常见视频网站
            video_link_pattern = r'https?://(?:www\.)?(?:bilibili\.com|b23\.tv|youtube\.com|youtu\.be|v\.qq\.com|iqiyi\.com|youku\.com|acfun\.cn|douyin\.com|tiktok\.com)/[^\s<>"\'{}|\\^`\[\]]*'
            # 通用HTTP/HTTPS链接模式（用于匹配其他视频网站）
            general_link_pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+'
            
            # 先匹配飞书链接
            feishu_links = re.findall(feishu_link_pattern, send_msgs)
            # 再匹配视频链接
            video_links = re.findall(video_link_pattern, send_msgs)
            # 清理链接：去除末尾的标点符号（如右括号、句号等）
            def clean_url(url):
                return url.rstrip('.,;:!?)\\]}）')
            feishu_links = [clean_url(link) for link in feishu_links]
            video_links = [clean_url(link) for link in video_links]
            # 合并所有链接（优先飞书链接，然后是视频链接）
            links = feishu_links + video_links
            
            # 优先检测"解析文档"关键词（更具体，避免与画板冲突）
            has_parse_doc_keyword = re.search(r'解析文档|保存文档', send_msgs, re.IGNORECASE)
            
            if links and has_parse_doc_keyword:
                # 解析文档
                doc_link = links[0]
                try:
                    result = self.doc_manager.parse_and_save_doc(doc_link)
                    if result.get("success"):
                        if result.get("already_exists"):
                            # 文档已存在
                            msg = f"✅ 文档已存在\n"
                            msg += f"文档标题：{result.get('title')}\n"
                            msg += f"文件位置：{result.get('file_path')}"
                        else:
                            # 新解析的文档
                            msg = f"✅ 文档解析成功！\n"
                            msg += f"文档标题：{result.get('title')}\n"
                            msg += f"文件已保存：{result.get('file_path')}"
                        self.feishu_msg.send_msg("open_id", user, msg, "text")
                    else:
                        error_msg = f"❌ 文档解析失败：{result.get('message')}"
                        self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 解析文档时出错：{str(e)}"
                    self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                return
            
            # 检测是否包含"解析画板"关键词（必须明确指定"画板"）
            has_parse_board_keyword = re.search(r'解析画板|画板', send_msgs, re.IGNORECASE)
            
            if links and has_parse_board_keyword:
                # 解析画板
                doc_link = links[0]
                try:
                    result = self.board_manager.parse_board_from_link(doc_link)
                    if result.get("success"):
                        query_key = result.get('query_key', result.get('root_node', ''))
                        if result.get("already_exists"):
                            # 画板已存在，输出历史已解析信息
                            msg = f"✅ 历史已解析并存档\n"
                            msg += f"文档标题：{result.get('doc_title', '未知')}\n"
                            msg += f"根节点：{result.get('root_node')}\n"
                            msg += f"节点数量：{result.get('node_count')}\n"
                            msg += f"文件位置：{result.get('json_file')}\n\n"
                            msg += f"您可以使用以下命令查询节点：\n"
                            msg += f"查询 {query_key}"
                        else:
                            # 新解析的画板
                            msg = f"✅ 画板解析成功！\n"
                            msg += f"文档标题：{result.get('doc_title', '未知')}\n"
                            msg += f"根节点：{result.get('root_node')}\n"
                            msg += f"节点数量：{result.get('node_count')}\n"
                            msg += f"文件已保存：{result.get('json_file')}\n\n"
                            msg += f"您可以使用以下命令查询节点：\n"
                            msg += f"查询 {query_key}"
                        self.feishu_msg.send_msg("open_id", user, msg, "text")
                    else:
                        error_msg = f"❌ 画板解析失败：{result.get('message')}"
                        self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 解析画板时出错：{str(e)}"
                    self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                return
            
            # 检测VAS维测方法查询（优先检测）
            is_vas_query = False
            vas_query_text = ""
            if self.vas_method_tree:
                # 检测"维持方法支持"相关查询
                vas_keywords = ["维持方法支持", "维测方法支持", "维测方法", "维持方法", "vas方法"]
                for keyword in vas_keywords:
                    if keyword in send_msgs:
                        is_vas_query = True
                        vas_query_text = send_msgs
                        break
            
            if is_vas_query:
                try:
                    # 显示根节点（应用周期：全阶段、开发阶段）
                    card = self.create_vas_method_card(self.vas_method_tree)
                    self.feishu_msg.send_msg("open_id", user, card, "interactive")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 查询维测方法时出错：{str(e)}"
                    self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                return
            
            # 检测"问题排查支持"关键词（优先检测）
            if re.search(r'问题排查支持', send_msgs, re.IGNORECASE):
                try:
                    # 硬编码生产环境的boards目录路径
                    boards_dir = "/data/code/magic-vse/boards"
                    json_files = [
                        os.path.join(boards_dir, "NT3诊断问题.json"),
                        os.path.join(boards_dir, "NT3控制器休眠唤醒问题.json")
                    ]
                    
                    root_nodes_info = []
                    for json_file in json_files:
                        if os.path.exists(json_file):
                            board_data = self.board_manager.load_board_data(json_file=json_file)
                            if board_data:
                                root_node = board_data.get("root_node", {})
                                root_name = root_node.get("name", "")
                                root_id = root_node.get("id", "")
                                if root_name and root_id:
                                    root_nodes_info.append({
                                        "root_name": root_name,
                                        "root_id": root_id,
                                        "json_file": json_file
                                    })
                    
                    if root_nodes_info:
                        # 创建包含多个根节点的卡片
                        card = self.create_multi_root_card(root_nodes_info)
                        self.feishu_msg.send_msg("open_id", user, card, "interactive")
                    else:
                        error_msg = "❌ 未找到问题排查支持的相关画板文件"
                        self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 加载问题排查支持时出错：{str(e)}"
                    self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                return
            
            # 检测画板查询（优先检测，避免与任务票查询冲突）
            # 1. 检测明确的画板查询关键词："查询画板"、"查询节点"
            # 2. 检测"文件名-根节点"格式（画板查询格式）
            # 3. 排除任务票查询关键词（问题、开发、测试、任务、清单、ticket、bug、票）
            is_board_query = False
            query_text = ""
            
            # 先检测是否包含任务票查询关键词（如果包含，则不是画板查询）
            has_task_ticket_keywords = re.search(r'查询.*?(?:问题|开发|测试|任务|清单|ticket|bug|票)', send_msgs, re.IGNORECASE)
            
            # 先检测明确的画板查询关键词
            has_query_board_keyword = re.search(r'查询画板|查询节点', send_msgs, re.IGNORECASE)
            if has_query_board_keyword:
                is_board_query = True
                # 提取查询内容（在"查询画板"或"查询节点"之后的内容）
                query_match = re.search(r'查询(?:画板|节点)\s*(.+)', send_msgs, re.IGNORECASE)
                if query_match:
                    query_text = query_match.group(1).strip()
                else:
                    # 如果没有具体内容，尝试提取"查询"后的内容
                    query_match = re.search(r'查询(.+)', send_msgs)
                    if query_match:
                        query_text = query_match.group(1).strip()
            elif not has_task_ticket_keywords:
                # 如果没有任务票查询关键词，检测"文件名-根节点"格式
                # 匹配格式：查询 文件名-根节点（包含"-"分隔符）
                # 提取"查询"后的所有内容（直到消息结束或遇到任务票关键词）
                # 先尝试匹配包含"-"的格式
                query_match = re.search(r'查询\s+([^\s]+-[^\s]+)', send_msgs)
                if query_match:
                    potential_query = query_match.group(1).strip()
                    # 检查是否匹配已存在的画板（通过search_root_nodes验证）
                    try:
                        test_results = self.board_manager.search_root_nodes(potential_query)
                        if test_results:
                            is_board_query = True
                            query_text = potential_query
                    except:
                        pass
                else:
                    # 如果没有匹配到"-"格式，提取"查询"后的所有内容
                    query_match = re.search(r'查询\s+(.+?)(?:\s+(?:问题|开发|测试|任务|清单|ticket|bug|票|任务票))?$', send_msgs, re.IGNORECASE)
                    if query_match:
                        potential_query = query_match.group(1).strip()
                        # 如果包含"-"，优先作为画板查询
                        if '-' in potential_query:
                            try:
                                test_results = self.board_manager.search_root_nodes(potential_query)
                                if test_results:
                                    is_board_query = True
                                    query_text = potential_query
                            except:
                                pass
                        else:
                            # 即使没有"-"，也尝试匹配画板（可能是部分匹配）
                            try:
                                test_results = self.board_manager.search_root_nodes(potential_query)
                                if test_results:
                                    is_board_query = True
                                    query_text = potential_query
                            except:
                                pass
            
            if is_board_query and query_text:
                try:
                    # 搜索根节点（只在"画板"文件夹中搜索）
                    root_nodes = self.board_manager.search_root_nodes(query_text)
                    if root_nodes:
                        # 找到匹配的根节点，展示第一个
                        root_node_info = root_nodes[0]
                        root_name = root_node_info["root_name"]
                        root_id = root_node_info["root_id"]
                        json_file = root_node_info["json_file"]
                        
                        # 获取子节点
                        children = self.board_manager.get_node_children(root_id, json_file=json_file)
                        
                        # 创建节点展示卡片
                        card = self.create_node_card(root_name, root_id, children, json_file)
                        self.feishu_msg.send_msg("open_id", user, card, "interactive")
                    else:
                        # 未查询到相关内容
                        error_msg = f"❌ 未查询到相关内容：{query_text}\n\n提示：请先使用'解析画板'功能解析画板"
                        self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 查询节点时出错：{str(e)}"
                    self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                return
            
            # 检测消息中是否包含文章链接和"推送"关键词
            # 只匹配合法的URL字符（字母、数字、下划线、横线、查询参数等），排除中文字符
            has_push_keyword = re.search(r'推送|push|分享|转发', send_msgs, re.IGNORECASE)
            
            if links and has_push_keyword:
                # 如果找到链接且包含推送关键词，生成文章推送卡片
                article_url = links[0]  # 取第一个链接
                try:
                    notify = JiraNotify()
                    card = notify.generate_article_card(article_url)
                    if card:
                        # 检查是否有@的用户，如果有则私信发送给被@的用户
                        target_users = []
                        if mentions_info:
                            for mention in mentions_info:
                                # 排除机器人自己
                                if mention.get("id", {}).get("open_id") and mention.get("id", {}).get("open_id") != user:
                                    open_id = mention["id"]["open_id"]
                                    name = mention.get("name", "unknown")
                                    target_users.append({"open_id": open_id, "name": name})
                        
                        if target_users:
                            # 如果有@的用户，私信发送给被@的用户
                            for target_user in target_users:
                                try:
                                    self.feishu_msg.send_msg("open_id", target_user["open_id"], card, "interactive")
                                    print(f"[generate_article_card] 成功发送文章卡片给@{target_user['name']}(私信): {article_url}")
                                except Exception as e:
                                    print(f"[generate_article_card] 发送卡片给@{target_user['name']}失败: {e}")
                            # 发送确认消息给当前用户
                            if len(target_users) == 1:
                                confirm_msg = f"已成功推送给 @{target_users[0]['name']}"
                            else:
                                names = "、".join([f"@{u['name']}" for u in target_users])
                                confirm_msg = f"已成功推送给 {names}"
                            self.feishu_msg.send_msg("open_id", user, confirm_msg, "text")
                        else:
                            # 如果没有@的用户，发送给当前用户
                            self.feishu_msg.send_msg("open_id", user, card, "interactive")
                            print(f"[generate_article_card] 成功发送文章卡片(私聊): {article_url}")
                        # 发送卡片后，不再执行后续的LLM调用，直接返回
                        return
                    else:
                        # 如果生成卡片失败，发送错误提示并返回
                        error_msg = "抱歉，无法获取文档信息，可能是权限不足或链接无效。请检查文档链接是否正确，并确保机器人有访问权限。"
                        self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                        print(f"[generate_article_card] 生成卡片失败，已发送错误提示(私聊): {article_url}")
                        return
                except Exception as e:
                    print(f"[generate_article_card] 生成或发送卡片失败(私聊): {e}")
                    import traceback
                    traceback.print_exc()
                    # 如果生成卡片失败，发送错误提示并返回
                    try:
                        error_msg = f"抱歉，生成推送卡片时出现错误：{str(e)}"
                        self.feishu_msg.send_msg("open_id", user, error_msg, "text")
                    except:
                        pass
                    return
            
            element_id = "id_"+str(int(time.time()*1000))
            save_id = JamMySQL().insert(VIDOHistory, user=user).id
            card_id = self.create_flow_card(element_id, save_id=save_id)
            self.feishu_msg.reply_msg(msg_id, json.dumps({"type":"card","data":{"card_id":card_id}}), msg_type="interactive")
        # try:
            # print(send_msgs,user)
            # 处理@的用户信息，构建user_info（格式：open_id|用户名）
            # 同时将消息中的占位符（如@_user_1）替换为真实用户名（如@Jie NI 倪杰）
            user_info = ""
            user_id_name = {}
            processed_body = send_msgs  # 处理后的消息内容
            
            # 添加当前用户信息
            try:
                current_user_info = self.feishu_msg.get_user_info(user)
                user_id_name[user] = current_user_info.get("name", "unknown")
            except:
                user_id_name[user] = "unknown"
            
            # 处理mentions_info中的被@用户，并替换消息中的占位符
            if mentions_info:
                for mention in mentions_info:
                    if mention.get("id", {}).get("open_id"):
                        open_id = mention["id"]["open_id"]
                        name = mention.get("name", "unknown")
                        # 提取JIRA user_id（如果存在）
                        jira_user_id = mention.get("id", {}).get("user_id", "")
                        user_id_name[open_id] = name
                        # 如果有JIRA user_id，也存储映射关系
                        if jira_user_id:
                            user_id_name[f"{open_id}_jira"] = jira_user_id
                        # 将消息中的占位符（如@_user_1）替换为真实用户名（如@Jie NI 倪杰）
                        if mention.get("key"):
                            processed_body = processed_body.replace(mention["key"], "@"+name)
            
            # 构建user_info字符串，格式：open_id|name 或 open_id|name|jira_user_id
            for key, value in user_id_name.items():
                if key.endswith("_jira"):
                    # JIRA user_id 单独存储，格式：open_id_jira|jira_user_id
                    continue
                # 查找对应的JIRA user_id
                jira_user_id = user_id_name.get(f"{key}_jira", "")
                if jira_user_id:
                    user_info += f"{key}|{value}|{jira_user_id}\n"
                else:
                    user_info += f"{key}|{value}\n"
            
            knowledge = self.get_knowledge(processed_body)
            # 为私聊传递用户ID和user_info，以便任务管理等功能使用
            # 注意：使用处理后的消息内容（processed_body），而不是原始的send_msgs
            inputs = {"app_name": self.app_name, "knowledge": knowledge, "body": processed_body, "user_id": user, "user_info": user_info, "stream": True}
            ret = self.llm_call(self.user_reply_task, **inputs)
        # except Exception as e:
            # print("大模型调用失败了",e)
        #     ret = "大模型调用失败了"
            i = 1
            if ret["response"]:
                send_d = ""
                temp_send = ""
                current_time = time.time()
                for cont in ret["response"]:
                    if cont:
                        temp_send += cont
                        if time.time() - current_time > 2:
                            send_d += temp_send
                            self.update_flow_card(card_id, element_id, send_d, sequence=i)
                            i += 1
                            temp_send = ""
                            current_time = time.time()
                        # send_d += cont
                        # self.update_flow_card(card_id, element_id, send_d, sequence=i)
                        # i += 1
                if temp_send:
                    send_d += temp_send
                    self.update_flow_card(card_id, element_id, send_d, sequence=i)
                    i += 1
            else:
                send_d = "服务器出了点问题(code:1001)，请联系<at id=ou_287877ad6ecdf314dfd669137365d995></at>"
                self.update_flow_card(card_id, element_id, send_d, sequence=i)
                i += 1
            JamMySQL().update(VIDOHistory, where={"id":save_id}, query=send_msgs, prompt=ret["user_prompt"], sys_prompt=ret["sys_prompt"], answer=send_d)
            self.update_card_config(card_id,sequence=i)
            # self.feishu_msg.send_msg("open_id", user, json.dumps({"text":ret}, ensure_ascii=False))

    def create_flow_card(self, element_id, data="生成中...", save_id = 0):
        card = {
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "streaming_mode": True,
                "streaming_config": {
                    "print_frequency_ms": {
                        "default": 70
                    },
                    "print_step": {
                        "default": 1
                    },
                    "print_strategy": "fast"
                },
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
                        "content": data,
                        "text_align": "left",
                        "text_size": "normal_v2",
                        "margin": "0px 0px 0px 0px",
                        "element_id": element_id
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
                                                    "id": save_id
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
                                                    "id": save_id
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
        card_id = self.feishu_msg.create_card_ins(card)
        return card_id
    
    def update_flow_card(self, card_id, element_id, data, sequence=0):
        self.feishu_msg.flow_card_update(card_id, element_id, data, sequence)
    
    def update_card_config(self, card_id, sequence):
        self.feishu_msg.update_card_config(card_id, {
            "config": {
                "update_multi": True,
                "streaming_mode": False,
                "streaming_config": {
                    "print_frequency_ms": {
                        "default": 70
                    },
                    "print_step": {
                        "default": 1
                    },
                    "print_strategy": "fast"
                },
                "style": {
                    "text_size": {
                        "normal_v2": {
                            "default": "normal",
                            "pc": "normal",
                            "mobile": "heading"
                        }
                    }
                }
            }
        }, sequence)


    def llm_call(self, task, **kwargs):
        # langfuse = get_client()
        # CrewAIInstrumentor().instrument(skip_dep_check=True)
        # LiteLLMInstrumentor().instrument()
        # with langfuse.start_as_current_span(name="vido-llm-call"):
            # ret = self.vido_agent.execute_task(task)
        ret = exec_task(task, **kwargs)
        # langfuse.flush()
        return ret

    def back_reply_msg(self, json_data):
        chat_id = json_data["event"]["message"]["chat_id"]
        sender_id = json_data["event"]["sender"]["sender_id"]["open_id"]
        message_id = json_data["event"]["message"]["message_id"]
        create_time = int(json_data["event"]["message"]["create_time"][:-3])
        parent_id = json_data["event"]["message"].get("parent_id", "")
        if message_id in self.recv_msg_ids:
            return
        self.recv_msg_ids.append(message_id)
        print("get user msg", json_data)
        if chat_id not in self.thread_lock:
                self.thread_lock[chat_id] = threading.Lock()
        if json_data["event"]["message"]["message_type"] != "text":
            return
        body = json.loads(json_data["event"]["message"]["content"])["text"]
        if_at = False
        has_mention_others = False  # 是否@了其他用户（不是机器人）
        user_id_name = {}
        for mention in json_data["event"]["message"].get("mentions", []):
            body = body.replace(mention["key"], "@"+mention["name"])
            # print(mention)
            open_id = mention["id"]["open_id"]
            name = mention["name"]
            # 提取JIRA user_id（如果存在）
            jira_user_id = mention.get("id", {}).get("user_id", "")
            user_id_name[open_id] = name
            # 如果有JIRA user_id，也存储映射关系
            if jira_user_id:
                user_id_name[f"{open_id}_jira"] = jira_user_id
            if mention["name"] == self.app_name:
                if_at = True
            else:
                has_mention_others = True  # @了其他用户
        if chat_id:
            self.thread_lock[chat_id].acquire()
        i = 0
        new_msg_flag = False
        if chat_id not in self.msg_record:
            self.msg_record[chat_id] = self.feishu_msg.get_group_msgs(chat_id, 60*60*24*3)
            # sender_name = "unknown"
            # for item in self.feishu_msg.p_id_name:
            #     if item["member_id"] == sender_id:
            #         sender_name = item["name"]
            #         user_id_name[item["member_id"]] = item["name"]
            #         break
        else:
            # sender_name = "unknown"
            # for item in self.feishu_msg.p_id_name:
            #     if item["member_id"] == sender_id:
            #         sender_name = item["name"]
            #         user_id_name[item["member_id"]] = item["name"]
            #         break
            # else:
            #     self.feishu_msg.get_group_members(chat_id)
            #     for item in self.feishu_msg.p_id_name:
            #         if item["member_id"] == sender_id:
            #             sender_name = item["name"]
            #             user_id_name[item["member_id"]] = item["name"]
            #             break
            new_msg_flag = True
        d_msg = ""
        card_id = None
        user_info = ""
        sender_info = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(create_time))}|{sender_id}|{message_id}|{parent_id}|{body}"
        for i in range(len(self.msg_record[chat_id])):
            item = self.msg_record[chat_id][i]
            # 将时间戳转换为可读的时间字符串，格式：年-月-日 时:分:秒
            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item['create_time']))
            user_id_name[item['user_id']] = item['user']
            # d_msg += f"{time_str} {item['user']}(id:{item['user_id']}): {item['msg']}\n"
            temp_m = repr(item['msg']).replace('|', ',').replace('\\n', ' ')
            d_msg += f"{time_str}|{item['user_id']}|{item['message_id']}|{item['parent_id']}|{temp_m}\n"
            user_id_name[item['user_id']] = item['user']
        if user_id_name.get(sender_id) is None:
            if not self.users.get(chat_id,{}).get(sender_id):
                chat_users = self.feishu_msg.get_group_members(chat_id)
                if chat_id not in self.users:
                    self.users[chat_id] = {}
                for item in chat_users:
                    self.users[chat_id][item["member_id"]] = item["name"]
            user_id_name[sender_id] = self.users[chat_id].get(sender_id, "unknown")

        if new_msg_flag:
            self.msg_record[chat_id].append({
                "create_time": create_time,
                "user_id": sender_id,
                "message_id": message_id,
                "parent_id": parent_id,
                "user": user_id_name[sender_id],
                "msg": body,
            })
        # 构建user_info字符串，格式：open_id|name 或 open_id|name|jira_user_id
        for key, value in user_id_name.items():
            if key.endswith("_jira"):
                # JIRA user_id 单独存储，格式：open_id_jira|jira_user_id
                continue
            # 查找对应的JIRA user_id
            jira_user_id = user_id_name.get(f"{key}_jira", "")
            if jira_user_id:
                user_info += f"{key}|{value}|{jira_user_id}\n"
            else:
                user_info += f"{key}|{value}\n"
        # body_msg = body_msg.format(sender_info=sender_info, d_msg=d_msg, chat_id=chat_id, user_info=user_info, knowledge=knowledge)
        
        if chat_id:
            self.thread_lock[chat_id].release()
        i = 1
        
        # 检测是否@了机器人并且消息中包含链接
        if if_at:
            # 提取消息中的飞书链接
            feishu_link_pattern = r'https?://nio\.feishu\.cn/(?:wiki|docx|sheets)/[a-zA-Z0-9_\-]+(?:\?[a-zA-Z0-9_\-=&%\.]*)?'
            # 视频链接模式：支持bilibili、youtube等常见视频网站
            video_link_pattern = r'https?://(?:www\.)?(?:bilibili\.com|b23\.tv|youtube\.com|youtu\.be|v\.qq\.com|iqiyi\.com|youku\.com|acfun\.cn|douyin\.com|tiktok\.com)/[^\s<>"\'{}|\\^`\[\]]*'
            # 通用HTTP/HTTPS链接模式（用于匹配其他视频网站）
            general_link_pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+'
            
            # 先匹配飞书链接
            feishu_links = re.findall(feishu_link_pattern, body)
            # 再匹配视频链接
            video_links = re.findall(video_link_pattern, body)
            # 清理链接：去除末尾的标点符号（如右括号、句号等）
            def clean_url(url):
                return url.rstrip('.,;:!?)\\]}）')
            feishu_links = [clean_url(link) for link in feishu_links]
            video_links = [clean_url(link) for link in video_links]
            # 合并所有链接（优先飞书链接，然后是视频链接）
            links = feishu_links + video_links
            
            # 优先检测"解析文档"关键词（更具体，避免与画板冲突）
            has_parse_doc_keyword = re.search(r'解析文档|保存文档', body, re.IGNORECASE)
            
            if links and has_parse_doc_keyword:
                # 解析文档
                doc_link = links[0]
                try:
                    result = self.doc_manager.parse_and_save_doc(doc_link)
                    if result.get("success"):
                        if result.get("already_exists"):
                            # 文档已存在
                            msg = f"✅ 文档已存在\n"
                            msg += f"文档标题：{result.get('title')}\n"
                            msg += f"文件位置：{result.get('file_path')}"
                        else:
                            # 新解析的文档
                            msg = f"✅ 文档解析成功！\n"
                            msg += f"文档标题：{result.get('title')}\n"
                            msg += f"文件已保存：{result.get('file_path')}"
                        self.feishu_msg.send_msg("chat_id", chat_id, msg, "text")
                    else:
                        error_msg = f"❌ 文档解析失败：{result.get('message')}"
                        self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 解析文档时出错：{str(e)}"
                    self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                return
            
            # 检测是否包含"解析画板"关键词（必须明确指定"画板"）
            has_parse_board_keyword = re.search(r'解析画板|画板', body, re.IGNORECASE)
            
            if links and has_parse_board_keyword:
                # 解析画板
                doc_link = links[0]
                try:
                    result = self.board_manager.parse_board_from_link(doc_link)
                    if result.get("success"):
                        query_key = result.get('query_key', result.get('root_node', ''))
                        if result.get("already_exists"):
                            # 画板已存在，输出历史已解析信息
                            msg = f"✅ 历史已解析并存档\n"
                            msg += f"文档标题：{result.get('doc_title', '未知')}\n"
                            msg += f"根节点：{result.get('root_node')}\n"
                            msg += f"节点数量：{result.get('node_count')}\n"
                            msg += f"文件位置：{result.get('json_file')}\n\n"
                            msg += f"您可以使用以下命令查询节点：\n"
                            msg += f"查询 {query_key}"
                        else:
                            # 新解析的画板
                            msg = f"✅ 画板解析成功！\n"
                            msg += f"文档标题：{result.get('doc_title', '未知')}\n"
                            msg += f"根节点：{result.get('root_node')}\n"
                            msg += f"节点数量：{result.get('node_count')}\n"
                            msg += f"文件已保存：{result.get('json_file')}\n\n"
                            msg += f"您可以使用以下命令查询节点：\n"
                            msg += f"查询 {query_key}"
                        self.feishu_msg.send_msg("chat_id", chat_id, msg, "text")
                    else:
                        error_msg = f"❌ 画板解析失败：{result.get('message')}"
                        self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 解析画板时出错：{str(e)}"
                    self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                return
            
            # 检测"问题排查支持"关键词（优先检测）
            if re.search(r'问题排查支持', body, re.IGNORECASE):
                try:
                    # 硬编码生产环境的boards目录路径
                    boards_dir = "/data/code/magic-vse/boards"
                    json_files = [
                        os.path.join(boards_dir, "NT3诊断问题.json"),
                        os.path.join(boards_dir, "NT3控制器休眠唤醒问题.json")
                    ]
                    
                    root_nodes_info = []
                    for json_file in json_files:
                        if os.path.exists(json_file):
                            board_data = self.board_manager.load_board_data(json_file=json_file)
                            if board_data:
                                root_node = board_data.get("root_node", {})
                                root_name = root_node.get("name", "")
                                root_id = root_node.get("id", "")
                                if root_name and root_id:
                                    root_nodes_info.append({
                                        "root_name": root_name,
                                        "root_id": root_id,
                                        "json_file": json_file
                                    })
                    
                    if root_nodes_info:
                        # 创建包含多个根节点的卡片
                        card = self.create_multi_root_card(root_nodes_info)
                        self.feishu_msg.send_msg("chat_id", chat_id, card, "interactive")
                    else:
                        error_msg = "❌ 未找到问题排查支持的相关画板文件"
                        self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 加载问题排查支持时出错：{str(e)}"
                    self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                return
            
            # 检测画板查询（优先检测，避免与任务票查询冲突）
            # 1. 检测明确的画板查询关键词："查询画板"、"查询节点"
            # 2. 检测"文件名-根节点"格式（画板查询格式）
            # 3. 排除任务票查询关键词（问题、开发、测试、任务、清单、ticket、bug、票）
            is_board_query = False
            query_text = ""
            
            # 先检测是否包含任务票查询关键词（如果包含，则不是画板查询）
            has_task_ticket_keywords = re.search(r'查询.*?(?:问题|开发|测试|任务|清单|ticket|bug|票)', body, re.IGNORECASE)
            
            # 先检测明确的画板查询关键词
            has_query_board_keyword = re.search(r'查询画板|查询节点', body, re.IGNORECASE)
            if has_query_board_keyword:
                is_board_query = True
                # 提取查询内容（在"查询画板"或"查询节点"之后的内容）
                query_match = re.search(r'查询(?:画板|节点)\s*(.+)', body, re.IGNORECASE)
                if query_match:
                    query_text = query_match.group(1).strip()
                else:
                    # 如果没有具体内容，尝试提取"查询"后的内容
                    query_match = re.search(r'查询(.+)', body)
                    if query_match:
                        query_text = query_match.group(1).strip()
            elif not has_task_ticket_keywords:
                # 如果没有任务票查询关键词，检测"文件名-根节点"格式
                # 匹配格式：查询 文件名-根节点（包含"-"分隔符）
                # 提取"查询"后的所有内容（直到消息结束或遇到任务票关键词）
                # 先尝试匹配包含"-"的格式
                query_match = re.search(r'查询\s+([^\s]+-[^\s]+)', body)
                if query_match:
                    potential_query = query_match.group(1).strip()
                    # 检查是否匹配已存在的画板（通过search_root_nodes验证）
                    try:
                        test_results = self.board_manager.search_root_nodes(potential_query)
                        if test_results:
                            is_board_query = True
                            query_text = potential_query
                    except:
                        pass
                else:
                    # 如果没有匹配到"-"格式，提取"查询"后的所有内容
                    query_match = re.search(r'查询\s+(.+?)(?:\s+(?:问题|开发|测试|任务|清单|ticket|bug|票|任务票))?$', body, re.IGNORECASE)
                    if query_match:
                        potential_query = query_match.group(1).strip()
                        # 如果包含"-"，优先作为画板查询
                        if '-' in potential_query:
                            try:
                                test_results = self.board_manager.search_root_nodes(potential_query)
                                if test_results:
                                    is_board_query = True
                                    query_text = potential_query
                            except:
                                pass
                        else:
                            # 即使没有"-"，也尝试匹配画板（可能是部分匹配）
                            try:
                                test_results = self.board_manager.search_root_nodes(potential_query)
                                if test_results:
                                    is_board_query = True
                                    query_text = potential_query
                            except:
                                pass
            
            if is_board_query and query_text:
                try:
                    # 搜索根节点（只在"画板"文件夹中搜索）
                    root_nodes = self.board_manager.search_root_nodes(query_text)
                    if root_nodes:
                        # 找到匹配的根节点，展示第一个
                        root_node_info = root_nodes[0]
                        root_name = root_node_info["root_name"]
                        root_id = root_node_info["root_id"]
                        json_file = root_node_info["json_file"]
                        
                        # 获取子节点
                        children = self.board_manager.get_node_children(root_id, json_file=json_file)
                        
                        # 创建节点展示卡片
                        card = self.create_node_card(root_name, root_id, children, json_file)
                        self.feishu_msg.send_msg("chat_id", chat_id, card, "interactive")
                    else:
                        # 未查询到相关内容
                        error_msg = f"❌ 未查询到相关内容：{query_text}\n\n提示：请先使用'解析画板'功能解析画板"
                        self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 查询节点时出错：{str(e)}"
                    self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                return
            
            # 检测是否包含"推送"关键词
            has_push_keyword = re.search(r'推送|push|分享|转发', body, re.IGNORECASE)
            
            if links and has_push_keyword:
                # 如果找到链接且包含推送关键词，生成文章推送卡片
                article_url = links[0]  # 取第一个链接
                try:
                    notify = JiraNotify()
                    card = notify.generate_article_card(article_url)
                    if card:
                        # 检查是否有@的用户，如果有则私信发送给被@的用户
                        target_users = []
                        if has_mention_others:
                            # 从mentions中提取被@的用户（排除机器人）
                            for mention in json_data["event"]["message"].get("mentions", []):
                                mention_open_id = mention.get("id", {}).get("open_id")
                                mention_name = mention.get("name", "unknown")
                                # 排除机器人自己（通过检查是否是机器人名称）
                                if mention_open_id and mention_name != self.app_name:
                                    target_users.append({"open_id": mention_open_id, "name": mention_name})
                        
                        if target_users:
                            # 如果有@的用户，私信发送给被@的用户
                            for target_user in target_users:
                                try:
                                    self.feishu_msg.send_msg("open_id", target_user["open_id"], card, "interactive")
                                    print(f"[generate_article_card] 成功发送文章卡片给@{target_user['name']}(私信): {article_url}")
                                except Exception as e:
                                    print(f"[generate_article_card] 发送卡片给@{target_user['name']}失败: {e}")
                            # 在群聊中发送确认消息
                            if len(target_users) == 1:
                                confirm_msg = f"已成功推送给 @{target_users[0]['name']}"
                            else:
                                names = "、".join([f"@{u['name']}" for u in target_users])
                                confirm_msg = f"已成功推送给 {names}"
                            self.feishu_msg.send_msg("chat_id", chat_id, confirm_msg, "text")
                        else:
                            # 如果没有@的用户，发送到群聊
                            self.feishu_msg.send_msg("chat_id", chat_id, card, "interactive")
                            print(f"[generate_article_card] 成功发送文章卡片(群聊): {article_url}")
                        # 发送卡片后，不再执行后续的LLM调用，直接返回
                        return
                    else:
                        # 如果生成卡片失败，发送错误提示并返回
                        error_msg = "抱歉，无法获取文档信息，可能是权限不足或链接无效。请检查文档链接是否正确，并确保机器人有访问权限。"
                        self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                        print(f"[generate_article_card] 生成卡片失败，已发送错误提示(群聊): {article_url}")
                        return
                except Exception as e:
                    print(f"[generate_article_card] 生成或发送卡片失败(群聊): {e}")
                    import traceback
                    traceback.print_exc()
                    # 如果生成卡片失败，发送错误提示并返回
                    try:
                        error_msg = f"抱歉，生成推送卡片时出现错误：{str(e)}"
                        self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                    except:
                        pass
                    return
            
            # 检测"今日任务汇总"关键词（必须在@机器人的情况下）
            has_task_summary_keyword = re.search(r'今日任务汇总|任务汇总|任务情况汇总', body, re.IGNORECASE)
            if has_task_summary_keyword:
                try:
                    from data_center.task import send_task_summary_to_group
                    from magic_jam import FeishuMsg
                    import asyncio
                    feishu_msg_instance = FeishuMsg()  # 创建独立的实例用于线程中
                    # 在新线程中异步调用任务汇总函数
                    def run_task_summary():
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(send_task_summary_to_group(chat_id))
                            loop.close()
                            print(f"[task_summary] 成功发送任务汇总到群聊: {chat_id}")
                        except Exception as e:
                            import traceback
                            traceback.print_exc()
                            error_msg = f"❌ 生成任务汇总时出错：{str(e)}"
                            try:
                                feishu_msg_instance.send_msg("chat_id", chat_id, error_msg, "text")
                            except:
                                pass
                            print(f"[task_summary] 发送任务汇总失败(群聊): {e}")
                    thread = threading.Thread(target=run_task_summary)
                    thread.start()
                    return
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"❌ 生成任务汇总时出错：{str(e)}"
                    self.feishu_msg.send_msg("chat_id", chat_id, error_msg, "text")
                    print(f"[task_summary] 发送任务汇总失败(群聊): {e}")
                    return
        
        if if_at:
            element_id = "id_"+str(int(time.time()*1000))
            save_id = JamMySQL().insert(VIDOHistory, user=sender_id, group_id=chat_id).id
            print("send reply msg")
            card_id = self.create_flow_card(element_id, save_id=save_id)
            try:
                self.feishu_msg.reply_msg(message_id, json.dumps({"type":"card","data":{"card_id":card_id}}), msg_type="interactive")
            except Exception as e:
                print(f"发送回复消息失败: {e}")
                import traceback
                traceback.print_exc()
                # 即使发送卡片失败，也继续执行后续流程
            knowledge = self.get_knowledge(body)
            # send_msgs.append({"role": "user", "content": body_msg})
            try:
                inputs = {"app_name": self.app_name, "chat_id": chat_id, "d_msg": d_msg, "user_info": user_info, "knowledge": knowledge, "sender_info": sender_info, "stream": True}
                # self.vido_agent.interpolate_inputs(inputs)
                # self.group_reply_task.interpolate_inputs_and_add_conversation_history(inputs)
                print(f"[GroupReplyTask] 开始调用 LLM, chat_id={chat_id}")
                ret = self.llm_call(self.group_reply_task, **inputs)
                print(f"[GroupReplyTask] LLM 返回, response type={type(ret.get('response'))}")
                if ret["response"]:
                    send_d = ""
                    temp_send = ""
                    current_time = time.time()
                    stream_start_time = time.time()
                    stream_timeout = 120  # 流式输出超时时间（秒）
                    chunk_count = 0
                    for cont in ret["response"]:
                        chunk_count += 1
                        # 检查流式输出是否超时
                        if time.time() - stream_start_time > stream_timeout:
                            print(f"[GroupReplyTask] 流式输出超时 ({stream_timeout}秒), chunk_count={chunk_count}")
                            if not send_d and not temp_send:
                                send_d = "✅ 已处理完成，请查看上方卡片"
                            break
                        if cont:
                            temp_send += cont
                            stream_start_time = time.time()  # 收到内容时重置超时计时
                            if time.time() - current_time > 2:
                                send_d += temp_send
                                self.update_flow_card(card_id, element_id, send_d, sequence=i)
                                i += 1
                                temp_send = ""
                                current_time = time.time()
                            # send_d += cont
                            # self.update_flow_card(card_id, element_id, send_d, sequence=i)
                            # i += 1
                    print(f"[GroupReplyTask] 流式输出结束, chunk_count={chunk_count}, send_d长度={len(send_d)}, temp_send长度={len(temp_send)}")
                    if temp_send:
                        send_d += temp_send
                        self.update_flow_card(card_id, element_id, send_d, sequence=i)
                        i += 1
                    # 如果流式输出没有任何内容，显示默认消息
                    if not send_d:
                        print(f"[GroupReplyTask] 流式输出为空，显示默认消息")
                        send_d = "✅ 已处理完成，请查看上方卡片"
                        self.update_flow_card(card_id, element_id, send_d, sequence=i)
                        i += 1
                else:
                    send_d = "服务器出了点问题(code:1002)，请联系<at id=ou_287877ad6ecdf314dfd669137365d995></at>"
                    self.update_flow_card(card_id, element_id, send_d, sequence=i)
                    i += 1
            except Exception as e:
                print("大模型调用失败了", e)
                import traceback
                traceback.print_exc()
                send_d = "服务器出了点问题(code:1003)，请联系<at id=ou_287877ad6ecdf314dfd669137365d995></at>"
                self.update_flow_card(card_id, element_id, send_d, sequence=i)
                i += 1
            # self.feishu_msg.reply_msg(message_id, ret)
            if chat_id:
                self.thread_lock[chat_id].acquire()
            self.msg_record[chat_id].append({
                "create_time": int(time.time()),
                "user_id": self.app_id,
                "message_id": "",
                "parent_id": None,
                "user": self.app_name,
                "msg": send_d,
            })
            if chat_id:
                self.thread_lock[chat_id].release()
        elif False:
            card_id = None
            try:
                # self.vido_agent.interpolate_inputs({"app_name": self.app_name})
                # self.check_need_reply_task.interpolate_inputs_and_add_conversation_history({"body": body})
                # 将是否@了其他用户的信息添加到消息中，方便 CheckNeedReplyTask 判断
                mention_info = "（消息中@了其他用户）" if has_mention_others else "（消息中未@其他用户）"
                sender_info_with_mention = sender_info + mention_info
                inputs = {"app_name": self.app_name, "body": sender_info_with_mention, "d_msg": "\n".join(d_msg.strip().split("\n")[-10:])}
                # ret = self.vido_agent.execute_task(self.check_need_reply_task)
                ret = self.llm_call(self.check_need_reply_task, **inputs)
            except Exception as e:
                ret = {"response": "大模型调用失败了"}
            # print(ret)
            JamMySQL().insert(VIDOHistory, query="判断是否需要处理用户消息", user=sender_id, prompt=ret.get("user_prompt", ""), sys_prompt=ret.get("sys_prompt", ""), answer=ret["response"], group_id=chat_id)
            if ret["response"].split("\n")[0].find("是") != -1 and ret["response"].split("\n")[0].find("不是") == -1:
                # send_msgs.append({"role": "user", "content": body_msg})
                element_id = "id_"+str(int(time.time()*1000))
                save_id = JamMySQL().insert(VIDOHistory, user=sender_id, group_id=chat_id).id
                print("send reply msg1")
                card_id = self.create_flow_card(element_id, save_id=save_id)
                try:
                    self.feishu_msg.reply_msg(message_id, json.dumps({"type":"card","data":{"card_id":card_id}}), msg_type="interactive")
                except Exception as e:
                    print(f"发送回复消息失败: {e}")
                    import traceback
                    traceback.print_exc()
                    # 即使发送卡片失败，也继续执行后续流程
                knowledge = self.get_knowledge(body)
                try:
                    inputs = {"app_name": self.app_name, "chat_id": chat_id, "d_msg": d_msg, "user_info": user_info, "knowledge": knowledge, "sender_info": sender_info, "stream": True}
                    # self.vido_agent.interpolate_inputs(inputs)
                    # self.group_reply_task.interpolate_inputs_and_add_conversation_history(inputs)
                    # ret = self.vido_agent.execute_task(self.group_reply_task)
                    print(f"[GroupReplyTask-else] 开始调用 LLM, chat_id={chat_id}")
                    ret = self.llm_call(self.group_reply_task, **inputs)
                    print(f"[GroupReplyTask-else] LLM 返回, response type={type(ret.get('response'))}")
                    if ret["response"]:
                        send_d = ""
                        temp_send = ""
                        current_time = time.time()
                        stream_start_time = time.time()
                        stream_timeout = 120  # 流式输出超时时间（秒）
                        chunk_count = 0
                        for cont in ret["response"]:
                            chunk_count += 1
                            # 检查流式输出是否超时
                            if time.time() - stream_start_time > stream_timeout:
                                print(f"[GroupReplyTask-else] 流式输出超时 ({stream_timeout}秒), chunk_count={chunk_count}")
                                if not send_d and not temp_send:
                                    send_d = "✅ 已处理完成，请查看上方卡片"
                                break
                            if cont:
                                temp_send += cont
                                stream_start_time = time.time()  # 收到内容时重置超时计时
                                if time.time() - current_time > 2:
                                    send_d += temp_send
                                    self.update_flow_card(card_id, element_id, send_d, sequence=i)
                                    i += 1
                                    temp_send = ""
                                    current_time = time.time()
                                # send_d += cont
                                # self.update_flow_card(card_id, element_id, send_d, sequence=i)
                                # i += 1
                        print(f"[GroupReplyTask-else] 流式输出结束, chunk_count={chunk_count}, send_d长度={len(send_d)}, temp_send长度={len(temp_send)}")
                        if temp_send:
                            send_d += temp_send
                            self.update_flow_card(card_id, element_id, send_d, sequence=i)
                            i += 1
                        # 如果流式输出没有任何内容，显示默认消息
                        if not send_d:
                            print(f"[GroupReplyTask-else] 流式输出为空，显示默认消息")
                            send_d = "✅ 已处理完成，请查看上方卡片"
                            self.update_flow_card(card_id, element_id, send_d, sequence=i)
                            i += 1
                    else:
                        send_d = "服务器出了点问题(code:1004)，请联系<at id=ou_287877ad6ecdf314dfd669137365d995></at>"
                        self.update_flow_card(card_id, element_id, send_d, sequence=i)
                        i += 1
                except Exception as e:
                    print("大模型调用失败了", e)
                    import traceback
                    traceback.print_exc()
                    send_d = "服务器出了点问题(code:1005)，请联系<at id=ou_287877ad6ecdf314dfd669137365d995></at>"
                    self.update_flow_card(card_id, element_id, send_d, sequence=i)
                    i += 1
        if card_id:
            JamMySQL().update(VIDOHistory, where={"id":save_id}, query=body, prompt=ret["user_prompt"], sys_prompt=ret["sys_prompt"], answer=send_d)
            self.update_card_config(card_id,sequence=i)

    def create_and_pin_card(self, group_id):
        card_msg = {
            "schema": "2.0",
            "config": {
                "update_multi": True
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": [
                    {
                        "tag": "column_set",
                        "columns": [
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "markdown",
                                        "content": "获取我的任务",
                                        "text_align": "left"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 1
                            },
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "button",
                                        "text": {
                                            "tag": "plain_text",
                                            "content": "查看详情"
                                        },
                                        "behaviors": [
                                            {
                                                "type": "callback",
                                                "value": {
                                                    "type": "show_task",
                                                    "id": "我的任务"
                                                }
                                            }
                                        ],
                                        "type": "primary",
                                        "width": "fill",
                                        "size": "large"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 1
                            }
                        ]
                    },
                    {
                        "tag": "column_set",
                        "columns": [
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "markdown",
                                        "content": "获取全部任务",
                                        "text_align": "left"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 1
                            },
                            {
                                "tag": "column",
                                "width": "weighted",
                                "elements": [
                                    {
                                        "tag": "button",
                                        "text": {
                                            "tag": "plain_text",
                                            "content": "查看详情"
                                        },
                                        "behaviors": [
                                            {
                                                "type": "callback",
                                                "value": {
                                                    "type": "show_task",
                                                    "id": "全部任务"
                                                }
                                            }
                                        ],
                                        "type": "primary",
                                        "width": "fill",
                                        "size": "large"
                                    }
                                ],
                                "vertical_align": "top",
                                "weight": 1
                            }
                        ]
                    }
                ]
            }
        }
        response = self.feishu_msg.send_msg("chat_id", group_id, json.dumps(card_msg, ensure_ascii=False), "interactive")
        ret_res = json.loads(response.raw.content)
        print(ret_res)
        msg_id = ret_res["data"]["message_id"]
        print(msg_id)
        self.feishu_msg.pin_msg(msg_id)
    
    def hello_func(self, chat_id):
        # 根据机器人名称设置不同的欢迎消息
        if self.app_name == "MyVSE":
            welcome_content = "大家好，我是 MyVSE。\n[使用说明](https://nio.feishu.cn/docx/T1pId9HKKoy25YxkVEkcbQE9n2c)"
        if self.app_name == "数字KiKi":
            welcome_content = "大家好，我是 数字KiKi \n"
        else:  # 默认 VIDO-AI
            welcome_content = f"大家好，我是{self.app_name}。\n[使用说明](https://nio.feishu.cn/wiki/ZNHNwVZzwiqziGkvWbMcEKK2nxr)"
        
        card={
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
                        "content": welcome_content,
                        "text_align": "left",
                        "text_size": "normal_v2",
                        "margin": "0px 0px 0px 0px"
                    }
                ]
            }
        }
        self.feishu_msg.send_msg("chat_id", chat_id, card, "interactive")
    
    def send_show_task(self, chat_id, open_id, id_type):
        status_map = {
            0: "进行中",
            1: "已完成",
            2: "已取消",
            3: "已超时"
        }
        task_card = {
            "open_id": open_id,
            "chat_id": chat_id,
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
                    "elements": []
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
        query_kwargs = {
            "group_id": chat_id
        }
        # db = next(get_db())
        # task = db.query(Task).filter(Task.group_id == chat_id)
        if id_type == "我的任务":
            # task = task.filter(Task.owner_id == open_id).all()
            query_kwargs["owner_id"] = open_id
            task_card["card"]["header"]["title"]["content"] = "我的任务"
        elif id_type == "全部任务":
            # task = task.all()
            task_card["card"]["header"]["title"]["content"] = "全部任务"
        task = self.jam_sql.query(Task, **query_kwargs)
        i = 1
        if not task:
            print("no task")
            return
        for item in task:
            task_card["card"]["body"]["elements"].append({
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
                                    "content": f"任务{i}： {item.content}",
                                    "text_size": "normal_v2",
                                    "text_align": "left",
                                    "text_color": "default"
                                },
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "vertical_align": "top",
                        "weight": 2
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "elements": [
                            {
                                "tag": "select_static",
                                "placeholder": {
                                "tag": "plain_text",
                                "content": status_map[item.status]
                                },
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                        "type": "change_status",
                                        "id": item.id
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
                                "width": "default",
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "vertical_align": "top",
                        "weight": 1
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "elements": [
                            {
                                "tag": "picker_datetime",
                                "initial_datetime": item.end_time.strftime("%Y-%m-%d %H:%M"),
                                "placeholder": {
                                    "tag": "plain_text",
                                    "content": "请选择"
                                },
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "type": "change_end_time",
                                            "id": item.id
                                        }
                                    }
                                ],
                                "width": "default",
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "vertical_align": "top",
                        "weight": 1
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "elements": [
                            {
                                "tag": "select_person",
                                "initial_option": item.owner_id,
                                "placeholder": {
                                    "tag": "plain_text",
                                    "content": "请选择"
                                },
                                "options": [
                                    {
                                        "value": item.owner_id
                                    }
                                ],
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "type": "change_task_owner",
                                            "id": item.id
                                        }
                                    }
                                ],
                                "width": "default",
                                "type": "default",
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "vertical_align": "top",
                        "weight": 1
                    }
                ],
                "margin": "0px 0px 0px 0px"
            })
            i += 1
        self.feishu_msg.send_one_card_msg(card_body=task_card)


    def add_help_harm_count(self, chat_id, open_id, id_type, mysql_id):
        if mysql_id not in self.help_harm_count:
            self.help_harm_count[mysql_id]={}
        if open_id not in self.help_harm_count[mysql_id]:
            self.help_harm_count[mysql_id][open_id] = {"helpful": 0, "harmful": 0}
        if id_type == "helpful" and self.help_harm_count[mysql_id][open_id]["helpful"] > 0:
            self.help_harm_count[mysql_id][open_id]["helpful"] += 1
            if self.help_harm_count[mysql_id][open_id]["helpful"] == 10:
                return "英雄所见略同"
            re_list = ["收到1个高质量👍，核心愉悦度+10%，能量满格!", "感谢您的认可!", "感谢你的反馈", "点赞已收到"]
            return random.choice(re_list)
        if id_type == "harmful" and self.help_harm_count[mysql_id][open_id]["harmful"] > 0:
            self.help_harm_count[mysql_id][open_id]["harmful"] += 1
            if self.help_harm_count[mysql_id][open_id]["harmful"] == 10:
                return "要被踩爆了"
            if self.help_harm_count[mysql_id][open_id]["harmful"] == 21:
                return "艹艹艹艹"
            re_list = ["很遗憾，给您带来不好的体验", "我们会努力改进", "我们会重视您的反馈"]
            return random.choice(re_list)

        this_sql = JamMySQL()
        already_item = this_sql.query(VIDOHistory, id=mysql_id)
        if not already_item:
            print("no item")
            return
        if id_type == "helpful":
            this_sql.update(VIDOHistory, where={"id": mysql_id}, helpful=already_item[0].helpful+1)
            self.help_harm_count[mysql_id][open_id]["helpful"] += 1
            return "感谢你的反馈"
        elif id_type == "harmful":
            this_sql.update(VIDOHistory, where={"id": mysql_id}, harmful=already_item[0].harmful+1)
            self.help_harm_count[mysql_id][open_id]["harmful"] += 1
            return "很遗憾，给您带来不好的体验"

    def create_node_card(self, node_name, node_id, children_nodes, json_file):
        """
        创建节点展示卡片
        
        Args:
            node_name: 节点名称
            node_id: 节点ID
            children_nodes: 子节点列表
            json_file: JSON文件路径
            
        Returns:
            dict: 卡片数据
        """
        card = {
            "schema": "2.0",
            "config": {
                "update_multi": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": node_name
                },
                "template": "blue"
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": []
            }
        }
        
        if not children_nodes:
            # 叶子节点，显示节点信息
            card["body"]["elements"].append({
                "tag": "markdown",
                "content": f"**{node_name}**\n\n这是最终节点",
                "text_align": "left"
            })
        else:
            # 有子节点，显示子节点列表
            card["body"]["elements"].append({
                "tag": "markdown",
                "content": f"**{node_name}**",
                "text_align": "left"
            })
            
            # 为每个子节点创建按钮
            for i, child in enumerate(children_nodes, 1):
                child_name = child.get("name", f"节点{i}")
                child_id = child.get("id", "")
                has_children = len(child.get("children", [])) > 0
                
                # 使用column_set来布局节点名称和按钮
                card["body"]["elements"].append({
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
                                        "content": f"{i}. {child_name}",
                                        "text_size": "normal_v2"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                }
                            ],
                            "vertical_align": "center",
                            "weight": 3
                        },
                        {
                            "tag": "column",
                            "width": "auto",
                            "elements": [
                                {
                                    "tag": "button",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "查看" if has_children else "详情"
                                    },
                                    "type": "primary",
                                    "width": "default",
                                    "size": "medium",
                                    "behaviors": [
                                        {
                                            "type": "callback",
                                            "value": {
                                                "type": "view_node",
                                                "node_id": child_id,
                                                "node_name": child_name,
                                                "json_file": json_file
                                            }
                                        }
                                    ],
                                    "margin": "0px 0px 0px 0px"
                                }
                            ],
                            "vertical_align": "center",
                            "weight": 1
                        }
                    ],
                    "margin": "8px 0px 8px 0px"
                })
        
        return card
    
    def create_multi_root_card(self, root_nodes_info):
        """
        创建包含多个根节点的卡片
        
        Args:
            root_nodes_info: 根节点信息列表，每个元素包含：
                - root_name: 根节点名称
                - root_id: 根节点ID
                - json_file: JSON文件路径
        
        Returns:
            dict: 卡片数据
        """
        card = {
            "schema": "2.0",
            "config": {
                "update_multi": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "问题排查支持"
                },
                "template": "blue"
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": []
            }
        }
        
        # 添加标题说明
        card["body"]["elements"].append({
            "tag": "markdown",
            "content": "**问题排查支持**\n\n请选择要查看的问题类型：",
            "text_align": "left"
        })
        
        # 为每个根节点创建按钮
        for i, root_info in enumerate(root_nodes_info, 1):
            root_name = root_info.get("root_name", f"根节点{i}")
            root_id = root_info.get("root_id", "")
            json_file = root_info.get("json_file", "")
            
            # 使用column_set来布局节点名称和按钮
            card["body"]["elements"].append({
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
                                    "content": f"{i}. {root_name}",
                                    "text_size": "normal_v2"
                                },
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "vertical_align": "center",
                        "weight": 3
                    },
                    {
                        "tag": "column",
                        "width": "auto",
                        "elements": [
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "查看"
                                },
                                "type": "primary",
                                "width": "default",
                                "size": "medium",
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "type": "view_node",
                                            "node_id": root_id,
                                            "node_name": root_name,
                                            "json_file": json_file
                                        }
                                    }
                                ],
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "vertical_align": "center",
                        "weight": 1
                    }
                ],
                "margin": "8px 0px 8px 0px"
            })
        
        return card
    
    def create_vas_method_card(self, tree_data, cycle_name=None, data_name=None):
        """
        创建VAS维测方法卡片
        
        Args:
            tree_data: VAS方法树数据
            cycle_name: 应用周期名称（可选，如果提供则显示该周期下的相关数据）
            data_name: 相关数据名称（可选，如果提供则显示该数据对应的维测方法）
            
        Returns:
            dict: 卡片数据
        """
        card = {
            "schema": "2.0",
            "config": {
                "update_multi": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": tree_data.get("name", "维持方法支持")
                },
                "template": "blue"
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": []
            }
        }
        
        # 如果指定了相关数据名称，显示该数据对应的维测方法
        if data_name and cycle_name:
            # 查找对应的周期和数据
            method_links = tree_data.get("method_links", {})
            for cycle in tree_data.get("children", []):
                if cycle.get("name") == cycle_name:
                    for data_item in cycle.get("children", []):
                        if data_item.get("name") == data_name:
                            methods = data_item.get("methods", [])
                            card["header"]["title"]["content"] = f"{data_name} - 维测方法"
                            card["body"]["elements"].append({
                                "tag": "markdown",
                                "content": f"**{data_name}**\n\n支持的维测方法：",
                                "text_align": "left"
                            })
                            
                            # 显示维测方法卡片（名称和链接）
                            for method in methods:
                                method_link = method_links.get(method, "")
                                if method_link:
                                    # 使用markdown格式显示链接
                                    card["body"]["elements"].append({
                                        "tag": "markdown",
                                        "content": f"• **{method}** [查看文档]({method_link})",
                                        "text_align": "left"
                                    })
                                else:
                                    # 如果没有链接，只显示名称
                                    card["body"]["elements"].append({
                                        "tag": "div",
                                        "text": {
                                            "tag": "plain_text",
                                            "content": f"• {method}",
                                            "text_size": "normal_v2"
                                        },
                                        "margin": "4px 0px 4px 0px"
                                    })
                            return card
        
        # 如果指定了周期名称，显示该周期下的相关数据
        if cycle_name:
            for cycle in tree_data.get("children", []):
                if cycle.get("name") == cycle_name:
                    card["header"]["title"]["content"] = f"{cycle_name} - 相关数据"
                    card["body"]["elements"].append({
                        "tag": "markdown",
                        "content": f"**{cycle_name}**\n\n相关数据列表：",
                        "text_align": "left"
                    })
                    
                    # 显示相关数据列表，每个数据可点击
                    for i, data_item in enumerate(cycle.get("children", []), 1):
                        data_name_item = data_item.get("name", "")
                        card["body"]["elements"].append({
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
                                                "content": f"{i}. {data_name_item}",
                                                "text_size": "normal_v2"
                                            },
                                            "margin": "0px 0px 0px 0px"
                                        }
                                    ],
                                    "vertical_align": "center",
                                    "weight": 3
                                },
                                {
                                    "tag": "column",
                                    "width": "auto",
                                    "elements": [
                                        {
                                            "tag": "button",
                                            "text": {
                                                "tag": "plain_text",
                                                "content": "查看方法"
                                            },
                                            "type": "primary",
                                            "width": "default",
                                            "size": "medium",
                                            "behaviors": [
                                                {
                                                    "type": "callback",
                                                    "value": {
                                                        "type": "view_vas_methods",
                                                        "cycle_name": cycle_name,
                                                        "data_name": data_name_item
                                                    }
                                                }
                                            ]
                                        }
                                    ],
                                    "vertical_align": "center",
                                    "weight": 1
                                }
                            ],
                            "margin": "8px 0px 8px 0px"
                        })
                    return card
        
        # 默认显示应用周期列表
        card["body"]["elements"].append({
            "tag": "markdown",
            "content": f"**{tree_data.get('name', '维持方法支持')}**\n\n请选择应用周期：",
            "text_align": "left"
        })
        
        # 显示应用周期卡片
        for i, cycle in enumerate(tree_data.get("children", []), 1):
            cycle_name_item = cycle.get("name", "")
            children_count = len(cycle.get("children", []))
            card["body"]["elements"].append({
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
                                    "content": f"{i}. {cycle_name_item} ({children_count}个相关数据)",
                                    "text_size": "normal_v2"
                                },
                                "margin": "0px 0px 0px 0px"
                            }
                        ],
                        "vertical_align": "center",
                        "weight": 3
                    },
                    {
                        "tag": "column",
                        "width": "auto",
                        "elements": [
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "查看"
                                },
                                "type": "primary",
                                "width": "default",
                                "size": "medium",
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "type": "view_vas_cycle",
                                            "cycle_name": cycle_name_item
                                        }
                                    }
                                ]
                            }
                        ],
                        "vertical_align": "center",
                        "weight": 1
                    }
                ],
                "margin": "8px 0px 8px 0px"
            })
        
        return card
    
    def send_f_reason(self, msg_id, data):
        # 生成失效原因
        # resDict = data["resDict"]
        resDict = json.loads(data["resDict"])
        analysisContext = json.loads(data["analysisContext"])
        imageAnalysisResultItem = data["imageAnalysisResultItem"]
        faultReportFaultModeRes = json.loads(data["faultReportFaultModeRes"])
        resDict["doc_sources"] = json.dumps(resDict["doc_sources"], ensure_ascii=False)
        resDict["kg_result"] = json.dumps(resDict["kg_result"], ensure_ascii=False)
        print(msg_id)
        print(resDict)
        print(analysisContext)
        print(imageAnalysisResultItem)
        print(faultReportFaultModeRes)
        resp3 = requests.post(
            f"{self.fmea_base_url}/kg-api/dfmea-fault-report/generate-fault-reason",
            headers={"Content-Type": "application/json"},
            data=json.dumps(
                {
                    "resDict": resDict,
                    "analysisContext": analysisContext,
                    "imageAnalysisResultItem": imageAnalysisResultItem,
                    "faultReportFaultModeRes": faultReportFaultModeRes,
                },
                ensure_ascii=False
            ),
        )
        if resp3.status_code != 200:
            print("generate-fault-reason failed", resp3.text)
            self.feishu_msg.reply_msg(msg_id, "生成失效原因失败，"+str(resp3.text), "text")    
            return
        r_c = ""
        for item in resp3.json()["data"]["faultReportFaultReasonRes"]:
            r_c += "\n- "+item["faultReason"]
        content = f"**失效类型:** {faultReportFaultModeRes[0].get('faultType', 'N/A')}\n**失效模式:** {faultReportFaultModeRes[0].get('faultMode', 'N/A')}\n**失效原因:** {r_c}"
        f_reason_card = {
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
                        "content": content,
                        "text_align": "left",
                        "text_size": "normal_v2",
                        "margin": "0px 0px 0px 0px"
                    }
                ]
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "失效原因"
                },
                "subtitle": {
                    "tag": "plain_text",
                    "content": ""
                },
                "template": "blue",
                "padding": "12px 12px 12px 12px"
            }
        }
        card_id = self.feishu_msg.create_card_ins(f_reason_card)
        self.feishu_msg.reply_msg(msg_id, json.dumps({"type":"card","data":{"card_id":card_id}}), "interactive")
    
    def handle_push_event(self,detail, msg_id, data, open_id):
        btn_type = data["type"]
        card_id = detail["card_id"]
        dep_name = detail["dep_name"]
        group_name = detail["group_name"]
        push_type = detail["push_type"]
        user_ids_str = detail["user_ids"]
        card_msg_id = detail["msg_id"]
        if btn_type == "push_status":
            retstr = f"消息ID：{msg_id}\n"
            try:
                ret = self.feishu_msg.batch_msg_progress(card_msg_id)
                ret1 = self.feishu_msg.batch_msg_info(card_msg_id)
                retstr+=f"推送总人数：{ret1['read_user']['total_count']}\n"
                retstr+=f"消息已读人数：{ret1['read_user']['read_count']}\n"
                if ret["batch_message_recall_progress"] and ret["batch_message_recall_progress"]["recall"]:
                    retstr+=f"消息已撤回：是\n"
                    retstr+=f"消息已撤回人数：{ret['batch_message_recall_progress']['recall_count']}\n"
                self.feishu_msg.reply_msg(msg_id, retstr, "text")    
            except Exception as e:
                print("batch_msg_progress failed", e)
                self.feishu_msg.reply_msg(msg_id, "查看消息状态失败"+str(e), "text")
                return
        elif btn_type == "push_recall":
            try:
                self.feishu_msg.batch_msg_recall(card_msg_id)
                self.feishu_msg.reply_msg(msg_id, f"撤回消息成功，消息ID: {msg_id}", "text")
            except Exception as e:
                print("batch_msg_recall failed", e)
                self.feishu_msg.reply_msg(msg_id, f"撤回消息失败，消息ID: {msg_id}"+str(e), "text")
                return
        else:
            department_ids = None
            if dep_name:
                department_ids = []
                true_dep_name = ""
                true_dep_number_num = 0
                try:
                    ret = self.feishu_msg.search_dep(dep_name)
                    if ret:
                        dep_id = ret[0]["department_id"]
                        department_ids.append(dep_id)
                        true_dep_name = ret[0]["name"]["default_value"]
                        true_dep_number_num = ret[0]["department_count"]["recursive_members_count"]
                        ret1 = self.feishu_msg.get_dep_child_list(dep_id)
                        for ite in ret1:
                            department_ids.append(ite["department_id"])
                    else:
                        self.feishu_msg.reply_msg(msg_id, f"查找部门：{dep_name} 失败"+str(e), "text")
                        return
                except Exception as e:
                    self.feishu_msg.reply_msg(msg_id, f"查找部门：{dep_name} 失败"+str(e), "text")
                    return
            open_ids = None
            user_ids = None
            if user_ids_str:
                user_ids = user_ids_str.replace("，",",").split(",")
            if group_name:  
                chat_id = None
                groups = self.feishu_msg.get_all_group_list()
                for one_group in groups:
                    if group_name == one_group["name"]:
                        chat_id = one_group["chat_id"]
                        break
                if chat_id:
                    open_ids = []
                    group_number = self.feishu_msg.get_group_members(chat_id)
                    for one_num in group_number:
                        open_ids.append(one_num["member_id"])
                else:
                    self.feishu_msg.reply_msg(msg_id, f"请先将此机器人加入到该群聊 {group_name} 中", "text")
                    return
            if btn_type == "push_view":
                msg_ret = self.feishu_msg.send_msg("open_id", open_id, "{\"type\":\"template\",\"data\":{\"template_id\":\""+card_id+"\"}}", "interactive")
                if push_type == "1":
                    review_text = "将发送此卡片消息到以下用户：\n"
                    if department_ids:
                        review_text += f"部门: {true_dep_name}, 人数: {true_dep_number_num}\n"
                    if user_ids:
                        review_text += f"用户: {user_ids_str}, 人数: {len(user_ids)}\n"
                    if open_ids:
                        review_text += f"群组: {group_name}, 人数: {len(open_ids)}\n"
                elif push_type == "2":
                    review_text = "将发送此卡片消息到以下群组：\n"
                    if open_ids:
                        review_text += f"群组: {group_name}\n"
                self.feishu_msg.reply_msg(msg_ret["message_id"], review_text, "text")
            elif btn_type == "push_push":
                if push_type == "2":
                    # 推送到群组
                    if group_name and chat_id:
                        self.feishu_msg.send_msg("chat_id", chat_id, "{\"type\":\"template\",\"data\":{\"template_id\":\""+card_id+"\"}}", "interactive")
                        self.feishu_msg.reply_msg(msg_id, f"已成功推送至该群聊 {group_name}", "text")
                elif push_type == "1":
                    # 推送到个人
                    card_ret = self.feishu_msg.batch_send_msg(content=None, card={"type":"template","data":{"template_id":card_id}}, msg_type="interactive", department_ids=department_ids, open_ids=open_ids, user_ids=user_ids)
                    print(card_ret)
                    self.feishu_msg.reply_msg(msg_id, f"已成功推送至个人, 推送信息ID为："+card_ret["message_id"], "text")
    def handle_card_callbak(self, data):
        print(data)
        # 处理VAS维测方法点击事件
        if data["event"]["action"]["tag"] == "button":
            action_value = data["event"]["action"].get("value", {})
            
            # 处理查看应用周期
            if action_value.get("type") == "view_vas_cycle":
                cycle_name = action_value.get("cycle_name")
                chat_id = data["event"]["context"].get("open_chat_id")
                open_id = data["event"]["operator"].get("open_id")
                
                try:
                    if self.vas_method_tree:
                        card = self.create_vas_method_card(self.vas_method_tree, cycle_name=cycle_name)
                        if chat_id:
                            self.feishu_msg.send_msg("chat_id", chat_id, card, "interactive")
                        elif open_id:
                            self.feishu_msg.send_msg("open_id", open_id, card, "interactive")
                        return f"已加载{cycle_name}的相关数据"
                    else:
                        return "VAS方法树数据未加载"
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    return f"加载周期数据失败：{str(e)}"
            
            # 处理查看相关数据对应的维测方法
            if action_value.get("type") == "view_vas_methods":
                cycle_name = action_value.get("cycle_name")
                data_name = action_value.get("data_name")
                chat_id = data["event"]["context"].get("open_chat_id")
                open_id = data["event"]["operator"].get("open_id")
                
                try:
                    if self.vas_method_tree:
                        card = self.create_vas_method_card(self.vas_method_tree, cycle_name=cycle_name, data_name=data_name)
                        if chat_id:
                            self.feishu_msg.send_msg("chat_id", chat_id, card, "interactive")
                        elif open_id:
                            self.feishu_msg.send_msg("open_id", open_id, card, "interactive")
                        return f"已加载{data_name}的维测方法"
                    else:
                        return "VAS方法树数据未加载"
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    return f"加载维测方法失败：{str(e)}"
            
            # 处理节点点击事件
            if action_value.get("type") == "view_node":
                node_id = action_value.get("node_id")
                node_name = action_value.get("node_name")
                json_file = action_value.get("json_file")
                chat_id = data["event"]["context"].get("open_chat_id")
                
                try:
                    # 获取节点的子节点
                    children = self.board_manager.get_node_children(node_id, json_file=json_file)
                    
                    # 创建新的节点卡片
                    card = self.create_node_card(node_name, node_id, children, json_file)
                    
                    # 更新卡片或发送新卡片
                    # 这里我们发送新卡片，用户可以看到历史路径
                    if chat_id:
                        self.feishu_msg.send_msg("chat_id", chat_id, card, "interactive")
                    else:
                        open_id = data["event"]["operator"].get("open_id")
                        if open_id:
                            self.feishu_msg.send_msg("open_id", open_id, card, "interactive")
                    
                    return "已加载子节点"
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    return f"加载节点失败：{str(e)}"
        
        if data["event"]["action"]["tag"] == "select_static":
            if data["event"]["action"]["value"]["type"] == "change_status":
                task_id = data["event"]["action"]["value"]["id"]
                chat_id = data["event"]["context"]["open_chat_id"]
                task_status = int(data["event"]["action"]["option"])-1
                this_task = self.jam_sql.query(Task, id=task_id)[0]
                if this_task.task_guid:
                    if task_status == 1:
                        self.feishu_msg.update_feishu_task(this_task.task_guid, completed_time=str(int(time.time()*1000)))
                    else:
                        self.feishu_msg.update_feishu_task(this_task.task_guid, completed_time="0")
                self.jam_sql.update(Task, where={"id": task_id}, done_time=datetime.strptime(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S"), status=task_status)
                # db = next(get_db())
                # task = db.query(Task).filter(Task.id == task_id).first()
                # task.done_time = datetime.strptime(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")
                # task.status = task_status
                # db.commit()
                # db.refresh(task)
        elif data["event"]["action"]["tag"] == "button":
            if data["event"]["action"]["value"]["type"] == "show_task":
                id_type = data["event"]["action"]["value"]["id"]
                chat_id = data["event"]["context"]["open_chat_id"]
                open_id = data["event"]["operator"]["open_id"]
                self.send_show_task(chat_id, open_id, id_type)
            elif data["event"]["action"]["value"]["type"] in ["helpful", "harmful"]:
                mysql_id = data["event"]["action"]["value"]["id"]
                id_type = data["event"]["action"]["value"]["type"]
                chat_id = data["event"]["context"]["open_chat_id"]
                open_id = data["event"]["operator"]["open_id"]
                return self.add_help_harm_count(chat_id, open_id, id_type, mysql_id)
            elif data["event"]["action"]["value"]["type"] in ["push_status", "push_view", "push_push", "push_recall"]:
                open_id = data["event"]["operator"]["open_id"]
                if open_id not in self.admin_list:
                    return "您不是管理员，不能执行此操作"
                if data["event"]["action"]["form_value"]["msg_id"] == "" and data["event"]["action"]["value"]["type"] in ["push_status", "push_recall"]:
                    return "推送消息的ID不能为空"
                if data["event"]["action"]["form_value"]["card_id"] == "" and data["event"]["action"]["value"]["type"] in ["push_view", "push_push"]:
                    return "卡片ID不能为空"
                if data["event"]["action"]["form_value"]["dep_name"] == "" and data["event"]["action"]["form_value"]["group_name"] == "" and data["event"]["action"]["form_value"]["user_ids"] == "" and data["event"]["action"]["value"]["type"] in ["push_view", "push_push"]:
                    return "需要指定消息接收人"
                threading.Thread(target=self.handle_push_event, args=(data["event"]["action"]["form_value"], data["event"]["context"]["open_message_id"], data["event"]["action"]["value"], open_id)).start()
            elif data["event"]["action"]["value"]["type"] == "failure_reason":
                threading.Thread(target=self.send_f_reason, args=(data["event"]["context"]["open_message_id"], data["event"]["action"]["value"])).start()
                return "失效原因生成中，请稍后3~5分钟"
            elif data["event"]["action"]["value"]["type"] == "failure_analysis":
                # 处理表单提交
                form_values = data["event"]["action"]["form_value"]
                # 获取表单字段值
                function_name = form_values.get("function_name", "")
                function_description = form_values.get("function_description", "")
                fusion_spectrum = form_values.get("fusion_spectrum", "")
                
                # 获取用户和聊天信息
                # chat_id = data["event"]["context"].get("open_chat_id")
                open_id = data["event"]["operator"].get("open_id")
                
                # 处理表单数据，可以保存到数据库或执行其他业务逻辑
                print(f"收到失效分析表单提交:")
                print(f"功能名称: {function_name}")
                print(f"功能描述: {function_description}")
                print(f"融合图谱: {fusion_spectrum}")
                self.fmea_req[open_id] = {"function_name": function_name, "function_description": function_description, "fusion_spectrum": fusion_spectrum}
                send_card = {
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
                                "content": "请回复该功能图片，参考如下图(仅接收图片格式)",
                                "text_align": "left",
                                "text_size": "normal_v2",
                                "margin": "0px 0px 0px 0px"
                            },
                            {
                                "tag": "img",
                                "img_key": "img_v3_02uq_b8bbae6b-a659-4565-97ce-4a9c543e125g",
                                "preview": True,
                                "transparent": False,
                                "scale_type": "fit_horizontal",
                                "margin": "0px 0px 0px 0px"
                            }
                        ]
                    }
                }
                card_id = self.feishu_msg.create_card_ins(send_card)
                self.feishu_msg.send_msg("open_id", open_id, json.dumps({"type":"card","data":{"card_id":card_id}}), "interactive")
                return "失效分析表单提交成功"
        elif data["event"]["action"]["tag"] == "picker_datetime":
            if data["event"]["action"]["value"]["type"] == "change_end_time":
                task_id = data["event"]["action"]["value"]["id"]
                end_time = data["event"]["action"]["option"]
                dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M %z')
                end_time = dt.strftime('%Y-%m-%d %H:%M:00')
                this_task = self.jam_sql.query(Task, id=task_id)[0]
                if this_task.task_guid:
                    self.feishu_msg.update_feishu_task(this_task.task_guid, end_time=str(int(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").timestamp()*1000)))
                self.jam_sql.update(Task, where={"id": task_id}, end_time=datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S"))
                # print(end_time)
                # db = next(get_db())
                # task = db.query(Task).filter(Task.id == task_id).first()
                # task.end_time = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
                # db.commit()
                # db.refresh(task)