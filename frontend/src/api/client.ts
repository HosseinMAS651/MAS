let csrfToken: string = '';

export function setCsrfToken(token: string) {
  csrfToken = token;
}

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, any>;

  constructor(message: string, code: string = 'ERROR', status: number = 400, details: Record<string, any> = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function request<T = any>(
  url: string,
  method: string = 'GET',
  body?: any,
  headers: Record<string, string> = {}
): Promise<T> {
  const reqHeaders: Record<string, string> = {
    Accept: 'application/json',
    ...headers,
  };

  if (csrfToken && method !== 'GET' && method !== 'HEAD') {
    reqHeaders['X-CSRF-Token'] = csrfToken;
  }

  let reqBody: any = body;
  if (body && !(body instanceof FormData)) {
    reqHeaders['Content-Type'] = 'application/json';
    reqBody = JSON.stringify(body);
  }

  const response = await fetch(url, {
    method,
    headers: reqHeaders,
    body: reqBody,
    credentials: 'include',
  });

  if (response.status === 304) {
    return null as any;
  }

  let data: any = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok || data.ok === false) {
    const err = data.error || {};
    const msg = err.message || (response.status === 401 ? 'لطفاً وارد شوید.' : 'خطایی در ارتباط با سرور رخ داد.');
    throw new ApiError(msg, err.code || `HTTP_${response.status}`, response.status, err.details || {});
  }

  return data;
}

export const api = {
  get: <T = any>(url: string, headers?: Record<string, string>) => request<T>(url, 'GET', undefined, headers),
  post: <T = any>(url: string, body?: any) => request<T>(url, 'POST', body),
  put: <T = any>(url: string, body?: any) => request<T>(url, 'PUT', body),
  delete: <T = any>(url: string) => request<T>(url, 'DELETE'),
  upload: <T = any>(url: string, formData: FormData) => request<T>(url, 'POST', formData),
};
