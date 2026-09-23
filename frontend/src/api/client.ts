let csrfToken = '';

export function setCsrfToken(token: string) {
  csrfToken = token || '';
}

function readCookie(name: string): string {
  const encoded = `${name}=`;
  const match = document.cookie.split('; ').find((part) => part.startsWith(encoded));
  return match ? decodeURIComponent(match.slice(encoded.length)) : '';
}

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, any>;
  constructor(message: string, code = 'ERROR', status = 400, details: Record<string, any> = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

interface NotModifiedResult { __notModified: true }

export function isNotModified(value: any): value is NotModifiedResult {
  return Boolean(value && value.__notModified);
}

async function request<T = any>(url: string, method = 'GET', body?: any, headers: Record<string, string> = {}): Promise<T> {
  const upper = method.toUpperCase();
  const reqHeaders: Record<string, string> = { Accept: 'application/json', ...headers };
  if (upper !== 'GET' && upper !== 'HEAD') {
    const token = csrfToken || readCookie('mas_csrf');
    if (token) reqHeaders['X-CSRF-Token'] = token;
  }

  let reqBody = body;
  if (body && !(body instanceof FormData)) {
    reqHeaders['Content-Type'] = 'application/json';
    reqBody = JSON.stringify(body);
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { method: upper, headers: reqHeaders, body: reqBody, credentials: 'include', signal: controller.signal });
    if (response.status === 304) return { __notModified: true } as T;

    let data: any = {};
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok || data.ok === false) {
      const err = data.error || {};
      const msg = err.message || (response.status === 401 ? 'لطفاً وارد شوید.' : response.status === 503 ? 'سرور یا دیتابیس موقتاً در دسترس نیست.' : 'خطایی در ارتباط با سرور رخ داد.');
      throw new ApiError(msg, err.code || `HTTP_${response.status}`, response.status, err.details || {});
    }
    return data as T;
  } catch (err: any) {
    if (err?.name === 'AbortError') throw new ApiError('پاسخ سرور بیش از حد طول کشید. لطفاً دوباره تلاش کنید.', 'REQUEST_TIMEOUT', 408);
    if (err instanceof ApiError) throw err;
    throw new ApiError('ارتباط با سرور برقرار نشد. اتصال اینترنت و وضعیت سرور را بررسی کنید.', 'NETWORK_ERROR', 0);
  } finally {
    window.clearTimeout(timeout);
  }
}

export const api = {
  get: <T = any>(url: string, headers?: Record<string, string>) => request<T>(url, 'GET', undefined, headers),
  post: <T = any>(url: string, body?: any) => request<T>(url, 'POST', body),
  put: <T = any>(url: string, body?: any) => request<T>(url, 'PUT', body),
  delete: <T = any>(url: string) => request<T>(url, 'DELETE'),
  upload: <T = any>(url: string, formData: FormData) => request<T>(url, 'POST', formData),
};
