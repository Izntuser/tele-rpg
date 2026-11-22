import { getTelegram } from '../telegram';
import type { components } from './schema';

export type AuthResponse = components['schemas']['AuthOut'];
export type MeResponse = components['schemas']['MeOut'];
export type User = components['schemas']['UserOut'];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`);
    this.name = 'ApiError';
  }
}

/** Telegram initData is missing (opened outside Telegram): login is impossible. */
export class NoInitDataError extends Error {
  constructor() {
    super('Open this app from Telegram');
    this.name = 'NoInitDataError';
  }
}

export type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RequestOptions {
  /** JSON-encoded, except a `FormData` (multipart upload), which is sent as-is. */
  body?: unknown;
  /** `blob` returns the response body as a Blob (file downloads); default JSON. */
  responseType?: 'json' | 'blob';
  /** `true` generates a fresh key; a string is sent as-is. Kept across the re-auth retry. */
  idempotencyKey?: string | true;
  signal?: AbortSignal;
}

export interface ApiClientOptions {
  baseUrl?: string;
  getInitData: () => string;
  fetch?: typeof fetch;
  newIdempotencyKey?: () => string;
}

export interface ApiClient {
  /** Exchange initData for a JWT (deduplicated while in flight); keeps the JWT in memory. */
  login(): Promise<AuthResponse>;
  request<T>(method: Method, path: string, options?: RequestOptions): Promise<T>;
  get<T>(path: string, options?: Omit<RequestOptions, 'body'>): Promise<T>;
  post<T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'body'>): Promise<T>;
  patch<T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'body'>): Promise<T>;
  delete<T>(path: string, options?: Omit<RequestOptions, 'body'>): Promise<T>;
  hasToken(): boolean;
  logout(): void;
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/** `ApiError.detail` of a successful response whose body was not JSON. */
export const NOT_JSON = 'Unexpected non-JSON response';

function errorDetail(body: unknown): unknown {
  if (body && typeof body === 'object' && 'detail' in body) {
    return (body as { detail: unknown }).detail;
  }
  return body;
}

/**
 * Fetch client for `/api`. The JWT lives only in this closure: never in localStorage,
 * sessionStorage, cookies or URLs. It is sent as `Authorization: Bearer`. A 401 triggers one
 * re-login with fresh initData and one retry of the request.
 */
export function createApiClient(options: ApiClientOptions): ApiClient {
  const baseUrl = options.baseUrl ?? '/api';
  const doFetch = options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const newKey = options.newIdempotencyKey ?? (() => crypto.randomUUID());
  let token: string | null = null;
  let pendingLogin: Promise<AuthResponse> | null = null;

  async function send(
    method: Method,
    path: string,
    body: unknown,
    headers: Record<string, string>,
    signal?: AbortSignal,
  ): Promise<Response> {
    const multipart = body instanceof FormData;
    const init: RequestInit = {
      method,
      headers: {
        Accept: 'application/json',
        // ngrok's free tier answers browser requests with an HTML interstitial (200) unless
        // this header is present; harmless on same-origin requests everywhere else.
        'ngrok-skip-browser-warning': '1',
        // A multipart body sets its own Content-Type (with the boundary).
        ...(body === undefined || multipart ? {} : { 'Content-Type': 'application/json' }),
        ...headers,
      },
      credentials: 'omit',
      cache: 'no-store',
      signal,
    };
    if (multipart) init.body = body;
    else if (body !== undefined) init.body = JSON.stringify(body);
    return doFetch(`${baseUrl}${path}`, init);
  }

  async function doLogin(): Promise<AuthResponse> {
    const initData = options.getInitData();
    if (!initData) throw new NoInitDataError();
    const response = await send('POST', '/auth/telegram', { init_data: initData }, {});
    const body = await readBody(response);
    if (!response.ok) {
      token = null;
      throw new ApiError(response.status, errorDetail(body));
    }
    const auth = body as AuthResponse;
    token = auth.jwt;
    return auth;
  }

  function login(): Promise<AuthResponse> {
    pendingLogin ??= doLogin().finally(() => {
      pendingLogin = null;
    });
    return pendingLogin;
  }

  async function request<T>(method: Method, path: string, opts: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = {};
    if (opts.idempotencyKey) {
      headers['Idempotency-Key'] = opts.idempotencyKey === true ? newKey() : opts.idempotencyKey;
    }
    if (token === null) await login();

    let response = await send(
      method,
      path,
      opts.body,
      { ...headers, Authorization: `Bearer ${token}` },
      opts.signal,
    );
    if (response.status === 401) {
      // The JWT expired or was revoked: re-authenticate once, then retry with the same key.
      token = null;
      await login();
      response = await send(
        method,
        path,
        opts.body,
        { ...headers, Authorization: `Bearer ${token}` },
        opts.signal,
      );
    }
    if (response.ok && opts.responseType === 'blob') return (await response.blob()) as T;
    const body = await readBody(response);
    if (!response.ok) throw new ApiError(response.status, errorDetail(body));
    // Every endpoint answers JSON (or 204). A 2xx with a text body is not our API (a tunnel or
    // proxy page, a dev-server fallback): callers would read fields off a string.
    if (typeof body === 'string') throw new ApiError(response.status, NOT_JSON);
    return body as T;
  }

  return {
    login,
    request,
    get: (path, o) => request('GET', path, o),
    post: (path, body, o) => request('POST', path, { ...o, body }),
    patch: (path, body, o) => request('PATCH', path, { ...o, body }),
    delete: (path, o) => request('DELETE', path, o),
    hasToken: () => token !== null,
    logout: () => {
      token = null;
    },
  };
}

/** The app-wide client; initData comes from the Telegram adapter. */
export const api = createApiClient({ getInitData: () => getTelegram().getInitData() });
