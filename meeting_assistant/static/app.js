const state = { meetings: [], selectedId: null, selected: null };

const ICONS = {
  check: '<svg class="icon" viewBox="0 0 24 24"><path d="M4.5 12.5l5 5 10-11"/></svg>',
  alert: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 3.5 4.5 19.5h15L12 3.5Z"/><path d="M12 10v4M12 16.8v.2"/></svg>',
  info: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 7.6v.2"/></svg>',
  close: '<svg class="icon" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  clock: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  trash: '<svg class="icon" viewBox="0 0 24 24"><path d="M4.5 7h15M9 7V4.5h6V7m-8 0 1 13h8l1-13M10 10.5v5.5M14 10.5v5.5"/></svg>',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[ch]));
const formatDate = value => value && value !== "待确认" ? value : "待确认";
const pad2 = n => String(n).padStart(2, "0");
const todayString = () => { const d = new Date(); return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; };
const formatDateTime = value => {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};
const formatNumber = value => Number(value).toLocaleString("zh-CN");
const confidenceText = value => value === null || value === undefined ? "" : `置信度 ${Math.round(Number(value) * 100)}%`;
const reviewStatusText = { succeeded: "待审核", confirmed: "已确认", edited: "已修改后确认", rejected: "已拒绝" };
const sourceKindText = { manual: "人工录入", ai_confirmed: "AI 建议" };

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body?.error?.message || "操作失败，请稍后重试");
    error.code = body?.error?.code;
    error.details = body?.error?.details;
    throw error;
  }
  return body;
}

function toast(message, type = "success") {
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  const icon = type === "error" ? ICONS.alert : ICONS.check;
  node.innerHTML = `${icon}<span></span>`;
  node.querySelector("span").textContent = message;
  $("#toast-stack").append(node);
  setTimeout(() => {
    node.classList.add("leaving");
    setTimeout(() => node.remove(), 220);
  }, 3600);
}

function buttonBusy(button, busy, text = "处理中…") {
  if (!button) return;
  if (busy) { button.dataset.label = button.innerHTML; button.disabled = true; button.textContent = text; }
  else { button.disabled = false; button.innerHTML = button.dataset.label || button.innerHTML; }
}

async function loadHealth() {
  const dot = $("#health-dot");
  try {
    const health = await api("/api/health");
    dot.classList.toggle("ok", Boolean(health.api_key_configured));
    dot.classList.toggle("down", false);
    $("#health-label").textContent = health.api_key_configured ? "AI 服务已就绪" : "AI 服务未配置";
  } catch {
    dot.classList.remove("ok");
    dot.classList.add("down");
    $("#health-label").textContent = "服务连接异常";
  }
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  $("#metric-meetings").textContent = data.meetings ?? data.meeting_count ?? 0;
  $("#metric-pending").textContent = data.pending_actions ?? data.pending ?? 0;
  const rate = data.completion_rate ?? 0;
  $("#metric-rate").textContent = `${Math.round(Number(rate) * (Number(rate) <= 1 ? 100 : 1))}%`;
  $("#metric-reviews").textContent = data.pending_reviews ?? data.pending_ai_reviews ?? 0;
}

function filterQuery() {
  const params = new URLSearchParams();
  const mapping = { q: "#filter-q", owner: "#filter-owner", meeting_type: "#filter-type", status: "#filter-status" };
  Object.entries(mapping).forEach(([key, selector]) => {
    const value = $(selector).value.trim();
    if (value) params.set(key, value);
  });
  return params.toString();
}

async function loadMeetings({ keepSelection = true } = {}) {
  if (!state.meetings.length) {
    $("#meeting-list").innerHTML = '<div class="skeleton-stack"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>';
  }
  const data = await api(`/api/meetings?${filterQuery()}`);
  state.meetings = data.items || [];
  $("#meeting-count").textContent = state.meetings.length;
  renderMeetings();
  if (keepSelection && state.selectedId && state.meetings.some(item => item.id === state.selectedId)) await selectMeeting(state.selectedId);
}

function mountFresh(root) {
  const fresh = !root.dataset.mounted;
  root.dataset.mounted = "1";
  return fresh;
}

function renderMeetings() {
  const root = $("#meeting-list");
  if (!state.meetings.length) {
    root.innerHTML = filterQuery()
      ? '<div class="loading">没有符合条件的会议，试试调整筛选条件</div>'
      : '<div class="loading">还没有会议，点击右上角「新建会议」开始</div>';
    return;
  }
  const fresh = mountFresh(root);
  root.innerHTML = state.meetings.map((item, index) => {
    const pending = item.pending_actions ?? item.action_counts?.pending ?? 0;
    const completed = item.completed_actions ?? item.action_counts?.completed ?? 0;
    const date = item.meeting_date || item.held_at || "";
    return `<article class="meeting-row ${fresh ? "enter " : ""}${item.id === state.selectedId ? "active" : ""}" data-meeting-id="${item.id}" tabindex="0" style="${fresh ? `animation-delay:${Math.min(index * 40, 320)}ms` : ""}">
      <button class="meeting-delete" type="button" data-meeting-id="${item.id}" aria-label="删除会议：${escapeHtml(item.title)}" title="删除会议">${ICONS.trash}</button>
      <h3>${escapeHtml(item.title)}</h3>
      <div class="meeting-row-meta"><span>${escapeHtml(item.meeting_type || "会议")}</span><span>·</span><span>${escapeHtml(date)}</span></div>
      <div class="row-tags">${pending ? `<span class="tag pending">${pending} 待办</span>` : ""}${completed ? `<span class="tag completed">${completed} 完成</span>` : ""}${!pending && !completed ? '<span class="tag">暂无行动项</span>' : ""}</div>
    </article>`;
  }).join("");
  $$(".meeting-row", root).forEach(node => {
    const open = () => selectMeeting(Number(node.dataset.meetingId));
    node.addEventListener("click", open);
    node.addEventListener("keydown", event => {
      if (event.target === node && ["Enter", " "].includes(event.key)) {
        event.preventDefault();
        open();
      }
    });
  });
  $$(".meeting-delete", root).forEach(button => {
    button.addEventListener("click", event => {
      event.stopPropagation();
      const item = state.meetings.find(meeting => meeting.id === Number(button.dataset.meetingId));
      if (item) openDeleteMeetingDialog(item);
    });
  });
}

async function selectMeeting(id) {
  state.selectedId = id;
  state.selected = await api(`/api/meetings/${id}`);
  renderMeetings();
  renderDetail();
}

function renderDetail() {
  const meeting = state.selected;
  $("#empty-state").classList.add("hidden");
  $("#detail-content").classList.remove("hidden");
  $("#detail-title").textContent = meeting.title;
  $("#detail-meta").textContent = `${meeting.meeting_type || "会议"} · ${meeting.meeting_date || meeting.held_at || "日期待确认"}`;
  $("#detail-record").textContent = meeting.content;
  renderActions(meeting.actions || meeting.action_items || []);
  renderAnalyses(meeting.analysis_runs || meeting.runs || []);
}

function clearDetail() {
  state.selectedId = null;
  state.selected = null;
  $("#detail-content").classList.add("hidden");
  $("#empty-state").classList.remove("hidden");
}

function renderActions(actions) {
  const root = $("#action-list");
  if (!actions.length) { root.innerHTML = '<div class="loading">暂无行动项，可手工新增，或等待 AI 建议确认后加入。</div>'; return; }
  const today = todayString();
  const fresh = mountFresh(root);
  root.innerHTML = actions.map((item, index) => {
    const completed = item.status === "completed" || item.status === "done";
    const overdue = !completed && item.due_date && item.due_date !== "待确认" && item.due_date < today;
    const quotes = item.source_quotes || (item.source_quote ? [item.source_quote] : []);
    const sourceText = sourceKindText[item.source_kind] || "人工录入";
    return `<article class="action-card ${fresh ? "enter " : ""}${completed ? "completed" : ""}" style="${fresh ? `animation-delay:${Math.min(index * 35, 280)}ms` : ""}">
      <input class="action-check" type="checkbox" ${completed ? "checked" : ""} data-action-id="${item.id}" data-version="${item.version || 1}" aria-label="切换完成状态">
      <div><h4>${escapeHtml(item.task || item.title)}</h4><div class="action-meta"><span>负责人：${escapeHtml(item.owner || "待确认")}</span><span>截止：${escapeHtml(formatDate(item.due_date))}</span><span>来源：${escapeHtml(sourceText)}</span></div>${quotes.length ? `<div class="source">“${escapeHtml(quotes[0])}”</div>` : ""}</div>
      <div class="action-controls"><span class="tag ${completed ? "completed" : "pending"}">${completed ? "已完成" : "待办"}</span>${overdue ? `<span class="tag overdue">${ICONS.clock}已逾期</span>` : ""}<button class="btn btn-ghost btn-small edit-action" type="button" data-action-id="${item.id}">编辑</button></div>
    </article>`;
  }).join("");
  $$(".action-check", root).forEach(box => box.addEventListener("change", async event => {
    const target = event.currentTarget;
    target.disabled = true;
    try {
      await api(`/api/actions/${target.dataset.actionId}`, { method: "PATCH", body: JSON.stringify({ status: target.checked ? "completed" : "pending", expected_version: Number(target.dataset.version) }) });
      await Promise.all([selectMeeting(state.selectedId), loadDashboard(), loadMeetings({ keepSelection: false })]);
      toast("行动项状态已更新");
    } catch (error) { target.checked = !target.checked; toast(error.message, "error"); }
    finally { target.disabled = false; }
  }));
  $$(".edit-action", root).forEach(button => button.addEventListener("click", () => {
    const item = actions.find(action => action.id === Number(button.dataset.actionId));
    if (item) openActionDialog(item);
  }));
}

function proposalFromRun(run) {
  return run.proposed || run.proposed_json || run.proposed_payload || {};
}

function renderProposalSnapshot(proposal) {
  const decisions = proposal.decisions || [];
  const actions = proposal.action_items || [];
  return `<div class="proposal-snapshot">
    <h5>会议摘要</h5><p>${escapeHtml(proposal.summary || "无")}</p>
    <h5>关键决策</h5>${decisions.length ? `<ul>${decisions.map(item => `<li>${escapeHtml(item.decision || item.text || item)}${item.source_quote ? `<small>原文：${escapeHtml(item.source_quote)}</small>` : ""}</li>`).join("")}</ul>` : '<p class="muted-copy">未识别到明确决策</p>'}
    <h5>行动项</h5>${actions.length ? `<div class="snapshot-actions">${actions.map(item => `<div><strong>${escapeHtml(item.task)}</strong><span>负责人：${escapeHtml(item.owner || "待确认")} · 截止：${escapeHtml(formatDate(item.due_date))}</span>${item.source_quotes?.length ? `<small>原文：${escapeHtml(item.source_quotes.join(" / "))}</small>` : ""}${confidenceText(item.confidence) ? `<em>${escapeHtml(confidenceText(item.confidence))}</em>` : ""}</div>`).join("")}</div>` : '<p class="muted-copy">本次分析未提取到行动项</p>'}
  </div>`;
}

function renderProposalEditor(proposal) {
  const decisions = proposal.decisions || [];
  const actions = proposal.action_items || [];
  return `<div class="proposal-editor">
    <label>会议摘要<textarea data-field="summary" rows="3">${escapeHtml(proposal.summary || "")}</textarea></label>
    <h5>关键决策</h5>
    <div class="decision-grid">${decisions.map((item, index) => `<div class="proposal-decision" data-index="${index}"><input data-field="decision" value="${escapeHtml(item.decision || item.text || "")}" aria-label="决策内容"><input data-field="source_quote" value="${escapeHtml(item.source_quote || "")}" aria-label="决策原文依据"><button class="btn btn-ghost btn-small remove-proposal-decision" type="button">移除</button></div>`).join("") || '<p class="muted-copy">没有可编辑的明确决策</p>'}</div>
    <h5>行动项</h5>
      <div class="proposal-grid">${actions.map((item, index) => `<div class="proposal-item" data-index="${index}">
      <div class="proposal-item-head"><strong>${escapeHtml(item.task)}</strong><div class="proposal-item-tools">${confidenceText(item.confidence) ? `<span>${escapeHtml(confidenceText(item.confidence))}</span>` : ""}<button class="btn btn-ghost btn-small remove-proposal-action" type="button">移除</button></div></div>
      <div class="proposal-fields"><input data-field="task" value="${escapeHtml(item.task)}" aria-label="任务"><input data-field="owner" value="${escapeHtml(item.owner || "待确认")}" aria-label="负责人"><input data-field="due_date" value="${escapeHtml(item.due_date || "待确认")}" aria-label="截止日期"></div>
      <textarea class="proposal-source-input" data-field="source_quotes" rows="2" aria-label="行动项原文依据">${escapeHtml((item.source_quotes || []).join("\n"))}</textarea>
    </div>`).join("") || '<p class="muted-copy">本次分析未提取到行动项</p>'}</div>
  </div>`;
}

function renderAnalyses(runs) {
  const root = $("#analysis-list");
  if (!runs.length) { root.innerHTML = '<div class="loading">尚未进行 AI 分析，点击右上角「AI 结构化分析」开始</div>'; return; }
  const fresh = mountFresh(root);
  const delay = index => (fresh ? `animation-delay:${Math.min(index * 45, 240)}ms` : "");
  root.innerHTML = runs.map((run, index) => {
    if (run.status === "failed") return `<div class="failed-card ${fresh ? "enter" : ""}" style="${delay(index)}">${ICONS.alert}<div><strong>本次分析未完成</strong><div>${escapeHtml(run.error_message || "AI 服务暂时不可用，会议与行动项功能不受影响。")}</div></div></div>`;
    const proposal = proposalFromRun(run);
    const status = run.review_status || run.status;
    const pending = ["pending", "succeeded", "awaiting_review"].includes(status);
    const warnings = run.warnings || [];
    const reviewBody = pending ? `
      <h4>原始 AI 建议（只读）</h4>
      ${renderProposalSnapshot(proposal)}
      <h4>人工编辑区</h4>
      <p class="review-help">「直接确认」采用上方原始建议；若调整了下方内容，请使用「保存修改并确认」。</p>
      ${renderProposalEditor(proposal)}
      <div class="analysis-actions"><button class="btn btn-ghost reject-run" type="button">拒绝建议</button><button class="btn btn-primary confirm-run" type="button">直接确认原始建议</button><button class="btn btn-primary edit-run" type="button">保存修改并确认</button></div>` : `
      <h4>审核结果对照</h4>
      <div class="proposal-comparison"><section><h5>原始 AI 建议</h5>${renderProposalSnapshot(proposal)}</section><section><h5>人工审核后的最终结果</h5>${run.final_payload ? renderProposalSnapshot(run.final_payload) : '<div class="rejected-result">该建议已拒绝，未生成行动项。</div>'}</section></div>`;
    return `<article class="analysis-card ${fresh ? "enter " : ""}${pending ? "" : "reviewed"}" data-run-id="${run.id}" style="${delay(index)}">
      <div class="analysis-head"><div><strong>AI 分析建议</strong><small>${escapeHtml(formatDateTime(run.created_at))}</small></div><span class="tag ${pending ? "pending" : status === "rejected" ? "rejected" : "completed"}">${escapeHtml(reviewStatusText[status] || status)}</span></div>
      <div class="analysis-body">
        ${warnings.length ? `<div class="warning-list">${ICONS.info}<span>分析提示：${warnings.map(escapeHtml).join("；")}</span></div>` : ""}
        ${reviewBody}
      </div>
    </article>`;
  }).join("");

  $$(".analysis-card", root).forEach(card => {
    $(".reject-run", card)?.addEventListener("click", () => reviewRun(card, "reject"));
    $(".confirm-run", card)?.addEventListener("click", () => reviewRun(card, "confirm"));
    $(".edit-run", card)?.addEventListener("click", () => reviewRun(card, "edit"));
    $$(".remove-proposal-decision", card).forEach(button => button.addEventListener("click", () => button.closest(".proposal-decision")?.remove()));
    $$(".remove-proposal-action", card).forEach(button => button.addEventListener("click", () => button.closest(".proposal-item")?.remove()));
  });
}

function editedProposal(card) {
  const run = (state.selected.analysis_runs || state.selected.runs || []).find(item => item.id === Number(card.dataset.runId));
  const source = structuredClone(proposalFromRun(run));
  source.summary = $('[data-field="summary"]', card).value.trim();
  if (!source.summary) throw new Error("会议摘要不能为空");
  source.decisions = $$(".proposal-decision", card).map(item => {
    const original = source.decisions[Number(item.dataset.index)];
    const decision = $('[data-field="decision"]', item).value.trim();
    const sourceQuote = $('[data-field="source_quote"]', item).value.trim();
    if (!decision || !sourceQuote) throw new Error("决策内容和原文依据不能为空");
    return { ...original, decision, source_quote: sourceQuote };
  });
  source.action_items = $$(".proposal-item", card).map(item => {
    const original = source.action_items[Number(item.dataset.index)];
    const task = $('[data-field="task"]', item).value.trim();
    const sourceQuotes = $('[data-field="source_quotes"]', item).value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (!task || !sourceQuotes.length) throw new Error("行动项任务和原文依据不能为空");
    return { ...original, task, owner: $('[data-field="owner"]', item).value.trim() || "待确认", due_date: $('[data-field="due_date"]', item).value.trim() || "待确认", source_quotes: sourceQuotes };
  });
  return source;
}

async function reviewRun(card, decision) {
  const button = $(`.${decision}-run`, card);
  buttonBusy(button, true);
  try {
    const notes = { reject: "人工审核拒绝", confirm: "人工直接确认原始建议", edit: "人工编辑后确认" };
    const payload = { decision, note: notes[decision] };
    if (decision === "edit") payload.final_payload = editedProposal(card);
    await api(`/api/analysis-runs/${card.dataset.runId}/review`, { method: "POST", body: JSON.stringify(payload) });
    await Promise.all([selectMeeting(state.selectedId), loadDashboard(), loadMeetings({ keepSelection: false })]);
    const messages = { reject: "已拒绝该 AI 建议，未生成行动项", confirm: "已确认 AI 建议，行动项已生成", edit: "已确认修改后的建议，行动项已生成" };
    toast(messages[decision]);
  } catch (error) { toast(error.message, "error"); }
  finally { buttonBusy(button, false); }
}

async function analyzeSelected() {
  if (!state.selectedId) return;
  const button = $("#analyze-button");
  buttonBusy(button, true, "AI 分析中…");
  $("#analysis-list").classList.add("analyzing-pulse");
  try {
    await api(`/api/meetings/${state.selectedId}/analyze`, { method: "POST", body: JSON.stringify({ prompt_version: "optimized" }) });
    await Promise.all([selectMeeting(state.selectedId), loadDashboard()]);
    toast("AI 分析完成，请审核建议");
  } catch (error) {
    await selectMeeting(state.selectedId);
    toast(`${error.message}。会议与行动项功能不受影响`, "error");
  } finally {
    buttonBusy(button, false);
    $("#analysis-list").classList.remove("analyzing-pulse");
  }
}

function validateMeetingContent(value, { showEmpty = true } = {}) {
  const record = $('#meeting-form [name="content"]');
  const length = value.length;
  const max = Number(window.APP_CONFIG.maxMeetingChars);
  let message = "";
  if (showEmpty && !value.trim()) message = "会议记录不能为空，请粘贴或输入会议内容。";
  else if (length > max) message = `会议记录过长：当前 ${formatNumber(length)} 字，最多 ${formatNumber(max)} 字。请删减后再保存。`;
  $("#record-error").textContent = message;
  record.classList.toggle("invalid", Boolean(message));
  record.setAttribute("aria-invalid", message ? "true" : "false");
  $("#char-hint").classList.toggle("invalid", length > max);
  return !message;
}

function openMeetingDialog(prefill = {}) {
  const dialog = $("#meeting-dialog");
  const form = $("#meeting-form");
  form.reset();
  form.elements.meeting_date.value = prefill.meeting_date || todayString();
  Object.entries(prefill).forEach(([key, value]) => { if (form.elements[key]) form.elements[key].value = value; });
  $("#char-count").textContent = formatNumber(form.elements.content.value.length);
  validateMeetingContent(form.elements.content.value, { showEmpty: false });
  dialog.showModal();
}

function openDeleteMeetingDialog(item) {
  const dialog = $("#delete-meeting-dialog");
  const form = $("#delete-meeting-form");
  const actionCount = Number(item.action_count ?? 0);
  form.elements.meeting_id.value = item.id;
  $("#delete-meeting-title").textContent = item.title;
  $("#delete-meeting-impact").textContent = actionCount
    ? `关联的 ${actionCount} 条行动项和相关审核记录也会一并删除。`
    : "会议记录和相关审核记录会一并删除。";
  dialog.showModal();
}

function openActionDialog(item = null) {
  const dialog = $("#action-dialog");
  const form = $("#action-form");
  form.reset();
  form.elements.action_id.value = item?.id || "";
  form.elements.expected_version.value = item?.version || "";
  form.elements.task.value = item?.task || item?.title || "";
  form.elements.owner.value = item?.owner || "待确认";
  form.elements.due_date.value = item?.due_date && item.due_date !== "待确认" ? item.due_date : "";
  $("#action-dialog-title").textContent = item ? "编辑行动项" : "新增行动项";
  $("#action-submit").textContent = item ? "保存修改" : "创建行动项";
  $("#action-source-field").classList.toggle("hidden", Boolean(item));
  dialog.showModal();
}

function bindForms() {
  $("#meeting-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form));
    if (!validateMeetingContent(payload.content)) {
      toast($("#record-error").textContent, "error");
      form.elements.content.focus();
      return;
    }
    const submit = $('button[type="submit"]', form);
    buttonBusy(submit, true, "保存中…");
    try {
      const meeting = await api("/api/meetings", { method: "POST", body: JSON.stringify(payload) });
      $("#meeting-dialog").close();
      await Promise.all([loadMeetings({ keepSelection: false }), loadDashboard()]);
      await selectMeeting(meeting.id);
      toast("会议已保存");
    } catch (error) { toast(error.message, "error"); }
    finally { buttonBusy(submit, false); }
  });

  $("#delete-meeting-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const meetingId = Number(form.elements.meeting_id.value);
    const meetingTitle = $("#delete-meeting-title").textContent;
    const deletingSelected = state.selectedId === meetingId;
    const submit = $("#delete-meeting-submit");
    buttonBusy(submit, true, "正在删除…");
    try {
      await api(`/api/meetings/${meetingId}`, { method: "DELETE" });
      $("#delete-meeting-dialog").close();
      if (deletingSelected) clearDetail();
      await Promise.all([loadMeetings({ keepSelection: false }), loadDashboard()]);
      if (deletingSelected && state.meetings.length) await selectMeeting(state.meetings[0].id);
      toast(`“${meetingTitle}”已删除`);
    } catch (error) { toast(error.message, "error"); }
    finally { buttonBusy(submit, false); }
  });

  $("#action-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    const editing = Boolean(data.action_id);
    const payload = { task: data.task, owner: data.owner || "待确认", due_date: data.due_date || "待确认" };
    if (!editing) Object.assign(payload, { source_quotes: data.source_quote ? [data.source_quote] : [], status: "pending" });
    const submit = $("#action-submit");
    buttonBusy(submit, true, editing ? "保存中…" : "创建中…");
    try {
      const result = editing
        ? await api(`/api/actions/${data.action_id}`, { method: "PATCH", body: JSON.stringify({ ...payload, expected_version: Number(data.expected_version) }) })
        : await api(`/api/meetings/${state.selectedId}/actions`, { method: "POST", body: JSON.stringify(payload) });
      $("#action-dialog").close();
      await Promise.all([selectMeeting(state.selectedId), loadDashboard(), loadMeetings({ keepSelection: false })]);
      toast(editing ? "行动项修改已保存" : result.created ? "行动项已创建" : "检测到重复行动项，未重复创建");
    } catch (error) { toast(error.message, "error"); }
    finally { buttonBusy(submit, false); }
  });

  const record = $('#meeting-form [name="content"]');
  record.addEventListener("input", () => {
    $("#char-count").textContent = formatNumber(record.value.length);
    validateMeetingContent(record.value);
  });
}

function bindNavigation() {
  $("#new-meeting-button").addEventListener("click", () => openMeetingDialog());
  $("#focus-create").addEventListener("click", () => openMeetingDialog());
  $("#analyze-button").addEventListener("click", analyzeSelected);
  $("#add-action-button").addEventListener("click", () => openActionDialog());
  $$('[data-close]').forEach(button => button.addEventListener("click", () => $(`#${button.dataset.close}`).close()));
  ["#filter-type", "#filter-status"].forEach(selector => $(selector).addEventListener("change", () => loadMeetings({ keepSelection: false }).catch(error => toast(error.message, "error"))));
  let searchTimer;
  ["#filter-q", "#filter-owner"].forEach(selector => $(selector).addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadMeetings({ keepSelection: false }).catch(error => toast(error.message, "error")), 250); }));
}

async function start() {
  bindForms();
  bindNavigation();
  const now = new Date();
  const weekDays = ["日", "一", "二", "三", "四", "五", "六"];
  $("#today-line").textContent = `${now.getFullYear()} 年 ${now.getMonth() + 1} 月 ${now.getDate()} 日 · 星期${weekDays[now.getDay()]}`;
  try {
    await Promise.all([loadHealth(), loadDashboard(), loadMeetings({ keepSelection: false })]);
    if (state.meetings.length) await selectMeeting(state.meetings[0].id);
  } catch (error) { toast(error.message, "error"); }
}

document.addEventListener("DOMContentLoaded", start);
