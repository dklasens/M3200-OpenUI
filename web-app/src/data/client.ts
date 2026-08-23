// HTTP client for the agent: token handling, envelope unwrapping, timeouts.
//
// The dashboard is served by the agent itself (single port, same origin),
// so all API paths are relative and no CORS is involved.

export const AUTH_EXPIRED_EVENT = 'm3200-auth-expired'

let _token: string | null = sessionStorage.getItem('m3200_token')

export function setToken(t: string) {
  _token = t
  sessionStorage.setItem('m3200_token', t)
}

export function clearToken() {
  _token = null
  sessionStorage.removeItem('m3200_token')
}

export function hasToken() {
  return !!_token
}

export class ApiError extends Error {
  status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function emitAuthExpired() {
  clearToken()
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
}

export async function req(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
  timeoutMs = 15_000,
): Promise<Record<string, unknown>> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  const headers: Record<string, string> = { ...(extraHeaders ?? {}) }
  if (_token) headers['Authorization'] = `Bearer ${_token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  try {
    let res: Response
    try {
      res = await fetch(path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      })
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        throw new ApiError('Timed out reaching the agent')
      }
      throw new ApiError('Failed to reach the agent')
    }

    let json: { ok?: boolean; data?: unknown; error?: string }
    try {
      json = await res.json()
    } catch {
      throw new ApiError(`Invalid response from agent (${res.status})`, res.status)
    }

    if (res.status === 401 && path !== '/api/auth/login') {
      emitAuthExpired()
    }
    if (!res.ok || !json.ok) {
      throw new ApiError(json.error ?? `request failed (${res.status})`, res.status)
    }
    return (json.data ?? {}) as Record<string, unknown>
  } finally {
    clearTimeout(timeout)
  }
}

export const get = (path: string) => req('GET', path)
export const post = (path: string, body?: unknown, extraHeaders?: Record<string, string>) =>
  req('POST', path, body, extraHeaders)

export async function login(password: string): Promise<{ token: string }> {
  const data = await req('POST', '/api/auth/login', { password })
  return { token: data.token as string }
}
