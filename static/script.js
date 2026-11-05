/* =========================================================
   RE:AIR - 화면 동작
   STEP 3: 화면 전환 + 시연용 데이터로 결과 표시
   (STEP 5~7에서 실제 AI 호출로 교체합니다)
   ========================================================= */

// ---------- 작은 도우미 함수들 ----------
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// AI가 만든 글자를 화면에 넣을 때 HTML 코드로 해석되지 않도록 안전하게 바꿔 줍니다.
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const list = (arr) => (Array.isArray(arr) ? arr : []).map((t) => `<li>${esc(t)}</li>`).join("");

// ---------- 앱 상태 (지금까지 입력/생성된 내용 저장) ----------
const state = {
  input: null,       // 사용자가 입력한 상황
  result: null,      // AI 분석 + 전략 3가지
  selectedId: null,  // 선택한 전략 (A/B/C)
  plan: null,        // 일정표 + 메시지 + 체크리스트
  resultDemo: false, // 분석 결과가 시연용 데이터인지
  planDemo: false,   // 일정·메시지가 시연용 데이터인지
  resultSeconds: 0,  // AI 분석에 걸린 시간
  planSeconds: 0,    // AI 계획 생성에 걸린 시간
};

let demoCache = null;
async function getDemo() {
  if (!demoCache) {
    const res = await fetch("/static/demo_data.json");
    demoCache = await res.json();
  }
  return demoCache;
}

// =========================================================
// 화면 전환
// =========================================================
const STEP_ORDER = ["input", "result", "plan", "action"];

function showView(name) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  document.body.dataset.view = name;

  const stepIndex = STEP_ORDER.indexOf(name);
  $("#stepper").hidden = stepIndex === -1;
  $$("#stepper li").forEach((li, i) => {
    li.classList.toggle("current", i === stepIndex);
    li.classList.toggle("done", i < stepIndex);
  });

  const isDemo = name === "result" ? state.resultDemo : state.planDemo;
  $$("[data-demo-banner]").forEach((b) => (b.hidden = !isDemo));
  updateAIBadges();
  window.scrollTo({ top: 0 });
}

// =========================================================
// 로딩 화면
// =========================================================
const LOADING_STEPS = {
  analyze: {
    title: "AI가 분석하고 있어요",
    steps: ["상황 이해하기", "연쇄 피해 분석하기", "복구 전략 3가지 만들기"],
    interval: 4000,
    hint: "보통 10~20초 걸려요",
  },
  plan: {
    title: "복구 계획을 만들고 있어요",
    steps: ["일정 다시 짜기", "3개 국어 문의문 쓰기", "할 일 정리하기"],
    interval: 4000,
    hint: "보통 10~20초 걸려요",
  },
};

async function withLoading(kind, task) {
  const { title, steps, interval, hint } = LOADING_STEPS[kind];
  $("#loading-title").textContent = title;
  $("#loading-hint").textContent = hint || "";
  const ul = $("#loading-steps");
  ul.innerHTML = steps.map((s) => `<li>${esc(s)}</li>`).join("");
  const items = $$("li", ul);
  let i = 0;
  const tick = () => {
    items.forEach((li, idx) => {
      li.classList.toggle("done", idx < i);
      li.classList.toggle("active", idx === i);
    });
  };
  tick();
  const timer = setInterval(() => {
    if (i < items.length - 1) { i++; tick(); }
  }, interval || 1300);

  $("#loading").hidden = false;
  try {
    return await task();
  } finally {
    clearInterval(timer);
    $("#loading").hidden = true;
  }
}

// =========================================================
// 입력 폼
// =========================================================
function collectInput() {
  const f = new FormData($("#trip-form"));
  const get = (name) => (f.get(name) || "").trim();
  return {
    problem_type: get("problem_type"),
    location: get("location"),
    destination: get("destination"),
    departure_time: get("departure_time"),
    remaining_time: get("remaining_time"),
    situation: get("situation"),
    budget: get("budget"),
    priority: get("priority"),
  };
}

async function fillExample() {
  const ex = (await getDemo()).example_input;
  const form = $("#trip-form");
  for (const [key, value] of Object.entries(ex)) {
    const fields = form.elements[key];
    if (!fields) continue;
    if (fields instanceof RadioNodeList && fields[0]?.type === "radio") {
      fields.forEach((r) => (r.checked = r.value === value));
    } else {
      fields.value = value;
    }
  }
  clearAllErrors();
  toast("예시 상황을 입력했어요");
}

// ---------- 입력값 검사 (STEP 4) ----------
const RULES = [
  { name: "problem_type",   message: "문제 유형을 선택해 주세요." },
  { name: "location",       message: "현재 위치를 입력해 주세요." },
  { name: "destination",    message: "목적지를 입력해 주세요." },
  { name: "departure_time", message: "출발 예정 시간을 입력해 주세요." },
  { name: "situation",      message: "지금 상황을 적어 주세요.", min: 15 },
  { name: "priority",       message: "가장 중요한 조건을 골라 주세요." },
];

function validateInput(input) {
  const errors = {};
  for (const rule of RULES) {
    const value = input[rule.name] || "";
    if (!value) errors[rule.name] = rule.message;
    else if (rule.min && value.length < rule.min) errors[rule.name] = `조금만 더 자세히 적어 주세요. (${rule.min}자 이상)`;
  }
  return errors;
}

// 입력 항목이 들어 있는 흰 카드(.field)를 찾습니다.
function fieldBox(name) {
  const el = $("#trip-form").elements[name];
  const node = el instanceof RadioNodeList ? el[0] : el;
  return node?.closest(".field");
}

function setError(name, message) {
  const box = fieldBox(name);
  if (!box) return;
  box.classList.add("has-error");
  let msg = $(".error-msg", box);
  if (!msg) {
    msg = document.createElement("p");
    msg.className = "error-msg";
    box.appendChild(msg);
  }
  msg.textContent = message;
}

function clearError(name) {
  const box = fieldBox(name);
  if (!box) return;
  box.classList.remove("has-error");
  $(".error-msg", box)?.remove();
}

function clearAllErrors() {
  RULES.forEach((r) => clearError(r.name));
}

function showErrors(errors) {
  clearAllErrors();
  const names = Object.keys(errors);
  names.forEach((name) => setError(name, errors[name]));
  // 첫 번째 오류 항목으로 화면 이동
  const first = fieldBox(names[0]);
  if (first) {
    first.scrollIntoView({ behavior: "smooth", block: "center" });
    const el = $("#trip-form").elements[names[0]];
    (el instanceof RadioNodeList ? el[0] : el)?.focus({ preventScroll: true });
  }
}

// 사용자가 다시 입력하면 해당 항목의 오류 표시를 지웁니다.
["input", "change"].forEach((type) =>
  $("#trip-form").addEventListener(type, (e) => {
    if (e.target.name) clearError(e.target.name);
  })
);

// ---------- 서버와 통신 ----------
async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* 응답이 JSON이 아닐 때 */ }
  return { ok: res.ok, status: res.status, data };
}

// ---------- AI 오류 안내 창 ----------
// 오류가 나면 [다시 시도] / [시연용 데이터로 보기]를 눌렀을 때 할 일을 기억해 둡니다.
let errorActions = { retry: null, demo: null };

function showAIError(message, actions) {
  errorActions = actions;
  $("#error-text").textContent = message;
  $("#error-panel").hidden = false;
}

function closeAIError() {
  $("#error-panel").hidden = true;
}

// ---------- 제출 ----------
$("#trip-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = collectInput();

  // 1) 브라우저에서 먼저 검사
  const errors = validateInput(input);
  if (Object.keys(errors).length) {
    showErrors(errors);
    return;
  }
  await runAnalyze(input);
});

// 2) 서버 → 생성형 AI로 상황 분석 + 전략 3가지 요청
async function runAnalyze(input) {
  let res;
  try {
    res = await withLoading("analyze", () => postJSON("/api/analyze", input));
  } catch {
    res = { ok: false, data: { error: "서버에 연결할 수 없어요. 서버가 켜져 있는지 확인해 주세요." } };
  }

  // 입력값 문제 (빈칸 등)
  if (!res.ok && res.data.errors) {
    showErrors(res.data.errors);
    return;
  }

  // AI 오류 → 안내 창 (다시 시도 / 시연용 데이터)
  if (!res.ok) {
    showAIError(res.data.error || "잠시 후 다시 시도해 주세요.", {
      retry: () => runAnalyze(input),
      demo: () => showDemoResult(res.data.input || input),
    });
    return;
  }

  // 3) 성공: AI 결과 표시
  state.input = res.data.input;
  state.result = { analysis: res.data.analysis, strategies: res.data.strategies };
  state.resultDemo = false;
  state.resultSeconds = res.data.seconds || 0;
  renderResult();
  showView("result");
}

async function showDemoResult(input) {
  const demo = await getDemo();
  state.input = input;
  state.result = { analysis: demo.analysis, strategies: demo.strategies };
  state.resultDemo = true;
  renderResult();
  showView("result");
}

// =========================================================
// 화면 3: 분석 + 전략
// =========================================================
const LEVEL_CLASS = { 높음: "level-high", 보통: "level-mid", 낮음: "level-low" };
const LEVEL_NUM = { 낮음: 1, 보통: 2, 높음: 3 };

function meter(label, level) {
  const n = LEVEL_NUM[level] || 0;
  const bars = [1, 2, 3].map((k) => `<i class="${k <= n ? "on" : ""}"></i>`).join("");
  return `<div class="meter"><small>${esc(label)}</small><b>${esc(level || "-")}</b><div class="meter-bar">${bars}</div></div>`;
}

function renderResult() {
  const { input } = state;
  const { analysis, strategies } = state.result;

  $("#input-summary").innerHTML = [
    `<span class="chip chip-red">${esc(input.problem_type)}</span>`,
    `<span class="chip"><b>경로</b>${esc(input.location)} → ${esc(input.destination)}</span>`,
    `<span class="chip"><b>출발 예정</b>${esc(input.departure_time)}</span>`,
    `<span class="chip"><b>예산</b>${esc(input.budget)}</span>`,
    `<span class="chip"><b>우선순위</b>${esc(input.priority)}</span>`,
  ].join("");

  $("#analysis-summary").textContent = analysis.summary;
  $("#analysis-problems").innerHTML = list(analysis.problems);
  $("#urgent-title").textContent = analysis.urgent?.title || "";
  $("#urgent-reason").textContent = analysis.urgent?.reason || "";

  $("#impact-grid").innerHTML = (analysis.impacts || [])
    .map((m) => `
      <div class="impact">
        <div class="impact-head"><b>${esc(m.area)}</b><span class="level ${LEVEL_CLASS[m.level] || "level-mid"}">${esc(m.level)}</span></div>
        <p>${esc(m.detail)}</p>
      </div>`)
    .join("");

  $("#check-first").innerHTML = list(analysis.check_first);

  $("#strategy-grid").innerHTML = strategies
    .map((s) => `
      <article class="card strategy ${s.recommended ? "recommended" : ""}">
        ${s.recommended ? `<span class="rec-badge">AI 추천</span>` : ""}
        <div class="strategy-top"><span class="gate">GATE</span><span class="tag tag-${esc(s.id).toLowerCase()}">${esc(s.id)}</span><span class="label">${esc(s.label)}</span></div>
        <h4>${esc(s.title)}</h4>
        <p class="desc">${esc(s.description)}</p>
        ${s.recommended && s.fit_reason ? `<p class="fit">${esc(s.fit_reason)}</p>` : ""}
        <div class="meters">
          ${meter("비용 부담", s.cost_level)}${meter("귀국 속도", s.speed_level)}${meter("일정 유지", s.keep_level)}
        </div>
        <div class="s-section s-actions"><h5>이렇게 하면 돼요</h5><ul>${list(s.actions)}</ul></div>
        <details class="more">
          <summary>장단점 · 주의사항 보기</summary>
          <div class="s-section s-pros"><h5>장점</h5><ul>${list(s.pros)}</ul></div>
          <div class="s-section s-cons"><h5>단점</h5><ul>${list(s.cons)}</ul></div>
          <div class="s-section s-cautions"><h5>주의사항</h5><ul>${list(s.cautions)}</ul></div>
        </details>
        <button class="btn ${s.recommended ? "btn-primary" : "btn-secondary"} btn-block" data-action="select-strategy" data-id="${esc(s.id)}">
          ${esc(s.id)}안으로 할게요
        </button>
      </article>`)
    .join("");
}

// 전략 선택 → 서버 → 생성형 AI로 일정표 + 문의문 + 체크리스트 요청 (STEP 7)
async function selectStrategy(id) {
  state.selectedId = id;
  const strategy = state.result.strategies.find((s) => s.id === id);

  // 시연용 분석 결과를 보고 있다면 계획도 시연용 데이터로 보여 줍니다. (AI 호출 안 함)
  if (state.resultDemo) return showDemoPlan(id);

  let res;
  try {
    res = await withLoading("plan", () => postJSON("/api/plan", { input: state.input, strategy }));
  } catch {
    res = { ok: false, data: { error: "서버에 연결할 수 없어요. 서버가 켜져 있는지 확인해 주세요." } };
  }

  if (!res.ok) {
    showAIError(res.data.error || "잠시 후 다시 시도해 주세요.", {
      retry: () => selectStrategy(id),
      demo: () => showDemoPlan(id),
    });
    return;
  }

  state.plan = { itinerary: res.data.itinerary, messages: res.data.messages, checklist: res.data.checklist };
  state.planDemo = false;
  state.planSeconds = res.data.seconds || 0;
  renderPlan();
  renderAction();
  showView("plan");
}

async function showDemoPlan(id) {
  const plans = (await getDemo()).plans;
  state.plan = plans[id] || plans.A;
  state.planDemo = true;
  renderPlan();
  renderAction();
  showView("plan");
}

// =========================================================
// 화면 4: 일정표
// =========================================================
const STATUS_CLASS = { 유지: "s-keep", 변경: "s-change", 추가: "s-add", 취소: "s-cancel" };
const ROW_CLASS = { 변경: "row-change", 취소: "row-cancel" };

function strategyPill() {
  const s = state.result.strategies.find((x) => x.id === state.selectedId);
  return s ? `${esc(s.id)}안 · ${esc(s.label)}` : "";
}

// 일정표 위의 탑승권 모양 카드 (출발지 ✈ 목적지 + 선택한 전략)
function renderBoardingPass() {
  const { input } = state;
  const s = state.result.strategies.find((x) => x.id === state.selectedId) || {};
  $("#boarding-pass").innerHTML = `
    <div class="bp-main">
      <div class="bp-city"><small>FROM</small><b>${esc(input.location)}</b></div>
      <div class="bp-plane">✈</div>
      <div class="bp-city"><small>TO</small><b>${esc(input.destination)}</b></div>
    </div>
    <div class="bp-stub">
      <small>GATE</small><b>${esc(s.id || "-")}</b>
      <span>${esc(s.label || "")}</span>
    </div>`;
}

function renderPlan() {
  const { itinerary } = state.plan;
  renderBoardingPass();
  $("#plan-summary").textContent = itinerary.summary;
  $("#itinerary-body").innerHTML = (itinerary.rows || [])
    .map((r) => `
      <tr class="${ROW_CLASS[r.status] || ""}">
        <td class="time">${esc(r.time)}</td>
        <td class="old">${esc(r.original)}</td>
        <td class="arrow">→</td>
        <td class="new">${esc(r.new)}</td>
        <td class="state"><span class="status ${STATUS_CLASS[r.status] || "s-keep"}">${esc(r.status)}</span></td>
      </tr>`)
    .join("");
}

// =========================================================
// 화면 5: 문의 메시지 + 체크리스트
// =========================================================
const LANGS = [
  { key: "ko", label: "한국어" },
  { key: "en", label: "English" },
  { key: "ja", label: "日本語" },
];

function renderAction() {
  const { messages, checklist } = state.plan;
  $("#action-strategy-pill").innerHTML = strategyPill();

  $("#message-list").innerHTML = (messages || [])
    .map((m, idx) => `
      <article class="card message" data-msg="${idx}" data-lang="en">
        <div class="message-head"><small>To. ${esc(m.target)}</small><h4>${esc(m.purpose)}</h4></div>
        <div class="lang-tabs">
          ${LANGS.map((l) => `<button class="lang-tab ${l.key === "en" ? "active" : ""}" data-action="lang" data-lang="${l.key}">${l.label}</button>`).join("")}
        </div>
        <div class="message-body">${esc(m.en)}</div>
        <div class="message-foot">
          <button class="btn btn-soft btn-sm" data-action="big">크게 보기</button>
          <button class="btn btn-soft btn-sm" data-action="copy">복사</button>
        </div>
      </article>`)
    .join("");

  const WHEN_CLASS = { "지금 즉시": "when-now", "1시간 이내": "when-hour" };
  $("#checklist").innerHTML = (checklist || [])
    .slice()
    .sort((a, b) => (a.priority ?? 99) - (b.priority ?? 99))
    .map((c) => `
      <li class="check-item">
        <label>
          <input type="checkbox">
          <div>
            <span class="when ${WHEN_CLASS[c.when] || "when-day"}">${esc(c.when)}</span>
            <b>${esc(c.task)}</b>
            ${c.detail ? `<p>${esc(c.detail)}</p>` : ""}
          </div>
        </label>
      </li>`)
    .join("");
  updateProgress();
}

function updateProgress() {
  const boxes = $$("#checklist input[type=checkbox]");
  const done = boxes.filter((b) => b.checked).length;
  $("#check-progress-text").textContent = `${done} / ${boxes.length} 완료`;
  $("#check-progress-bar").style.width = boxes.length ? `${(done / boxes.length) * 100}%` : "0";
}

function switchLang(card, lang) {
  const m = state.plan.messages[Number(card.dataset.msg)];
  card.dataset.lang = lang;
  $(".message-body", card).textContent = m[lang] || "";
  $$(".lang-tab", card).forEach((t) => t.classList.toggle("active", t.dataset.lang === lang));
}

async function copyMessage(card) {
  await copyText($(".message-body", card).textContent);
  toast("복사했어요");
}

// =========================================================
// STEP 8: AI 배지 / 크게 보기 / 전체 계획 복사
// =========================================================
function updateAIBadges() {
  const info = {
    result: { demo: state.resultDemo, seconds: state.resultSeconds },
    plan: { demo: state.planDemo, seconds: state.planSeconds },
  };
  $$("[data-ai-badge]").forEach((el) => {
    const { demo, seconds } = info[el.dataset.aiBadge];
    el.hidden = demo || !seconds;
    el.textContent = `✨ AI가 ${seconds}초 만에 생성`;
  });
}

function showBig(card) {
  const m = state.plan.messages[Number(card.dataset.msg)];
  $("#big-target").textContent = `To. ${m.target}`;
  $("#big-text").textContent = $(".message-body", card).textContent;
  $("#big-text").lang = card.dataset.lang; // 일본어 줄바꿈 처리용
  $("#big-view").hidden = false;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

function buildPlanText() {
  const { input, plan } = state;
  const s = state.result.strategies.find((x) => x.id === state.selectedId) || {};
  const lines = [
    `[RE:AIR 여행 복구 계획]`,
    `${input.problem_type} · ${input.location} → ${input.destination}`,
    `선택한 전략: ${s.id}안 ${s.label} - ${s.title}`,
    ``,
    `■ 새 일정`,
    ...plan.itinerary.rows.map((r) => `- ${r.time} [${r.status}] ${r.new}`),
    ``,
    `■ 할 일`,
    ...plan.checklist.map((c) => `${c.priority}. (${c.when}) ${c.task}`),
    ``,
    `■ 문의 메시지`,
    ...plan.messages.flatMap((m) => [`▷ ${m.target} - ${m.purpose}`, `KO: ${m.ko}`, `EN: ${m.en}`, `JA: ${m.ja}`, ``]),
    `※ AI 제안이에요. 실제 항공편·숙소 정보는 직접 확인해 주세요.`,
  ];
  return lines.join("\n");
}

// =========================================================
// 알림(토스트)
// =========================================================
let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2000);
}

// =========================================================
// 다시 시작
// =========================================================
function restart() {
  $("#trip-form").reset();
  clearAllErrors();
  Object.assign(state, { input: null, result: null, selectedId: null, plan: null, resultDemo: false, planDemo: false, resultSeconds: 0, planSeconds: 0 });
  showView("input");
}

// =========================================================
// 버튼 클릭 처리 (data-action 속성으로 구분)
// =========================================================
document.addEventListener("click", async (e) => {
  // 완료된 단계 표시를 누르면 그 화면으로 돌아가기
  const stepLi = e.target.closest("#stepper li.done");
  if (stepLi) return showView(stepLi.dataset.step);

  const btn = e.target.closest("[data-action]");
  if (!btn) return;

  switch (btn.dataset.action) {
    case "go-landing":      showView("landing"); break;
    case "start":           showView("input"); break;
    case "demo-start":      showView("input"); await fillExample(); break;
    case "fill-example":    await fillExample(); break;
    case "select-strategy": await selectStrategy(btn.dataset.id); break;
    case "back-result":     showView("result"); break;
    case "go-action":       showView("action"); break;
    case "back-plan":       showView("plan"); break;
    case "restart":         restart(); break;
    case "retry":           closeAIError(); await errorActions.retry?.(); break;
    case "use-demo":        closeAIError(); await errorActions.demo?.(); break;
    case "close-error":     closeAIError(); break;
    case "big":             showBig(btn.closest(".message")); break;
    case "close-big":       $("#big-view").hidden = true; break;
    case "install":         await installApp(); break;
    case "copy-all":        await copyText(buildPlanText()); toast("전체 계획을 복사했어요"); break;
    case "lang":            switchLang(btn.closest(".message"), btn.dataset.lang); break;
    case "copy":            await copyMessage(btn.closest(".message")); break;
  }
});

document.addEventListener("change", (e) => {
  if (e.target.matches("#checklist input[type=checkbox]")) updateProgress();
});

// Esc 키로 크게 보기 / 오류 창 닫기
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  $("#big-view").hidden = true;
  closeAIError();
});

// =========================================================
// 앱 설치 (PWA)
// =========================================================
// 1) 서비스 워커 등록: 앱 화면을 저장해 두어 설치·오프라인 실행이 가능해집니다.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

// 2) 브라우저가 '설치 가능'하다고 알려 주면 [앱 설치] 버튼을 보여 줍니다.
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $$(".install-btn").forEach((b) => (b.hidden = false));
});

async function installApp() {
  if (!installPrompt) return;
  installPrompt.prompt();
  const { outcome } = await installPrompt.userChoice;
  if (outcome === "accepted") toast("RE:AIR 앱을 설치했어요");
  installPrompt = null;
  $$(".install-btn").forEach((b) => (b.hidden = true));
}

window.addEventListener("appinstalled", () => {
  $$(".install-btn").forEach((b) => (b.hidden = true));
});
