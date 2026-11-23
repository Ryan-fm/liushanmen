# Liushanmen

[简体中文](README.md) · **English**

A local intelligence agent. Describe what you want to track, watch sources return in real time, and decide whether to keep monitoring.

## Quick start

Requires Python 3.11 or later. The app runs on the standard library.

```sh
git clone https://github.com/Ryan-fm/liushanmen.git
cd liushanmen
python3 app.py
```

Open the [local workspace](http://127.0.0.1:8765/) and try “Track the latest F1 news.” Switch between English and Chinese in the top-right corner.

## Features

- **Live search** shows sources, headlines, and article links from RSS / Atom feeds and Google News.
- **Custom monitoring** lets you set keywords, thresholds, and check intervals. Review the preview and confirm to start scheduled checks.
- **Event review** supports CSV / JSON imports, trial runs, evidence review, and Markdown briefings.

## Architecture

- The [web interface](static/) uses plain HTML, CSS, and JavaScript to display streamed search progress.
- The [Python service](app.py) provides the API and scheduler. The [analysis modules](intel/) handle source retrieval, deduplication, and rule matching.
- SQLite stores tasks, evidence, and events. Scheduled monitoring runs while the local service is active.

The analysis modules draw on the separation of responsibilities in [BettaFish](https://github.com/666ghj/BettaFish).
