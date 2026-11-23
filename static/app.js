import { language, setLanguage, t, updateChrome } from "./i18n.js";

const page = document.querySelector("#page");
const dialog = document.querySelector("#overlay");
const taskNav = document.querySelector("#task-nav");
const toastEl = document.querySelector("#toast");

const TEMPLATES = {
  news: "帮我跟踪 F1 比赛的新闻",
  sports: "主场比赛期间监测「秋季杯」，重点盯入场、验票、交通与接驳。近 48 小时内至少 3 条相关反馈时调查。",
  game: "盯住游戏「远星纪行」新版本的玩家反馈，重点核实闪退、登录失败和存档问题。近 72 小时至少 3 条才提报。",
  brand: "跟踪新品「南岸随行杯」的用户投诉，关注商品质量和售后。近 48 小时至少 3 条独立反馈才发起调查。",
  business: "跟踪「智慧场馆」相关的招标，关注新项目、更正和延期。近 7 天有 1 条相关信息就核对。",
};
const scenarios = { sports: "体育赛事", game: "游戏版本", brand: "品牌口碑", business: "行业商机", general: "自定义" };
const kinds = { internal: "自有资料", public: "公开资料", media: "媒体文字稿" };
const statuses = { open: ["待核查", "r"], investigating: ["研判中", "a"], resolved: ["已处理", "g"] };
const stages = { alert: ["达到阈值", "r"], watch: ["观察中", "a"], quiet: ["无匹配", ""] };
const freshDraft = (intent = "", useModel = false) => ({ intent, useModel, selected: "", error: "" });
const freshAgent = (intent = "", useModel = false) => ({
  ...freshDraft(intent, useModel), proposal: null, preview: null, viewOnly: false, note: "", loading: false,
  sources: new Map(), searchHours: 0, summarizing: false, controller: null,
});
const state = { meta: { feeds: [] }, task: null, memories: [], memoryDrafts: new Map(),
  sequence: 0, agent: freshAgent(), homeDraft: freshDraft() };
let focusComposerOnLoad = false;
let toastTimer;

const escape = value => String(value ?? "").replace(/[&<>"']/g, char => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
));
const safeURL = value => {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
};
const stamp = value => value ? new Intl.DateTimeFormat(language() === "en" ? "en-US" : "zh-CN", {
  timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit",
  minute: "2-digit", hourCycle: "h23",
}).format(new Date(value)) : "—";
const joinTerms = values => values.join(language() === "en" ? ", " : "、");
const builtinNames = new Set(["Formula 1 官方", "Python 发布记录", "BettaFish 发布记录"]);
const sourceName = name => {
  if (name.startsWith("Google 新闻 · ")) return t("Google 新闻") + name.slice("Google 新闻".length);
  return builtinNames.has(name) ? t(name) : name;
};
const pill = (text, tone = "") => `<span class="pill ${escape(tone)}">${escape(text)}</span>`;
const statusPill = ([label, tone]) => pill(t(label), tone);
const button = (label, action, primary = false, attrs = "") =>
  `<button class="button ${primary ? "primary" : ""}" type="button" data-act="${action}" ${attrs}>${label}</button>`;
const section = (title, html, extra = "") => `
  <section class="section-block"><div class="section-heading"><h2>${title}</h2>${extra}</div>${html}</section>`;
const ICON_PATHS = {
  arrow: '<path d="M12 19V5m-6 6 6-6 6 6"/>',
  diagonal: '<path d="M6 18 18 6M8 6h10v10"/>',
  news: '<path d="M5 5h14v14H5zM8 9h8m-8 4h8m-8 3h4"/>',
  sports: '<path d="M8 4h8v4a4 4 0 0 1-8 0V4Zm0 2H4v2a4 4 0 0 0 4 4m8-6h4v2a4 4 0 0 1-4 4m-4 0v6m-4 2h8"/>',
  game: '<path d="M8 7h8a4 4 0 0 1 4 3l1 4a2.5 2.5 0 0 1-4 2.5L15 15H9l-2 1.5A2.5 2.5 0 0 1 3 14l1-4a4 4 0 0 1 4-3Zm0 3v4m-2-2h4m5-1h.01m3 2h.01"/>',
  brand: '<path d="M5 8h14l1 12H4L5 8Zm4 2V6a3 3 0 1 1 6 0v4"/>',
  business: '<path d="M5 19V5m0 14h14M8 15l4-4 3 2 4-6m-4 0h4v4"/>',
  signal: '<path d="M2 12h4l3-6 4 12 3-6h6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 8v4l2.5 1.5"/>',
  search: '<circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 4 4"/>',
  memory: '<rect x="5" y="4" width="14" height="16" rx="2"/><path d="M9 8h6m-6 4h6m-6 4h3"/>',
  inbox: '<path d="M4 5h16v13H4zM4 13h4l2 2h4l2-2h4"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
};
function icon(name) {
  return `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true">${ICON_PATHS[name]}</svg>`;
}
const empty = (message, action = "") => `<div class="empty"><p>${escape(message)}</p>${action}</div>`;
const hrefFor = (id, view = "summary", extra = "") => `#task/${encodeURIComponent(id)}/${view}${extra ? "/" + encodeURIComponent(extra) : ""}`;
const apiTask = id => "/api/tasks/" + encodeURIComponent(id);

async function api(path, body) {
  const config = { headers: { "Accept-Language": language() } };
  if (body !== undefined) {
    config.method = "POST";
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(body);
  }
  const response = await fetch(path, config);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || t("请求失败"));
  return value;
}

async function discover(payload, signal, onProgress) {
  const response = await fetch("/api/discover", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/x-ndjson", "Accept-Language": language() },
    body: JSON.stringify(payload), signal,
  });
  if (!response.ok || !response.headers.get("Content-Type")?.includes("application/x-ndjson")) {
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || t("请求失败"));
    return result;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) throw new Error(t("检索连接已中断，请重试"));
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const { type, data } = JSON.parse(line);
        if (type === "error") throw new Error(data.error);
        if (type === "result") return data;
        onProgress(type, data);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function toast(message) {
  window.clearTimeout(toastTimer);
  toastEl.textContent = message;
  toastEl.hidden = false;
  toastTimer = window.setTimeout(() => { toastEl.hidden = true; }, 4500);
}

function viewDialog(title, content) {
  dialog.innerHTML = `<header class="dialog-header"><h2 id="dialog-title">${escape(title)}</h2>
    <button class="icon-button" type="button" data-act="close" aria-label="${t("关闭")}">×</button></header>${content}`;
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
  dialog.querySelector("form textarea, form input, form select, summary")?.focus();
}

function parseRoute() {
  const parts = location.hash.slice(1).split("/");
  if (!parts[0] || parts[0] === "home") return { name: "home" };
  if (parts[0] === "task" && /^[a-f0-9]{12}$/.test(parts[1] || "")) {
    const tab = ["rules", "sources", "runs", "event"].includes(parts[2]) ? parts[2] : "summary";
    return { name: "task", id: parts[1], tab, extra: parts[3] || "" };
  }
  return { name: parts[0] === "events" ? "events" : "overview" };
}

function showLayout(route) {
  document.body.classList.toggle("home-route", route.name === "home");
}

function localizeWorkspace() {
  updateChrome();
  document.querySelector("#mode").textContent = state.meta.modelConfigured ? t("模型已配置") : t("本地规则模式");
}

async function refresh({ focus = false, editedRules = null } = {}) {
  const sequence = ++state.sequence;
  const route = parseRoute();
  showLayout(route);
  if (focus) {
    page.innerHTML = `<p class="loading">${t("正在读取…")}</p>`;
    window.scrollTo(0, 0);
    closeMenu();
  }
  try {
    const [{ tasks: allTasks }, task, evidence, insights, memories] = await Promise.all([
      api("/api/tasks"),
      route.name === "task" ? api(apiTask(route.id)) : Promise.resolve(null),
      route.tab === "sources" ? api(apiTask(route.id) + "/evidence") : Promise.resolve(null),
      route.tab === "summary" ? api(apiTask(route.id) + "/insights") : Promise.resolve(null),
      route.tab === "summary" ? api(apiTask(route.id) + "/memory") : Promise.resolve({ notes: [] }),
    ]);
    if (sequence !== state.sequence) return;
    const userTasks = allTasks.filter(item => !item.demo);
    const tasks = userTasks.length ? userTasks : allTasks;
    state.task = task;
    state.memories = memories.notes;
    let events = null;
    if (route.name === "events") {
      const details = await Promise.all(tasks.map(item => api(apiTask(item.id))));
      if (sequence !== state.sequence) return;
      events = details.flatMap(item => item.events.map(event => ({ ...event, task: item })));
      events.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    }
    nav(tasks, route, task?.plan.title);
    if (route.name === "home") renderHome(userTasks);
    else if (route.name === "overview") renderOverview();
    else if (route.name === "events") renderEvents(events);
    else renderTask(task, route, { evidence, editedRules, insights });
    if (route.name === "overview" && focusComposerOnLoad) {
      focusComposerOnLoad = false;
      document.querySelector("#agent-intent")?.focus();
    } else if (focus) {
      page.focus({ preventScroll: true });
    }
  } catch (error) {
    if (sequence === state.sequence) page.innerHTML = empty(error.message, `<a class="button" href="#overview">${t("回到工作台")}</a>`);
  }
}

function nav(tasks, route, taskTitle) {
  for (const link of document.querySelectorAll("[data-nav]")) {
    if (link.dataset.nav === route.name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const groups = [
    [t("监测任务"), tasks.filter(task => !task.demo)],
    [t("演示任务"), tasks.filter(task => task.demo)],
  ];
  taskNav.innerHTML = groups.map(([label, items]) => items.length ? `
    <div class="task-group"><div class="side-heading">${label}</div>
      ${items.map(task => `<a href="${hrefFor(task.id)}" ${route.id === task.id ? 'aria-current="page"' : ""}>
        <span class="task-icon ${task.active ? "active-task" : ""}" aria-hidden="true"></span>
        <span class="task-label" title="${escape(task.plan.title)}">${escape(task.plan.title)}</span>
      </a>`).join("")}
    </div>` : "").join("");
  document.querySelector("#crumb").textContent = route.name === "task"
    ? (taskTitle || t("监测任务"))
    : route.name === "events" ? t("事件中心") : t("Agent 工作台");
}

function renderOverview() {
  const agent = state.agent;
  const inProgress = agent.loading || agent.proposal || agent.sources.size;
  page.innerHTML = `<div class="agent-workspace ${inProgress ? "has-conversation" : ""}">
    ${inProgress ? renderConversation(agent) : renderComposer(agent)}
  </div>`;
}

function renderHome(tasks) {
  const recent = tasks.slice(0, 3);
  const accent = t("追踪");
  page.innerHTML = `<div class="home-workspace">
    <div class="home-backdrop" aria-hidden="true">
      <div class="radar-floor"><div class="radar-plane"></div></div>
      <div class="orbital-scene">
        <div class="orbital-volume">
          <i class="orbital-ring ring-horizontal"></i><i class="orbital-ring ring-vertical"></i><i class="orbital-ring ring-diagonal"></i>
          <div class="signal-cube"><i></i><i></i><i></i><i></i><i></i><i></i></div>
        </div>
      </div>
    </div>
    <div class="home-content">
      <div class="home-intro">
        <h1>${t("你想追踪什么？").replace(accent, `<span>${accent}</span>`)}</h1>
        <p>${t("说说你关心的事。六扇门会查找新闻、展示来源，或帮你起草监测方案。")}</p>
      </div>
      ${composerForm(state.homeDraft)}
      ${composerSuggestions(state.homeDraft)}
      ${recent.length ? `<section class="home-recent" aria-label="${t("最近任务")}">
        <h2>${t("最近任务")}</h2><ul>${recent.map(task => `<li><a href="${hrefFor(task.id)}">
          ${icon("signal")}<span>${escape(task.plan.title)}</span>${icon("diagonal")}</a></li>`).join("")}</ul>
      </section>` : ""}
    </div>
  </div>`;
}

function renderComposer(agent) {
  return `<div class="agent-launch"><header class="agent-intro">
      <div class="agent-signal" aria-hidden="true"><span class="signal-grid"></span><span class="signal-rings"></span>
        <span class="signal-sweep"></span><i></i><i></i><i></i></div>
      <div class="agent-emblem" aria-hidden="true">${mark()}</div>
      <h1>${t("你想持续关注什么？")}</h1>
      <p>${t("说说你关心的事。六扇门会查找相关新闻，或帮你起草监测方案。")}</p>
    </header>${composerForm(agent)}${composerSuggestions(agent)}</div>`;
}

function composerForm(draft) {
  return `<form class="composer" data-form="propose">
      <label class="sr-only" for="agent-intent">${t("描述监测需求")}</label>
      <textarea id="agent-intent" name="intent" maxlength="1000" rows="4" required
        placeholder="${t("例如，帮我跟踪 F1 比赛的新闻…")}">${escape(draft.intent)}</textarea>
      <div class="composer-toolbar">
        <div class="composer-context">
          <button class="example-prompt" type="button" data-act="template" data-template="news">${icon("news")}${t("试试 F1 新闻")}</button>
          ${state.meta.modelConfigured
            ? `<label class="checkbox"><input type="checkbox" name="useModel" ${draft.useModel ? "checked" : ""}>${t("用模型起草")}</label>`
            : ""}
        </div>
        <div class="composer-submit"><span class="composer-hint"><kbd>Enter</kbd> ${t("发送")}</span>
          <button class="button primary send" type="submit">${t("交给 Agent")} ${icon("arrow")}</button></div>
      </div>
      <p class="form-error composer-error" role="alert" ${draft.error ? "" : "hidden"}>${escape(draft.error)}</p>
    </form>`;
}

function composerSuggestions(draft) {
  const suggestions = [
    ["sports", t("赛场反馈"), t("盯入场、验票和接驳")],
    ["game", t("游戏发版"), t("找闪退、登录和存档问题")],
    ["brand", t("新品口碑"), t("跟踪商品质量与售后反馈")],
    ["business", t("行业动态"), t("跟踪新招标和公告变更")],
  ];
  return `<section class="suggestions" aria-label="${t("需求示例")}">
      <h2>${t("从一个场景开始")}</h2>
      <div class="suggestions-grid">${suggestions.map(([key, label, description]) => `
        <button class="suggestion ${draft.selected === key ? "suggestion-selected" : ""}" type="button" data-act="template" data-template="${key}">
          <span class="scene-icon scene-${key}">${icon(key)}</span>
          <span class="suggestion-copy"><strong>${label}</strong><small>${description}</small></span>
          <span class="suggestion-arrow">${icon("diagonal")}</span>
        </button>`).join("")}</div>
    </section>`;
}

function mark() {
  return '<span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></span>';
}

function renderConversation(agent) {
  const response = agent.loading ? "" : agent.preview ? renderNews(agent) : agent.proposal
    ? `<h1 tabindex="-1" class="reply-title">${t("监测方案已生成")}</h1>
      <p class="reply-copy">${t("检查关注对象和触发条件，保存后即可导入证据和试跑。")}</p>
      <div class="card plan-card">${ruleForm(agent.proposal, "", t("保存为任务"), "create", agent.intent, agent.note)}</div>`
    : `<h1 tabindex="-1" class="reply-title">${t("这次检索没有完成")}</h1>
      <p class="reply-copy" role="alert">${escape(agent.error)}</p>${button(t("返回需求"), "back-intent")}`;
  return `<section class="conversation" aria-label="${t("监测方案会话")}">
    <div class="user-turn"><p>${escape(agent.intent)}</p></div>
    <div class="agent-turn">
      <div class="agent-avatar">${mark()}</div>
      <div class="agent-reply">
        <div class="agent-name">${t("六扇门")}</div>
        <div id="agent-progress">${renderSearchProgress(agent)}</div>
        <p id="agent-announcement" class="sr-only" role="status"></p>
        ${response}
      </div>
    </div>
  </section>`;
}

function sourceStatus(source, loading) {
  if (source.status === "ok") return source.matched ? t("找到 {count} 条", {count: source.matched}) : t("没有符合范围的报道");
  if (source.status === "failed") return t("读取失败");
  return loading ? t("正在读取") : t("未完成");
}

function renderSource(source, loading) {
  const status = sourceStatus(source, loading);
  return `<li class="search-source" id="lookup-${escape(source.id)}">
    <div class="source-progress-row">
      <span class="source-progress-icon ${source.status === "ok" ? "source-done" : ""}">${icon(source.status === "ok" ? "check" : "news")}</span>
      <span class="source-progress-name">${escape(sourceName(source.source))}</span>
      <span class="source-progress-status ${source.status === "failed" ? "source-failed" : ""}">
        ${loading && source.status === "checking" ? '<span class="working-dot" aria-hidden="true"></span>' : ""}${status}</span>
    </div>
    ${source.status === "failed" ? `<p class="source-detail">${escape(source.note)}</p>` : ""}
    ${source.samples?.length ? `<ul class="source-samples" aria-label="${t("标题样例")}">${source.samples.map(item => {
      const link = safeURL(item.url);
      return `<li>${link ? `<a href="${escape(link)}" target="_blank" rel="noopener noreferrer">${escape(item.title)}${icon("diagonal")}</a>`
        : escape(item.title)}${item.source !== source.source ? ` <span class="sample-publisher">· ${escape(sourceName(item.source))}</span>` : ""}</li>`;
    }).join("")}</ul>` : ""}
  </li>`;
}

function progressCaption(agent) {
  const finished = [...agent.sources.values()].filter(source => source.status !== "checking").length;
  if (agent.summarizing && agent.loading) return t("正在整理新闻结果…");
  return agent.loading ? t("{finished} / {total} 个来源已返回", {finished, total: agent.sources.size})
    : t("{finished} 个来源已返回", {finished});
}

function renderSearchProgress(agent) {
  if (!agent.sources.size) {
    return agent.loading ? `<p class="working" role="status"><span class="working-dot" aria-hidden="true"></span>${t("正在理解你的需求…")}</p>` : "";
  }
  const hours = agent.searchHours;
  const scope = hours % 24 === 0 ? t("近 {count} 天", {count: hours / 24}) : t("近 {count} 小时", {count: hours});
  const header = `<span class="search-progress-title">${icon("search")}${agent.loading ? t("检索进度") : t("检索过程")}</span>
    <span class="progress-scope">${scope}</span><span class="progress-caption">${progressCaption(agent)}</span>`;
  const list = `<ul class="search-sources" aria-label="${t("查询来源")}">${[...agent.sources.values()]
    .map(source => renderSource(source, agent.loading)).join("")}</ul>`;
  return agent.loading
    ? `<section class="search-progress" aria-label="${t("新闻检索进度")}"><div class="search-progress-head">${header}</div>${list}</section>`
    : `<details class="search-progress" ${agent.error ? "open" : ""}><summary class="search-progress-head">${header}${icon("chevron")}</summary>${list}</details>`;
}

function updateSearchProgress(agent, type, data) {
  if (type === "checking_sources") {
    agent.searchHours = data.hours;
    for (const source of data.sources) agent.sources.set(source.id, { ...source, status: "checking" });
  } else if (type === "source_result") {
    agent.sources.set(data.id, data);
  } else if (type === "summarizing") {
    agent.summarizing = true;
  }

  if (state.agent !== agent || parseRoute().name !== "overview") return;
  const panel = document.querySelector("#agent-progress");
  if (!panel) return;
  const list = panel.querySelector(".search-sources");
  if (!list) {
    panel.innerHTML = renderSearchProgress(agent);
  } else if (type === "checking_sources") {
    for (const source of data.sources) {
      list.insertAdjacentHTML("beforeend", renderSource(agent.sources.get(source.id), true));
    }
  } else if (type === "source_result") {
    const row = document.getElementById(`lookup-${data.id}`);
    if (row) row.outerHTML = renderSource(data, true);
  }
  const caption = panel.querySelector(".progress-caption");
  if (caption) caption.textContent = progressCaption(agent);
  document.querySelector("#agent-announcement").textContent = type === "source_result"
    ? joinTerms([sourceName(data.source), sourceStatus(data, true)])
    : type === "checking_sources" ? t("正在查询 {sources}", {sources: joinTerms(data.sources.map(source => sourceName(source.source)))})
      : t("正在整理新闻结果");
}

function renderNews(agent) {
  const preview = agent.preview;
  const items = preview.items.map(item => {
    const link = safeURL(item.url);
    return `<li class="news-item">
      <div class="row news-meta"><span class="news-publisher">${escape(sourceName(item.source))}</span><time class="meta" datetime="${escape(item.published_at)}">
        ${item.published_missing ? t("首次发现") + " " : ""}${stamp(item.published_at)}
      </time></div>
      <h2>${link ? `<a href="${escape(link)}" target="_blank" rel="noopener noreferrer">${escape(item.title)}${icon("diagonal")}</a>` : escape(item.title)}</h2>
      ${item.summary ? `<p>${escape(item.summary)}</p>` : ""}
      ${item.via_news_search ? `<span class="meta">${t("通过 Google 新闻查看")}</span>` : ""}
    </li>`;
  });
  const sources = preview.sources.map(source => pill(sourceName(source.source) + (source.status === "ok" ? "" : " · " + t("读取失败")),
    source.status === "ok" ? "g" : "a")).join("");
  const count = preview.count;
  const shown = preview.items.length;
  const summary = count === 0 ? t("本轮没有查到可展示的报道，可以调整关键词后重试。")
    : count > shown ? t("本轮查到 {count} 条去重后的新闻，下方展示 {shown} 条。", {count, shown})
      : t("本轮查到 {count} 条去重后的新闻。", {count});
  return `<div class="news-heading"><h1 tabindex="-1" class="reply-title">${escape(t("{subject} 新闻", {subject: preview.label}))}</h1>
    <div class="row news-sources">${sources}<span class="news-time meta">${icon("clock")} ${t("查询时间")} ${stamp(preview.checked_at)}</span></div>
    <p class="reply-copy">${summary}</p></div>
    ${items.length ? `<ul class="card news-list" aria-label="${t("新闻预览")}">${items.slice(0, 4).join("")}</ul>` : ""}
    ${items.length > 4 ? `<details class="news-extra"><summary>${t("查看另外 {count} 条", {count: items.length - 4})}</summary>
      <ul class="card news-list" aria-label="${t("更多新闻")}">${items.slice(4).join("")}</ul></details>` : ""}
    ${agent.viewOnly
      ? `<div class="news-actions"><span class="meta">${t("未开启持续监测")}</span>${button(t("修改需求"), "back-intent")}${button(t("设置持续监测"), "review-news", true)}</div>`
      : `<div class="card plan-card subscribe-card"><div class="subscribe-heading">
        <span class="scene-icon">${icon("signal")}</span><h2 class="subscribe-title">${t("要持续跟踪这些新闻吗？")}</h2>${pill(t("尚未开启"))}</div>
        ${ruleForm(agent.proposal, "", t("确认并开启监测"), "create", agent.intent, agent.note)}</div>`}`;
}

function planPreview(plan) {
  const labels = plan.topics.map(topic => topic.label).filter(Boolean);
  return `<h2>${escape(plan.title || t("未命名任务"))}</h2>
    <dl class="plan-facts">
      <div><dt>${t("关注对象")}</dt><dd>${escape(joinTerms(plan.entities) || t("不限对象"))}</dd></div>
      <div><dt>${t("研判主题")}</dt><dd>${escape(joinTerms(labels) || t("待填写"))}</dd></div>
      <div><dt>${t("触发条件")}</dt><dd>${t("回看 {hours} 小时 · 至少 {minimum} 条记录、{channels} 个来源", plan)}</dd></div>
      ${state.agent.preview ? `<div class="plan-frequency"><dt>${t("检查频率")}</dt><dd>${t("每 {minutes} 分钟检查一次", {minutes: plan.cadence})}</dd></div>` : ""}
    </dl>`;
}

function openComposer(intent = "", useModel = false) {
  state.agent.controller?.abort();
  state.agent = freshAgent(intent, useModel);
  closeMenu();
  if (parseRoute().name !== "overview") {
    focusComposerOnLoad = true;
    location.hash = "#overview";
    return;
  }
  renderOverview();
  document.querySelector("#agent-intent")?.focus();
}

async function requestPlan(form) {
  const data = new FormData(form);
  const intent = String(data.get("intent") ?? "").trim();
  const useModel = data.get("useModel") === "on";
  if (!intent) {
    const message = form.querySelector(".composer-error");
    message.textContent = t("请先输入想追踪的内容。");
    message.hidden = false;
    form.elements.intent.focus();
    return;
  }
  state.agent.controller?.abort();
  const agent = freshAgent(intent, useModel);
  state.agent = agent;
  agent.controller = new AbortController();
  agent.loading = true;
  if (parseRoute().name === "home") location.hash = "#overview";
  else renderOverview();
  try {
    const { plan, note, preview } = await discover({ intent, useModel }, agent.controller.signal,
      (type, data) => updateSearchProgress(agent, type, data));
    agent.proposal = plan;
    agent.preview = preview || null;
    agent.note = note;
  } catch (error) {
    agent.error = error.message;
  } finally {
    agent.controller = null;
    agent.loading = false;
    if (state.agent === agent && parseRoute().name === "overview") {
      renderOverview();
      (document.querySelector(".reply-title") || document.querySelector("#agent-intent"))?.focus();
    }
  }
}

function eventRow(event) {
  return `<article class="card event-row"><a class="event-link" href="${hrefFor(event.task.id, "event", event.id)}">
    <div class="event-main"><h3>${escape(event.label)}</h3>
    <p>${escape(event.task.plan.title)} · ${t("{count} 条独立记录 · {sources} 个来源", {count: event.count, sources: event.sources.length})}${event.task.demo ? " · " + t("演示") : ""}</p>
    </div>${statusPill(statuses[event.status] || statuses.open)}${icon("diagonal")}</a></article>`;
}

function renderEvents(events) {
  const pending = events.filter(event => event.status !== "resolved");
  const resolved = events.filter(event => event.status === "resolved");
  page.innerHTML = `<div class="page-title"><div><h1>${t("事件中心")}</h1><p>${t("跨任务查看待核查事件和处理进展。")}</p></div></div>
    ${section(t("待处理"), pending.length ? pending.map(eventRow).join("") : empty(t("暂无待处理事件。")), `<span class="meta">${t("{count} 件", {count: pending.length})}</span>`)}
    ${section(t("已处理"), resolved.length ? resolved.map(eventRow).join("") : empty(t("暂无已处理事件。")), `<span class="meta">${t("{count} 件", {count: resolved.length})}</span>`)}`;
}

function renderTask(task, route, { evidence, editedRules, insights }) {
  const tab = route.tab;
  const activeTab = tab === "event" ? "summary" : tab;
  const tabs = { summary: t("研判概览"), rules: t("监测规则"), sources: t("证据库"), runs: t("运行记录") };
  const title = `<div class="page-title"><div>
    <div class="row">${pill(t(scenarios[task.plan.scenario] || "自定义"))}${task.demo ? pill(t("合成演示"), "a") : ""}
    ${pill(task.active ? t("监测中") : t("已暂停"), task.active ? "g" : "")}</div>
    <h1 class="task-title">${escape(task.plan.title)}</h1><p>${escape(task.plan.goal)}</p>
    </div><div class="row task-actions">
      ${button(task.active ? t("暂停") : t("启用方案"), "toggle-active", !task.active)}
      ${button(t("试跑规则"), "trial")}
      ${task.active ? button(t("立即检查"), "live", true) : ""}
    </div></div>`;
  const tabbar = `<nav class="tabs" aria-label="${t("任务视图")}">${Object.entries(tabs).map(([key, label]) =>
    `<a href="${hrefFor(task.id, key)}" ${key === activeTab ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</nav>`;
  let content;
  if (tab === "rules") content = ruleForm(editedRules || task.plan, t("修改方案"), t("保存规则"), "update", task.intent);
  else if (tab === "sources") content = sourcesTab(task, evidence);
  else if (tab === "runs") content = runsTab(task, route.extra);
  else if (tab === "event") {
    const event = task.events.find(item => item.id === route.extra);
    content = event ? eventDetail(event) : empty(t("找不到该事件。"), `<a class="button" href="${hrefFor(task.id)}">${t("返回任务")}</a>`);
  } else content = summaryTab(task, insights);
  page.innerHTML = title + tabbar + content;
}

function summaryTab(task, insights) {
  const last = task.runs[0];
  const latestCheck = insights.checks.at(-1);
  const events = task.events.map(event => ({ ...event, task }));
  return `<div class="overview-metrics" aria-label="${t("监测指标")}">
    ${metric("inbox", t("累计证据"), insights.evidence_count)}
    ${metric("signal", t("待处理事件"), events.filter(event => event.status !== "resolved").length)}
    ${metric("clock", t("最近正式检查"), latestCheck ? stamp(latestCheck.at) : "—", "metric-time")}
  </div>
  <div class="overview-grid"><div class="overview-data">
    ${checkChart(insights.checks)}
    ${sourceChart(task, insights)}
    ${section(t("已归档的事件"), events.length ? events.map(eventRow).join("") : empty(
      t("试跑可以预览触发结果。启用方案并正式检查后，符合规则的主题会在这里形成事件。"),
      `<a class="button" href="${hrefFor(task.id, "sources")}">${t("查看或导入证据")}</a>`))}
    ${last ? section(t("最近运行"), runCard(last, false),
      `<a href="${hrefFor(task.id, "runs", last.id)}">${t("查看运行记录")}</a>`) : ""}
    </div><aside class="overview-side">${memoryPanel(task)}
    <div class="card event-panel rules-panel"><div class="row rules-panel-title"><span class="scene-icon">${icon("signal")}</span><h3>${t("当前规则")}</h3></div>
      <p class="meta">${t("方案第 {revision} 版", {revision: task.revision})} · ${task.plan.generatedBy === "model" ? t("模型起草") : t("本地规则起草")}</p>
      <dl class="rule-facts">
        <div><dt>${t("观察窗口")}</dt><dd>${t("{hours} 小时", task.plan)}</dd></div>
        <div><dt>${t("触发条件")}</dt><dd>${t("至少 {minimum} 条记录、{channels} 个来源", task.plan)}</dd></div>
        <div><dt>${t("检查频率")}</dt><dd>${t("每 {minutes} 分钟", {minutes: task.plan.cadence})}</dd></div>
        ${task.active && task.next_at ? `<div><dt>${t("下次检查")}</dt><dd>${stamp(task.next_at)}</dd></div>` : ""}
      </dl>
      <div class="row rule-links"><a href="${hrefFor(task.id, "rules")}">${t("修改规则")}</a>
        <a href="${apiTask(task.id)}/report?lang=${language()}" download>${t("导出情报简报")}</a></div>
    </div></aside></div>`;
}

function metric(symbol, label, value, extra = "") {
  return `<div class="card overview-metric">
    <span class="scene-icon">${icon(symbol)}</span>
    <div><span class="meta">${label}</span><strong class="${extra}">${value}</strong></div>
  </div>`;
}

function checkChart(checks) {
  const title = t("检查趋势");
  const header = `<div class="chart-title"><h2>${title}</h2><p class="meta">${t("最近正式检查的输入记录数")}</p></div>`;
  if (!checks.length) return `<section class="card insight-chart">${header}<p class="chart-empty">${t("完成首次正式检查后，这里会显示记录数。")}</p></section>`;
  const max = Math.max(1, ...checks.map(check => check.count));
  const baseline = 110;
  const yFor = count => baseline - (count / max) * 94;
  const points = checks.map((check, index) => ({
    ...check, x: checks.length === 1 ? 234 : 39 + index * 392 / (checks.length - 1), y: yFor(check.count),
  }));
  const path = points.map(point => `${point.x},${point.y}`).join(" ");
  const ticks = [...new Set([max, Math.floor(max / 2), 0])];
  const values = points.map(point => `<li><time datetime="${escape(point.at)}">${stamp(point.at)}</time><strong>${point.count}</strong></li>`).join("");
  return `<section class="card insight-chart">${header}
    <svg class="check-chart" viewBox="0 0 448 120" role="img" aria-label="${title}">
      <defs><linearGradient id="check-chart-fill" x2="0" y2="1"><stop offset="0" stop-color="#8875ff" stop-opacity=".27"/>
        <stop offset="1" stop-color="#8875ff" stop-opacity=".03"/></linearGradient></defs>
      ${ticks.map(count => `<line x1="39" x2="431" y1="${yFor(count)}" y2="${yFor(count)}" />
        <text x="30" y="${yFor(count) + 4}" text-anchor="end">${count}</text>`).join("")}
      ${points.length > 1 ? `<polygon points="${points[0].x},${baseline} ${path} ${points.at(-1).x},${baseline}" fill="url(#check-chart-fill)"/>
        <polyline points="${path}" fill="none" />` : ""}
      ${points.map(point => `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${stamp(point.at)} · ${point.count}</title></circle>`).join("")}
    </svg>
    <div class="chart-dates"><span>${stamp(points[0].at)}</span>${points.length > 1 ? `<span>${stamp(points.at(-1).at)}</span>` : ""}</div>
    <details class="chart-values"><summary>${t("查看检查数值")}</summary><ul>${values}</ul></details>
  </section>`;
}

function sourceChart(task, { sources, evidence_count: total }) {
  const other = total - sources.reduce((sum, source) => sum + source.count, 0);
  const groups = other ? [...sources, { name: t("其他来源"), count: other }] : sources;
  return `<section class="card insight-chart">
    <div class="chart-title row spread"><h2>${t("来源分布")}</h2><a href="${hrefFor(task.id, "sources")}">${t("证据库")}</a></div>
    ${total ? `<p class="meta">${t("按已保存的证据记录统计")}</p><ul class="source-bars">
      ${groups.map(source => `<li><div><span>${escape(sourceName(source.name))}</span><strong>${source.count}</strong></div>
        <meter min="0" max="${total}" value="${source.count}" aria-label="${escape(sourceName(source.name))}"></meter></li>`).join("")}
      </ul>` : `<p class="chart-empty">${t("暂无已保存的证据。采集或导入后会显示各来源的数量。")}</p>`}
  </section>`;
}

function memoryPanel(task) {
  const notes = state.memories;
  const rows = notes.map(note => `<li class="memory-note">
    <time class="meta" datetime="${escape(note.updated_at)}">${stamp(note.updated_at)}</time>
    <p>${escape(note.text)}</p>
    <div class="row memory-actions">
      ${button(t("用这条记忆起草"), "memory-draft", false, `data-note="${escape(note.id)}"`)}
      ${button(t("编辑"), "memory-edit", false, `data-note="${escape(note.id)}"`)}
      ${button(t("删除"), "memory-remove", false, `data-note="${escape(note.id)}"`)}
    </div>
  </li>`);
  return `<section class="card memory-panel">
    <div class="row memory-panel-title"><span class="scene-icon">${icon("memory")}</span><h2>${t("Agent 记忆")}</h2>
      ${notes.length ? pill(t("{count} 条记忆", {count: notes.length})) : ""}</div>
    <p class="meta">${t("把想法和后续关注点留在这个任务里。")}</p>
    <form data-form="memory-add">
      <label class="sr-only" for="task-memory">${t("记下一个想法")}</label>
      <textarea id="task-memory" name="text" required maxlength="2000" rows="3"
        placeholder="${t("例如，关注：安全车、车手变动")}">${escape(state.memoryDrafts.get(task.id))}</textarea>
      ${formError}<div class="form-actions"><button type="submit" class="button primary">${t("记下来")}</button></div>
    </form>
    ${rows.length ? `<ul class="memory-notes">${rows.slice(0, 3).join("")}</ul>` : ""}
    ${rows.length > 3 ? `<details><summary>${t("查看其余 {count} 条记忆", {count: rows.length - 3})}</summary>
      <ul class="memory-notes">${rows.slice(3).join("")}</ul></details>` : ""}
    ${task.intent ? `<details class="memory-original"><summary>${t("原始需求")}</summary><p>${escape(task.intent)}</p></details>` : ""}
  </section>`;
}

function evidenceBlock(item, detailButton = true) {
  const link = safeURL(item.url);
  return `<div class="source">
    <div class="row">${pill(sourceName(item.source), "g")}${pill(t(kinds[item.kind] || "记录"))}
      <time class="meta" datetime="${escape(item.published_at)}">${item.published_missing ? t("首次发现") + " " : ""}${stamp(item.published_at)}</time>
      ${item.synthetic ? pill(t("演示"), "a") : ""}</div>
    ${item.title ? `<p><strong>${escape(item.title)}</strong></p>` : ""}
    <p>${escape(item.text)}</p>
    <div class="row meta">${item.entity ? `<span>${escape(item.entity)}</span>` : ""}
      ${item.reference ? `<span>${escape(t("编号 {reference}", {reference: item.reference}))}</span>` : ""}
      ${link ? `<a href="${escape(link)}" target="_blank" rel="noopener noreferrer">${t("打开来源")}</a>` : ""}
      ${detailButton ? button(t("查看完整记录"), "evidence", false, `data-evidence="${escape(item.id)}"`) : ""}
    </div></div>`;
}

function eventDetail(event) {
  return `<div class="detail-layout">
    <div>
      <div class="card event-panel section-block">
        <div class="row spread"><h2>${escape(event.label)}</h2>${statusPill(statuses[event.status])}</div>
        <p>${escape(event.explanation)}</p>
        <p class="meta">${t("{count} 条独立记录 · 去重前 {raw} 条", {count: event.count, raw: event.raw_count})}</p>
        ${event.entities.length ? `<div class="row topic-chips">${event.entities.map(item => pill(item.name + " · " + item.count)).join("")}</div>` : ""}
      </div>
      ${section(t("证据"), `<div class="card">${event.evidence_archived ? `<p class="notice">${t("以下是先前保存的历史证据。")}</p>` : ""}
      ${event.evidence.length ? event.evidence.map(item => evidenceBlock(item)).join("") : `<p>${t("当前没有可展示的证据。")}</p>`}</div>`)}
    </div>
    <aside>
      <div class="card event-panel"><h3>${t("建议下一步")}</h3>
        <p class="meta">${t("建议负责人")} · ${escape(event.owner)}</p><p>${escape(event.action)}</p>
        ${event.model ? `<div class="notice"><strong>${t("模型建议")}</strong><p>${escape(event.model.summary)}</p>
          <p>${escape(event.model.next_check)}</p><div class="row">${event.model.ids.map((id, i) =>
            button(t("引用 {number}", {number: i + 1}), "evidence", false, `data-evidence="${escape(id)}"`)).join("")}</div></div>` : ""}
        ${followup(event.followup)}
        <div class="form-actions">
          ${event.status === "open" ? button(t("开始研判"), "event-status", true, `data-event="${event.id}" data-status="investigating"`) : ""}
          ${event.status === "resolved" ? button(t("重新打开"), "event-status", false, `data-event="${event.id}" data-status="open"`)
            : button(t("标记已处理"), "event-status", false, `data-event="${event.id}" data-status="resolved"`)}
        </div>
      </div>
      <div class="card event-panel"><h3>${t("处置进展")}</h3>
        <ol class="history">${[...event.history].reverse().map(item =>
          `<li><time datetime="${escape(item.at)}">${stamp(item.at)}</time>${escape(item.text)}</li>`).join("")}</ol>
      </div>
    </aside>
  </div>`;
}

function followup(item) {
  if (!item) return "";
  return `<details><summary>${escape(item.title)}</summary><p>${escape(item.note)}</p></details>`;
}

function sourcesTab(task, evidence) {
  const base = `<div class="card event-panel section-block"><div class="row spread"><h2>${t("数据来源")}</h2>${button(t("＋ 导入证据"), "import", true)}</div>
    <p class="meta">${t("CSV 或 JSON。媒体文字稿和视频字幕可以按文本导入。")}</p>
    <div class="row topic-chips">${task.plan.feeds.map(id => pill(sourceName(state.meta.feeds.find(feed => feed.id === id)?.name || id), "g")).join("")}
      ${task.plan.news_query ? pill(t("公开新闻") + " · " + task.plan.news_query, "g") : ""}
      ${task.plan.feeds.length || task.plan.news_query ? "" : pill(t("未启用 RSS"))}
      <a href="${hrefFor(task.id, "rules")}">${t("配置 RSS")}</a></div></div>`;
  if (!evidence) return base;
  return base + section(t("已保存的来源记录"), evidence.items.length ? `<div class="card">
    ${evidence.items.map(item => evidenceBlock({ ...item, text: item.text.slice(0, 400) })).join("")}</div>`
    : empty(t("还没有导入或采集到证据。"), button(t("导入证据"), "import", true)),
    `<span class="meta">${t("共 {count} 条", {count: evidence.count})}${evidence.count > evidence.items.length ? t("，显示最近 150 条") : ""}</span>`);
}

function runsTab(task, selected) {
  return section(t("运行记录"), task.runs.length ? task.runs.map(run => runCard(run, run.id === selected)).join("") :
    empty(t("还没有运行记录。"), button(t("试跑规则"), "trial", true)));
}

function runCard(run, expanded) {
  const result = run.result;
  const windowText = t("观察窗口 {from} 至 {to} · {total} 条输入 · {alerts} 个触发 · {observations} 个观察中",
    {...result, from: stamp(result.window.from), to: stamp(result.window.to)});
  return `<article class="card run-card">
    <div class="row spread"><h3>${run.mode === "trial" ? t("试跑") : t("正式检查")} · ${stamp(run.created_at)}</h3>
      <span class="meta">${t("规则第 {revision} 版", {revision: result.revision})}</span></div>
    <p class="meta">${windowText}</p>
    <details ${expanded ? "open" : ""}><summary>${t("查看研判与来源状态")}</summary>
      ${result.sources.length ? `<div class="topic-chips row">${result.sources.map(source =>
        pill(sourceName(source.source) + " · " + source.note, source.status === "failed" ? "r" : "g")).join("")}</div>` : ""}
      ${result.candidates.map(candidate => `<div class="source">
        <div class="row"><strong>${escape(candidate.label)}</strong>${statusPill(stages[candidate.stage])}</div>
        <p>${escape(candidate.explanation)}</p>${followup(candidate.followup)}
        ${candidate.evidence.length ? `<details><summary>${t("查看代表性证据")}</summary>
          ${candidate.evidence.map(item => evidenceBlock(item)).join("")}</details>` : ""}
      </div>`).join("")}
      <details><summary>${t("各模块执行情况")}</summary><ul class="trace">${result.trace.map(item =>
        `<li>${escape(item.title)} · ${escape(item.note)}</li>`).join("")}</ul></details>
    </details>
  </article>`;
}

const input = (name, label, value, attrs = "", full = false) => `<label class="field ${full ? "full" : ""}">${label}
    <input name="${name}" value="${escape(value)}" ${attrs}></label>`;
const textArea = (name, label, value, extra = "") => `<label class="field full">${label}
    <textarea name="${name}" ${extra}>${escape(value)}</textarea></label>`;
const formError = '<p class="form-error" role="alert"></p>';

function topicForm(topic = {}) {
  return `<fieldset class="topic"><legend>${t("研判主题")}</legend><div class="form-grid">
    ${input("label", t("主题名称"), topic.label, 'required maxlength="48"')}
    ${input("owner", t("建议负责人"), topic.owner, 'maxlength="64"')}
    ${input("terms", t("关键词（逗号分隔）"), topic.terms?.join("，"), `required placeholder="${t("例如：排队，验票，闸机")}"`, true)}
    ${input("action", t("优先核查动作"), topic.action, 'maxlength="260"', true)}
    </div><div class="form-actions">${button(t("删除主题"), "remove-topic")}</div></fieldset>`;
}

function ruleForm(plan, title, submit, type, intent = "", note = "") {
  const draft = type === "create";
  const html = `<form data-form="${type}" data-scenario="${escape(plan.scenario)}" data-origin="${escape(plan.generatedBy)}" data-locale="${escape(plan.locale || "zh-CN")}">
    ${draft ? `<input name="intent" type="hidden" value="${escape(intent)}"><div class="plan-preview">${planPreview(plan)}</div>`
      : `<div class="section-heading"><h2>${title}</h2></div>`}
    ${note ? `<p class="notice warn">${escape(note)}</p>` : ""}
    ${draft ? `<details class="draft-editor"><summary>${t("编辑方案和数据来源")}</summary><div class="draft-fields">` : ""}
    <div class="form-grid">
      ${input("title", t("任务名称"), plan.title, 'required maxlength="64"', true)}
      ${textArea("goal", t("目标"), plan.goal, 'required maxlength="1000"')}
      ${input("entities", t("对象筛选词（逗号分隔，留空表示不限）"), plan.entities.join("，"), "", true)}
      ${input("minimum", t("至少几条独立记录"), plan.minimum, 'type="number" min="1" max="1000" required')}
      ${input("channels", t("至少几个不同来源"), plan.channels, 'type="number" min="1" max="12" required')}
      ${input("hours", t("观察窗口（小时）"), plan.hours, 'type="number" min="1" max="2160" required')}
      ${input("cadence", t("检查间隔（分钟）"), plan.cadence, 'type="number" min="5" max="10080" required')}
    </div>
    <fieldset><legend>${t("RSS / Atom 来源")}</legend><div class="row">
      ${state.meta.feeds.map(feed => `<label class="checkbox"><input type="checkbox" name="feed" value="${escape(feed.id)}"
        ${plan.feeds.includes(feed.id) ? "checked" : ""}>${escape(sourceName(feed.name))}</label>`).join("") || `<p class="help">${t("当前没有配置 RSS。")}</p>`}
    </div><p class="help">${t("每个任务也可独立导入自有证据。")}</p></fieldset>
    ${plan.news_query || (draft && state.agent.preview) ? `
      ${input("news_query", t("补充公开新闻搜索词（选填）"), plan.news_query || "", 'maxlength="120"', true)}
      <p class="help">${t("填写后会使用 Google 新闻 RSS 定期查询该词。")}</p>` : ""}
    <div class="topics">${plan.topics.map(topicForm).join("")}</div>
    ${button(t("＋ 添加主题"), "append-topic")}
    ${draft ? "</div></details>" : ""}
    ${formError}
    <div class="form-actions">
      ${draft ? button(t("修改需求"), "back-intent") : ""}
      ${draft && state.agent.preview ? button(t("仅看本次"), "view-only") : ""}
      <button class="button primary" type="submit">${submit}</button>
    </div>
  </form>`;
  return type === "update" ? '<div class="card">' + html + "</div>" : html;
}

function makePlan(form) {
  const data = new FormData(form);
  const split = text => String(text ?? "").split(/[，,、\n]+/).map(word => word.trim()).filter(Boolean);
  return {
    title: data.get("title"), goal: data.get("goal"), scenario: form.dataset.scenario,
    generatedBy: form.dataset.origin, locale: form.dataset.locale, entities: split(data.get("entities")),
    minimum: Number(data.get("minimum")), channels: Number(data.get("channels")),
    hours: Number(data.get("hours")), cadence: Number(data.get("cadence")),
    feeds: data.getAll("feed"),
    news_query: data.get("news_query") || "",
    topics: [...form.querySelectorAll(".topic")].map(item => ({
      label: item.querySelector('[name="label"]').value, terms: split(item.querySelector('[name="terms"]').value),
      owner: item.querySelector('[name="owner"]').value, action: item.querySelector('[name="action"]').value,
    })),
  };
}

function openRun(mode) {
  const name = mode === "trial" ? t("试跑监测规则") : t("立即检查");
  viewDialog(name, `<form data-form="run" data-mode="${mode}">
    <p class="notice">${mode === "trial" ? t("试跑只生成运行记录。可以用已保存证据回放历史时间。") : t("读取已配置的来源，并将符合条件的结果同步到事件中心。")}</p>
    ${mode === "trial" ? input("asOf", t("历史截止时间（北京时间，可留空）"), "", 'type="datetime-local"', true) : ""}
    ${state.meta.modelConfigured ? `<label class="checkbox topic-chips"><input type="checkbox" name="useModel">${t("将候选证据发送给配置的模型，生成补充研判")}</label>` : ""}
    ${formError}<div class="form-actions"><button class="button primary" type="submit">${mode === "trial" ? t("开始试跑") : t("开始检查")}</button></div>
  </form>`);
}

function openImport() {
  viewDialog(t("导入证据"), `<form data-form="import">
    <p class="notice">${t("必填列为 text 和 published_at。可选 source、kind、title、entity、reference、external_id 和 url。")}</p>
    <div class="form-grid">${input("source", t("默认来源名称"), t("文件导入"), 'required maxlength="100"')}
      <label class="field">${t("默认来源类型")}<select name="kind">${Object.entries(kinds).map(([key, label]) =>
        `<option value="${key}">${t(label)}</option>`).join("")}</select></label>
      <label class="field full">${t("选择 CSV 或 JSON 文件")}<input name="file" type="file" accept=".csv,.json,text/csv,application/json"></label>
      ${textArea("pasted", t("也可粘贴 CSV 或 JSON"), "", 'placeholder="text,published_at,source"')}
    </div>${formError}<div class="form-actions"><button class="button primary" type="submit">${t("导入")}</button></div>
  </form>`);
}

async function openMemoryAction(element) {
  const note = state.memories.find(item => item.id === element.dataset.note);
  if (!note) return;
  const action = element.dataset.act;
  const task = state.task;
  if (action === "memory-edit") {
    viewDialog(t("编辑记忆"), `<form data-form="memory-edit" data-note="${escape(note.id)}">
      ${textArea("text", t("记忆内容"), note.text, 'required maxlength="2000"')}
      ${formError}<div class="form-actions"><button type="submit" class="button primary">${t("保存")}</button></div></form>`);
  } else if (action === "memory-remove") {
    viewDialog(t("删除这条记忆？"), `<form data-form="memory-remove" data-note="${escape(note.id)}">
      <p class="memory-quote">${escape(note.text)}</p>
      ${formError}<div class="form-actions">${button(t("取消"), "close")}
        <button type="submit" class="button primary">${t("删除")}</button></div></form>`);
  } else {
    element.disabled = true;
    try {
      const { plan, revision } = await api(apiTask(task.id) + "/memory/" + encodeURIComponent(note.id) + "/draft", {});
      if (parseRoute().id !== task.id) return;
      viewDialog(t("由记忆生成的规则草案"), ruleForm(plan, t("核对并编辑规则"), t("保存规则"), "update", task.intent,
        t("已把这条记忆提炼成关注词。检查关键词后再保存规则。")));
      dialog.querySelector('[data-form="update"]').dataset.revision = revision;
    } catch (error) {
      toast(error.message);
    } finally {
      element.disabled = false;
    }
  }
}

function readRecords(content) {
  const text = content.replace(/^\uFEFF/, "").trim();
  if (!text) throw new Error(t("请选择文件或粘贴记录"));
  if (text.startsWith("[") || text.startsWith("{")) {
    const value = JSON.parse(text);
    const records = Array.isArray(value) ? value : value?.records;
    if (!Array.isArray(records)) throw new Error(t("JSON 须为记录数组，或含 records 数组的对象"));
    return records;
  }
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i <= text.length; i++) {
    const char = text[i] || "\n";
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { field += '"'; i++; }
      else if (quoted || field === "") quoted = !quoted;
      else field += char;
    } else if (!quoted && (char === "," || char === "\r" || char === "\n")) {
      row.push(field);
      field = "";
      if (char === ",") continue;
      if (char === "\r" && text[i + 1] === "\n") i++;
      if (row.some(cell => cell.trim())) rows.push(row);
      row = [];
    } else field += char;
  }
  if (quoted) throw new Error(t("CSV 引号没有闭合"));
  const headers = rows.shift()?.map(item => item.trim()) || [];
  if (!headers.includes("text") || !headers.some(key => ["published_at", "timestamp"].includes(key))) {
    throw new Error(t("CSV 表头须包含 text 和 published_at"));
  }
  if (new Set(headers).size !== headers.length) throw new Error(t("CSV 表头包含重复列名"));
  return rows.map((cells, index) => {
    if (cells.length !== headers.length) throw new Error(t("CSV 第 {row} 行列数不匹配", {row: index + 2}));
    return Object.fromEntries(headers.map((key, i) => [key, cells[i]]));
  });
}

async function submitForm(form) {
  const action = form.dataset.form;
  const data = new FormData(form);
  const task = state.task;
  if (action === "create") {
    const agent = state.agent;
    const news = agent.preview;
    const plan = makePlan(form);
    const created = news
      ? await api("/api/news/confirm", { preview_id: news.id, plan })
      : await api("/api/tasks", { intent: data.get("intent"), plan });
    const message = news ? t("持续监测已开启，本轮新闻已保存到证据库。") : t("已创建监测任务，可导入证据后试跑。");
    if (state.agent === agent) {
      state.agent = freshAgent();
      if (parseRoute().name === "overview") {
        location.hash = hrefFor(created.id, "sources");
        toast(message);
        return;
      }
    }
    await refresh();
    toast(message);
  } else if (action === "update") {
    const payload = { plan: makePlan(form) };
    if (form.dataset.revision) payload.revision = Number(form.dataset.revision);
    await api(apiTask(task.id) + "/rules", payload);
    if (dialog.contains(form)) dialog.close();
    await refresh();
    toast(t("规则已保存。"));
  } else if (["memory-add", "memory-edit", "memory-remove"].includes(action)) {
    const path = apiTask(task.id) + "/memory";
    const text = data.get("text");
    if (action === "memory-add") {
      await api(path, { text });
      if (state.memoryDrafts.get(task.id) === text) state.memoryDrafts.delete(task.id);
    } else {
      const notePath = path + "/" + encodeURIComponent(form.dataset.note);
      if (action === "memory-edit") await api(notePath, { text });
      else await api(notePath + "/remove", {});
      dialog.close();
    }
    if (parseRoute().id === task.id) await refresh();
    toast(action === "memory-remove" ? t("记忆已删除。") : t("记忆已保存。"));
  } else if (action === "run") {
    const history = data.get("asOf");
    const run = await api(apiTask(task.id) + "/run", {
      mode: form.dataset.mode, asOf: history ? history + ":00+08:00" : null,
      useModel: data.get("useModel") === "on",
    });
    dialog.close();
    location.hash = hrefFor(task.id, "runs", run.id);
    toast(run.mode === "trial" ? t("试跑完成。") : t("正式检查完成。"));
  } else if (action === "import") {
    const file = data.get("file");
    if (file?.size > 6 * 1024 * 1024) throw new Error(t("文件不得超过 6 MB"));
    const records = readRecords(file?.size ? await file.text() : data.get("pasted"));
    const { added, duplicates } = await api(apiTask(task.id) + "/import", {
      source: data.get("source"), kind: data.get("kind"), records,
    });
    dialog.close();
    await refresh();
    toast(t("导入 {added} 条，跳过 {duplicates} 条重复记录。", {added, duplicates}));
  } else if (action === "status") {
    await api(apiTask(task.id) + "/events/" + form.dataset.event + "/status", {
      status: form.dataset.status, note: data.get("note"),
    });
    dialog.close();
    await refresh();
    toast(t("处置进展已保存。"));
  }
}

function closeMenu() {
  document.body.classList.remove("menu-open");
  document.querySelector(".mobile-toggle").setAttribute("aria-expanded", "false");
}

function syncDraft(form) {
  if (form?.dataset.form !== "create" || !state.agent.proposal) return;
  state.agent.proposal = makePlan(form);
  form.querySelector(".plan-preview").innerHTML = planPreview(state.agent.proposal);
}

function composerDraft() {
  return parseRoute().name === "home" ? state.homeDraft : state.agent;
}

document.addEventListener("input", event => {
  if (event.target.id === "task-memory" && state.task) {
    state.memoryDrafts.set(state.task.id, event.target.value);
  }
  if (event.target.id === "agent-intent") {
    const draft = composerDraft();
    draft.intent = event.target.value;
    const message = event.target.form.querySelector(".composer-error");
    message.hidden = true;
    draft.error = "";
  }
  syncDraft(event.target.form);
});

document.addEventListener("change", async event => {
  if (event.target.matches(".language-select")) {
    const hash = location.hash;
    const editor = page.querySelector('form[data-form="update"]');
    const editedRules = editor ? makePlan(editor) : null;
    const expanded = [...page.querySelectorAll("details")].map(detail => detail.open);
    setLanguage(event.target.value);
    localizeWorkspace();
    await refresh({ editedRules });
    if (location.hash === hash) {
      page.querySelectorAll("details").forEach((detail, index) => {
        if (expanded[index]) detail.open = true;
      });
    }
    return;
  }
  if (event.target.name === "useModel" && event.target.form?.dataset.form === "propose") {
    composerDraft().useModel = event.target.checked;
  }
  syncDraft(event.target.form);
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.body.classList.contains("menu-open")) {
    closeMenu();
    document.querySelector(".mobile-toggle").focus();
  }
  if (event.target.id === "agent-intent" && event.key === "Enter" && !event.shiftKey &&
      !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    event.target.form.requestSubmit();
  }
});

document.addEventListener("invalid", event => {
  const editor = event.target.closest(".draft-editor");
  if (editor) editor.open = true;
}, true);

document.addEventListener("submit", async event => {
  const form = event.target.closest("[data-form]");
  if (!form) return;
  event.preventDefault();
  if (form.dataset.form === "propose") {
    await requestPlan(form);
    return;
  }
  const submit = form.querySelector('button[type="submit"]');
  const error = form.querySelector(".form-error");
  if (submit.disabled) return;
  submit.disabled = true;
  const original = submit.textContent;
  submit.textContent = t("处理中…");
  error.textContent = "";
  try { await submitForm(form); }
  catch (exception) {
    error.textContent = exception.message;
    const editor = form.querySelector(".draft-editor");
    if (editor) editor.open = true;
  }
  finally { submit.disabled = false; submit.textContent = original; }
});

document.addEventListener("click", async event => {
  const element = event.target.closest("[data-act]");
  if (!element || element.disabled) return;
  const action = element.dataset.act;
  const form = element.closest("form");
  if (action === "create") openComposer();
  if (action === "close") dialog.close();
  if (action === "menu") element.setAttribute("aria-expanded", String(document.body.classList.toggle("menu-open")));
  if (action === "close-menu") closeMenu();
  if (action === "back-intent") openComposer(state.agent.intent, state.agent.useModel);
  if ((action === "view-only" || action === "review-news") && state.agent.preview) {
    state.agent.viewOnly = action === "view-only";
    renderOverview();
    document.querySelector(".reply-title")?.focus({ preventScroll: true });
  }
  if (action === "template") {
    const intent = document.querySelector("#agent-intent");
    if (!intent) return;
    composerDraft().selected = element.dataset.template;
    for (const suggestion of document.querySelectorAll(".suggestion")) {
      suggestion.classList.toggle("suggestion-selected", suggestion === element);
    }
    intent.value = t(TEMPLATES[element.dataset.template]);
    intent.dispatchEvent(new Event("input", { bubbles: true }));
    intent.focus();
  }
  if (action === "append-topic") {
    const container = form.querySelector(".topics");
    if (container.children.length < 12) container.insertAdjacentHTML("beforeend", topicForm());
    else toast(t("每个方案最多 12 个主题。"));
    syncDraft(form);
  }
  if (action === "remove-topic") {
    if (form.querySelectorAll(".topic").length === 1) toast(t("方案至少需要一个主题。"));
    else element.closest(".topic").remove();
    syncDraft(form);
  }
  if (action === "trial" || action === "live") openRun(action);
  if (action === "import") openImport();
  if (["memory-draft", "memory-edit", "memory-remove"].includes(action)) await openMemoryAction(element);
  if (action === "event-status") {
    const [label] = statuses[element.dataset.status];
    viewDialog(t(label), `<form data-form="status" data-event="${escape(element.dataset.event)}" data-status="${escape(element.dataset.status)}">
      ${textArea("note", t("记一条处理进展"), "", `required maxlength="1000" placeholder="${t("已做了什么，或准备核实什么？")}"`)}
      ${formError}<div class="form-actions"><button type="submit" class="button primary">${t("保存")}</button></div></form>`);
  }
  if (action === "toggle-active" || action === "evidence") {
    element.disabled = true;
    const task = state.task;
    try {
      if (action === "toggle-active") {
        const next = !task.active;
        await api(apiTask(task.id) + "/active", { active: next });
        await refresh();
        toast(next ? t("已启用，后台会自动检查。也可以立即检查。") : t("已暂停自动检查。"));
      } else {
        const item = await api(apiTask(task.id) + "/evidence/" + encodeURIComponent(element.dataset.evidence));
        viewDialog(t("原始证据"), evidenceBlock(item, false));
      }
    } catch (error) { toast(error.message); }
    finally { element.disabled = false; }
  }
});

document.querySelector(".skip-link").addEventListener("click", event => {
  event.preventDefault();
  page.focus();
});

window.addEventListener("hashchange", () => refresh({ focus: true }));
showLayout(parseRoute());
localizeWorkspace();
try {
  state.meta = await api("/api/meta");
  localizeWorkspace();
  await refresh();
} catch (error) {
  page.innerHTML = empty(error.message, `<a class="button" href="/">${t("重试")}</a>`);
}
