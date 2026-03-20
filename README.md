<h1 align="center">🚀 Feishu Bot</h1>

<p align="center">
  基于 <b>FastAPI + Feishu WebSocket/Event</b> 的自动化机器人服务
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Feishu-Bot-0052CC?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Status-Active-success?style=for-the-badge" />
</p>

---

## ✨ Features

- 🚀 支持飞书消息接入（`p2p` / `group`）
- 🧩 支持卡片回调动作处理
- ⚡ FastAPI 服务化部署（健康检查、可扩展 API）
- 🛡️ 内置超时保护与重试机制（避免任务长时间阻塞）
- 🧱 模块化目录结构（`agent` / `data_center`）

---

## 🗂️ Project Structure

```text
Feishu_Bot/
├── agent/                     # Agent 执行逻辑
├── data_center/               # 数据模型、任务配置、提醒逻辑
├── main.py                    # 服务入口（FastAPI + Feishu hook）
├── executor.py                # 执行器核心
├── requirements.txt           # Python 依赖
├── install_env.sh             # 环境安装脚本
└── feishu机器人开发流程与调用逻辑.md  # 项目详细设计文档
```

---

## ⚙️ Quick Start

### 1) Clone

```bash
git clone <your-repo-url>
cd Feishu_Bot
```

### 2) Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

可选（内部网络环境）：

```bash
bash install_env.sh
```

### 3) Configure environment

创建 `.env` 并配置飞书与业务侧所需密钥（示例）：

```bash
# Feishu
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret

# Optional: LLM / tracing / jira / etc.
OPENAI_API_KEY=your_key
LANGFUSE_SECRET_KEY=your_key
```

> 🔒 请勿将 `.env` 提交到 GitHub。

### 4) Run

```bash
python3 main.py
```

默认服务地址：`http://0.0.0.0:7999`

健康检查：

```bash
curl http://127.0.0.1:7999/health
```

---

## 📌 Runtime Notes

- 服务启动后会尝试建立飞书 WebSocket 连接；失败时会按策略重试。
- 消息处理包含超时保护（默认 300 秒），超时会自动回提示。
- 日志输出在 `logs/app.log`（带轮转）。

---

## 🧠 Development Tips

- 推荐先阅读：`feishu机器人开发流程与调用逻辑.md`
- 新增业务能力时，优先放到 `agent/` 与 `data_center/` 对应模块
- 建议补充测试和示例配置，方便团队协作

---

## 🛣️ Roadmap

- [ ] 增加 Docker 部署支持
- [ ] 增加配置模板（`.env.example`）
- [ ] 增加单元测试与接口测试
- [ ] 增加 CI（lint + test）

---

## 📄 License

如需开源，建议补充 `MIT`/`Apache-2.0` 许可证文件。