/**
 * 电子围栏几何（features 组）：矩形转多边形、顶点规整、包围盒、面积、点在多边形内。
 *
 * 全是纯函数，不碰 canvas/DOM。后端 `backend/app/services/fence.py` 有对应的 Python 实现，
 * 两边的判定口径刻意保持一致（坐标同为原图像素，容差同为 2px）。
 * 绘制交互在 `web/canvas/fence-editor.js`，渲染在 `web/canvas/annotator.js`。
 */
import { MIN_FENCE_VERTICES } from "../../shared/contracts.js";

/** 顶点去重容差（原图像素）。前端两次点击几乎不可能完全重合，容差太小会多出顶点。 */
const POINT_EPSILON = 2;

/**
 * 把矩形转成四点多边形（顺时针）。
 * @param {number} x1
 * @param {number} y1
 * @param {number} x2
 * @param {number} y2
 * @returns {number[][]} 左上 → 右上 → 右下 → 左下
 * 边界：两个角点顺序任意，函数内部先归一化。
 */
export function rectToPolygon(x1, y1, x2, y2) {
  const left = Math.min(x1, x2);
  const right = Math.max(x1, x2);
  const top = Math.min(y1, y2);
  const bottom = Math.max(y1, y2);
  return [
    [left, top],
    [right, top],
    [right, bottom],
    [left, bottom],
  ];
}

/**
 * 规整顶点列：夹回图像范围、去掉重合点、去掉与首点重合的尾部闭合点。
 * @param {number[][]} points 原图像素坐标
 * @param {{width: number, height: number}} natural 图片尺寸
 * @returns {{ok: true, points: number[][]} | {ok: false, error: string}}
 * 边界：不抛异常，非法输入一律返回 `{ok:false}` 带中文提示。
 */
export function normalizeFence(points, natural) {
  if (!Array.isArray(points) || points.length < MIN_FENCE_VERTICES) {
    return { ok: false, error: `围栏至少需要 ${MIN_FENCE_VERTICES} 个顶点` };
  }
  const width = natural?.width || 0;
  const height = natural?.height || 0;
  if (!width || !height) return { ok: false, error: "图片尺寸未知，无法确定围栏坐标" };

  const cleaned = [];
  for (const point of points) {
    if (!Array.isArray(point) || point.length !== 2) {
      return { ok: false, error: "围栏顶点必须是 [x, y]" };
    }
    const x = clamp(Number(point[0]), 0, width);
    const y = clamp(Number(point[1]), 0, height);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return { ok: false, error: "围栏顶点坐标必须是数字" };
    }
    if (cleaned.length && samePoint(cleaned[cleaned.length - 1], [x, y])) continue;
    cleaned.push([x, y]);
  }
  while (cleaned.length >= 2 && samePoint(cleaned[0], cleaned[cleaned.length - 1])) {
    cleaned.pop();
  }
  if (cleaned.length < MIN_FENCE_VERTICES) {
    return { ok: false, error: "顶点重合过多，请拉开距离再画" };
  }
  if (polygonArea(cleaned) < 4) {
    return { ok: false, error: "围栏面积太小，请画大一些" };
  }
  return { ok: true, points: cleaned };
}

/**
 * 围栏外接矩形。
 * @param {number[][]} points
 * @returns {{x1: number, y1: number, x2: number, y2: number}}
 * 边界：空数组返回全 0。
 */
export function fenceBounds(points) {
  if (!points || !points.length) return { x1: 0, y1: 0, x2: 0, y2: 0 };
  let x1 = Infinity;
  let y1 = Infinity;
  let x2 = -Infinity;
  let y2 = -Infinity;
  for (const [x, y] of points) {
    if (x < x1) x1 = x;
    if (y < y1) y1 = y;
    if (x > x2) x2 = x;
    if (y > y2) y2 = y;
  }
  return { x1, y1, x2, y2 };
}

/**
 * 多边形面积（鞋带公式取绝对值）。
 * @param {number[][]} points
 * @returns {number} 像素面积；顶点不足 3 个返回 0
 */
export function polygonArea(points) {
  if (!points || points.length < 3) return 0;
  let total = 0;
  for (let i = 0; i < points.length; i += 1) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    total += x1 * y2 - x2 * y1;
  }
  return Math.abs(total) / 2;
}

/**
 * 射线法判断点是否在多边形内。边界与顶点算在内。
 * @param {number} x
 * @param {number} y
 * @param {number[][]} points
 * @returns {boolean}
 */
export function pointInPolygon(x, y, points) {
  if (!points || points.length < 3) return false;
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    if (onSegment(x, y, xi, yi, xj, yj)) return true;
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/**
 * 点是否靠近某个顶点，用于「点击首点闭合多边形」。
 * @param {{x: number, y: number}} point
 * @param {number[][]} points
 * @param {number} [tolerance] 屏幕像素容差（调用方按缩放换算后传入）
 * @returns {number} 命中的顶点索引，未命中返回 -1
 */
export function nearestVertexIndex(point, points, tolerance = 8) {
  let best = -1;
  let bestDistance = Infinity;
  (points || []).forEach((vertex, index) => {
    const dx = vertex[0] - point.x;
    const dy = vertex[1] - point.y;
    const distance = Math.hypot(dx, dy);
    if (distance <= tolerance && distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  });
  return best;
}

/**
 * 围栏摘要文案，供工具栏与结果面板显示。
 * @param {number[][]|null} points
 * @returns {string}
 */
export function describeFence(points) {
  if (!points || !points.length) return "未设置";
  const area = Math.round(polygonArea(points));
  return `${points.length} 顶点 · ${area.toLocaleString("zh-CN")} px²`;
}

/**
 * 判断围栏形状是矩形（4 点且对边平行），仅用于渲染时是否画角点。
 * @param {number[][]} points
 * @returns {boolean}
 */
export function isRectangleFence(points) {
  if (!points || points.length !== 4) return false;
  const [a, b, c, d] = points;
  return (
    Math.abs(a[1] - b[1]) < POINT_EPSILON &&
    Math.abs(c[1] - d[1]) < POINT_EPSILON &&
    Math.abs(a[0] - d[0]) < POINT_EPSILON &&
    Math.abs(b[0] - c[0]) < POINT_EPSILON
  );
}

/* ----------------------------- 内部工具 ----------------------------- */

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return Number.NaN;
  return Math.min(Math.max(value, min), max);
}

function samePoint(a, b) {
  return Math.abs(a[0] - b[0]) < POINT_EPSILON && Math.abs(a[1] - b[1]) < POINT_EPSILON;
}

function onSegment(x, y, x1, y1, x2, y2) {
  const cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1);
  if (Math.abs(cross) > 1e-6) return false;
  return (
    Math.min(x1, x2) - 1e-6 <= x &&
    x <= Math.max(x1, x2) + 1e-6 &&
    Math.min(y1, y2) - 1e-6 <= y &&
    y <= Math.max(y1, y2) + 1e-6
  );
}
