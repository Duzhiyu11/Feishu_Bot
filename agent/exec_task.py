from magic_jam import JamLLM
from .mcp import mcp
from .task import *
import copy
jam_llm = JamLLM(mcp_url=mcp.mcp)
def exec_task(task: str, **kwargs):
    """执行任务"""
    try:
        this_task = eval(task)
    except Exception as e:
        raise Exception(f"没有找到该任务：{task}")
    e_kwargs = {k:v for k,v in this_task.__dict__.items() if not k.startswith("__")}
    if hasattr(this_task, "agent"):
        llm_kwargs = {k:v for k,v in this_task.agent.__dict__.items() if not k.startswith("__")}
    else:
        llm_kwargs = copy.deepcopy(e_kwargs)
    llm_kwargs.pop("prompt")
    for k,v in llm_kwargs.items():
        e_kwargs[k] = v
    for iitem in ["agent", "temperature", "top_p", "tools", "prompt", "response_format", "base_url", "api_key", "model_name", "n", "size", "type", "thinking"]:
        if iitem in e_kwargs:
            e_kwargs.pop(iitem)
    if kwargs.get("stream") == True:
        llm_kwargs["stream"] = True
        kwargs.pop("stream")
    for k,v in kwargs.items():
        e_kwargs[k] = v
    history_conversation = []
    if kwargs.get("history_conversation") and isinstance(kwargs["history_conversation"], list):
        history_conversation = kwargs["history_conversation"]
        kwargs.pop("history_conversation")
    agent_tools = []
    if hasattr(this_task, "agent"):
        # 确保所有必需的参数都存在，如果不存在则使用默认值
        try:
            sys_prompt = this_task.agent.prompt.format(**e_kwargs)
        except KeyError as e:
            # 如果缺少参数，尝试使用空字符串作为默认值
            missing_key = str(e).strip("'")
            e_kwargs[missing_key] = ""
            sys_prompt = this_task.agent.prompt.format(**e_kwargs)
        if hasattr(this_task.agent, "tools"):
            agent_tools = this_task.agent.tools
    else:
        sys_prompt = ""
    # 确保所有必需的参数都存在，如果不存在则使用默认值
    try:
        user_prompt = this_task.prompt.format(**e_kwargs)
    except KeyError as e:
        # 如果缺少参数，尝试使用空字符串作为默认值
        missing_key = str(e).strip("'")
        e_kwargs[missing_key] = ""
        user_prompt = this_task.prompt.format(**e_kwargs)
    if hasattr(this_task, "tools"):
        llm_kwargs.pop("tools")
        agent_tools = this_task.tools
    
    function_definitions = None
    if agent_tools:
        function_definitions = jam_llm.get_function_definitions_sync(apply_tools=agent_tools)
    req_msg = []
    if hasattr(this_task, "agent"):
        req_msg += [{"role": "system", "content": sys_prompt}]
    if history_conversation:
        req_msg += history_conversation + [{"role": "user", "content": user_prompt}]
    else:
        req_msg += [{"role": "user", "content": user_prompt}]
    llm_response = jam_llm.invoke(req_msg, function_definitions=function_definitions, **llm_kwargs)
    return {"response": llm_response, "sys_prompt": sys_prompt, "user_prompt": user_prompt, **e_kwargs, **llm_kwargs}
    
# def exec_task(task: str, **kwargs):
#     """执行任务"""
#     try:
#         this_task = eval(task)
#     except Exception as e:
#         raise Exception(f"没有找到该任务：{task}")
#     llm_kwargs = {k:v for k,v in this_task.agent.__dict__.items() if not k.startswith("__")}
#     if kwargs.get("stream") == True:
#         llm_kwargs["stream"] = True
#     llm_kwargs.pop("prompt")
#     sys_prompt = this_task.agent.prompt.format(current_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), **kwargs)
#     user_prompt = this_task.prompt.format(**kwargs)
#     agent_tools = []
#     if hasattr(this_task.agent, "tools"):
#         agent_tools = this_task.agent.tools
#     if hasattr(this_task, "tools"):
#         llm_kwargs.pop("tools")
#         agent_tools = this_task.tools
    
#     function_definitions = None
#     if agent_tools:
#         function_definitions = jam_llm.get_function_definitions_sync(apply_tools=agent_tools)
#     llm_response = jam_llm.invoke([{"role": "system", "content": sys_prompt},{"role": "user", "content": user_prompt}], function_definitions=function_definitions, **llm_kwargs)
#     return llm_response
    