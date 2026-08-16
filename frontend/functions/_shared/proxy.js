const JSON_HEADERS = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
}

/**
 * Forward a same-origin Pages request to the configured FastAPI server.
 * The backend origin stays in Cloudflare configuration because deployment
 * addresses can change and must not be bundled into browser JavaScript.
 */
export async function proxyRequest(request, env) {
  const backendUrl = buildBackendUrl(env.BACKEND_ORIGIN, request.url)
  if (backendUrl === null) {
    return jsonError(
      503,
      'proxy_not_configured',
      'The backend origin is not configured.',
    )
  }

  const headers = new Headers(request.headers)
  const incomingUrl = new URL(request.url)
  headers.set('X-Forwarded-Host', incomingUrl.host)
  headers.set('X-Forwarded-Proto', incomingUrl.protocol.slice(0, -1))

  try {
    const forwardsBody = !['GET', 'HEAD'].includes(request.method)
    const forwardedRequest = new Request(backendUrl, {
      method: request.method,
      headers,
      body: forwardsBody ? await request.arrayBuffer() : undefined,
      redirect: 'manual',
    })
    return await fetch(forwardedRequest)
  } catch {
    return jsonError(
      502,
      'backend_unreachable',
      'The backend service could not be reached.',
    )
  }
}

function buildBackendUrl(origin, requestUrl) {
  if (typeof origin !== 'string' || origin.trim() === '') {
    return null
  }

  try {
    const backendUrl = new URL(origin)
    if (!['http:', 'https:'].includes(backendUrl.protocol)) {
      return null
    }

    const incomingUrl = new URL(requestUrl)
    backendUrl.pathname = incomingUrl.pathname
    backendUrl.search = incomingUrl.search
    backendUrl.hash = ''
    return backendUrl
  } catch {
    return null
  }
}

function jsonError(status, code, message) {
  return new Response(
    JSON.stringify({ error: { code, message } }),
    { status, headers: JSON_HEADERS },
  )
}
