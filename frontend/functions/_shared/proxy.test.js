import { afterEach, describe, expect, it, vi } from 'vitest'

import { proxyRequest } from './proxy.js'

describe('Pages backend proxy', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('forwards the path, query, method, headers, and body', async () => {
    const backendResponse = new Response(
      JSON.stringify({ status: 'accepted' }),
      { status: 202, headers: { 'content-type': 'application/json' } },
    )
    const fetchMock = vi.fn().mockResolvedValue(backendResponse)
    vi.stubGlobal('fetch', fetchMock)

    const request = new Request(
      'https://ai-photography-coach.pages.dev/api/v2/problem-reports?source=web',
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: 'test' }),
      },
    )

    const response = await proxyRequest(request, {
      BACKEND_ORIGIN: 'https://backend.example.com/',
    })

    expect(response).toBe(backendResponse)
    expect(fetchMock).toHaveBeenCalledOnce()
    const forwardedRequest = fetchMock.mock.calls[0][0]
    expect(forwardedRequest.url).toBe(
      'https://backend.example.com/api/v2/problem-reports?source=web',
    )
    expect(forwardedRequest.method).toBe('POST')
    expect(forwardedRequest.headers.get('x-forwarded-host')).toBe(
      'ai-photography-coach.pages.dev',
    )
    expect(await forwardedRequest.json()).toEqual({ message: 'test' })
  })

  it('returns 503 when the backend origin is missing', async () => {
    const response = await proxyRequest(
      new Request('https://ai-photography-coach.pages.dev/health'),
      {},
    )

    expect(response.status).toBe(503)
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'proxy_not_configured',
        message: 'The backend origin is not configured.',
      },
    })
  })

  it('returns 502 when the backend cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    const response = await proxyRequest(
      new Request('https://ai-photography-coach.pages.dev/health'),
      { BACKEND_ORIGIN: 'https://backend.example.com' },
    )

    expect(response.status).toBe(502)
    await expect(response.json()).resolves.toMatchObject({
      error: { code: 'backend_unreachable' },
    })
  })
})
