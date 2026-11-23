# 六扇门

**简体中文** · [English](README.en.md)

一个本地情报 Agent。用一句话指定关注对象，实时查看检索进度和来源，再决定是否持续监测。

## 快速开始

需要 Python 3.11 或更新版本，使用标准库即可运行。

```sh
git clone https://github.com/Ryan-fm/liushanmen.git
cd liushanmen
python3 app.py
```

打开 [本地工作台](http://127.0.0.1:8765/)，试试「帮我跟踪 F1 比赛的新闻」。右上角可切换中英文。

## 主要功能

- **实时检索**并行查询 Google 新闻和 Bing 新闻，并为 F1、NBA、足球等主题匹配专属订阅。
- **今日情报收件箱**汇总当日进展，合并相似报道，并显示来源读取失败和恢复情况。
- **提醒与简报**支持 macOS 桌面提醒和本地 Markdown 日报。可在收件箱设置，后台服务运行时生效。
- **自定义监测**可调整关键词、阈值和检查频率。看完预览并确认后才会开启持续监测。
- **任务图表与记忆**展示趋势和来源，自动优先展示命中关注点的新闻和证据。也可从记忆起草规则，保存后生效。
- **事件研判**支持导入 CSV / JSON、试跑规则、查看证据和导出 Markdown 简报。

## 架构

- [Web 界面](static/)使用原生 HTML、CSS 和 JavaScript，接收流式检索进度。
- [Python 服务](app.py)负责 API 和调度，[研判模块](intel/)负责检索、去重和规则匹配。
- SQLite 保存任务、证据和事件。应用在本地运行，后台监测随服务运行。

研判模块的职责拆分参考了 [BettaFish](https://github.com/666ghj/BettaFish)。
