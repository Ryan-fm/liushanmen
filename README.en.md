# Liushanmen

[简体中文](README.md) · **English**

A local-first intelligence monitoring agent. Define a topic in natural language, review a preview with sources, and confirm before starting scheduled checks. Task chat answers follow-ups using saved evidence and shared memory.

## Run locally

Requires Python 3.11+. The commands below use Python 3.11. The core uses the Python standard library and plain HTML, CSS, and JavaScript.

```sh
git clone https://github.com/Ryan-fm/liushanmen.git
cd liushanmen
python3.11 app.py
```

Open the [local workspace](http://127.0.0.1:8765/) and try “Track the latest F1 news.” Use `--empty` to skip demo data or `--db` to select a database. The service binds to loopback and stores data in `data/` by default.

## Technical architecture

| Layer | Implementation |
| --- | --- |
| Web and API | The [web interface](static/) calls a [Python HTTP server](app.py). Request `application/x-ndjson` from `POST /api/discover` to stream source status, sample records, and the final preview. |
| Intent and retrieval | [Search routing](intel/news.py) identifies the topic and queries Google News, Bing News, and relevant RSS/Atom feeds in parallel. Dedicated adapters read [official F1 results](intel/f1_results.py) and [daily Au99.99 quotes from the Shanghai Gold Exchange](intel/gold_quotes.py). |
| Monitoring and delivery | The [monitoring engine](intel/engine.py) evaluates lookback windows and thresholds for independent records and sources. Live checks persist evidence and events. The [daily inbox](intel/inbox.py) groups similar coverage and surfaces source failures. [Delivery](intel/delivery.py) handles macOS notifications and Markdown briefings. |
| Chat and memory | [Task chat](intel/task_chat.py) reads task evidence, recent conversation, and memory. It validates citation IDs in model answers, with a local evidence fallback. The app writes explicit memory commands directly. Shared memory carries across tasks, while task memory informs task-level retrieval and analysis. |
| Persistence | [SQLite storage](intel/store.py) tracks plans, evidence, events, runs, chat, memory, and the notification queue. Scheduled checks start after confirmation. Scheduling and delivery run inside the local service. |

### Agent workflow

1. Enter a goal and follow the retrieval progress. The preview includes original sources, matching interests, and failed reads.
2. Confirm a monitoring plan. Adjust the sources, check cadence, and thresholds, or run a trial first.
3. Review trends, evidence, and events in the task overview or ask follow-ups in Chat. Say “Remember: keep replies short” for a shared preference, or “Task memory: focus on driver changes” for a task-specific note.

## Model configuration

Copy the [configuration template](.env.example) to `.env` and choose one setup. Task chat reads the file on the next question. Environment variables inherited at startup take precedence.

- **Codex CLI** — Set `LSM_TASK_PROVIDER=codex` to use a local CLI signed in with ChatGPT. Set `LSM_TASK_CODEX_BIN` or `LSM_TASK_CODEX_MODEL` to select a binary or model. Inference goes to OpenAI through that login.
- **OpenAI-compatible API** — Set `LSM_TASK_LLM_ENDPOINT`, `LSM_TASK_LLM_MODEL`, and `LSM_TASK_LLM_KEY` if the provider requires it. Use the full Chat Completions URL. For the official OpenAI endpoint, `OPENAI_MODEL` and `OPENAI_API_KEY` also work.

External models receive the current question, recent conversation, relevant task material, and selected shared memories. Git ignores `.env` and local data.

## Development checks

```sh
python3.11 -m unittest discover -s tests -v
```

Tests cover source parsing, checks and briefings, task isolation, shared memory, and citation validation. The analysis modules draw on the separation of responsibilities in [BettaFish](https://github.com/666ghj/BettaFish).
