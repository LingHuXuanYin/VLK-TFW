/**
 * 结果面板渲染（web 组）：统计、警告、答案高亮、候选框表格、提示词、原始 JSON。
 *
 * 四个 tab 的容器 id 定义在 index.html；这里只负责往里填内容。
 */
import { colorForLabel, collectLabels } from "../../features/bbox/bbox-geometry.js";
import { PALETTE } from "../../shared/contracts.js";
import { $, esc } from "../dom.js";

/**
 * 清空结果区（切到没跑过的任务时调用）。
 */
export function clearResult() {
  $("resultSubtitle").textContent = "尚未运行";
  $("stats").innerHTML = "";
  $("warnings").innerHTML = "";
  answerBox().innerHTML = '<span class="muted">运行后在此显示模型原始回复。</span>';
  $("boxTable").innerHTML = "";
  $("promptBox").textContent = "";
  $("rawBox").textContent = "";
}

/**
 * 渲染一次成功的结果。
 * @param {import("../../shared/contracts.js").TaskResult} res
 * 边界：`res.ok` 为假时直接返回，由 `showError` 负责失败展示。
 */
export function renderResult(res) {
  if (!res || !res.ok) return;
  $("resultSubtitle").textContent = `${res.task_name} · ${new Date().toLocaleTimeString("zh-CN", {
    hour12: false,
  })}`;

  const stats = [
    ["耗时", `${res.elapsed_ms} ms`],
    ["Tokens", `${res.prompt_tokens} → ${res.completion_tokens}`],
    ["返回框", (res.result_bbox_list || []).length],
    ["候选框", `${res.boxes_count}（${res.boxes_source}）`],
    [
      "围栏",
      res.fence_applied
        ? `${res.fence_vertices} 顶点${res.fence_cropped ? " · 裁剪推理" : " · 整图推理"}`
        : "未启用",
    ],
    ["lang", res.lang],
    ["max_new_tokens", res.max_new_tokens],
  ];
  $("stats").innerHTML = stats
    .map(([key, value]) => `<div class="stat">${key}<b>${esc(value)}</b></div>`)
    .join("");

  $("warnings").innerHTML = (res.warnings || [])
    .map((warn) => `<div class="warn-item"><span>⚠</span><span>${esc(warn)}</span></div>`)
    .join("");

  answerBox().innerHTML = renderAnswer(res.answer);
  renderBoxTable(res);
  $("promptBox").textContent = res.prompt || "(无)";
  $("rawBox").textContent = JSON.stringify(buildRawView(res), null, 2);

  selectTab("answer");
}

/**
 * 渲染失败态：把后端 `detail` 放到警告区。
 * @param {string} message
 */
export function showError(message) {
  $("resultSubtitle").textContent = "运行失败";
  $("stats").innerHTML = "";
  $("warnings").innerHTML = `<div class="warn-item err"><span>✕</span><span>${esc(message)}</span></div>`;
  answerBox().innerHTML = '<span class="muted">请求未成功，请查看上方错误信息。</span>';
  $("boxTable").innerHTML = "";
  $("promptBox").textContent = "";
  $("rawBox").textContent = "";
  selectTab("answer");
}

/**
 * 切换结果面板 tab。
 * @param {"answer"|"boxes"|"prompt"|"raw"} name
 */
export function selectTab(name) {
  document.querySelectorAll("#resultTabs .tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.panel !== name);
  });
}

/**
 * 把 `<ground>/<objects>/<think>/<answer>` 与 `<objN>` 标成分色高亮。
 * @param {string} text 模型原始回复
 * @returns {string} 已转义并注入 span 的 HTML
 * 边界：先整体转义再替换，避免模型输出里的标签被当作真实 HTML 执行。
 */
function renderAnswer(text) {
  let html = esc(text || "");
  html = html.replace(/&lt;(\/?)(ground|objects|think|answer)&gt;/g, (_m, slash, tag) => {
    const cls = tag === "objects" ? "ground" : tag;
    return `<span class="tag tag-${cls}">&lt;${slash}${tag}&gt;</span>`;
  });
  html = html.replace(/&lt;obj(\d+)&gt;/g, (_m, index) => `<span class="tag tag-obj">&lt;obj${index}&gt;</span>`);
  return html;
}

/**
 * 渲染返回框表格。
 * @param {import("../../shared/contracts.js").TaskResult} res
 */
function renderBoxTable(res) {
  const rows = res.result_bbox_list || [];
  const labels = collectLabels(rows);
  const body = rows.length
    ? rows
        .map((box) => {
          const color = colorForLabel(box.label, labels, PALETTE);
          return `<tr>
              <td class="mono">${esc(box.object_index)}</td>
              <td><span class="swatch" style="background:${color}"></span>${esc(box.label)}</td>
              <td class="mono">${box.xmin.toFixed(1)}</td>
              <td class="mono">${box.ymin.toFixed(1)}</td>
              <td class="mono">${box.xmax.toFixed(1)}</td>
              <td class="mono">${box.ymax.toFixed(1)}</td>
            </tr>`;
        })
        .join("")
    : `<tr><td colspan="6" style="text-align:center;color:#98a2b3;padding:18px">${
        res.task === "vqa" ? "vqa 为纯文本任务，result_bbox_list 恒为空" : "无返回框"
      }</td></tr>`;

  $("boxTable").innerHTML = `<thead><tr>
        <th>object_index</th><th>label</th><th>xmin</th><th>ymin</th><th>xmax</th><th>ymax</th>
      </tr></thead><tbody>${body}</tbody>`;
}

/**
 * 「原始 JSON」面板的内容：只挑排查用得上的字段，不把整个响应原样倒出来。
 * @param {import("../../shared/contracts.js").TaskResult} res
 * @returns {object}
 */
function buildRawView(res) {
  return {
    task: res.task,
    answer: res.answer,
    result_bbox_list: res.result_bbox_list,
    prompt_tokens: res.prompt_tokens,
    completion_tokens: res.completion_tokens,
    elapsed_ms: res.elapsed_ms,
    request: {
      text: res.text,
      lang: res.lang,
      max_new_tokens: res.max_new_tokens,
      temperature: res.temperature,
      top_p: res.top_p,
      boxes_count: res.boxes_count,
      fence_applied: res.fence_applied,
      fence_vertices: res.fence_vertices,
      fence_cropped: res.fence_cropped,
      target_region_indexes: res.target_region_indexes,
    },
  };
}

/** 答案面板里的 `.answer-box` 容器。 */
function answerBox() {
  return $("panelAnswer").querySelector(".answer-box");
}
