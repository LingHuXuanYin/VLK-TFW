/**
 * 全量调测表格渲染（web 组）：七行任务、逐行状态/tokens/耗时/答案摘要。
 */
import { answerPreview, summarizeSuite } from "../../features/suite/suite-summary.js";
import { esc } from "../dom.js";

/**
 * 渲染全量调测表格骨架。
 * @param {Object} deps
 * @param {HTMLElement} deps.table 表格容器
 * @param {object[]} deps.tasks 任务列表（顺序即执行顺序）
 * @param {Record<string, object>} deps.forms 各任务当前参数
 * @param {{onText: Function, onLang: Function, onRowClick: Function}} deps.handlers
 *   onText(taskId, value) / onLang(taskId, value) / onRowClick(taskId)
 */
export function renderSuiteTable({ table, tasks, forms, handlers }) {
  const rows = tasks
    .map((task, index) => {
      const form = forms[task.id];
      const textCell = task.needs_index
        ? `<span class="muted small">点选 / 默认 obj0</span>`
        : `<input type="text" data-suite-text="${task.id}" value="${esc(form.text)}" />`;
      return `<tr data-suite-row="${task.id}">
          <td>${index + 1}</td>
          <td><strong>${esc(task.name)}</strong><div class="muted" style="font-size:11px">${esc(task.id)}</div></td>
          <td>${textCell}</td>
          <td>
            <select data-suite-lang="${task.id}">
              <option value="zh"${form.lang === "zh" ? " selected" : ""}>zh</option>
              <option value="en"${form.lang === "en" ? " selected" : ""}>en</option>
            </select>
          </td>
          <td class="status-cell" data-suite-status="${task.id}">待运行</td>
          <td class="mono" data-suite-tokens="${task.id}">—</td>
          <td class="mono" data-suite-elapsed="${task.id}">—</td>
          <td data-suite-answer="${task.id}" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">—</td>
        </tr>`;
    })
    .join("");

  table.innerHTML = `<thead><tr>
        <th>#</th><th>任务</th><th>text</th><th>lang</th><th>状态</th><th>tokens</th><th>耗时</th><th>答案摘要</th>
      </tr></thead><tbody>${rows}</tbody>`;

  table.querySelectorAll("[data-suite-text]").forEach((input) => {
    input.oninput = () => handlers.onText(input.dataset.suiteText, input.value);
  });
  table.querySelectorAll("[data-suite-lang]").forEach((select) => {
    select.onchange = () => handlers.onLang(select.dataset.suiteLang, select.value);
  });
  table.querySelectorAll("tbody tr").forEach((row) => {
    row.style.cursor = "pointer";
    row.onclick = (event) => {
      if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
      handlers.onRowClick(row.dataset.suiteRow);
    };
  });
}

/**
 * 开跑前把所有行重置为「排队中」。
 */
export function resetSuiteRows() {
  document.querySelectorAll("[data-suite-status]").forEach((el) => {
    el.textContent = "排队中";
    el.className = "status-cell";
  });
  document.querySelectorAll("[data-suite-tokens]").forEach((el) => (el.textContent = "—"));
  document.querySelectorAll("[data-suite-elapsed]").forEach((el) => (el.textContent = "—"));
  document.querySelectorAll("[data-suite-answer]").forEach((el) => (el.textContent = "—"));
}

/**
 * 把一次全量调测的结果写回表格。
 * @param {import("../../shared/contracts.js").TaskResult[]} results
 * @returns {{summary: {total: number, okCount: number, failed: object[], allOk: boolean}, okTaskIds: string[]}}
 * 边界：失败行只显示错误文案，不显示 tokens/耗时。
 */
export function applySuiteResult(results) {
  const okTaskIds = [];
  (results || []).forEach((result) => {
    const status = document.querySelector(`[data-suite-status="${result.task}"]`);
    const tokens = document.querySelector(`[data-suite-tokens="${result.task}"]`);
    const elapsed = document.querySelector(`[data-suite-elapsed="${result.task}"]`);
    const answer = document.querySelector(`[data-suite-answer="${result.task}"]`);
    if (!status || !tokens || !elapsed || !answer) return;

    if (result.ok) {
      status.textContent = "✓ 成功";
      status.className = "status-cell ok";
      tokens.textContent = `${result.prompt_tokens}→${result.completion_tokens}`;
      elapsed.textContent = `${result.elapsed_ms}ms`;
      answer.textContent = answerPreview(result.answer);
      answer.title = result.answer || "";
      okTaskIds.push(result.task);
    } else {
      status.textContent = "✕ 失败";
      status.className = "status-cell fail";
      answer.textContent = result.error || "未知错误";
      answer.title = result.error || "";
    }
  });
  return { summary: summarizeSuite(results), okTaskIds };
}

/**
 * 设置表格下方说明文案。
 * @param {string} text
 */
export function setSuiteFoot(text) {
  const foot = document.getElementById("suiteFoot");
  if (foot) foot.textContent = text;
}
