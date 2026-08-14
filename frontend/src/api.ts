import type { AnalysisResponse, ApiErrorResponse } from './types'

const ERROR_MESSAGES: Record<string, string> = {
  invalid_image: '这不是有效的 JPEG、PNG 或 WebP 图片，请重新选择。',
  image_too_large: '图片超过 10 MiB，请压缩后重试。',
  invalid_request: '提交内容不完整，请检查照片和拍摄意图。',
  model_rate_limited: '模型服务当前请求较多，请稍后重试。',
  invalid_model_output: '模型返回的报告格式异常，请重新分析。',
  model_unavailable: '模型服务暂时不可用，请稍后重试。',
  model_timeout: '本次分析超时，请稍后重试。',
  internal_error: '服务器出现异常，请稍后重试。',
}

export class AnalysisApiError extends Error {
  public readonly code: string
  public readonly status: number | null

  constructor(
    message: string,
    code: string,
    status: number | null,
  ) {
    super(message)
    this.name = 'AnalysisApiError'
    this.code = code
    this.status = status
  }
}

export async function analyzePhoto(
  photo: File,
  intent: string,
): Promise<AnalysisResponse> {
  const formData = new FormData()
  formData.append('photo', photo)
  if (intent.trim()) {
    formData.append('intent', intent.trim())
  }

  let response: Response
  try {
    response = await fetch('/api/v2/analyze', {
      method: 'POST',
      body: formData,
    })
  } catch {
    throw new AnalysisApiError(
      '无法连接分析服务，请确认后端已经启动。',
      'network_error',
      null,
    )
  }

  const payload = await readJson(response)
  if (!response.ok) {
    const errorPayload = isApiErrorResponse(payload) ? payload : null
    const code = errorPayload?.error.code ?? `http_${response.status}`
    throw new AnalysisApiError(
      ERROR_MESSAGES[code] ?? '分析失败，请稍后重试。',
      code,
      response.status,
    )
  }

  if (!isAnalysisResponse(payload)) {
    throw new AnalysisApiError(
      '服务器返回了无法识别的报告，请重新分析。',
      'invalid_response',
      response.status,
    )
  }

  return payload
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (!isRecord(value) || !isRecord(value.error)) {
    return false
  }
  return typeof value.error.code === 'string' && typeof value.error.message === 'string'
}

function isAnalysisResponse(value: unknown): value is AnalysisResponse {
  if (!isRecord(value) || !isRecord(value.report) || !isRecord(value.metadata)) {
    return false
  }
  const dimensions = value.report.dimensions
  return (
    isRecord(dimensions) &&
    ['composition', 'lighting', 'color', 'subject_expression', 'visual_storytelling'].every(
      (key) => isDimension(dimensions[key]),
    ) &&
    Array.isArray(value.report.priority_actions) &&
    value.report.priority_actions.length === 3 &&
    isRecord(value.report.next_shooting_exercise) &&
    typeof value.metadata.provider === 'string' &&
    typeof value.metadata.model === 'string'
  )
}

function isDimension(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.rating === 'number' &&
    value.rating >= 1 &&
    value.rating <= 5 &&
    typeof value.summary === 'string' &&
    Array.isArray(value.visual_evidence) &&
    Array.isArray(value.strengths) &&
    typeof value.main_issue === 'string' &&
    Array.isArray(value.improvement_suggestions)
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
