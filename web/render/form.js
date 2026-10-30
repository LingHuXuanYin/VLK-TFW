/**
 * 任务参数面板渲染（web 组）：提示词模板、对应 Python 调用、参数字段、已知坑。
 *
 * 表单值不改在这里，只把用户输入通过 handlers 回抛给 main.js（单一状态源在 main）。
 */
import { parseRegionIndexes } from "../../features/form/form-model.js";
import { templateFor } from "../../features/task/task-catalog.js";
import { $, esc } from "../dom.js";

/**
 * 渲染当前任务的表单。
 * @param {Object} deps
 * @param {object} deps.task 任务定义
 * @param {import("../../shared/contracts.js").FormState} deps.form 该任务当前参数
 * @param {number} deps.number 任务序号（1 起）
 * @param {number[]} deps.selectedIndexes 画布上已选的候选框索引
 * @param {{onText: Function, onLang: Function, onNumber: Function, onIndexes: Function}} deps.handlers
 *   onText(value) / onLang(lang) / onNumber(field, value) / onIndexes(indexes)
 * @returns {{syncIndexes: (indexes: number[]) => void}} 画布点选后回填索引输入框
 */
export function renderTaskForm({ task, form, number, selectedIndexes, handlers }) {
  $("taskTitle").textContent = `${number}. ${task.name}`;
  $("taskSummary").textContent = task.summary;
  $("taskBadge").textContent = task.badge;

  const template = templateFor(task, form.lang);
  const parts = [];

  parts.push(
    `<div class="template-box"><b>提示词模板（${esc(form.lang)}）</b><br>${esc(template)}</div>`
  );
  parts.push(`<div class="code-call">${esc(task.call)}</div>`);

  if (task.needs_index) {
    parts.push(`
        <div class="field">
          <label>目标区域索引 <span class="desc">target_region_indexes · list[int]</span></label>
          <input type="text" id="indexesInput" placeholder="例如 0, 2（点选左侧候选框自动填充）" value="${esc(
            [...selectedIndexes].sort((a, b) => a - b).join(", ")
          )}" />
        </div>`);
  } else {
    parts.push(`
        <div class="field">
          <label>${esc(task.text_label)} <span class="desc">text</span></label>
          <textarea id="textInput" spellcheck="false" placeholder="${esc(task.text_placeholder)}">${esc(
            form.text || ""
          )}</textarea>
        </div>`);
  }

  parts.push(`
      <div class="field-row">
        <div class="field">
          <label>提示词语言 <span class="desc">lang</span></label>
          <select id="langInput">
            <option value="zh"${form.lang === "zh" ? " selected" : ""}>zh（中文模板）</option>
            <option value="en"${form.lang === "en" ? " selected" : ""}>en（英文模板）</option>
          </select>
        </div>
        <div class="field">
          <label>max_new_tokens <span class="desc">输出上限</span></label>
          <input type="number" id="tokensInput" min="8" max="8192" step="8" value="${esc(
            form.max_new_tokens
          )}" />
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label>temperature <span class="desc">0 = 贪心</span></label>
          <input type="number" id="tempInput" min="0" max="2" step="0.1" value="${esc(form.temperature)}" />
        </div>
        <div class="field">
          <label>top_p <span class="desc">仅采样时生效</span></label>
          <input type="number" id="topPInput" min="0" max="1" step="0.05" value="${esc(form.top_p)}" />
        </div>
      </div>`);

  parts.push(`<ul class="tips">${task.tips.map((tip) => `<li>${esc(tip)}</li>`).join("")}</ul>`);
  $("formBody").innerHTML = parts.join("");

  bindHandlers(handlers);

  return {
    syncIndexes(indexes) {
      const input = $("indexesInput");
      if (input) input.value = [...indexes].sort((a, b) => a - b).join(", ");
    },
  };
}

/**
 * 绑定字段事件。字段是否存在于 DOM 由任务类型决定（区域任务没有 text，其余没有索引）。
 * @param {{onText: Function, onLang: Function, onNumber: Function, onIndexes: Function}} handlers
 */
function bindHandlers(handlers) {
  const textInput = $("textInput");
  if (textInput) textInput.oninput = () => handlers.onText(textInput.value);

  const indexesInput = $("indexesInput");
  if (indexesInput) {
    indexesInput.onchange = () => {
      const indexes = parseRegionIndexes(indexesInput.value);
      indexesInput.value = indexes.join(", ");
      handlers.onIndexes(indexes);
    };
  }

  const langInput = $("langInput");
  if (langInput) langInput.onchange = () => handlers.onLang(langInput.value);

  const tokensInput = $("tokensInput");
  if (tokensInput) {
    tokensInput.oninput = (event) => handlers.onNumber("max_new_tokens", Number(event.target.value) || 512);
  }

  const tempInput = $("tempInput");
  if (tempInput) {
    tempInput.oninput = (event) => handlers.onNumber("temperature", Number(event.target.value));
  }

  const topPInput = $("topPInput");
  if (topPInput) {
    topPInput.oninput = (event) => handlers.onNumber("top_p", Number(event.target.value));
  }
}
