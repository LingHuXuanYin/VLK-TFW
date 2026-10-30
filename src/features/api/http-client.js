/**
 * HTTP 客户端：把 `fetch` 作为依赖注入，逻辑层不直接摸全局运行时。
 *
 * 属于 features 组，禁止 import 任何 UI 模块。浏览器可用，Node 18+ 也可用（自带 fetch/FormData）。
 */

/** 带状态码与响应体的接口错误，UI 层用它展示 `detail` 文案。 */
export class ApiError extends Error {
  /**
   * @param {string} message 面向用户的文案（后端 detail 优先）
   * @param {number} status  HTTP 状态码
   * @param {unknown} payload 解析后的响应体，可能为 null
   */
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

/**
 * 创建 HTTP 客户端。
 * @param {{ fetchImpl?: (input: string, init?: object) => Promise<any> }} [options]
 *   fetchImpl 不传时用 `globalThis.fetch`；测试可注入假实现。
 * @returns {{
 *   request: (path: string, options?: object) => Promise<any>,
 *   get: (path: string) => Promise<any>,
 *   postJson: (path: string, body?: object) => Promise<any>,
 *   postForm: (path: string, form: any) => Promise<any>
 * }}
 */
export function createHttpClient({ fetchImpl } = {}) {
  const doFetch = fetchImpl || ((input, init) => globalThis.fetch(input, init));

  /**
   * 发一个请求并解析 JSON。
   * 异常：非 2xx 抛 `ApiError`（文案优先取 `detail`，其次 `message`，最后 `HTTP <status>`）；
   *      网络层失败原样抛出（通常是 TypeError）。
   * 边界：204 或非 JSON 响应体时 `data` 为 null，不视为错误。
   */
  async function request(path, options = {}) {
    const init = { method: options.method || "GET", signal: options.signal, headers: {} };
    if (options.json !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.json);
    } else if (options.form !== undefined) {
      init.body = options.form; // multipart 交给浏览器设 Content-Type
    }
    const res = await doFetch(path, init);
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      /* 非 JSON 响应体按空处理 */
    }
    if (!res.ok) {
      const raw = (data && (data.detail || data.message)) || `HTTP ${res.status}`;
      throw new ApiError(typeof raw === "string" ? raw : JSON.stringify(raw), res.status, data);
    }
    return data;
  }

  return {
    request,
    get: (path) => request(path),
    postJson: (path, body) => request(path, { method: "POST", json: body ?? {} }),
    postForm: (path, form) => request(path, { method: "POST", form }),
  };
}
