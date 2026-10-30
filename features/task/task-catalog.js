/**
 * 任务目录逻辑：分组、编号、提示词模板取值。
 *
 * 属于 features 组。任务的**数据**来自后端 `/api/meta`，本文件只做纯计算，
 * 不硬编码任何任务信息，也不碰 DOM。
 */

/**
 * 建立任务索引。
 * @param {import("../../shared/contracts.js").TaskMeta[]} tasks
 * @returns {{ list: object[], byId: Record<string, object> }}
 */
export function indexTasks(tasks) {
  const list = Array.isArray(tasks) ? tasks : [];
  return { list, byId: Object.fromEntries(list.map((t) => [t.id, t])) };
}

/**
 * 任务在文档顺序里的序号（1 起）。
 * @param {{ list: object[] }} catalog
 * @param {string} id
 * @returns {number} 未命中返回 0
 */
export function taskNumber(catalog, id) {
  return catalog.list.findIndex((t) => t.id === id) + 1;
}

/**
 * 按分组归拢任务，用于左侧导航。
 * @param {{ list: object[] }} catalog
 * @param {string[]} groups 分组顺序
 * @returns {{ label: string, tasks: object[] }[]} 空分组也会保留（占位可见）
 */
export function groupTasks(catalog, groups) {
  return (groups || []).map((label) => ({
    label,
    tasks: catalog.list.filter((t) => t.group === label),
  }));
}

/**
 * 取某语言下的提示词模板。
 * @param {object} task
 * @param {"en"|"zh"} lang
 * @returns {string} 缺失该语言时回退英文模板；都没有返回空串
 */
export function templateFor(task, lang) {
  if (!task || !task.templates) return "";
  return task.templates[lang] || task.templates.en || "";
}
