/**
 * VLX 调测台端点适配器：把 HTTP 细节挡在业务与 UI 之外。
 *
 * 属于 features 组。入参注入 `http`（见 `http-client.js`），不关心底层是 fetch 还是别的。
 * 换成小程序时只需换一个 http 实现，本文件不用改。
 */

/**
 * 创建 API 适配器。
 * @param {{ http: { get: Function, postJson: Function, postForm: Function } }} deps
 * @returns {{
 *   getMeta: () => Promise<any>,
 *   getStatus: () => Promise<any>,
 *   loadModel: () => Promise<any>,
 *   loadDemo: () => Promise<any>,
 *   uploadImage: (file: any) => Promise<any>,
 *   getProposals: (imageId: string, force?: boolean) => Promise<any>,
 *   runTask: (taskId: string, payload: object) => Promise<any>,
 *   runSuite: (payload: object) => Promise<any>
 * }}
 */
export function createVlxApi({ http }) {
  return {
    /** 任务元数据 + 环境信息（模型/权重路径、图像长边上限、分组）。 */
    getMeta: () => http.get("/api/meta"),

    /** 模型状态快照（idle/loading/ready/error + infer_busy）。 */
    getStatus: () => http.get("/api/status"),

    /** 触发或重试模型加载。已 ready/loading 时后端幂等返回。 */
    loadModel: () => http.postJson("/api/model/load"),

    /** 载入 VLX-Seek 自带示例图，返回落盘后的元信息。 */
    loadDemo: () => http.get("/api/demo"),

    /**
     * 上传图片（multipart 字段名必须为 `file`）。
     * @param {Blob|File} file 浏览器选中的文件
     * @returns {Promise<{ok: boolean, image_id: string, width: number, height: number}>}
     */
    uploadImage: (file) => {
      const form = new FormData();
      form.append("file", file);
      return http.postForm("/api/images", form);
    },

    /**
     * 取候选框；`force=true` 忽略磁盘缓存。
     * @returns {Promise<{boxes: number[][], source: "cache"|"wedetect", count: number, elapsed_ms?: number}>}
     */
    getProposals: (imageId, force = false) => http.postJson("/api/proposals", { image_id: imageId, force }),

    /**
     * 跑单个任务。
     * @param {string} taskId 七个任务之一
     * @param {object} payload 见 `RunPayload`
     * @returns {Promise<object>} 见 `TaskResult`
     */
    runTask: (taskId, payload) => http.postJson(`/api/tasks/${encodeURIComponent(taskId)}/run`, payload),

    /**
     * 串行跑完七个任务。
     * @param {object} payload `{image_id, bbox_list, auto_proposals, overrides}`
     * @returns {Promise<object>} 见 `SuiteResult`
     */
    runSuite: (payload) => http.postJson("/api/suite/run", payload),
  };
}
