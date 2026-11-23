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
const freshAgent = (intent = "", useModel = false, monitoring = false) => ({
  ...freshDraft(intent, useModel), proposal: null, preview: null, answer: null, officialLookup: false,
  viewOnly: false, note: "", loading: false, monitoring, newsScope: null, goldQuoteLookup: false,
  sources: new Map(), searchHours: 0, memoryFocus: [], summarizing: false, controller: null,
});
const state = { meta: { feeds: [] }, task: null, dashboard: null, memories: [], memoryDrafts: new Map(), chatDrafts: new Map(),
  workspaceMemory: [], chatRequests: new Map(), sequence: 0, agent: freshAgent(), homeDraft: freshDraft() };
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
const builtinNames = new Set([
  "Formula 1 官方", "Python 发布记录", "BettaFish 发布记录", "BBC Sport · 足球", "ESPN · 足球", "OpenAI 官方",
  "Hugging Face 博客", "BBC 科技", "美联储公告", "香港电台 · 财经", "香港电台 · 体育", "香港电台 · 大中华",
  "arXiv · AI 预印本", "NASA 官方", "上海黄金交易所 · Au99.99",
]);
const newsProviderNames = { google: "Google 新闻", bing: "Bing 新闻" };
const sourceName = name => {
  const provider = Object.values(newsProviderNames).find(label => name.startsWith(label + " · "));
  if (provider) return t(provider) + name.slice(provider.length);
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
  bell: '<path d="M18 8a6 6 0 0 0-12 0v5l-2 3h16l-2-3V8Zm-8 11a2 2 0 0 0 4 0"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  chat: '<path d="M6 4h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-6l-5 3v-3H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/><path d="M8 9h8m-8 4h5"/>',
  link: '<path d="m10 13 4-4m-6 1 3-3a3.5 3.5 0 0 1 5 5l-3 3m-1-5-3 3a3.5 3.5 0 0 0 5 5l3-3"/>',
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
    const tab = ["chat", "rules", "sources", "runs", "event"].includes(parts[2]) ? parts[2] : "summary";
    return { name: "task", id: parts[1], tab, extra: parts[3] || "" };
  }
  return { name: ["events", "inbox"].includes(parts[0]) ? parts[0] : "overview" };
}

function showLayout(route) {
  document.body.classList.toggle("home-route", route.name === "home");
  document.body.classList.toggle("task-chat-route", route.tab === "chat");
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
    const [{ tasks: allTasks }, task, evidence, insights, memories, inbox, delivery, chat, dashboard, workspaceMemory] = await Promise.all([
      api("/api/tasks"),
      route.name === "task" ? api(apiTask(route.id)) : Promise.resolve(null),
      route.tab === "sources" ? api(apiTask(route.id) + "/evidence") : Promise.resolve(null),
      route.tab === "summary" ? api(apiTask(route.id) + "/insights") : Promise.resolve(null),
      ["summary", "chat"].includes(route.tab) ? api(apiTask(route.id) + "/memory") : Promise.resolve({ notes: [] }),
      route.name === "inbox" ? api("/api/inbox") : Promise.resolve(null),
      route.name === "inbox" ? api("/api/delivery") : Promise.resolve(null),
      route.tab === "chat" ? api(apiTask(route.id) + "/chat") : Promise.resolve(null),
      route.tab === "summary" ? api(apiTask(route.id) + "/dashboard") : Promise.resolve(null),
      route.tab === "chat" ? api("/api/memory") : Promise.resolve({ notes: [] }),
    ]);
    if (sequence !== state.sequence) return;
    const userTasks = allTasks.filter(item => !item.demo);
    const tasks = userTasks.length ? userTasks : allTasks;
    state.task = task;
    state.dashboard = dashboard;
    state.memories = memories.notes;
    state.workspaceMemory = workspaceMemory.notes;
    let events = null;
    if (route.name === "events") {
      const details = await Promise.all(tasks.map(item => api(apiTask(item.id))));
      if (sequence !== state.sequence) return;
      events = details.flatMap(item => item.events.map(event => ({ ...event, task: item })));
      events.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    }
    nav(tasks, route, dashboard?.title || task?.plan.title);
    if (route.name === "home") renderHome(userTasks);
    else if (route.name === "overview") renderOverview();
    else if (route.name === "inbox") renderInbox(inbox, delivery, userTasks);
    else if (route.name === "events") renderEvents(events);
    else renderTask(task, route, { evidence, editedRules, insights, chat, dashboard });
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
  const titles = new Map();
  for (const task of tasks) titles.set(task.plan.title, (titles.get(task.plan.title) || 0) + 1);
  taskNav.innerHTML = groups.map(([label, items]) => items.length ? `
    <div class="task-group"><div class="side-heading">${label}</div>
      ${items.map(task => `<a href="${hrefFor(task.id)}" ${route.id === task.id ? 'aria-current="page"' : ""}>
        <span class="task-icon ${task.active ? "active-task" : ""}" aria-hidden="true"></span>
        <span class="task-copy"><span class="task-label" title="${escape(task.plan.title)}">${escape(task.plan.title)}</span>
          ${titles.get(task.plan.title) > 1 && task.plan.goal ? `<span class="task-context" title="${escape(task.plan.goal)}">${escape(task.plan.goal)}</span>` : ""}</span>
      </a>`).join("")}
    </div>` : "").join("");
  document.querySelector("#crumb").textContent = route.name === "task"
    ? (taskTitle || t("监测任务"))
    : t({ inbox: "今日情报", events: "事件中心" }[route.name] || "Agent 工作台");
}

function renderOverview() {
  const agent = state.agent;
  const inProgress = agent.loading || agent.answer || agent.proposal || agent.sources.size;
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
        <a class="home-inbox-link" href="#inbox">${icon("inbox")}${t("今日情报")}${icon("diagonal")}</a>
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
      <p>${t(agent.monitoring ? "输入主题或关键词，六扇门会判断要跟踪哪些新闻。" : "说说你关心的事。六扇门会查找相关新闻，或帮你起草监测方案。")}</p>
    </header>${composerForm(agent)}${composerSuggestions(agent)}</div>`;
}

function composerForm(draft) {
  return `<form class="composer" data-form="propose" data-mode="${draft.monitoring ? "monitor" : "ask"}">
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

function renderAgentReply(agent) {
  if (agent.loading) return "";
  if (agent.answer) return renderRaceAnswer(agent.answer);
  if (agent.preview?.market) return renderMarketPreview(agent);
  if (agent.preview) return renderNews(agent);
  if (agent.proposal) {
    return `<h1 tabindex="-1" class="reply-title">${t("监测方案已生成")}</h1>
      <p class="reply-copy">${t("检查关注对象和触发条件，保存后即可导入证据和试跑。")}</p>
      <div class="card plan-card">${ruleForm(agent.proposal, "", t("保存为任务"), "create", agent.intent, agent.note)}</div>`;
  }
  return `<h1 tabindex="-1" class="reply-title">${t("这次检索没有完成")}</h1>
      <p class="reply-copy" role="alert">${escape(agent.error)}</p>${button(t("返回需求"), "back-intent")}`;
}

function renderConversation(agent) {
  return `<section class="conversation" aria-label="${t("监测方案会话")}">
    <div class="user-turn"><p>${escape(agent.intent)}</p></div>
    <div class="agent-turn">
      <div class="agent-avatar">${mark()}</div>
      <div class="agent-reply">
        <div class="agent-name">${t("六扇门")}</div>
        <div id="agent-progress">${renderSearchProgress(agent)}</div>
        <p id="agent-announcement" class="sr-only" role="status"></p>
        ${renderAgentReply(agent)}
      </div>
    </div>
  </section>`;
}

function renderRaceAnswer(answer) {
  const localized = language() !== "en";
  const race = localized ? answer.race_zh : answer.race;
  const url = safeURL(answer.url);
  const found = answer.status === "found";
  const link = url ? `<a class="button primary" href="${escape(url)}" target="_blank" rel="noopener noreferrer">
    ${t(found ? "查看 F1 官方正赛成绩" : "查看 F1 官方赛果目录")} ${icon("diagonal")}</a>` : "";
  if (!found) {
    const message = answer.status === "unavailable" ? t("暂时无法读取 F1 官方成绩。")
      : t("暂未找到 {season} 年{race}的官方正赛成绩。", {season: answer.season, race});
    return `<section class="card race-answer">
      <h1 tabindex="-1" class="reply-title">${escape(message)}</h1>
      <div class="row race-answer-actions">${link}${button(t("返回需求"), "back-intent")}</div>
    </section>`;
  }
  const driver = localized && answer.driver_zh ? answer.driver_zh : answer.driver;
  const team = localized && answer.team_zh ? answer.team_zh : answer.team;
  return `<section class="card race-answer">
    <div class="race-answer-heading">
      <span class="scene-icon">${icon("sports")}</span>
      <div><p class="meta">${escape(t("{season} 年{race}正赛冠军", {season: answer.season, race}))}</p>
      <h1 tabindex="-1" class="reply-title">${escape(driver)}</h1>
      ${driver !== answer.driver ? `<p class="meta race-driver-name">${escape(answer.driver)}</p>` : ""}</div>
    </div>
    <dl class="race-answer-facts">
      <div><dt>${t("车队")}</dt><dd>${escape(team)}</dd></div>
      <div><dt>${t("正赛用时")}</dt><dd>${escape(answer.time)}</dd></div>
    </dl>
    <div class="row race-answer-actions">${link}${button(t("继续提问"), "create")}</div>
  </section>`;
}

function sourceStatus(source, loading) {
  if (source.status === "ok") return source.matched ? t("找到 {count} 条", {count: source.matched}) : t("没有符合范围的报道");
  if (source.status === "failed") return t("读取失败");
  return loading ? t("正在读取") : t("未完成");
}

function memoryContext(focus) {
  if (!focus?.length) return "";
  return `<div class="memory-context">
    <strong>${icon("memory")}${t("已参考任务记忆")}</strong>
    <span>${escape(joinTerms(focus))}</span>
  </div>`;
}

function memoryMatch(item) {
  return item.memory_hits?.length ? pill(t("记忆命中") + " · " + joinTerms(item.memory_hits), "memory-hit") : "";
}

function scopeContext(scope) {
  if (!scope) return "";
  const focus = joinTerms(scope.topics.map(topic => t(topic)));
  return `<div class="memory-context news-scope">
    <strong>${icon("search")}${t("识别到的新闻范围")}</strong>
    <span>${escape(scope.label)}${focus ? " · " + escape(focus) : ""}</span>
  </div>`;
}

function scopeMatch(item) {
  return item.scope_hits?.length ? pill(joinTerms(item.scope_hits.map(topic => t(topic))), "scope-hit") : "";
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
        : escape(item.title)}${item.source !== source.source ? ` <span class="sample-publisher">· ${escape(sourceName(item.source))}</span>` : ""} ${scopeMatch(item)} ${memoryMatch(item)}</li>`;
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
    return agent.loading ? `${scopeContext(agent.newsScope)}
      <p class="working" role="status"><span class="working-dot" aria-hidden="true"></span>
      ${t(agent.goldQuoteLookup ? "正在读取上金所日行情…" :
        agent.officialLookup ? "正在查询 F1 官方正赛成绩…" : agent.newsScope ? "正在选择对应信源…" : "正在理解你的需求…")}</p>` : "";
  }
  const hours = agent.searchHours;
  const scope = hours % 24 === 0 ? t("近 {count} 天", {count: hours / 24}) : t("近 {count} 小时", {count: hours});
  const header = `<span class="search-progress-title">${icon("search")}${agent.loading ? t("检索进度") : t("检索过程")}</span>
    <span class="progress-scope">${scope}</span><span class="progress-caption">${progressCaption(agent)}</span>`;
  const list = `<ul class="search-sources" aria-label="${t("查询来源")}">${[...agent.sources.values()]
    .map(source => renderSource(source, agent.loading)).join("")}</ul>`;
  return agent.loading
    ? `<section class="search-progress" aria-label="${t(agent.goldQuoteLookup ? "行情检索进度" : "新闻检索进度")}"><div class="search-progress-head">${header}</div>
        ${scopeContext(agent.newsScope)}${memoryContext(agent.memoryFocus)}${list}</section>`
    : `<details class="search-progress" ${agent.error ? "open" : ""}><summary class="search-progress-head">${header}${icon("chevron")}</summary>${list}</details>`;
}

function updateSearchProgress(agent, type, data) {
  if (type === "checking_sources") {
    agent.searchHours = data.hours;
    agent.memoryFocus = data.memory_focus || [];
    for (const source of data.sources) agent.sources.set(source.id, { ...source, status: "checking" });
  } else if (type === "source_result") {
    agent.sources.set(data.id, data);
  } else if (type === "summarizing") {
    agent.summarizing = true;
  } else if (type === "official_result_lookup") {
    agent.officialLookup = true;
  } else if (type === "news_scope") {
    agent.newsScope = data;
  } else if (type === "gold_quote_lookup") {
    agent.goldQuoteLookup = true;
  }

  if (state.agent !== agent || parseRoute().name !== "overview") return;
  const panel = document.querySelector("#agent-progress");
  if (!panel) return;
  if (["official_result_lookup", "news_scope", "gold_quote_lookup"].includes(type)) {
    panel.innerHTML = renderSearchProgress(agent);
    return;
  }
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

function renderMarketPreview(agent) {
  const { quotes, url } = agent.preview.market;
  const failed = agent.preview.sources.some(source => source.status === "failed");
  return `<h1 tabindex="-1" class="reply-title">${t("黄金收盘走势")}</h1>
    ${failed ? `<p class="notice warn">${t("当前无法读取上金所日行情。")}</p>` : ""}
    ${goldPriceChart(quotes, url)}
    ${agent.viewOnly ? `<div class="news-actions"><span class="meta">${t("未开启持续监测")}</span>
      ${button(t("修改需求"), "back-intent")}${button(t("设置持续监测"), "review-news", true)}</div>`
      : `<div class="card plan-card subscribe-card"><h2 class="subscribe-title">${t("要持续跟踪这个行情吗？")}</h2>
        ${ruleForm(agent.proposal, "", t("确认并开启监测"), "create", agent.intent, agent.note)}</div>`}`;
}

function renderNews(agent) {
  const preview = agent.preview;
  const items = preview.items.map(item => {
    const link = safeURL(item.url);
    return `<li class="news-item">
      <div class="row news-meta"><span class="news-publisher">${escape(sourceName(item.source))}</span><time class="meta" datetime="${escape(item.published_at)}">
        ${item.published_missing ? t("首次发现") + " " : ""}${stamp(item.published_at)}
      </time>${scopeMatch(item)}${memoryMatch(item)}</div>
      <h2>${link ? `<a href="${escape(link)}" target="_blank" rel="noopener noreferrer">${escape(item.title)}${icon("diagonal")}</a>` : escape(item.title)}</h2>
      ${item.summary ? `<p>${escape(item.summary)}</p>` : ""}
      ${item.via_news_search ? `<span class="meta">${t("通过 Google 新闻查看")}</span>`
        : item.news_provider === "bing" ? `<span class="meta">${t("由 Bing 新闻检索")}</span>` : ""}
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
    ${scopeContext(preview.scope)}
    ${memoryContext(preview.memory_focus)}
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

function openComposer(intent = "", useModel = false, monitoring = false) {
  state.agent.controller?.abort();
  state.agent = freshAgent(intent, useModel, monitoring);
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
  const monitoring = form.dataset.mode === "monitor";
  if (!intent) {
    const message = form.querySelector(".composer-error");
    message.textContent = t("请先输入想追踪的内容。");
    message.hidden = false;
    form.elements.intent.focus();
    return;
  }
  state.agent.controller?.abort();
  const agent = freshAgent(intent, useModel, monitoring);
  state.agent = agent;
  agent.controller = new AbortController();
  agent.loading = true;
  if (parseRoute().name === "home") location.hash = "#overview";
  else renderOverview();
  try {
    const { plan, note, preview, answer } = await discover({ intent, useModel, mode: form.dataset.mode }, agent.controller.signal,
      (type, data) => updateSearchProgress(agent, type, data));
    agent.proposal = plan;
    agent.preview = preview || null;
    agent.answer = answer || null;
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

function renderInbox(inbox, delivery, tasks) {
  const priority = inbox.stories.filter(story => story.priority || story.focus.length).length;
  const failed = inbox.failures.filter(source => !source.recovered_at).length;
  const needsSources = tasks.find(task => !task.plan.feeds.length && !task.plan.news_query);
  page.innerHTML = `<div class="inbox-title page-title">
    <div><p class="inbox-date">${icon("clock")} <time datetime="${escape(inbox.date)}">${escape(inbox.date)}</time> ${t("北京时间")}</p>
      <h1>${t("今日情报收件箱")}</h1></div>
    <div class="row task-actions">
      ${delivery.latest_day ? `<a class="button" href="/api/briefings/latest" download>${t("下载最新简报")}</a>` : ""}
      ${button(icon("bell") + t("提醒与简报"), "delivery-settings")}
      ${button(t("刷新收件箱"), "refresh-inbox", inbox.stories.length > 0)}
    </div>
  </div>
  <div class="overview-metrics" aria-label="${t("今日概况")}">
    ${metric("inbox", t("今日进展"), inbox.stories.length)}
    ${metric("signal", t("优先查看"), priority, priority ? "metric-priority" : "")}
    ${metric("news", t("来源待检查"), failed, failed ? "metric-alert" : "")}
  </div>
  <div class="inbox-layout">
    <section class="inbox-stories"><div class="section-heading"><h2>${t("今日进展")}</h2>
      <span class="meta">${t("{count} 个关注任务", {count: inbox.task_count})}</span></div>
      ${inbox.stories.length ? inbox.stories.map(inboxStory).join("") : `<div class="card inbox-empty">
        <div class="scene-icon">${icon("inbox")}</div>
        <h3>${t("今天暂无进展")}</h3>
        ${needsSources ? `<p>${t("为关注的任务选择信源，开始收集更新。")}</p>
          <a class="button primary" href="${hrefFor(needsSources.id, "rules")}">${t("配置来源")}</a>`
          : !inbox.task_count ? `<p>${t("创建关注任务后，今天的进展会汇总到这里。")}</p>
            <a class="button primary" href="#overview">${t("前往 Agent 工作台")}</a>` : ""}
      </div>`}
    </section>
    ${inboxSourceHealth(inbox)}
  </div>`;
}

function inboxStory(story) {
  const top = story.priority || story.focus.length;
  return `<details class="card inbox-story ${top ? "inbox-priority" : ""}">
    <summary class="inbox-story-heading">
      <div class="row inbox-story-meta">
        ${story.priority ? pill(t("规则触发"), "a") : ""}
        ${memoryMatch({memory_hits: story.focus})}
        <time class="meta" datetime="${escape(story.at)}">${stamp(story.at)}</time>
      </div>
      <span class="inbox-story-title">${escape(story.title)}${icon("chevron")}</span>
      ${story.summary ? `<span class="inbox-summary-copy">${escape(story.summary)}</span>` : ""}
      <span class="meta">${story.reports.length
        ? t("{count} 篇报道 · {sources} 个来源", {count: story.reports.length, sources: story.sources})
        : t("事件更新")}</span>
    </summary>
    <div class="inbox-story-body">
      ${story.reports.length ? `<h3>${t("报道与原文")}</h3><ul class="inbox-reports">${story.reports.map(inboxReport).join("")}</ul>` : ""}
      ${story.events.length ? `<div class="inbox-links"><span class="meta">${t("关联事件")}</span>
        ${story.events.map(event => `<a href="${hrefFor(event.task_id, "event", event.id)}">${escape(event.label)}</a>
          ${statusPill(statuses[event.status] || statuses.open)}`).join("")}</div>` : ""}
      <div class="inbox-links"><span class="meta">${t("关联任务")}</span>
        ${story.tasks.map(task => `<a href="${hrefFor(task.id)}">${escape(task.title)}</a>`).join("")}</div>
    </div>
  </details>`;
}

function inboxReport(report) {
  const link = safeURL(report.url);
  return `<li><div><strong>${escape(report.title || report.source)}</strong>
      <p class="meta">${escape(sourceName(report.source))} · ${report.published_missing ? t("首次发现") + " " : ""}
        <time datetime="${escape(report.published_at)}">${stamp(report.published_at)}</time></p></div>
    ${link ? `<a class="button inbox-original" href="${escape(link)}" target="_blank" rel="noopener noreferrer">${t("查看原文")} ${icon("diagonal")}</a>`
      : button(t("查看完整记录"), "evidence", false, `data-task="${escape(report.task_id)}" data-evidence="${escape(report.id)}"`)}
  </li>`;
}

function inboxSourceHealth(inbox) {
  const status = inbox.sources_checked ? t("今日检查未发现来源读取失败。") : t("今天还没有正式的来源检查记录。");
  return `<aside class="card inbox-health"><div class="row inbox-health-title"><span class="scene-icon">${icon("signal")}</span>
    <h2>${t("来源状态")}</h2></div>
    ${inbox.failures.length ? `<ul class="inbox-failures">${inbox.failures.map(source => `<li>
      <div class="row spread"><strong>${escape(sourceName(source.source))}</strong>
        ${source.recovered_at ? pill(t("已恢复"), "g") : pill(t("读取失败"), "r")}</div>
      <p class="meta">${escape(source.task.title)} · ${escape(source.note)}</p>
      <p class="meta">${t("失败时间")} ${stamp(source.at)}
        ${source.recovered_at ? ` · ${t("恢复时间")} ${stamp(source.recovered_at)}` : ""}</p>
      <a href="${hrefFor(source.task.id, "runs", source.run_id)}">${t("查看运行记录")}</a>
    </li>`).join("")}</ul>` : `<p class="meta inbox-health-empty">${status}</p>`}
  </aside>`;
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

function renderTask(task, route, { evidence, editedRules, insights, chat, dashboard }) {
  const tab = route.tab;
  const activeTab = tab === "event" ? "summary" : tab;
  const needsSources = tab === "summary" && !task.plan.feeds.length && !task.plan.news_query && !insights.evidence_count;
  const tabs = { summary: t("研判概览"), chat: t("任务问答"), rules: t("监测规则"), sources: t("证据库"), runs: t("运行记录") };
  const title = `<div class="page-title ${tab === "summary" ? "summary-page-title" : tab === "chat" ? "task-chat-title" : ""}"><div>
    <div class="row">${pill(t(scenarios[task.plan.scenario] || "自定义"))}${task.demo ? pill(t("合成演示"), "a") : ""}
    ${pill(task.active ? t("监测中") : t("已暂停"), task.active ? "g" : "")}</div>
    <h1 class="task-title">${escape(dashboard?.title || task.plan.title)}</h1>
    ${dashboard?.focus.length ? `<div class="row dashboard-focus">${dashboard.focus.map(label => pill(t(label))).join("")}</div>`
      : !["summary", "chat"].includes(tab) ? `<p>${escape(task.plan.goal)}</p>` : ""}
    </div><div class="row task-actions">
      ${dashboard ? button(t("定制概览"), "dashboard-settings") : ""}
      ${button(task.active ? t("暂停") : t("启用方案"), "toggle-active", !task.active)}
      ${button(t("试跑规则"), "trial")}
      ${task.active ? button(t("立即检查"), "live", !needsSources) : ""}
      <details class="task-options">
        <summary class="button" aria-label="${t("更多任务操作")}" title="${t("更多任务操作")}">${icon("more")}</summary>
        <div class="task-options-menu">${button(t("删除任务"), "task-delete")}</div>
      </details>
    </div></div>`;
  const tabbar = `<nav class="tabs" aria-label="${t("任务视图")}">${Object.entries(tabs).map(([key, label]) =>
    `<a href="${hrefFor(task.id, key)}" ${key === activeTab ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</nav>`;
  let content;
  if (tab === "chat") content = taskChat(task, chat.turns, chat.model);
  else if (tab === "rules") content = ruleForm(editedRules || task.plan, t("修改方案"), t("保存规则"), "update", task.intent);
  else if (tab === "sources") content = sourcesTab(task, evidence);
  else if (tab === "runs") content = runsTab(task, route.extra);
  else if (tab === "event") {
    const event = task.events.find(item => item.id === route.extra);
    content = event ? eventDetail(event) : empty(t("找不到该事件。"), `<a class="button" href="${hrefFor(task.id)}">${t("返回任务")}</a>`);
  } else content = summaryTab(task, insights, dashboard);
  page.innerHTML = title + tabbar + content;
  if (tab === "chat") scrollChatToLatest();
}

function taskChat(task, turns, model) {
  const samples = [["news", "今天有什么新进展？"], ["clock", "最近一次检查有什么结果？"], ["signal", "有哪些来源读取失败？"]];
  const usesCodex = model?.provider === "codex";
  const modelLabel = usesCodex ? "Codex" : model?.local ? t("本机模型") : t("外部模型");
  const modelNote = !model ? t("在项目 .env 填写模型配置。保存后，下次提问自动生效。") :
    usesCodex ? t("提问、相关任务资料和全局记忆会通过已登录的 Codex 发送给 OpenAI。") :
    model.local ? "" : t("提问、相关任务资料和全局记忆会发送给此模型。");
  const modelStatus = `<span class="chat-model-dot"></span><span>${model ? modelLabel : t("AI 待配置")}</span>`;
  const pending = state.chatRequests.get(task.id);
  return `<section class="task-chat" aria-labelledby="task-chat-title" data-task="${task.id}" data-model="${Boolean(model)}">
    <header class="task-chat-header">
      <span class="task-chat-avatar">${icon("chat")}</span>
      <h2 id="task-chat-title">${t("任务问答")}</h2>
      ${modelNote ? `<details class="chat-model ${model ? "chat-model-ready" : ""}">
        <summary>${modelStatus}${icon("chevron")}</summary>
        <div class="chat-model-note">${model ? `<strong>${escape(model.name)}</strong>` : ""}<p>${modelNote}</p></div>
      </details>` : `<span class="chat-model chat-model-ready" title="${escape(model.name)}">${modelStatus}</span>`}
      ${button(icon("memory") + t("全局记忆") + (state.workspaceMemory.length ? ` <span>${state.workspaceMemory.length}</span>` : ""),
        "chat-memory", false, `aria-haspopup="dialog" aria-label="${t("查看全局记忆")}"`)}
    </header>
    <div class="task-chat-scroll" tabindex="0" role="region" aria-label="${t("对话记录")}">
      <div class="task-chat-content">
        <div class="task-chat-start" ${turns.length || pending ? "hidden" : ""}>
          <span class="task-chat-avatar">${icon("chat")}</span><h3>${t("问这个任务")}</h3>
          <p class="meta">${t("从本任务的证据、事件和运行记录里找答案。")}</p>
          <div class="task-chat-samples">${samples.map(([symbol, sample]) => `<button type="button" data-act="task-chat-sample"
            data-question="${escape(t(sample))}">${icon(symbol)}<span>${t(sample)}</span>${icon("diagonal")}</button>`).join("")}</div>
        </div>
        <ol class="task-chat-history">${turns.map(turn => chatTurn(task.id, turn)).join("")}</ol>
        <div class="task-chat-pending" role="status">${pending ? chatPending(pending, Boolean(model)) : ""}</div>
      </div>
    </div>
    <div class="task-chat-dock">
      <button class="button chat-latest" data-act="chat-latest" type="button" hidden>${t("最新消息")} ${icon("chevron")}</button>
      <form class="composer task-chat-form" data-form="task-chat">
        <label class="sr-only" for="task-chat-input">${t("输入关于这个任务的问题")}</label>
        <textarea id="task-chat-input" name="question" rows="1" maxlength="1000" required
          placeholder="${t("输入关于这个任务的问题")}">${escape(state.chatDrafts.get(task.id))}</textarea>
        <div class="composer-toolbar">
          <span class="chat-scope">${icon("inbox")}${t("仅限当前任务")}</span>
          <div class="composer-submit"><span class="composer-hint"><kbd>Enter</kbd> ${t("发送")}</span>
            <button class="button primary send" type="submit" aria-label="${t("发送消息")}" ${pending ? "disabled" : ""}>${icon("arrow")}</button></div>
        </div>
        ${formError}
      </form>
    </div>
  </section>`;
}

function chatPending(question, hasModel) {
  return `<div class="user-turn"><p>${escape(question)}</p></div>
    <div class="chat-wait"><span class="task-chat-avatar">${icon("chat")}</span>
      <span class="working"><span class="working-dot" aria-hidden="true"></span>${t(hasModel ? "正在结合任务资料生成回答…" : "正在准备回答…")}</span></div>`;
}

function latestChatOffset(scroller) {
  const end = scroller.scrollHeight - scroller.clientHeight;
  if (scroller.querySelector(".task-chat-pending:not(:empty)")) return end;
  const latest = scroller.querySelector(".task-chat-turn:last-child");
  return latest ? Math.min(end, Math.max(0, latest.offsetTop - 12)) : 0;
}

function scrollChatToLatest(panel = page.querySelector(".task-chat")) {
  if (!panel) return;
  const scroller = panel.querySelector(".task-chat-scroll");
  scroller.scrollTop = latestChatOffset(scroller);
  panel.querySelector(".chat-latest").hidden = true;
}

async function submitTaskChat(form) {
  const panel = form.closest(".task-chat");
  const key = panel.dataset.task;
  const input = form.elements.question;
  const question = input.value.trim();
  if (!question || state.chatRequests.has(key)) return;
  state.chatRequests.set(key, question);
  state.chatDrafts.delete(key);
  input.value = "";
  form.querySelector(".form-error").textContent = "";
  form.querySelector(".send").disabled = true;
  panel.querySelector(".task-chat-start").hidden = true;
  panel.querySelector(".task-chat-pending").innerHTML = chatPending(question, panel.dataset.model === "true");
  input.focus({ preventScroll: true });
  scrollChatToLatest(panel);
  let failure;
  try {
    await api(apiTask(key) + "/chat", { question });
  } catch (error) {
    failure = error;
  } finally {
    state.chatRequests.delete(key);
  }

  if (failure && !state.chatDrafts.get(key)) state.chatDrafts.set(key, question);
  const route = parseRoute();
  if (route.tab !== "chat" || route.id !== key) return;
  if (!failure) {
    const refocus = document.activeElement?.id === "task-chat-input";
    await refresh();
    if (refocus) page.querySelector(`.task-chat[data-task="${key}"] textarea`)?.focus({ preventScroll: true });
    return;
  }
  const current = page.querySelector(`.task-chat[data-task="${key}"]`);
  if (!current) return;
  current.querySelector(".task-chat-pending").replaceChildren();
  current.querySelector(".task-chat-start").hidden = Boolean(current.querySelector(".task-chat-turn"));
  current.querySelector(".send").disabled = false;
  current.querySelector("textarea").value = state.chatDrafts.get(key);
  current.querySelector(".form-error").textContent = failure.message;
}

function chatTurn(taskId, turn) {
  const answer = turn.reply;
  const modelLabel = answer.mode === "memory" ? ["Agent 记忆", "g"] :
    answer.mode === "model" ? [answer.provider === "codex" ? "Codex 回答" : "AI 回答", "g"] :
    ({ unconfigured: ["AI 待配置", "a"], failed: ["AI 调用失败", "a"] }[answer.modelState] ||
      ["本地证据", ""]);
  const numbers = new Map(answer.references.map((item, index) => [item.id, index + 1]));
  return `<li class="task-chat-turn">
    <div class="user-turn"><p>${escape(turn.question)}</p></div>
    <article class="task-chat-answer" tabindex="-1" aria-label="${t("六扇门")}">
      <span class="task-chat-avatar assistant-avatar">${icon("chat")}</span>
      <div class="task-chat-reply"><div class="task-chat-speaker"><strong>${t("六扇门")}</strong>
        ${pill(t(modelLabel[0]), modelLabel[1])}
        <time class="meta" datetime="${escape(turn.created_at)}">${stamp(turn.created_at)}</time></div>
      ${answer.text ? `<p class="task-chat-prose">${escape(answer.text)}</p>` : ""}
      ${answer.memory ? `<button type="button" class="chat-saved-memory" data-act="chat-memory" aria-haspopup="dialog">
        ${icon("check")}<span>${escape(memoryNoteText(answer.memory.text))}</span>${icon("diagonal")}</button>` : ""}
      ${answer.points.length ? `<ul class="task-chat-points">${answer.points.map(point => chatPoint(turn, point, numbers)).join("")}</ul>` : ""}
      ${answer.limitation ? `<p class="meta task-chat-prose">${escape(answer.limitation)}</p>` : ""}
      ${answer.modelState === "unconfigured" ? `<p class="meta task-chat-prose">${t("这条回复生成时没有可用的模型配置。")}</p>` : ""}
      ${answer.modelState === "failed" ? `<p class="meta task-chat-prose">${t("本次未能生成 AI 回答，已展示本地证据。")}</p>` : ""}
      ${answer.references.length ? `<details class="task-chat-citations"><summary>${icon("link")}
        <span>${answer.references.length === 1 ? t("1 条引用") : t("{count} 条引用", {count: answer.references.length})}</span>${icon("chevron")}</summary><ol>
        ${answer.references.map((item, index) => chatReference(taskId, turn.id, item, index + 1)).join("")}
      </ol></details>` : ""}
      </div>
    </article>
  </li>`;
}

function chatPoint(turn, point, numbers) {
  let content = escape(turn.reply.mode === "memory" ? memoryNoteText(point.text) : point.text);
  if (turn.reply.mode === "local" && point.text.includes("\n")) {
    const lineEnd = point.text.indexOf("\n");
    const title = point.text.slice(0, lineEnd).trim();
    const description = point.text.slice(lineEnd + 1).trim();
    content = `<strong>${escape(title)}</strong>${description && description !== title ? `<br>${escape(description)}` : ""}`;
  }
  const citations = point.refs.map(id => {
    const number = numbers.get(id);
    if (!number) return "";
    const target = `chat-${escape(turn.id)}-${number}`;
    return ` <a class="chat-citation-number" href="#${target}" data-act="chat-citation" data-ref="${target}"
      aria-label="${t("查看引用 {number}", {number})}">[${number}]</a>`;
  }).join("");
  return `<li><p>${content}${citations}</p></li>`;
}

function chatReference(taskId, turnId, item, number) {
  let action;
  let label = item.label;
  if (item.kind === "evidence") {
    const link = safeURL(item.url);
    action = `${button(t("查看记录"), "evidence", false, `data-evidence="${escape(item.target)}"`)}
      ${link ? `<a href="${escape(link)}" target="_blank" rel="noopener noreferrer">${t("查看原文")} ${icon("diagonal")}</a>` : ""}`;
  } else if (item.kind === "workspace_memory") {
    label = memoryNoteText(label);
    action = button(t("查看全局记忆"), "chat-memory", false, 'aria-haspopup="dialog"');
  } else {
    const route = item.kind === "event" ? "event" : item.kind === "run" ? "runs" : "rules";
    label ||= t(route === "runs" ? "运行记录" : "监测规则");
    action = `<a href="${hrefFor(taskId, route, item.target)}">${t("查看详情")} ${icon("diagonal")}</a>`;
  }
  return `<li id="chat-${escape(turnId)}-${number}" tabindex="-1">
    <div class="chat-reference-title"><strong>${escape(label)}</strong><p class="meta">${[
      item.source ? escape(sourceName(item.source)) : "",
      item.at ? (item.first_seen ? t("首次发现") + " " : "") + stamp(item.at) : "",
    ].filter(Boolean).join(" · ")}</p></div>
    <div class="row">${action}</div>
  </li>`;
}

const dashboardModules = {
  metrics: "监测指标", trend: "检查趋势", activity: "证据增量", sources: "来源分布",
  event_chart: "事件状态", latest: "最新证据", events: "事件列表", chat: "任务问答",
  memory: "Agent 记忆", rules: "当前规则", gold_price: "黄金收盘走势",
};
const chartModules = new Set(["trend", "activity", "sources", "event_chart", "gold_price"]);

function summaryTab(task, insights, dashboard) {
  const chartsOnly = dashboard.modules.every(module => chartModules.has(module));
  return `<div class="dashboard-grid" aria-label="${t("任务概览")}">${dashboard.modules.map(module =>
    `<div class="dashboard-widget ${module === "metrics" ? "dashboard-full" : ""}" data-module="${module}">
      ${dashboardWidget(module, task, insights, dashboard, chartsOnly)}
    </div>`).join("")}</div>`;
}

function dashboardWidget(module, task, insights, dashboard, chartsOnly) {
  switch (module) {
    case "metrics": {
      const latestCheck = insights.checks.at(-1);
      return `<div class="overview-metrics" aria-label="${t("监测指标")}">
        ${metric("inbox", t("累计证据"), insights.evidence_count)}
        ${metric("signal", t("待处理事件"), task.events.filter(event => event.status !== "resolved").length)}
        ${metric("clock", t("最近正式检查"), latestCheck ? stamp(latestCheck.at) : "—", "metric-time")}
      </div>`;
    }
    case "trend":
      return checkChart(insights.checks, chartsOnly);
    case "activity":
      return activityChart(insights.activity);
    case "gold_price":
      return goldPriceChart(insights.gold_quotes);
    case "event_chart":
      return eventStatusChart(task.events);
    case "sources": {
      if (insights.evidence_count || chartsOnly) return sourceChart(task, insights);
      const configured = task.plan.feeds.length || task.plan.news_query;
      return `<section class="card overview-source-setup">
        <span class="scene-icon">${icon("news")}</span><div><h2>${t("来源分布")}</h2>
        <p class="meta">${configured ? t("待采集证据") : t("尚未选择信源")}</p></div>
        <a class="button ${configured ? "" : "primary"}" href="${hrefFor(task.id, configured ? "sources" : "rules")}">${configured ? t("证据库") : t("配置来源")}</a>
      </section>`;
    }
    case "latest":
      return latestDashboardEvidence(task, insights.recent, dashboard.price);
    case "events": {
      const events = task.events.map(event => ({ ...event, task }));
      return `<section class="card dashboard-events"><h2>${t("事件列表")}</h2>
        ${events.length ? events.slice(0, 4).map(eventRow).join("") : `<p class="meta">${t("当前任务尚无事件。")}</p>`}</section>`;
    }
    case "chat":
      return `<section class="card overview-source-setup"><span class="scene-icon">${icon("search")}</span>
        <div><h2>${t("问这个任务")}</h2><p class="meta">${t("查看证据和运行结果。")}</p></div>
        <a class="button" href="${hrefFor(task.id, "chat")}">${t("任务问答")}</a></section>`;
    case "memory":
      return memoryPanel(task);
    case "rules":
      return dashboardRules(task);
    default:
      return "";
  }
}

function latestDashboardEvidence(task, records, price) {
  return `<section class="card"><div class="row spread dashboard-module-title">
    <h2>${t(price ? "报价资料" : "最新证据")}</h2>
    <a href="${hrefFor(task.id, "sources")}">${t("证据库")}</a></div>
    ${records.length ? `<ul class="dashboard-evidence">${records.map(item => {
      const link = safeURL(item.url);
      return `<li><div><strong>${escape(item.title)}</strong><p class="meta">${escape(sourceName(item.source))} · ${stamp(item.published_at)}</p></div>
        ${link ? `<a href="${escape(link)}" target="_blank" rel="noopener noreferrer">${t("查看原文")} ${icon("diagonal")}</a>`
          : button(t("查看记录"), "evidence", false, `data-evidence="${escape(item.id)}"`)}</li>`;
    }).join("")}</ul>` : `<p class="chart-empty">${t(price ? "等待采集或导入本任务的报价资料。" : "还没有本任务的证据。")}</p>`}
  </section>`;
}

function activityChart(days) {
  const max = Math.max(1, ...days.map(item => item.count));
  const bar = (item, index) => {
    const x = 42 + 57 * index;
    const height = item.count / max * 70;
    const count = item.count;
    const day = item.day.slice(5).replace("-", "/");
    return `<rect x="${x - 12}" y="${90 - height}" width="24" height="${height}" rx="4">
        <title>${day} · ${count}</title></rect>
      <text x="${x}" y="${83 - height}" text-anchor="middle">${count}</text>
      <text x="${x}" y="109" text-anchor="middle">${day}</text>`;
  };
  return `<section class="card insight-chart"><div class="row spread">
    <h2>${t("证据增量")}</h2><span class="meta">${t("近 7 天 · 北京时间")}</span></div>
    <svg class="check-chart activity-chart" viewBox="0 0 426 120" role="img" aria-label="${t("近 7 天证据量")}">
      <line x1="18" x2="408" y1="90" y2="90"/>${days.map(bar).join("")}</svg>
  </section>`;
}

function eventStatusChart(events) {
  const total = events.length;
  const bands = ["open", "investigating", "resolved"].map(status => {
    const count = events.filter(event => event.status === status).length;
    const label = t(statuses[status][0]);
    return `<li><div><span>${label}</span><strong>${count}</strong></div>
      <meter min="0" max="${Math.max(1, total)}" value="${count}" aria-label="${label}"></meter></li>`;
  });
  return `<section class="card insight-chart"><div class="row spread">
    <h2>${t("事件状态")}</h2><span class="meta">${t("{count} 件", {count: total})}</span></div>
    <ul class="source-bars event-status-bars">${bands.join("")}</ul>
  </section>`;
}

function goldPriceChart(quotes, report = "https://www.sge.com.cn/sjzx/quotation_daily_new") {
  const priceFormat = new Intl.NumberFormat(language() === "en" ? "en-US" : "zh-CN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
  const pointValues = quotes.map(item => Number(item.close));
  const latest = quotes.at(-1);
  const source = safeURL(latest?.url || report);
  const bottom = 104;
  const min = Math.min(...pointValues);
  const max = Math.max(...pointValues);
  const extent = max - min;
  const points = quotes.map((item, i) => ({
    x: quotes.length > 1 ? 61 + i * 360 / (quotes.length - 1) : 241,
    y: extent ? bottom - (Number(item.close) - min) * 79 / extent : 65,
    item,
  }));
  const line = points.map(point => `${point.x},${point.y}`).join(" ");
  return `<section class="card insight-chart gold-quote-chart">
    <div class="row spread"><h2>Au99.99</h2><span class="meta">${t("近 14 天 · 收盘")}</span></div>
    ${latest ? `<div class="gold-latest"><strong>${priceFormat.format(Number(latest.close))}</strong>
        <span>${t("人民币/克")}</span><time class="meta" datetime="${escape(latest.day)}">${escape(latest.day)}</time></div>
      <svg class="check-chart" viewBox="0 0 448 124" role="img" aria-label="${t("黄金收盘走势")}">
        <line x1="61" x2="421" y1="${bottom}" y2="${bottom}"/>
        ${extent ? `<line x1="61" x2="421" y1="25" y2="25"/>
          <text x="53" y="29" text-anchor="end">${priceFormat.format(max)}</text>
          <text x="53" y="${bottom + 4}" text-anchor="end">${priceFormat.format(min)}</text>`
          : `<text x="53" y="69" text-anchor="end">${priceFormat.format(max)}</text>`}
        <polyline points="${line}" fill="none"/>
        ${points.map(point => `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${escape(point.item.day)} · ${escape(point.item.close)}</title></circle>`).join("")}
      </svg>
      <div class="chart-dates"><span>${escape(quotes[0].day)}</span>${quotes.length > 1 ? `<span>${escape(latest.day)}</span>` : ""}</div>`
      : `<p class="chart-empty">${t("暂无已公布的收盘价格。")}</p>`}
    ${source ? `<a class="gold-source-link" href="${escape(source)}" target="_blank" rel="noopener noreferrer">
      ${t("查看上金所官方行情")} ${icon("diagonal")}</a>` : ""}
  </section>`;
}

function dashboardRules(task) {
  return `<details class="card event-panel rules-panel overview-rules"><summary class="row rules-panel-title">
      <span class="scene-icon">${icon("signal")}</span><strong>${t("当前规则")}</strong>
      <span class="meta">${t("每 {minutes} 分钟", {minutes: task.plan.cadence})}</span>${icon("chevron")}</summary>
      <p class="meta">${t("方案第 {revision} 版", {revision: task.revision})} · ${task.plan.generatedBy === "model" ? t("模型起草") : t("本地规则起草")}</p>
      <dl class="rule-facts">
        <div><dt>${t("观察窗口")}</dt><dd>${t("{hours} 小时", task.plan)}</dd></div>
        <div><dt>${t("触发条件")}</dt><dd>${t("至少 {minimum} 条记录、{channels} 个来源", task.plan)}</dd></div>
        <div><dt>${t("检查频率")}</dt><dd>${t("每 {minutes} 分钟", {minutes: task.plan.cadence})}</dd></div>
        ${task.active && task.next_at ? `<div><dt>${t("下次检查")}</dt><dd>${stamp(task.next_at)}</dd></div>` : ""}
      </dl>
      <div class="row rule-links"><a href="${hrefFor(task.id, "rules")}">${t("修改规则")}</a>
        <a href="${hrefFor(task.id, "runs")}">${t("查看运行记录")}</a>
        <a href="${apiTask(task.id)}/report?lang=${language()}" download>${t("导出情报简报")}</a></div>
    </details>`;
}

function metric(symbol, label, value, extra = "") {
  return `<div class="card overview-metric">
    <span class="scene-icon">${icon(symbol)}</span>
    <div><span class="meta">${label}</span><strong class="${extra}">${value}</strong></div>
  </div>`;
}

function checkChart(checks, chartsOnly = false) {
  const title = t("检查趋势");
  const header = `<div class="chart-title"><h2>${title}</h2><p class="meta">${t("最近正式检查的输入记录数")}</p></div>`;
  if (!chartsOnly && !checks.some(check => check.count)) {
    return `<section class="card insight-chart empty-trend">
      <div class="row spread"><h2>${title}</h2><span class="meta">${checks.length
        ? t("{count} 次检查", {count: checks.length}) : t("尚无检查")}</span></div>
      ${checks.length ? `<div class="zero-checks" aria-hidden="true">${checks.map(() => "<i></i>").join("")}</div>` : ""}
      <p class="meta">${checks.length ? t("这些检查均未采集到记录。") : t("等待首次正式检查。")}</p>
    </section>`;
  }
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
      <defs><linearGradient id="check-chart-fill" x2="0" y2="1"><stop offset="0" stop-color="#299b90" stop-opacity=".27"/>
        <stop offset="1" stop-color="#299b90" stop-opacity=".03"/></linearGradient></defs>
      ${ticks.map(count => `<line x1="39" x2="431" y1="${yFor(count)}" y2="${yFor(count)}" />
        <text x="30" y="${yFor(count) + 4}" text-anchor="end">${count}</text>`).join("")}
      ${points.length > 1 ? `<polygon points="${points[0].x},${baseline} ${path} ${points.at(-1).x},${baseline}" fill="url(#check-chart-fill)"/>
        <polyline points="${path}" fill="none" />` : ""}
      ${points.map(point => `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${stamp(point.at)} · ${point.count}</title></circle>`).join("")}
    </svg>
    ${points.length ? `<div class="chart-dates"><span>${stamp(points[0].at)}</span>${points.length > 1 ? `<span>${stamp(points.at(-1).at)}</span>` : ""}</div>
      <details class="chart-values"><summary>${t("查看检查数值")}</summary><ul>${values}</ul></details>`
      : `<p class="meta">${t("等待首次正式检查。")}</p>`}
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

function memoryNoteText(text) {
  return text.startsWith("称呼：") ? t("称呼：{name}", {name: text.slice("称呼：".length)}) : text;
}

function memoryPanel(task, { inDialog = false, scope = "task" } = {}) {
  const isWorkspace = scope === "workspace";
  const notes = isWorkspace ? state.workspaceMemory : state.memories;
  const rows = notes.map(note => `<li class="memory-note">
    <details><summary>${escape(memoryNoteText(note.text).split("\n")[0])}</summary>
    <time class="meta" datetime="${escape(note.updated_at)}">${stamp(note.updated_at)}</time><p>${escape(memoryNoteText(note.text))}</p>
    <div class="row memory-actions">
      ${isWorkspace || note.text.startsWith("称呼：") ? "" : button(t("用这条记忆起草"), "memory-draft", false, `data-note="${escape(note.id)}"`)}
      ${button(t("编辑"), "memory-edit", false, `data-scope="${scope}" data-note="${escape(note.id)}"`)}
      ${button(t("删除"), "memory-remove", false, `data-scope="${scope}" data-note="${escape(note.id)}"`)}
    </div></details>
  </li>`);
  return `<section class="${inDialog ? "chat-memory-panel" : "card memory-panel"}">
    <div class="row memory-panel-title">${inDialog ? `<h3>${t(isWorkspace ? "全局记忆" : "当前任务记忆")}</h3>` :
      `<span class="scene-icon">${icon("memory")}</span><h2>${t("Agent 记忆")}</h2>`}
      ${button(icon("plus") + t("记想法"), "memory-new", false, `data-scope="${scope}"`)}</div>
    ${rows.length ? `<ul class="memory-notes">${rows.slice(0, 3).join("")}</ul>` : `<p class="meta">${t("还没有记忆")}</p>`}
    ${rows.length > 3 ? `<details><summary>${t("查看其余 {count} 条记忆", {count: rows.length - 3})}</summary>
      <ul class="memory-notes">${rows.slice(3).join("")}</ul></details>` : ""}
    ${!inDialog && task.intent ? `<details class="memory-original"><summary>${t("原始需求")}</summary><p>${escape(task.intent)}</p></details>` : ""}
  </section>`;
}

function evidenceBlock(item, detailButton = true) {
  const link = safeURL(item.url);
  return `<div class="source">
    <div class="row">${pill(sourceName(item.source), "g")}${pill(t(kinds[item.kind] || "记录"))}
      <time class="meta" datetime="${escape(item.published_at)}">${item.published_missing ? t("首次发现") + " " : ""}${stamp(item.published_at)}</time>
      ${item.synthetic ? pill(t("演示"), "a") : ""}${memoryMatch(item)}</div>
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
      ${task.plan.news_query ? (task.plan.news_providers || ["google"]).map(provider =>
        pill(t(newsProviderNames[provider]) + " · " + task.plan.news_query, "g")).join("") : ""}
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
  const review = result.memory_review;
  const windowText = t("观察窗口 {from} 至 {to} · {total} 条输入 · {alerts} 个触发 · {observations} 个观察中",
    {...result, from: stamp(result.window.from), to: stamp(result.window.to)});
  return `<article class="card run-card">
    <div class="row spread"><h3>${run.mode === "trial" ? t("试跑") : t("正式检查")} · ${stamp(run.created_at)}</h3>
      <span class="meta">${t("规则第 {revision} 版", {revision: result.revision})}</span></div>
    <p class="meta">${windowText}</p>
    ${review ? memoryContext(review.focus) : ""}
    ${review?.count ? `<details class="memory-review" ${expanded ? "open" : ""}>
      <summary>${t("记忆命中 {count} 条 · 查看代表记录", {count: review.count})}</summary>
      ${review.items.map(item => evidenceBlock(item)).join("")}
    </details>` : review ? `<p class="meta">${t("本次检查未命中记忆关注词。")}</p>` : ""}
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

function feedOptions(selected) {
  const labels = {
    f1: "F1 赛车", sports: "体育", tech: "科技与 AI", research: "科研", finance: "财经",
    news: "中文新闻", versions: "版本发布", custom: "自定义订阅",
  };
  const groups = new Map();
  for (const feed of state.meta.feeds) {
    const label = labels[feed.group] || labels.custom;
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(feed);
  }
  if (!groups.size) return `<p class="help">${t("当前没有配置 RSS。")}</p>`;
  return `<div class="feed-options">${[...groups.entries()].map(([label, feeds]) => {
    const count = feeds.filter(feed => selected.includes(feed.id)).length;
    return `<details ${count ? "open" : ""}><summary>${t(label)} <span class="meta feed-count">${count} / ${feeds.length}</span></summary>
      <div class="row">${feeds.map(feed => `<label class="checkbox"><input type="checkbox" name="feed" value="${escape(feed.id)}"
        ${selected.includes(feed.id) ? "checked" : ""}>${escape(sourceName(feed.name))}</label>`).join("")}</div></details>`;
  }).join("")}</div>`;
}

function ruleForm(plan, title, submit, type, intent = "", note = "") {
  const draft = type === "create";
  const providers = plan.news_providers || ["google"];
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
    <fieldset><legend>${t("订阅与行情来源")}</legend>${feedOptions(plan.feeds)}</fieldset>
    <fieldset><legend>${t("公开新闻搜索")}</legend>
      ${input("news_query", t("补充公开新闻搜索词（选填）"), plan.news_query || "", 'maxlength="120"', true)}
      <div class="row search-provider-options">${Object.entries(newsProviderNames).map(([id, name]) =>
        `<label class="checkbox"><input type="checkbox" name="news_provider" value="${id}"
          ${providers.includes(id) ? "checked" : ""}>${t(name)}</label>`).join("")}</div>
      <p class="help">${t("填写搜索词后，定期读取所选渠道的新闻。")}</p>
    </fieldset>
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
    news_providers: data.getAll("news_provider"),
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
  const scope = element.dataset.scope === "workspace" ? "workspace" : "task";
  const notes = scope === "workspace" ? state.workspaceMemory : state.memories;
  const note = notes.find(item => item.id === element.dataset.note);
  if (!note) return;
  const action = element.dataset.act;
  const task = state.task;
  if (action === "memory-edit") {
    viewDialog(t("编辑记忆"), `<form data-form="memory-edit" data-scope="${scope}" data-note="${escape(note.id)}">
      ${textArea("text", t("记忆内容"), note.text, 'required maxlength="2000"')}
      ${formError}<div class="form-actions"><button type="submit" class="button primary">${t("保存")}</button></div></form>`);
  } else if (action === "memory-remove") {
    viewDialog(t("删除这条记忆？"), `<form data-form="memory-remove" data-scope="${scope}" data-note="${escape(note.id)}">
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

function openTaskDelete() {
  const task = state.task;
  const title = state.dashboard?.title || task.plan.title;
  viewDialog(t("删除任务"), `<form data-form="task-delete" data-task="${escape(task.id)}">
    <div class="task-delete-target"><strong>${escape(title)}</strong><p class="meta">${escape(task.plan.goal)}</p></div>
    <p class="notice warn">${t("任务的证据、事件、运行记录、对话、记忆和概览设置将一起删除。此操作无法撤销。")}</p>
    ${formError}<div class="form-actions">${button(t("取消"), "close", false, "autofocus")}
      <button type="submit" class="button danger">${t("确认删除")}</button></div>
  </form>`);
}

function dashboardChoices(modules) {
  const order = [...new Set([...modules, ...Object.keys(dashboardModules)])];
  return order.map(key => `<li>
    <label class="checkbox"><input type="checkbox" name="module" value="${key}" ${modules.includes(key) ? "checked" : ""}>
      ${t(dashboardModules[key])}</label>
    <div class="row">${chartModules.has(key) ? pill(t("图表")) : ""}
      ${button(t("上移"), "dashboard-up")}${button(t("下移"), "dashboard-down")}</div>
  </li>`).join("");
}

function openDashboardSettings() {
  const layout = state.dashboard;
  if (!layout) return;
  viewDialog(t("定制概览"), `<form data-form="dashboard" class="dashboard-form">
    ${input("title", t("概览标题"), layout.title, 'required maxlength="64"', true)}
    ${textArea("instruction", t("告诉六扇门你想看什么"), "", `maxlength="500" rows="2" placeholder="${t("例如，都是图；或把来源分布放最前面。")}"`)}
    <div class="row dashboard-generation">
      ${button(t("生成布局"), "dashboard-generate")}
      ${button(t("全图模式"), "dashboard-charts")}
    </div>
    <fieldset><legend>${t("模块与顺序")}</legend>
      <ul class="dashboard-choice-list">${dashboardChoices(layout.modules)}</ul>
    </fieldset>
    <p class="meta dashboard-feedback" role="status"></p>
    ${formError}<div class="form-actions">
      ${layout.custom ? button(t("恢复自动布局"), "dashboard-reset") : ""}
      <button class="button primary" type="submit">${t("应用到该任务")}</button></div>
  </form>`);
}

async function generateDashboardLayout(element, form) {
  const data = new FormData(form);
  const modules = data.getAll("module");
  const title = String(data.get("title") || "").trim();
  const instruction = element.dataset.act === "dashboard-charts" ? "都是图" : data.get("instruction");
  const payload = {instruction};
  if (modules.length && title) payload.layout = {title, modules};
  const feedback = form.querySelector(".dashboard-feedback");
  const error = form.querySelector(".form-error");
  error.textContent = "";
  feedback.textContent = "";
  element.disabled = true;
  try {
    const proposal = await api(apiTask(state.task.id) + "/dashboard/preview", payload);
    form.querySelector('[name="title"]').value = proposal.title;
    form.querySelector(".dashboard-choice-list").innerHTML = dashboardChoices(proposal.modules);
    feedback.textContent = t("模块已生成，请核对后应用。");
  } catch (exception) {
    error.textContent = exception.message;
  } finally {
    element.disabled = false;
  }
}

async function openDeliverySettings() {
  try {
    const settings = await api("/api/delivery");
    if (parseRoute().name !== "inbox") return;
    viewDialog(t("提醒与简报"), `<form class="delivery-form" data-form="delivery">
      <label class="checkbox"><input type="checkbox" name="alerts"
        ${settings.alerts ? "checked" : ""} ${settings.desktop_available ? "" : "disabled"}>${t("重要变化桌面提醒")}</label>
      <label class="checkbox"><input type="checkbox" name="daily" ${settings.daily ? "checked" : ""}>${t("每日自动生成简报")}</label>
      ${input("time", t("简报时间（北京时间）"), settings.time, 'type="time" required')}
      <p class="help">${t("后台服务运行时可发送提醒和生成简报。")}</p>
      ${settings.desktop_available ? "" : `<p class="help">${t("桌面提醒当前支持 macOS。")}</p>`}
      ${settings.last_error ? `<p class="notice warn">${t("上次桌面提醒发送失败，系统将重试。")}</p>` : ""}
      ${formError}<p class="meta delivery-status" role="status"></p>
      <div class="form-actions">${settings.desktop_available ? button(t("发送测试提醒"), "delivery-test") : ""}
        <button type="submit" class="button primary">${t("保存")}</button></div>
    </form>`);
  } catch (error) {
    toast(error.message);
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
  if (action === "task-delete") {
    const key = form.dataset.task;
    await api(apiTask(key) + "/remove", {confirmed: true});
    state.memoryDrafts.delete(key);
    state.chatDrafts.delete(key);
    dialog.close();
    if (parseRoute().id === key) location.hash = "#overview";
    else await refresh();
    toast(t("任务已删除。"));
  } else if (action === "dashboard") {
    await api(apiTask(task.id) + "/dashboard", {title: data.get("title"), modules: data.getAll("module")});
    dialog.close();
    await refresh();
    toast(t("任务概览已更新。"));
  } else if (action === "create") {
    const agent = state.agent;
    const news = agent.preview;
    const plan = makePlan(form);
    const created = news
      ? await api("/api/news/confirm", { preview_id: news.id, plan })
      : await api("/api/tasks", { intent: data.get("intent"), plan });
    const message = news ? t(news.market ? "持续监测已开启，本轮行情已保存到证据库。" : "持续监测已开启，本轮新闻已保存到证据库。")
      : t("已创建监测任务，可导入证据后试跑。");
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
  } else if (action === "delivery") {
    await api("/api/delivery", {alerts: data.get("alerts") === "on", daily: data.get("daily") === "on", time: data.get("time")});
    dialog.close();
    await refresh();
    toast(t("提醒设置已保存。"));
  } else if (["memory-add", "memory-edit", "memory-remove"].includes(action)) {
    const workspace = form.dataset.scope === "workspace";
    const path = workspace ? "/api/memory" : apiTask(task.id) + "/memory";
    const draftKey = workspace ? "workspace" : task.id;
    const text = data.get("text");
    if (action === "memory-add") {
      await api(path, { text });
      if (state.memoryDrafts.get(draftKey) === text) state.memoryDrafts.delete(draftKey);
    } else {
      const notePath = path + "/" + encodeURIComponent(form.dataset.note);
      if (action === "memory-edit") await api(notePath, { text });
      else await api(notePath + "/remove", {});
    }
    if (dialog.contains(form)) dialog.close();
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
  if (event.target.id === "task-chat-input" && state.task) state.chatDrafts.set(state.task.id, event.target.value);
  if (event.target.id === "task-memory" && state.task) {
    const key = event.target.form.dataset.scope === "workspace" ? "workspace" : state.task.id;
    state.memoryDrafts.set(key, event.target.value);
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
  if (event.target.name === "feed") {
    const group = event.target.closest(".feed-options details");
    if (group) {
      const feeds = [...group.querySelectorAll('input[name="feed"]')];
      group.querySelector(".feed-count").textContent = `${feeds.filter(feed => feed.checked).length} / ${feeds.length}`;
    }
  }
  syncDraft(event.target.form);
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    const menu = document.querySelector(".task-options[open]");
    if (menu) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  }
  if (event.key === "Escape" && document.body.classList.contains("menu-open")) {
    closeMenu();
    document.querySelector(".mobile-toggle").focus();
  }
  if (["agent-intent", "task-chat-input"].includes(event.target.id) && event.key === "Enter" && !event.shiftKey &&
      !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    event.target.form.requestSubmit();
  }
});

document.addEventListener("invalid", event => {
  const editor = event.target.closest(".draft-editor");
  if (editor) editor.open = true;
}, true);

document.addEventListener("scroll", event => {
  const scroller = event.target;
  if (!scroller.classList?.contains("task-chat-scroll")) return;
  scroller.closest(".task-chat").querySelector(".chat-latest").hidden =
    latestChatOffset(scroller) - scroller.scrollTop < 80;
}, true);

document.addEventListener("submit", async event => {
  const form = event.target.closest("[data-form]");
  if (!form) return;
  event.preventDefault();
  if (form.dataset.form === "propose") {
    await requestPlan(form);
    return;
  }
  if (form.dataset.form === "task-chat") {
    await submitTaskChat(form);
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
  finally {
    submit.disabled = false;
    submit.textContent = original;
  }
});

document.addEventListener("click", async event => {
  const menu = document.querySelector(".task-options[open]");
  if (menu && !menu.contains(event.target)) menu.open = false;
  const element = event.target.closest("[data-act]");
  if (!element || element.disabled) return;
  const action = element.dataset.act;
  const form = element.closest("form");
  if (action === "task-delete") {
    element.closest(".task-options").open = false;
    openTaskDelete();
  }
  if (action === "create") openComposer("", false, element.dataset.mode === "monitor");
  if (action === "dashboard-settings") openDashboardSettings();
  if (action === "dashboard-generate" || action === "dashboard-charts") await generateDashboardLayout(element, form);
  if (action === "dashboard-up" || action === "dashboard-down") {
    const row = element.closest("li");
    if (action === "dashboard-up" && row.previousElementSibling) row.previousElementSibling.before(row);
    if (action === "dashboard-down" && row.nextElementSibling) row.nextElementSibling.after(row);
    element.focus();
  }
  if (action === "dashboard-reset") {
    element.disabled = true;
    try {
      await api(apiTask(state.task.id) + "/dashboard", {reset: true});
      dialog.close();
      await refresh();
      toast(t("已恢复自动布局。"));
    } catch (error) {
      form.querySelector(".form-error").textContent = error.message;
    } finally {
      element.disabled = false;
    }
  }
  if (action === "task-chat-sample") {
    const input = document.querySelector("#task-chat-input");
    input.value = element.dataset.question;
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.focus();
  }
  if (action === "chat-citation") {
    event.preventDefault();
    const reference = document.getElementById(element.dataset.ref);
    if (!reference) return;
    reference.closest("details").open = true;
    reference.focus({ preventScroll: true });
    reference.scrollIntoView({ block: "nearest" });
  }
  if (action === "chat-latest") {
    const panel = element.closest(".task-chat");
    scrollChatToLatest(panel);
    panel.querySelector(".task-chat-scroll").focus({ preventScroll: true });
  }
  if (action === "close") dialog.close();
  if (action === "menu") element.setAttribute("aria-expanded", String(document.body.classList.toggle("menu-open")));
  if (action === "close-menu") closeMenu();
  if (action === "back-intent") openComposer(state.agent.intent, state.agent.useModel, state.agent.monitoring);
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
  if (action === "chat-memory") {
    viewDialog(t("Agent 记忆"), `<div class="chat-memory-groups">
      ${memoryPanel(state.task, { inDialog: true, scope: "workspace" })}${memoryPanel(state.task, { inDialog: true })}</div>`);
  }
  if (action === "memory-new") {
    const scope = element.dataset.scope === "workspace" ? "workspace" : "task";
    const key = scope === "workspace" ? "workspace" : state.task.id;
    const placeholder = t(scope === "workspace" ? "例如，回复尽量简短" : "例如，关注：安全车、车手变动");
    viewDialog(t(scope === "workspace" ? "新增全局记忆" : "记下一个想法"), `<form data-form="memory-add" data-scope="${scope}">
      ${textArea("text", t("记忆内容"), state.memoryDrafts.get(key) || "",
        `id="task-memory" required maxlength="2000" placeholder="${escape(placeholder)}"`)}
      ${formError}<div class="form-actions"><button type="submit" class="button primary">${t("记下来")}</button></div></form>`);
  }
  if (action === "refresh-inbox") {
    element.disabled = true;
    await refresh();
    return;
  }
  if (action === "delivery-settings") await openDeliverySettings();
  if (action === "delivery-test") {
    const status = form.querySelector(".delivery-status");
    element.disabled = true;
    try {
      await api("/api/delivery/test", {});
      status.textContent = t("测试提醒已提交到系统通知。");
    } catch (error) {
      status.textContent = error.message;
    } finally {
      element.disabled = false;
    }
  }
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
        const item = await api(apiTask(element.dataset.task || task.id) + "/evidence/" + encodeURIComponent(element.dataset.evidence));
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
