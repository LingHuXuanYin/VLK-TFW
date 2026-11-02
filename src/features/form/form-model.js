/**
 * 表单模型：默认值、持久化合并、请求体构造、区域索引解析、入参校验。
 *
 * 属于 features 组。所有函数都是纯函数（只吃参数、吐结果），表单状态由 web 层持有。
 */
import { DEFAULT_TOP_P } from "../../shared/contracts.js";

/** 表单里允许持久化的字段，防止浏览器本地存储里混进历史脏键。 */
const FORM_KEYS = ["text", "lang", "max_new_tokens", "temperature", "top_p"];

/**
 * 某任务的默认表单值。
 * @param {import("../../shared/contracts.js").TaskMeta} task
 * @returns {import("../../shared/contracts.js").FormState}
 */
export function defaultForm(task) {
  return {
    text: task.default_text ?? "",
    lang: task.default_lang || "en",
    max_new_tokens: task.default_max_new_tokens ?? 512,
    temperature: task.default_temperature ?? 0,
    top_p: DEFAULT_TOP_P,
  };
}

/**
 * 合并浏览器本地存储里存过的参数，得到初始表单集合。
 * @param {object[]} tasks
 * @param {Record<string, object>} [saved] 键为 task.id
 * @returns {Record<string, import("../../shared/contracts.js").FormState>}
 * 边界：saved 里的非法值（类型不符）会被忽略，回退到默认值。
 */
export function hydrateForms(tasks, saved = {}) {
  const out = {};
  for (const task of tasks || []) {
    const base = defaultForm(task);
    const patch = saved[task.id] || {};
    for (const key of FORM_KEYS) {
      if (patch[key] === undefined || patch[key] === null) continue;
      const sameType = typeof patch[key] === typeof base[key];
      if (sameType) base[key] = patch[key];
    }
    if (base.lang !== "zh" && base.lang !== "en") base.lang = task.default_lang || "en";
    out[task.id] = base;
  }
  return out;
}

/**
 * 解析用户输入的区域索引，如 `"0, 2 3"` → `[0, 2, 3]`。
 * @param {string} raw
 * @returns {number[]} 去重升序的非负整数；非法片段直接丢弃，不抛异常
 */
export function parseRegionIndexes(raw) {
  const values = String(raw || "")
    .split(/[,\s]+/)
    .filter(Boolean)
    .map(Number)
    .filter((n) => Number.isInteger(n) && n >= 0);
  return [...new Set(values)].sort((a, b) => a - b);
}

/**
 * 构造单任务请求体。
 * @param {Object} input
 * @param {object} input.task 任务定义
 * @param {import("../../shared/contracts.js").FormState} input.form
 * @param {string|null} input.imageId
 * @param {number[][]} input.boxes 画布上的候选框（空数组表示不传，后端自动生成）
 * @param {number[]} input.regionIndexes 区域任务的索引
 * @param {number[][]|null} [input.roi] 电子围栏多边形；null 表示不限区域
 * @returns {import("../../shared/contracts.js").RunPayload}
 * 边界：区域任务的 text 恒为空串（提示词由索引拼 `<objN>`）；其余任务取表单内容。
 */
export function buildRunPayload({ task, form, imageId, boxes, regionIndexes, roi = null }) {
  const needsIndex = Boolean(task.needs_index);
  return {
    image_id: imageId,
    text: needsIndex ? "" : String(form.text ?? ""),
    lang: form.lang,
    bbox_list: boxes && boxes.length ? boxes : null,
    roi: roi && roi.length ? roi : null,
    auto_proposals: true,
    target_region_indexes: needsIndex ? regionIndexes : null,
    max_new_tokens: form.max_new_tokens,
    temperature: form.temperature,
    top_p: form.top_p,
  };
}

/**
 * 构造全量调测的 per-task 覆盖参数。
 * @param {object[]} tasks
 * @param {Record<string, import("../../shared/contracts.js").FormState>} forms
 * @returns {Record<string, object>} 键为 task.id
 */
export function buildSuiteOverrides(tasks, forms) {
  const out = {};
  for (const task of tasks || []) {
    const form = forms[task.id];
    out[task.id] = {
      text: task.needs_index ? "" : String(form.text ?? ""),
      lang: form.lang,
      max_new_tokens: form.max_new_tokens,
      temperature: form.temperature,
      top_p: form.top_p,
    };
  }
  return out;
}

/**
 * 运行前的本地校验（与后端规则对齐，省掉一次注定 400 的请求）。
 * @param {{task: object, form: object, imageId: string|null, regionIndexes: number[]}} input
 * @returns {string|null} 有问题返回提示文案，通过返回 null
 * 边界：vqa 与区域任务不校验 text；区域任务必须至少一个索引。
 */
export function validateRunInput({ task, form, imageId, regionIndexes }) {
  if (!imageId) return "请先上传图片";
  if (task.needs_index && !(regionIndexes && regionIndexes.length)) {
    return "区域任务请先在左侧图点选至少一个候选框";
  }
  if (!task.needs_index && task.id !== "vqa" && !String(form.text ?? "").trim()) {
    return `${task.name} 的 text 不能为空`;
  }
  return null;
}
