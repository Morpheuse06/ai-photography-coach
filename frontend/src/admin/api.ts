/** Typed HTTP client for the management API. */

import type { ErrorBody } from './types'

const TOKEN_KEY = 'photography-admin-token'

export class AdminApiError extends Error {
  public readonly code: string
  public readonly status: number

  constructor(message: string, code: string, status: number) {
    super(message)
    this.name = 'AdminApiError'
    this.code = code
    this.status = status
  }
}

export function getStoredToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function storeToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
}

export async function adminFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  const token = getStoredToken()
  if (token !== null) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return fetch(path, { ...options, headers })
}

export async function adminRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response
  try {
    response = await adminFetch(path, options)
  } catch {
    throw new AdminApiError(
      '无法连接管理服务，请确认后端已经启动。',
      'network_error',
      0,
    )
  }
  if (response.status === 401) {
    clearToken()
    window.dispatchEvent(new Event('admin-session-expired'))
    throw new AdminApiError('管理员会话已过期，请重新登录。', 'session_expired', 401)
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | ErrorBody
      | null
    throw new AdminApiError(
      body?.error?.message ?? `请求失败（HTTP ${response.status}）。`,
      body?.error?.code ?? 'internal_error',
      response.status,
    )
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export function queryString(
  params: Record<string, string | number | boolean | undefined | null>,
): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}
