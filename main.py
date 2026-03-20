from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn
import json
import asyncio
import threading
import logging
import time
import socket
import requests
from data_center.task import init_task
from contextlib import asynccontextmanager
import executor
import os
from logging.handlers import RotatingFileHandler
import concurrent.futures

# Configure logging - 同时输出到文件和控制台
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

# 创建logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建formatter
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# 文件handler（带轮转，最大10MB，保留5个备份）
file_handler = RotatingFileHandler(
    log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# 控制台handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# 添加handlers
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 避免重复日志
logger.propagate = False


# 创建FastAPI应用实例
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # Startup
    await init_task()
    # Initialize database, cache, etc.
    yield
    # Shutdown


app = FastAPI(title="Magic VIDO API", version="1.0.0", lifespan=app_lifespan)

# 数据存储（在实际应用中应该使用数据库）


# 请求模型定义
class AddDataRequest(BaseModel):
    data: str


class SearchDataRequest(BaseModel):
    question: str


class SearchDataResponse(BaseModel):
    result: str


# 健康检查端点
@app.get("/health")
async def health_check():
    """
    健康检查接口
    """
    return {"status": "healthy", "message": "API服务运行正常"}


this_executor = executor.Executor()
TIMEOUT_SECONDS = 300  # 5分钟


def msg_recv(json_data):

    def run_with_timeout(func, timeout, timeout_callback, *args):
        """
        带超时执行器
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args)
            try:
                future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                logger.error("任务执行超时")
                try:
                    timeout_callback()
                except Exception as e:
                    logger.error(f"超时回调失败: {e}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.error(f"任务执行异常: {e}")

    # ================= P2P =================
    if json_data["event"]["message"]["chat_type"] == "p2p":

        user = json_data["event"]["sender"]["sender_id"]["open_id"]

        # if json_data["event"]["message"]["message_type"] != "text":
        #     return

        mentions_info = json_data["event"]["message"].get("mentions", [])
        message_id = json_data["event"]["message"]["message_id"]

        print(user)

        # ⭐ 超时回调
        def p2p_timeout_callback():
            try:
                this_executor.feishu_msg.send_text(user, "⚠️ 处理超时，请重新运行")
            except Exception as e:
                logger.error(f"发送超时提示失败: {e}")

        thread = threading.Thread(
            target=run_with_timeout,
            args=(
                this_executor.back_send_msg,
                TIMEOUT_SECONDS,
                p2p_timeout_callback,
                user,
                message_id,
                json_data,
                mentions_info,
            ),
        )
        thread.start()

    # ================= GROUP =================
    elif json_data["event"]["message"]["chat_type"] == "group":

        chat_id = json_data["event"]["message"]["chat_id"]

        def group_timeout_callback():
            try:
                this_executor.feishu_msg.send_text(chat_id, "⚠️ 处理超时，请重新运行")
            except Exception as e:
                logger.error(f"群超时提示失败: {e}")

        thread = threading.Thread(
            target=run_with_timeout,
            args=(
                this_executor.back_reply_msg,
                TIMEOUT_SECONDS,
                group_timeout_callback,
                json_data,
            ),
        )
        thread.start()

    else:
        print("unknow chat_type", json_data)


def cb_card_action(json_data):
    try:
        ret = this_executor.handle_card_callbak(json_data)
        if not ret:
            ret = "操作成功"
        resp = {"toast": {"type": "info", "content": ret}}
    except:
        resp = {"toast": {"type": "error", "content": "操作失败"}}
    return resp


def cb_chat_member_bot_added(data):
    chat_id = data["event"]["chat_id"]
    # this_executor.create_and_pin_card(chat_id)
    this_executor.hello_func(chat_id)


def check_network_connectivity():
    """检查网络连接"""
    logger.info("检查网络连接...")
    try:
        # 检查能否访问飞书 API
        response = requests.get("https://open.feishu.cn", timeout=5)
        logger.info(f"✓ 可以访问飞书服务 (状态码: {response.status_code})")
        return True
    except requests.exceptions.Timeout:
        logger.warning("✗ 连接飞书服务超时")
        return False
    except requests.exceptions.ConnectionError:
        logger.warning("✗ 无法连接到飞书服务，请检查网络连接")
        return False
    except Exception as e:
        logger.warning(f"✗ 网络检查失败: {e}")
        return False


def start_feishu_websocket():
    """启动飞书 websocket 连接，带重试机制"""
    import os

    # 保存原始代理设置
    original_proxy_vars = {
        "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
        "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
        "http_proxy": os.environ.get("http_proxy"),
        "https_proxy": os.environ.get("https_proxy"),
        "NO_PROXY": os.environ.get("NO_PROXY"),
        "no_proxy": os.environ.get("no_proxy"),
    }

    # 设置 NO_PROXY 让飞书域名绕过代理（websocket 连接需要直连）
    no_proxy_list = ["open.feishu.cn", "*.feishu.cn", "*.larksuite.com", "localhost"]
    if original_proxy_vars.get("NO_PROXY"):
        no_proxy_list.extend(original_proxy_vars["NO_PROXY"].split(","))
    os.environ["NO_PROXY"] = ",".join(no_proxy_list)
    os.environ["no_proxy"] = ",".join(no_proxy_list)

    logger.info(f"已设置 NO_PROXY: {os.environ['NO_PROXY']}")

    # 先检查网络连接
    if not check_network_connectivity():
        logger.warning("网络连接检查失败，但将继续尝试连接...")

    max_retries = 5
    retry_delay = 10  # 秒

    for attempt in range(max_retries):
        try:
            logger.info(
                f"尝试连接飞书 websocket (第 {attempt + 1}/{max_retries} 次)..."
            )
            this_executor.feishu_msg.msg_hook(
                cb_msg_recv=msg_recv,
                cb_card_action=cb_card_action,
                cb_chat_member_bot_added=cb_chat_member_bot_added,
            )
            logger.info("飞书 websocket 连接成功")
            break
        except Exception as e:
            logger.error(
                f"飞书 websocket 连接失败 (尝试 {attempt + 1}/{max_retries}): {e}"
            )
            if attempt < max_retries - 1:
                logger.info(f"等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                logger.error(
                    "飞书 websocket 连接失败，已达到最大重试次数。应用将继续运行，但无法接收飞书消息。"
                )
                logger.error("请检查：")
                logger.error("1. 网络连接是否正常")
                logger.error("2. 防火墙是否阻止 websocket 连接")
                logger.error("3. 飞书 app_id 和 app_secret 是否正确")
                logger.error("4. 飞书服务是否可用")
                logger.error("5. 代理服务器是否支持 websocket 连接")
        finally:
            # 恢复原始代理设置（如果需要）
            pass


if __name__ == "__main__":
    # 在后台线程启动飞书 websocket，失败不影响主应用
    feishu_thread = threading.Thread(target=start_feishu_websocket, daemon=True)
    feishu_thread.start()

    # 给一点时间让 websocket 连接尝试开始
    time.sleep(1)

    logger.info("启动 FastAPI 服务器...")
    uvicorn.run(app="main:app", host="0.0.0.0", port=7999, reload=False)
