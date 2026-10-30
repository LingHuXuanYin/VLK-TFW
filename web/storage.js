/**
 * 表单持久化（web 组）：包一层 localStorage，读写失败降级为内存态。
 *
 * 为什么在 web 而不是 features：`localStorage` 是浏览器全局，逻辑层不能依赖。
 */

/**
 * 读取上次保存的参数快照。
 * @param {string} key
 * @returns {Record<string, object>} 无数据或解析失败返回空对象（不抛异常）
 */
export function loadFormSnapshot(key) {
  try {
    const raw = globalThis.localStorage?.getItem(key);
    if (!raw) return {};
    const data = JSON.parse(raw);
    return data && typeof data === "object" ? data : {};
  } catch (_) {
    return {};
  }
}

/**
 * 保存参数快照。
 * @param {string} key
 * @param {Record<string, object>} forms
 * @returns {boolean} 是否写入成功（隐私模式/超额可能失败）
 */
export function saveFormSnapshot(key, forms) {
  try {
    globalThis.localStorage?.setItem(key, JSON.stringify(forms));
    return true;
  } catch (_) {
    return false;
  }
}
