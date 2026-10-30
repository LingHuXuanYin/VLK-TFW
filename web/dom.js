/**
 * DOM 小工具（web 组）。只做取元素与转义，不含业务。
 */

/**
 * 按 id 取元素。
 * @param {string} id
 * @returns {HTMLElement}
 */
export const $ = (id) => document.getElementById(id);

/**
 * 转义 HTML 特殊字符，所有插入 innerHTML 的动态文本都必须过一遍。
 * @param {unknown} value
 * @returns {string}
 */
export function esc(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
