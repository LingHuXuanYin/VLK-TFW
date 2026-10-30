/**
 * 左侧任务导航渲染（web 组）：按分组列出七个任务 + 综合调度入口。
 */
import { groupTasks, taskNumber } from "../../features/task/task-catalog.js";
import { esc } from "../dom.js";

/**
 * 渲染导航。
 * @param {Object} deps
 * @param {HTMLElement} deps.nav 导航容器
 * @param {{list: object[], byId: object}} deps.catalog 任务索引
 * @param {string[]} deps.groups 分组顺序
 * @param {(taskId: string) => void} deps.onSelect 点任务
 * @param {() => void} deps.onSuite 点「一键全量调测」
 * @returns {void}
 */
export function renderNav({ nav, catalog, groups, onSelect, onSuite }) {
  nav.innerHTML = "";

  groupTasks(catalog, groups).forEach(({ label, tasks }) => {
    const wrap = document.createElement("div");
    wrap.className = "nav-group";
    const title = document.createElement("div");
    title.className = "nav-group-label";
    title.textContent = label;
    wrap.appendChild(title);
    tasks.forEach((task) =>
      wrap.appendChild(navItem({ id: task.id, num: taskNumber(catalog, task.id), name: task.name, onSelect }))
    );
    nav.appendChild(wrap);
  });

  const extra = document.createElement("div");
  extra.className = "nav-group";
  const title = document.createElement("div");
  title.className = "nav-group-label";
  title.textContent = "综合调度";
  extra.appendChild(title);
  extra.appendChild(navItem({ id: "__suite", num: "★", name: "一键全量调测", onSelect: null, onSuite }));
  nav.appendChild(extra);
}

/**
 * 切换高亮项。
 * @param {string} id 任务 id 或 `__suite`
 */
export function setActiveNav(id) {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.task === id);
  });
}

/**
 * 给跑成功的任务打绿点（重复调用幂等）。
 * @param {string} taskId
 */
export function markNavDone(taskId) {
  const item = document.querySelector(`.nav-item[data-task="${taskId}"]`);
  if (item && !item.querySelector(".dot-ok")) {
    const dot = document.createElement("span");
    dot.className = "dot-ok";
    item.appendChild(dot);
  }
}

/**
 * 造一个导航项。
 * @param {{id: string, num: number|string, name: string, onSelect: Function|null, onSuite?: Function}} spec
 * @returns {HTMLElement}
 */
function navItem({ id, num, name, onSelect, onSuite }) {
  const el = document.createElement("div");
  el.className = "nav-item";
  el.dataset.task = id;
  el.innerHTML = `<span class="nav-num">${esc(num)}</span><span>${esc(name)}</span>`;
  if (id === "__suite") {
    el.onclick = () => {
      setActiveNav("__suite");
      if (onSuite) onSuite();
    };
  } else {
    el.onclick = () => onSelect(id);
  }
  return el;
}
