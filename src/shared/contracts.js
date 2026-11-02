/**
 * 双端共用的类型契约与常量（JSDoc typedef + 常量，无运行时依赖）。
 *
 * 契约来源：`backend/app/schemas.py` 与 `backend/app/services/task_runner.py` 的返回值。
 * 改后端字段时同步改这里，`features/` 与 `web/` 都从这里取类型。
 */

/**
 * 一个任务的元数据（来自 `/api/meta` 的 tasks 数组）。
 * @typedef {Object} TaskMeta
 * @property {string} id                     任务 id，如 "detection"
 * @property {string} name                   中文名
 * @property {string} group                  分组名，需出现在 groups 里
 * @property {string} badge                  角标文案
 * @property {string} summary                一句话说明
 * @property {string} text_label             text 输入框标题
 * @property {string} text_placeholder       text 输入框占位符
 * @property {string} default_text           默认 text
 * @property {boolean} needs_bbox            是否需要候选框
 * @property {boolean} needs_index           是否需要 target_region_indexes
 * @property {"en"|"zh"} default_lang        默认提示词语言
 * @property {number} default_max_new_tokens 默认输出上限
 * @property {number} default_temperature    默认温度
 * @property {Record<string,string>} templates 语言 → 提示词模板
 * @property {string} call                   对应的 Python 调用签名（仅展示）
 * @property {string[]} tips                 已知坑
 */

/**
 * 图片元信息（`/api/images`、`/api/demo` 响应去掉 ok 后的部分）。
 * @typedef {Object} ImageMeta
 * @property {string} image_id
 * @property {string} filename
 * @property {number} width
 * @property {number} height
 * @property {number[]} original_size
 * @property {boolean} resized
 */

/**
 * 单个任务的表单状态（会持久化到 localStorage）。
 * @typedef {Object} FormState
 * @property {string} text
 * @property {"en"|"zh"} lang
 * @property {number} max_new_tokens
 * @property {number} temperature
 * @property {number} top_p
 */

/**
 * 电子围栏：一组原图像素顶点（首尾自动闭合）。
 * @typedef {number[][]} Fence
 *   `[[x, y], ...]`，至少 3 个顶点。矩形也用它表达（4 个顶点）。
 *   与候选框同坐标系：以落盘图（长边 ≤1280）为准。
 */

/**
 * 单任务运行请求体。
 * @typedef {Object} RunPayload
 * @property {string} image_id
 * @property {string} text
 * @property {"en"|"zh"} lang
 * @property {number[][]|null} bbox_list
 * @property {Fence|null} roi 电子围栏，null 表示整图
 * @property {boolean} auto_proposals
 * @property {number[]|null} target_region_indexes
 * @property {number} max_new_tokens
 * @property {number} temperature
 * @property {number} top_p
 */

/**
 * 模型返回的单个框。
 * @typedef {Object} ResultBox
 * @property {number} object_index
 * @property {string} label
 * @property {number} xmin
 * @property {number} ymin
 * @property {number} xmax
 * @property {number} ymax
 */

/**
 * 单任务运行结果（失败时只有 ok/task/task_name/error/elapsed_ms）。
 * @typedef {Object} TaskResult
 * @property {boolean} ok
 * @property {string} task
 * @property {string} task_name
 * @property {string} [answer]
 * @property {ResultBox[]} [result_bbox_list]
 * @property {number} [prompt_tokens]
 * @property {number} [completion_tokens]
 * @property {number} elapsed_ms
 * @property {string} [prompt]
 * @property {"en"|"zh"} [lang]
 * @property {string} [text]
 * @property {number} [max_new_tokens]
 * @property {number} [temperature]
 * @property {number} [top_p]
 * @property {string} [boxes_source]    request | wedetect | wedetect-cache | none
 * @property {number} [boxes_count]
 * @property {boolean} [fence_applied]  本次是否启用电子围栏
 * @property {number} [fence_vertices]  围栏顶点数
 * @property {boolean} [fence_cropped]  候选框是否在围栏裁剪出的子图上推理
 * @property {number[]|null} [target_region_indexes]
 * @property {string[]} [warnings]
 * @property {string} [error]
 */

/**
 * 全量调测响应。
 * @typedef {Object} SuiteResult
 * @property {boolean} ok
 * @property {TaskResult[]} results
 * @property {number} total_elapsed_ms
 */

/**
 * 模型状态（`/api/status`）。
 * @typedef {Object} ModelStatus
 * @property {"idle"|"loading"|"ready"|"error"} status
 * @property {string} message
 * @property {string|null} error
 * @property {number|null} load_seconds
 * @property {string|null} loaded_at
 * @property {string} model_path
 * @property {string|null} device
 * @property {boolean} [infer_busy]
 */

/** 结果框按 label 分组配色。红/橙/青/蓝… 高对比，深浅色主题都看得清。 */
export const PALETTE = [
  "#e5484d",
  "#f5a524",
  "#12a594",
  "#3d5afe",
  "#8e4ec6",
  "#d6409f",
  "#0e9f6e",
  "#e8590c",
];

/** 表单持久化的 localStorage 键。改键名等于丢弃用户已存的参数。 */
export const FORM_STORE_KEY = "taozi-vlx-forms-v1";

/** 电子围栏描边色。刻意避开 PALETTE，别和结果框标签色混。 */
export const FENCE_COLOR = "#00d0ff";

/** 围栏最少顶点数，与后端 `fence.normalize` 的校验一致。 */
export const MIN_FENCE_VERTICES = 3;

/** top_p 默认值：任务目录里没有 default_top_p，统一取 1.0（等价不截断）。 */
export const DEFAULT_TOP_P = 1.0;

/** 区域任务提示词里的指代写法：索引 i → `<obj{i}>`。 */
export const objTag = (index) => `<obj${index}>`;
