import { proxyRequest } from './_shared/proxy.js'

export function onRequest(context) {
  return proxyRequest(context.request, context.env)
}
