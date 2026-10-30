/**
 * 全量调测结果汇总：通过数、失败清单、答案摘要。
 *
 * 属于 features 组：只做数据加工，渲染在 `web/render/suite.js`。
 */

/**
 * 汇总一次全量调测。
 * @param {import("../../shared/contracts.js").TaskResult[]} results
 * @returns {{total: number, okCount: number, failed: object[], allOk: boolean}}
 * 边界：空数组视为「未运行」，allOk 为 false（避免空结果被当成全绿）。
 */
export function summarizeSuite(results) {
  const list = Array.isArray(results) ? results : [];
  const failed = list.filter((r) => !r || !r.ok);
  return {
    total: list.length,
    okCount: list.length - failed.length,
    failed,
    allOk: Boolean(list.length) && failed.length === 0,
  };
}

/**
 * 把答案压成一行摘要（表格里显示）。
 * @param {string} text
 * @param {number} [maxLength] 默认 80
 * @returns {string} 空白折叠后的截断文本；空输入返回 "—"
 */
export function answerPreview(text, maxLength = 80) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) return "—";
  return normalized.slice(0, maxLength);
}
