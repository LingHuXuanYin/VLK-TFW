/**
 * 电子围栏绘制交互（web 组）：矩形拖拽、多边形逐点拾取。
 *
 * 只处理「按下 / 拖动 / 点击」到「得到一组顶点」的过程，结果通过 `onChange` 交出去；
 * 怎么画由 `annotator.setFence / setFenceDraft` 负责，围栏存哪由 `main.js` 决定。
 *
 * 事件全部绑在 canvas 的**捕获阶段**并 `stopPropagation`：
 * 否则画布上的候选框点选（挂在祖先 dropzone 的 click 上）会在画围栏时被一起触发。
 */
import {
  nearestVertexIndex,
  normalizeFence,
  rectToPolygon,
} from "../../features/fence/fence-geometry.js";

/** 点中首点而闭合多边形的屏幕像素容差。 */
const SNAP_PIXELS = 10;

/**
 * 创建围栏绘制器。
 * @param {Object} deps
 * @param {HTMLCanvasElement} deps.canvas
 * @param {ReturnType<import("./annotator.js").createAnnotator>} deps.annotator
 * @param {(points: number[][]) => void} deps.onChange 绘制成功回调（原图像素顶点列）
 * @param {(mode: "none"|"rect"|"polygon") => void} deps.onModeChange 模式变化回调
 * @param {(message: string) => void} deps.onError 顶点不足等非法状态提示
 * @returns {{
 *   setMode: (mode: "none"|"rect"|"polygon") => void,
 *   getMode: () => "none"|"rect"|"polygon",
 *   isActive: () => boolean,
 *   cancel: () => void,
 *   closePolygon: () => void,
 *   undo: () => void,
 *   destroy: () => void
 * }}
 */
export function createFenceEditor({ canvas, annotator, onChange, onModeChange, onError }) {
  let mode = "none";
  let draft = [];
  let dragStart = null;
  let dragging = false;
  /** 矩形 mouseup 后紧跟的 click 不能再冒泡去点选候选框。 */
  let suppressClick = false;

  /**
   * 切换绘制模式。切走时丢弃未完成的草稿。
   * @param {"none"|"rect"|"polygon"} next
   */
  function setMode(next) {
    mode = next;
    draft = [];
    dragStart = null;
    dragging = false;
    annotator.setFenceDraft([]);
    canvas.style.cursor = mode === "none" ? "default" : "crosshair";
    onModeChange(mode);
  }

  /** 只在有草稿时重绘草稿层，避免整图重绘。 */
  function paintDraft() {
    annotator.setFenceDraft(draft);
  }

  /**
   * 提交草稿：校验通过才算数。
   * 异常：顶点不足或面积过小 → `onError` 提示，保留草稿继续画。
   */
  function commit(points, quiet = false) {
    const natural = annotator.naturalSize();
    if (!natural) return;
    const result = normalizeFence(points, natural);
    if (!result.ok) {
      if (!quiet) onError(result.error);
      return;
    }
    onChange(result.points);
    setMode("none");
  }

  /** 屏幕像素容差换成原图坐标下的容差（画布被缩小显示时容差要放大）。 */
  function snapTolerance() {
    const natural = annotator.naturalSize();
    if (!natural || !canvas.width) return SNAP_PIXELS;
    return (SNAP_PIXELS * natural.width) / canvas.width;
  }

  /** 鼠标事件 → 原图坐标；越界时夹回图内，避免拖出画布产生负坐标。 */
  function pointOf(event) {
    const point = annotator.toImagePoint(event);
    if (!point) return null;
    const natural = annotator.naturalSize();
    if (!natural) return null;
    return {
      x: Math.min(Math.max(point.x, 0), natural.width),
      y: Math.min(Math.max(point.y, 0), natural.height),
    };
  }

  function onMouseDown(event) {
    // 新一轮按下先清掉上一轮遗留的抑制标志：
    // 若上次拖出画布外释放，浏览器不会补发 click，标志会残留并吞掉下一次点选
    suppressClick = false;
    if (mode === "none" || event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    if (mode !== "rect") return;
    const point = pointOf(event);
    if (!point) return;
    dragging = true;
    dragStart = point;
    draft = [];
  }

  function onMouseMove(event) {
    if (mode === "none") return;
    if (mode === "rect") {
      if (!dragging || !dragStart) return;
      event.stopPropagation();
      const point = pointOf(event);
      if (!point) return;
      draft = rectToPolygon(dragStart.x, dragStart.y, point.x, point.y);
      paintDraft();
      return;
    }
    // 多边形：把鼠标当前位置当作临时末点做预览
    if (!draft.length) return;
    const point = pointOf(event);
    if (!point) return;
    annotator.setFenceDraft([...draft, [point.x, point.y]]);
  }

  function onMouseUp(event) {
    if (mode !== "rect" || !dragging) return;
    dragging = false;
    dragStart = null;
    suppressClick = true;
    if (!draft.length) return; // 只点了一下没拖，静默忽略，不报「顶点不足」
    const natural = annotator.naturalSize();
    if (!natural) return;
    const result = normalizeFence(draft, natural);
    if (!result.ok) {
      draft = [];
      annotator.setFenceDraft([]);
      onError(result.error);
      return;
    }
    onChange(result.points);
    setMode("none");
  }

  function onClick(event) {
    // 必须早于 mode 判断：矩形提交后 mode 已回到 none，此时这个 click 仍要拦住，
    // 否则会冒泡到 dropzone 被当成「点选候选框」
    if (suppressClick) {
      suppressClick = false;
      event.stopPropagation();
      event.preventDefault();
      return;
    }
    if (mode !== "polygon") return;
    event.stopPropagation();
    event.preventDefault();

    const point = pointOf(event);
    if (!point) return;
    const tolerance = snapTolerance();
    const hitIndex = nearestVertexIndex(point, draft, tolerance);
    if (hitIndex === 0 && draft.length >= 3) {
      closePolygon();
      return;
    }
    draft = [...draft, [point.x, point.y]];
    paintDraft();
  }

  function onDblClick(event) {
    if (mode !== "polygon") return;
    event.stopPropagation();
    event.preventDefault();
    // 双击的两次 click 已各加一个几乎重合的点，先去掉再闭合
    if (draft.length >= 2) draft = draft.slice(0, -2);
    closePolygon(true);
  }

  /** 闭合多边形并提交；顶点不足时静默丢弃，交给 `onError` 说明原因。 */
  function closePolygon(quiet = false) {
    if (mode !== "polygon") return;
    if (draft.length < 3) {
      if (!quiet) onError("多边形至少需要 3 个顶点");
      return;
    }
    commit(draft, quiet);
    draft = [];
  }

  /** 取消当前绘制并退出模式。 */
  function cancel() {
    setMode("none");
  }

  /** 撤销最后一个顶点（多边形模式，Backspace 触发）。 */
  function undo() {
    if (mode !== "polygon" || !draft.length) return;
    draft = draft.slice(0, -1);
    paintDraft();
  }

  function onKeyDown(event) {
    if (mode === "none") return;
    if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    } else if (event.key === "Enter" && mode === "polygon") {
      event.preventDefault();
      closePolygon();
    } else if (event.key === "Backspace" && mode === "polygon") {
      event.preventDefault();
      undo();
    }
  }

  canvas.addEventListener("mousedown", onMouseDown, true);
  canvas.addEventListener("mousemove", onMouseMove, true);
  canvas.addEventListener("mouseup", onMouseUp, true);
  canvas.addEventListener("click", onClick, true);
  canvas.addEventListener("dblclick", onDblClick, true);
  window.addEventListener("mouseup", onMouseUp);
  window.addEventListener("keydown", onKeyDown);

  return {
    setMode,
    getMode: () => mode,
    isActive: () => mode !== "none",
    cancel,
    closePolygon,
    undo,
    /** 解绑所有监听（换图或页面卸载时用，当前版本未调用，留作对称的清理入口）。 */
    destroy() {
      canvas.removeEventListener("mousedown", onMouseDown, true);
      canvas.removeEventListener("mousemove", onMouseMove, true);
      canvas.removeEventListener("mouseup", onMouseUp, true);
      canvas.removeEventListener("click", onClick, true);
      canvas.removeEventListener("dblclick", onDblClick, true);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("keydown", onKeyDown);
    },
  };
}
