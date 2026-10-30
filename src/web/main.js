/**
 * 调测台主控（web 组）：持有页面状态、绑定事件、编排 features 与 render。
 *
 * 状态只在这里：`features/` 全是不带状态的纯函数，`render/` 只把状态画成 DOM。
 * 唯一的数据出入口是 `features/api/vlx-api.js`，本文件不出现裸 `fetch`。
 */
import { createHttpClient } from "../features/api/http-client.js";
import { createVlxApi } from "../features/api/vlx-api.js";
import { normalizeBoxes } from "../features/bbox/bbox-geometry.js";
import {
  buildRunPayload,
  buildSuiteOverrides,
  hydrateForms,
  parseRegionIndexes,
  validateRunInput,
} from "../features/form/form-model.js";
import { indexTasks, taskNumber } from "../features/task/task-catalog.js";
import { FORM_STORE_KEY, PALETTE } from "../shared/contracts.js";
import { createAnnotator } from "./canvas/annotator.js";
import { $ } from "./dom.js";
import { markNavDone, renderNav, setActiveNav } from "./render/nav.js";
import { renderTaskForm } from "./render/form.js";
import { clearResult, renderResult, selectTab, showError } from "./render/result.js";
import { applySuiteResult, renderSuiteTable, resetSuiteRows, setSuiteFoot } from "./render/suite.js";
import { loadFormSnapshot, saveFormSnapshot } from "./storage.js";

const api = createVlxApi({ http: createHttpClient() });
const annotator = createAnnotator({ canvas: $("canvas"), container: $("dropzone"), palette: PALETTE });

/** 页面状态：唯一可变状态源。 */
const state = {
  catalog: { list: [], byId: {} },
  groups: [],
  current: "vqa",
  image: null,
  boxes: [],
  selected: [],
  showBoxes: true,
  forms: {},
  status: null,
  busy: false,
  result: null,
  resultTask: null,
  suiteResults: {},
  wedetectReady: false,
};

/** 当前表单渲染句柄，用于画布点选后回填索引输入框。 */
let formView = null;
/** 状态轮询定时器，避免重复注册。 */
let statusTimer = null;

/* ----------------------------- 基础工具 ----------------------------- */

/**
 * 右下角浮层提示。
 * @param {string} message
 * @param {boolean} [isError]
 */
function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = "toast"), 3200);
}

/** 把当前表单集合写回 localStorage（表单在输入时就会调用，刷新不丢参数）。 */
function persistForms() {
  saveFormSnapshot(FORM_STORE_KEY, state.forms);
}

/* ----------------------------- 元数据与初始化 ----------------------------- */

/**
 * 拉取任务元数据并完成首屏渲染。
 * 异常：接口失败时提示初始化失败，页面保持空态（不白屏）。
 */
async function loadMeta() {
  const meta = await api.getMeta();
  state.catalog = indexTasks(meta.tasks);
  state.groups = meta.groups || [];
  state.forms = hydrateForms(state.catalog.list, loadFormSnapshot(FORM_STORE_KEY));
  state.wedetectReady = Boolean(meta.wedetect_ready);

  renderNav({
    nav: $("nav"),
    catalog: state.catalog,
    groups: state.groups,
    onSelect: selectTask,
    onSuite: () => $("suiteCard").scrollIntoView({ behavior: "smooth", block: "start" }),
  });
  renderSuite();

  selectTask("vqa");
  pollStatus();
  if (!statusTimer) statusTimer = setInterval(pollStatus, 2500);

  // 深链：#demo 直接载入示例图并生成候选框，便于快速开测
  if (location.hash === "#demo") {
    await loadDemo();
    await generateProposals();
  }
}

/**
 * 渲染全量调测表格。
 */
function renderSuite() {
  renderSuiteTable({
    table: $("suiteTable"),
    tasks: state.catalog.list,
    forms: state.forms,
    handlers: {
      onText(taskId, value) {
        state.forms[taskId].text = value;
        persistForms();
      },
      onLang(taskId, value) {
        state.forms[taskId].lang = value;
        persistForms();
      },
      onRowClick(taskId) {
        const result = state.suiteResults[taskId];
        if (!result) return;
        state.result = result;
        state.resultTask = taskId;
        selectTask(taskId);
        annotator.setResult(result);
        $("resultCard").scrollIntoView({ behavior: "smooth", block: "center" });
      },
    },
  });
}

/**
 * 切换当前任务。
 * @param {string} taskId
 */
function selectTask(taskId) {
  state.current = taskId;
  setActiveNav(taskId);
  renderCurrentForm();
  renderResultForTask();
}

/** 渲染当前任务的参数面板。 */
function renderCurrentForm() {
  const task = state.catalog.byId[state.current];
  if (!task) return;
  formView = renderTaskForm({
    task,
    form: state.forms[task.id],
    number: taskNumber(state.catalog, task.id),
    selectedIndexes: state.selected,
    handlers: formHandlers,
  });
}

/** 表单字段变化的统一出口：改 state → 持久化 →（必要时）重渲染。 */
const formHandlers = {
  onText(value) {
    state.forms[state.current].text = value;
    persistForms();
  },
  onLang(lang) {
    state.forms[state.current].lang = lang;
    persistForms();
    renderCurrentForm();
  },
  onNumber(field, value) {
    state.forms[state.current][field] = value;
    persistForms();
  },
  onIndexes(indexes) {
    state.selected = indexes;
    annotator.setSelected(indexes);
    updateSelectedBar();
  },
};

/* ----------------------------- 模型状态 ----------------------------- */

/**
 * 轮询模型状态并刷新右上角状态胶囊。
 * 异常：服务未连上时显示「服务未连接」，不弹错误（轮询噪音大）。
 */
async function pollStatus() {
  try {
    const status = await api.getStatus();
    state.status = status;

    const pill = $("modelPill");
    pill.className = `model-pill ${status.status}`;
    const labels = {
      idle: "未加载",
      loading: "模型加载中…",
      ready: "模型就绪",
      error: "加载失败",
    };
    let text = labels[status.status] || status.status;
    if (status.status === "ready" && status.load_seconds) text += ` · ${status.load_seconds}s`;
    $("modelText").textContent = text;
    $("deviceChip").textContent = `device ${status.device || "—"}`;
    pill.title = status.error || status.message;

    if (status.status === "error") toast(`模型加载失败：${status.error || ""}`, true);
    updateRunButtons();
  } catch (_) {
    $("modelText").textContent = "服务未连接";
    $("modelPill").className = "model-pill error";
  }
}

/** 按模型状态与忙碌态刷新运行按钮可用性。 */
function updateRunButtons() {
  const ready = state.status && state.status.status === "ready";
  $("runBtn").disabled = !ready || state.busy;
  if (!ready) {
    $("runStatus").textContent =
      state.status && state.status.status === "loading" ? "模型加载中，稍候即可运行…" : "";
  } else if (!state.busy && $("runStatus").textContent.startsWith("模型")) {
    $("runStatus").textContent = "";
  }
  $("suiteBtn").disabled = !ready || state.busy;
}

/* ----------------------------- 图像与候选框 ----------------------------- */

/**
 * 上传本地图片。
 * @param {File} file
 */
async function uploadFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) return toast("请选择图片文件", true);
  try {
    const info = await api.uploadImage(file);
    applyImage(info);
    toast(
      `图片已载入：${info.width}×${info.height}` + (info.resized ? "（已缩放到长边 1280）" : "")
    );
  } catch (err) {
    toast(`上传失败：${err.message}`, true);
  }
}

/** 载入 VLX-Seek 自带示例图。 */
async function loadDemo() {
  try {
    const info = await api.loadDemo();
    applyImage(info);
    toast("已载入 VLX-Seek 示例图");
  } catch (err) {
    toast(`示例图载入失败：${err.message}`, true);
  }
}

/**
 * 把新图片落到界面上：清空旧框与旧结果，重新加载画布。
 * @param {import("../shared/contracts.js").ImageMeta} info
 */
function applyImage(info) {
  state.image = info;
  state.boxes = [];
  state.selected = [];
  state.result = null;
  state.resultTask = null;

  $("imageMeta").textContent =
    `${info.filename || "image"} · ${info.width}×${info.height}` +
    (info.resized ? `（原图 ${info.original_size.join("×")}）` : "");
  $("dropzone").classList.add("has-image");
  $("toggleBoxes").disabled = false;
  $("clearBoxesBtn").disabled = true;
  $("proposalBtn").disabled = false;

  annotator.setBoxes([]);
  annotator.setSelected([]);
  annotator.setResult(null);
  updateBoxStat();
  updateSelectedBar();
  renderResultForTask();

  const img = new Image();
  img.onload = () => annotator.setImage(img);
  img.onerror = () => toast("图片渲染失败", true);
  img.src = `/api/images/${info.image_id}?t=${Date.now()}`;
}

/** 刷新候选框计数与相关按钮状态。 */
function updateBoxStat() {
  const count = state.boxes.length;
  $("boxStat").textContent = count
    ? `候选框 ${count} 个`
    : "候选框 0 个（运行时自动用 WeDetect 生成）";
  $("clearBoxesBtn").disabled = !count;
  $("proposalBtn").disabled = !state.image || state.busy;
}

/** 刷新「已选区域」条：chips + 清空链接。 */
function updateSelectedBar() {
  const box = $("selectedIndexes");
  if (!state.selected.length) {
    box.innerHTML = '<span class="muted small">无（区域任务需要至少选中一个框）</span>';
  } else {
    const sorted = [...state.selected].sort((a, b) => a - b);
    box.innerHTML =
      sorted.map((i) => `<span class="chip">obj${i}</span>`).join(" ") +
      ' <a href="#" id="clearSel" class="small" style="color:#3d5afe;margin-left:4px">清空</a>';
    const link = $("clearSel");
    if (link) {
      link.onclick = (event) => {
        event.preventDefault();
        state.selected = [];
        annotator.setSelected([]);
        updateSelectedBar();
      };
    }
  }
  if (formView) formView.syncIndexes(state.selected);
}

/** 点选/取消一个候选框。 */
function toggleSelection(index) {
  if (index < 0) return;
  const pos = state.selected.indexOf(index);
  if (pos >= 0) state.selected.splice(pos, 1);
  else state.selected.push(index);
  annotator.setSelected(state.selected);
  updateSelectedBar();
  const task = state.catalog.byId[state.current];
  if (!(task && task.needs_index)) toast(`已选中候选框 obj${index}（索引仅区域任务使用）`);
}

/** 让后端生成候选框（结果按图缓存）。 */
async function generateProposals() {
  if (!state.image) return toast("请先上传图片", true);
  if (!state.wedetectReady) return toast("WeDetect 权重缺失，请手动传入 bbox_list", true);

  $("proposalBtn").disabled = true;
  $("proposalBtn").textContent = "生成中…";
  try {
    const res = await api.getProposals(state.image.image_id);
    state.boxes = res.boxes;
    state.selected = [];
    annotator.setBoxes(res.boxes);
    annotator.setSelected([]);
    updateBoxStat();
    updateSelectedBar();
    toast(
      `候选框 ${res.count} 个（${
        res.source === "cache" ? "缓存" : `${(res.elapsed_ms / 1000).toFixed(1)}s`
      }）`
    );
  } catch (err) {
    toast(`候选框生成失败：${err.message}`, true);
  } finally {
    $("proposalBtn").textContent = "生成候选框 (WeDetect)";
    $("proposalBtn").disabled = !state.image;
  }
}

/** 应用手动粘贴的候选框 JSON。 */
function applyManualBoxes() {
  const result = normalizeBoxes($("bboxInput").value);
  if (!result.ok) return toast(result.error, true);
  if (!state.image) return toast("请先上传图片，坐标以该图为准", true);

  state.boxes = result.boxes;
  state.selected = [];
  annotator.setBoxes(result.boxes);
  annotator.setSelected([]);
  updateBoxStat();
  updateSelectedBar();
  toast(`已应用 ${result.boxes.length} 个候选框`);
}

/* ----------------------------- 运行 ----------------------------- */

/**
 * 跑当前任务。
 * 异常：`ApiError` 的 detail 同时进结果区与浮层提示。
 */
async function runTask() {
  const task = state.catalog.byId[state.current];
  const form = state.forms[state.current];
  const regionIndexes = task.needs_index
    ? parseRegionIndexes($("indexesInput") ? $("indexesInput").value : "")
    : [];
  const problem = validateRunInput({
    task,
    form,
    imageId: state.image ? state.image.image_id : null,
    regionIndexes,
  });
  if (problem) return toast(problem, true);
  if (!state.status || state.status.status !== "ready") return toast("模型尚未就绪", true);

  const payload = buildRunPayload({
    task,
    form,
    imageId: state.image.image_id,
    boxes: state.boxes,
    regionIndexes,
  });

  setBusy(true, task.id === "reasoning_detection" ? "推理中，思考链约需 20s…" : "运行中…");
  try {
    const res = await api.runTask(task.id, payload);
    state.result = res;
    state.resultTask = task.id;

    // 后端自动生成的候选框回填到画布，后续任务可直接复用
    if (res.boxes_source && res.boxes_source.startsWith("wedetect")) {
      try {
        const proposals = await api.getProposals(state.image.image_id);
        state.boxes = proposals.boxes;
        annotator.setBoxes(proposals.boxes);
        updateBoxStat();
      } catch (_) {
        /* 回填失败不影响本次结果 */
      }
    }

    renderResult(res);
    annotator.setResult(res);
    markNavDone(task.id);
    toast(`${task.name} 完成 · ${res.elapsed_ms}ms`);
  } catch (err) {
    showError(err.message);
    annotator.setResult(null);
    toast(err.message, true);
  } finally {
    setBusy(false);
  }
}

/**
 * 切换忙碌态（禁用运行按钮 + 状态文案）。
 * @param {boolean} busy
 * @param {string} [text]
 */
function setBusy(busy, text) {
  state.busy = busy;
  $("runBtn").disabled = busy;
  $("suiteBtn").disabled = busy;
  $("proposalBtn").disabled = busy || !state.image;
  $("runStatus").textContent = busy ? text || "运行中…" : "";
}

/** 按当前任务决定显示结果还是空态。 */
function renderResultForTask() {
  if (state.result && state.resultTask === state.current) renderResult(state.result);
  else clearResult();
}

/**
 * 串行跑完七个任务。
 */
async function runSuite() {
  if (!state.image) return toast("请先上传图片", true);
  if (!state.status || state.status.status !== "ready") return toast("模型尚未就绪", true);

  const overrides = buildSuiteOverrides(state.catalog.list, state.forms);
  setBusy(true, "全量调测进行中…");
  setSuiteFoot("运行中，reasoning_detection 最慢，请耐心等待…");
  resetSuiteRows();

  try {
    const res = await api.runSuite({
      image_id: state.image.image_id,
      bbox_list: state.boxes.length ? state.boxes : null,
      auto_proposals: true,
      overrides,
    });
    state.suiteResults = {};
    res.results.forEach((result) => (state.suiteResults[result.task] = result));

    const { summary, okTaskIds } = applySuiteResult(res.results);
    okTaskIds.forEach(markNavDone);
    setSuiteFoot(
      `完成 ${summary.okCount}/${summary.total} 个任务 · 总耗时 ${(
        res.total_elapsed_ms / 1000
      ).toFixed(2)}s · 点击任意行查看详情`
    );
    toast(`全量调测结束：${summary.okCount}/${summary.total} 成功`);

    const first = res.results.find((r) => r.ok);
    if (first) {
      state.result = first;
      state.resultTask = first.task;
      selectTask(first.task);
      annotator.setResult(first);
    }
  } catch (err) {
    setSuiteFoot("");
    toast(err.message, true);
    showError(err.message);
  } finally {
    setBusy(false);
  }
}

/* ----------------------------- 事件绑定 ----------------------------- */

/** 绑定所有 DOM 事件。 */
function bind() {
  $("uploadBtn").onclick = () => $("fileInput").click();
  $("fileInput").onchange = (event) => {
    uploadFile(event.target.files[0]);
    event.target.value = "";
  };
  $("demoBtn").onclick = loadDemo;

  const dropzone = $("dropzone");
  dropzone.onclick = (event) => {
    if (!state.image) return $("fileInput").click();
    if (event.target !== $("canvas")) return;
    toggleSelection(annotator.hitTestEvent(event));
  };
  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
    uploadFile(event.dataTransfer.files[0]);
  });

  $("canvas").addEventListener("mousemove", (event) => annotator.updateHover(event));
  $("canvas").addEventListener("mouseleave", () => annotator.clearHover());

  $("proposalBtn").onclick = generateProposals;
  $("clearBoxesBtn").onclick = () => {
    state.boxes = [];
    state.selected = [];
    state.result = null;
    annotator.setBoxes([]);
    annotator.setSelected([]);
    annotator.setResult(null);
    updateBoxStat();
    updateSelectedBar();
  };
  $("toggleBoxes").onchange = (event) => {
    state.showBoxes = event.target.checked;
    annotator.setShowBoxes(state.showBoxes);
  };
  $("applyBboxBtn").onclick = applyManualBoxes;

  $("runBtn").onclick = runTask;
  $("suiteBtn").onclick = runSuite;
  $("reloadBtn").onclick = async () => {
    try {
      await api.loadModel();
      toast("已触发模型加载");
      pollStatus();
    } catch (err) {
      toast(err.message, true);
    }
  };

  $("resultTabs").onclick = (event) => {
    const tab = event.target.closest(".tab");
    if (tab) selectTab(tab.dataset.tab);
  };

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (!annotator.hasImage()) return;
      annotator.resizeAndDraw();
    }, 120);
  });
}

bind();
loadMeta().catch((err) => {
  toast(`初始化失败：${err.message}`, true);
  $("modelText").textContent = "初始化失败";
});
