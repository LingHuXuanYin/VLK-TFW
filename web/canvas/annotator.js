/**
 * 画布渲染与点选（web 组）：候选框细线、悬停高亮、选中填充、结果框标注。
 *
 * 只负责「把当前视图状态画出来」和「告诉我点到哪个框」；
 * 谁选中了哪个框由 `main.js` 决定。几何计算全部来自 `features/bbox/bbox-geometry.js`。
 */
import { colorForLabel, collectLabels, fitCanvas, hitTest, toImageCoords } from "../../features/bbox/bbox-geometry.js";

/**
 * 创建画布控制器。
 * @param {{canvas: HTMLCanvasElement, container: HTMLElement, palette: string[]}} deps
 *   container 用于取可用宽度（通常是 dropzone）。
 * @returns {{
 *   setImage: (img: HTMLImageElement|null) => void,
 *   setBoxes: (boxes: number[][]) => void,
 *   setSelected: (indexes: number[]) => void,
 *   setShowBoxes: (show: boolean) => void,
 *   setResult: (result: object|null) => void,
 *   hitTestEvent: (event: MouseEvent) => number,
 *   updateHover: (event: MouseEvent) => {changed: boolean, index: number},
 *   clearHover: () => boolean,
 *   redraw: () => void,
 *   resizeAndDraw: () => void,
 *   hasImage: () => boolean
 * }}
 */
export function createAnnotator({ canvas, container, palette }) {
  const view = { img: null, boxes: [], selected: [], hovered: -1, showBoxes: true, result: null };

  /**
   * 按容器宽度重算画布像素尺寸（含 DPR），图片未就绪时不做任何事。
   * 边界：容器宽度变化（窗口 resize）后必须重新调用，否则框会错位。
   */
  function resize() {
    const img = view.img;
    if (!img) return;
    const size = fitCanvas({
      containerWidth: container.clientWidth,
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      dpr: globalThis.devicePixelRatio || 1,
    });
    canvas.width = size.pixelWidth;
    canvas.height = size.pixelHeight;
    canvas.style.width = `${size.cssWidth}px`;
    canvas.style.height = `${size.cssHeight}px`;
  }

  /**
   * 重绘整个画布。
   * 顺序：底图 → 候选框（选中/悬停/普通三态）→ 结果框（带 label 色条）。
   * 边界：100 个候选框只给选中/悬停的标 `objN`，全标会糊成一片。
   */
  function draw() {
    const img = view.img;
    const ctx = canvas.getContext("2d");
    if (!img || !canvas.width) return;

    const s = canvas.width / img.naturalWidth;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    if (view.showBoxes) {
      ctx.font = `${10 * s}px ui-monospace, Consolas, monospace`;
      ctx.textBaseline = "top";
      view.boxes.forEach((box, i) => {
        const [x1, y1, x2, y2] = box;
        const isSelected = view.selected.includes(i);
        const isHovered = view.hovered === i;
        ctx.strokeStyle = isSelected ? "#3d5afe" : isHovered ? "#f5a524" : "rgba(255,255,255,.32)";
        ctx.lineWidth = (isSelected ? 2 : isHovered ? 1.8 : 0.8) * s;
        if (isSelected) {
          ctx.fillStyle = "rgba(61,90,254,.16)";
          ctx.fillRect(x1 * s, y1 * s, (x2 - x1) * s, (y2 - y1) * s);
        }
        ctx.strokeRect(x1 * s, y1 * s, (x2 - x1) * s, (y2 - y1) * s);
        if (isSelected || isHovered) {
          const tag = `obj${i}`;
          const tagWidth = ctx.measureText(tag).width + 5 * s;
          const tagHeight = 12 * s;
          const tagY = y1 - tagHeight >= 0 ? y1 - tagHeight : y1;
          ctx.fillStyle = isSelected ? "rgba(61,90,254,.94)" : "rgba(245,165,36,.95)";
          ctx.fillRect(x1 * s, tagY, tagWidth, tagHeight);
          ctx.fillStyle = "#fff";
          ctx.fillText(tag, x1 * s + 2.5 * s, tagY + 1.5 * s);
        }
      });
    }

    const resultBoxes = view.result?.result_bbox_list || [];
    if (resultBoxes.length) {
      const labels = collectLabels(resultBoxes);
      resultBoxes.forEach((box) => {
        const color = colorForLabel(box.label, labels, palette);
        const x1 = box.xmin * s;
        const y1 = box.ymin * s;
        const x2 = box.xmax * s;
        const y2 = box.ymax * s;
        ctx.strokeStyle = color;
        ctx.lineWidth = 2.5 * s;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
        const text = (box.label || "").slice(0, 28) || String(box.object_index);
        ctx.font = `600 ${11 * s}px "Segoe UI", "Microsoft YaHei", sans-serif`;
        const textWidth = ctx.measureText(text).width + 8 * s;
        const textHeight = 15 * s;
        const textY = y1 - textHeight > 0 ? y1 - textHeight : y1;
        ctx.fillStyle = color;
        ctx.fillRect(x1, textY, textWidth, textHeight);
        ctx.fillStyle = "#fff";
        ctx.textBaseline = "middle";
        ctx.fillText(text, x1 + 4 * s, textY + textHeight / 2);
        ctx.textBaseline = "top";
      });
    }
  }

  /**
   * 把鼠标事件换算成原图坐标后做命中测试。
   * @returns {number} 索引，未命中 -1；图片未就绪恒 -1
   */
  function hitTestEvent(event) {
    const img = view.img;
    if (!img) return -1;
    const rect = canvas.getBoundingClientRect();
    const point = toImageCoords(
      { x: event.clientX, y: event.clientY },
      rect,
      { width: img.naturalWidth, height: img.naturalHeight }
    );
    return hitTest(view.boxes, point);
  }

  return {
    setImage(img) {
      view.img = img;
      resize();
      draw();
    },
    setBoxes(boxes) {
      view.boxes = boxes || [];
      draw();
    },
    setSelected(indexes) {
      view.selected = indexes || [];
      draw();
    },
    setShowBoxes(show) {
      view.showBoxes = Boolean(show);
      draw();
    },
    setResult(result) {
      view.result = result;
      draw();
    },
    hitTestEvent,
    /** 悬停变化时才重绘；返回是否变化与当前索引。 */
    updateHover(event) {
      const index = hitTestEvent(event);
      if (index === view.hovered) return { changed: false, index };
      view.hovered = index;
      canvas.style.cursor = index >= 0 ? "pointer" : "crosshair";
      draw();
      return { changed: true, index };
    },
    /** 鼠标移出画布时清掉悬停态；返回是否真的变了。 */
    clearHover() {
      if (view.hovered === -1) return false;
      view.hovered = -1;
      draw();
      return true;
    },
    redraw: draw,
    resizeAndDraw() {
      resize();
      draw();
    },
    hasImage: () => Boolean(view.img),
  };
}
