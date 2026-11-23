# 六扇门

**简体中文** · [English](README.en.md)

本地优先的情报监测 Agent。用自然语言定义关注主题，先查看带来源的检索预览，再确认是否启用持续监测。任务 Chat 可以结合已保存证据与跨任务记忆回答追问。

## 本地运行

需要 Python 3.11+，以下命令使用 Python 3.11。核心服务仅使用 Python 标准库，前端为原生 HTML、CSS 和 JavaScript。

```sh
git clone https://github.com/Ryan-fm/liushanmen.git
cd liushanmen
python3.11 app.py
```

打开 [本地工作台](http://127.0.0.1:8765/)，试试「帮我跟踪 F1 比赛的新闻」。可用 `--empty` 跳过演示数据，或用 `--db` 指定数据库路径。默认数据目录为 `data/`，服务监听本机回环地址。

## 技术架构

| 层 | 实现 |
| --- | --- |
| Web 与 API | [原生 Web 界面](static/)调用 [Python HTTP 服务](app.py)。`POST /api/discover` 接受 `application/x-ndjson` 响应格式，逐步返回信源状态、样本和最终预览。 |
| 意图与采集 | [检索路由](intel/news.py)识别查询主题，按主题并行读取 Google 新闻、Bing 新闻和 RSS/Atom 订阅。专项适配器读取 [F1 官方赛果](intel/f1_results.py)及[上海黄金交易所 Au99.99 日行情](intel/gold_quotes.py)。 |
| 监测与交付 | [监测引擎](intel/engine.py)按照观察窗口、独立记录数与来源数研判。正式检查保存证据和事件，[今日情报](intel/inbox.py)归并相似报道并展示信源故障，[交付模块](intel/delivery.py)处理 macOS 桌面提醒与 Markdown 日报。 |
| Chat 与记忆 | [任务 Chat](intel/task_chat.py)读取当前任务的证据、历史对话和记忆。模型回复会校验引用 ID，模型不可用时回到本地证据。显式记忆指令由应用直接写入。全局记忆跨任务共享，任务记忆参与本任务的检索和研判。 |
| 持久化 | [SQLite 存储](intel/store.py)维护方案、证据、事件、运行记录、对话、记忆和通知队列。用户确认后才启用持续监测，调度和提醒随本地服务运行。 |

### Agent 工作流

1. 输入目标并查看检索过程。预览中可以核对新闻原文、命中的关注词及读取失败的信源。
2. 确认监测方案。可按主题调整来源、检查频率和阈值，并先试跑查看触发结果。
3. 在任务概览中查看趋势、证据与事件，或用 Chat 追问。全局偏好可以说「记住：回复尽量简短」，任务专属笔记可以说「任务记忆：关注车手变动」。

## 模型配置

把 [配置模板](.env.example) 复制到 `.env` 并选一组配置。任务 Chat 会在下一次提问时读取文件，启动时继承的环境变量优先。

- **Codex CLI** — 使用已通过 ChatGPT 登录的本机 CLI。设置 `LSM_TASK_PROVIDER=codex`，可用 `LSM_TASK_CODEX_BIN` 或 `LSM_TASK_CODEX_MODEL` 指定路径和模型。推理通过该登录连接 OpenAI。
- **OpenAI 兼容接口** — 设置 `LSM_TASK_LLM_ENDPOINT`、`LSM_TASK_LLM_MODEL` 和接口要求的 `LSM_TASK_LLM_KEY`。Endpoint 使用完整的 Chat Completions 路径。OpenAI 官方接口也可用 `OPENAI_MODEL` 和 `OPENAI_API_KEY`。

使用外部模型时，问答会发送当前问题、近期对话、相关任务资料和部分全局记忆。`.env` 与本地数据目录由 Git 忽略。

## 开发验证

```sh
python3.11 -m unittest discover -s tests -v
```

测试覆盖信源解析、监测和简报、任务范围隔离、跨任务记忆及引用校验。情报研判的职责拆分参考了 [BettaFish](https://github.com/666ghj/BettaFish)。
