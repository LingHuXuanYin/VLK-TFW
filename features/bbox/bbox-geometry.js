/**
 * 候选框几何计算：坐标映射、命中测试、配色、粘贴 JSON 校验、画布尺寸。
 *
 * 属于 features 组：全是纯数学，不碰 canvas/DOM。画布绘制在 `web/canvas/annotator.js`。
 */

/**
 * 把鼠标事件的视口坐标换算成原图像素坐标。
 * @param {{x: number, y: number}} clientPoint 相对视口
 * @param {{left: number, top: number, width: number, height: number}} rect 画布包围盒
 * @param {{width: number, height: number}} natural 图片原始尺寸
 * @returns {{x: number, y: number}}
 * 边界：rect 宽高为 0（未渲染）时返回 0,0。
 */
export function toImageCoords(clientPoint, rect, natural) {
  if (!rect.width || !rect.height) return { x: 0, y: 0 };
  return {
    x: ((clientPoint.x - rect.left) / rect.width) * natural.width,
    y: ((clientPoint.y - rect.top) / rect.height) * natural.height,
  };
}

/**
 * 命中测试：返回包含该点的**面积最小**候选框索引。
 * @param {number[][]} boxes `[[x1,y1,x2,y2], ...]` 原图像素
 * @param {{x: number, y: number}} point
 * @returns {number} 命中索引；未命中返回 -1
 * 边界：100 个候选框高度重叠，取最小面积符合「点小框选小目标」的直觉。
 */
export function hitTest(boxes, point) {
  let best = -1;
  let bestArea = Infinity;
  (boxes || []).forEach((box, i) => {
    const [x1, y1, x2, y2] = box;
    if (point.x < x1 || point.x > x2 || point.y < y1 || point.y > y2) return;
    const area = (x2 - x1) * (y2 - y1);
    if (area < bestArea) {
      bestArea = area;
      best = i;
    }
  });
  return best;
}

/**
 * 按出现顺序收集 label（结果框配色按这个顺序取色）。
 * @param {{label: string}[]} resultBoxes
 * @returns {string[]}
 */
export function collectLabels(resultBoxes) {
  return [...new Set((resultBoxes || []).map((b) => b.label))];
}

/**
 * 取某 label 的颜色。
 * @param {string} label
 * @param {string[]} labels `collectLabels` 的结果
 * @param {string[]} palette
 * @returns {string} 十六进制色值；palette 为空时退回黑色
 */
export function colorForLabel(label, labels, palette) {
  if (!palette || !palette.length) return "#000";
  const index = labels.indexOf(label);
  return palette[(index < 0 ? 0 : index) % palette.length];
}

/**
 * 校验手动粘贴的候选框 JSON。
 * @param {string} raw 用户输入的文本
 * @returns {{ok: true, boxes: number[][]} | {ok: false, error: string}}
 * 边界：允许空白与换行；只要有一个框格式不对就整体拒绝，不做部分接受。
 */
export function normalizeBoxes(raw) {
  const text = String(raw || "").trim();
  if (!text) return { ok: false, error: "请先粘贴 JSON 数组" };
  let data;
  try {
    data = JSON.parse(text);
  } catch (err) {
    return { ok: false, error: `JSON 解析失败：${err.message}` };
  }
  if (!Array.isArray(data) || !data.length) {
    return { ok: false, error: "需要非空的 [[x1,y1,x2,y2], …]" };
  }
  const bad = data.find(
    (b) => !Array.isArray(b) || b.length !== 4 || b.some((v) => typeof v !== "number")
  );
  if (bad) return { ok: false, error: "每个框必须是 4 个数字，例如 [100,50,300,250]" };
  return { ok: true, boxes: data };
}

/**
 * 按容器宽度与图片宽高比算出画布尺寸（含 DPR 缩放）。
 * @param {{containerWidth: number, naturalWidth: number, naturalHeight: number, dpr?: number, minWidth?: number}} input
 * @returns {{cssWidth: number, cssHeight: number, pixelWidth: number, pixelHeight: number}}
 * 边界：`minWidth` 默认 240，避免窄容器把图画成一条线。
 */
export function fitCanvas({ containerWidth, naturalWidth, naturalHeight, dpr = 1, minWidth = 240 }) {
  const cssWidth = Math.max(minWidth, Math.round(containerWidth - 2));
  const cssHeight = Math.round((cssWidth * naturalHeight) / naturalWidth);
  return {
    cssWidth,
    cssHeight,
    pixelWidth: Math.round(cssWidth * dpr),
    pixelHeight: Math.round(cssHeight * dpr),
  };
}
