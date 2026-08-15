import type {
  AnalysisResponse,
  ApiErrorResponse,
  ProblemCategory,
  ProblemReportReceipt,
  RatingReasonCode,
  RatingReceipt,
  RatingTarget,
  RatingVote,
} from './types'

const ERROR_MESSAGES: Record<string, string> = {
  invalid_image: '这不是有效的 JPEG、PNG 或 WebP 图片，请重新选择。',
  image_too_large: '图片超过 10 MiB，请压缩后重试。',
  invalid_request: '提交内容不完整，请检查照片和拍摄意图。',
  model_rate_limited: '模型服务当前请求较多，请稍后重试。',
  invalid_model_output: '模型返回的报告格式异常，请重新分析。',
  model_unavailable: '模型服务暂时不可用，请稍后重试。',
  model_timeout: '本次分析超时，请稍后重试。',
  internal_error: '服务器出现异常，请稍后重试。',
  access_code_required: '当前需要邀请码才能分析，请填写后重试。',
  access_denied: '邀请码无效、已过期或已撤销，请检查后重试。',
  analysis_closed: '新分析暂时关闭，请稍后再来。',
  idempotency_conflict: '请求重放冲突，请刷新页面后重试。',
  access_quota_exhausted: '该邀请码的次数已用完。',
  request_rate_limited: '提交过于频繁，请稍后再试。',
  global_quota_exhausted: '今日分析额度已用完，请明天再来。',
  concurrency_limit_reached: '同时分析的人数较多，请稍后再试。',
  control_plane_unavailable: '分析服务暂时不可用，请稍后重试。',
  feedback_forbidden: '反馈凭据无效，请重新分析后再评价。',
  feedback_rate_limited: '反馈提交过于频繁，请稍后再试。',
  analysis_not_found: '该次分析已不存在，无法提交反馈。',
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
  accessCode: string,
): Promise<AnalysisResponse> {
  const formData = new FormData()
  formData.append('photo', photo)
  if (intent.trim()) {
    formData.append('intent', intent.trim())
  }

  const headers: Record<string, string> = {
    'Idempotency-Key': crypto.randomUUID(),
  }
  if (accessCode.trim()) {
    headers['X-Access-Code'] = accessCode.trim()
  }

  let response: Response
  try {
    response = await fetch('/api/v2/analyze', {
      method: 'POST',
      body: formData,
      headers,
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

export async function upsertRating(
  analysisId: string,
  feedbackToken: string,
  target: RatingTarget,
  vote: RatingVote,
  reasonCodes: RatingReasonCode[] = [],
  comment: string | null = null,
): Promise<RatingReceipt> {
  return feedbackRequest<RatingReceipt>(
    `/api/v2/analyses/${analysisId}/ratings/${target}`,
    {
      method: 'PUT',
      body: JSON.stringify({ vote, reason_codes: reasonCodes, comment }),
    },
    feedbackToken,
  )
}

export async function deleteRating(
  analysisId: string,
  feedbackToken: string,
  target: RatingTarget,
): Promise<void> {
  await feedbackRequest<null>(
    `/api/v2/analyses/${analysisId}/ratings/${target}`,
    { method: 'DELETE' },
    feedbackToken,
  )
}

export async function submitProblemReport(
  payload: {
    analysis_id: string | null
    category: ProblemCategory
    message: string
    include_runtime_metadata: boolean
  },
): Promise<ProblemReportReceipt> {
  return feedbackRequest<ProblemReportReceipt>(
    '/api/v2/problem-reports',
    { method: 'POST', body: JSON.stringify(payload) },
    null,
  )
}

async function feedbackRequest<T>(
  path: string,
  options: RequestInit,
  feedbackToken: string | null,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (feedbackToken !== null) {
    headers.Authorization = `Bearer ${feedbackToken}`
  }

  let response: Response
  try {
    response = await fetch(path, { ...options, headers })
  } catch {
    throw new AnalysisApiError(
      '无法连接分析服务，请确认后端已经启动。',
      'network_error',
      null,
    )
  }

  if (response.status === 204) {
    return null as T
  }

  const payload = await readJson(response)
  if (!response.ok) {
    const errorPayload = isApiErrorResponse(payload) ? payload : null
    const code = errorPayload?.error.code ?? `http_${response.status}`
    throw new AnalysisApiError(
      ERROR_MESSAGES[code] ?? '反馈提交失败，请稍后重试。',
      code,
      response.status,
    )
  }
  return payload as T
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
    typeof value.metadata.model === 'string' &&
    isRetrievalMetadata(value.metadata.retrieval) &&
    isAnalysisInteraction(value.interaction)
  )
}

function isAnalysisInteraction(value: unknown): boolean {
  if (value === undefined || value === null) return true
  return (
    isRecord(value) &&
    typeof value.analysis_id === 'string' &&
    typeof value.feedback_token === 'string' &&
    isRecord(value.access) &&
    ['open', 'code_required', 'closed'].includes(String(value.access.mode)) &&
    (value.access.remaining_uses === null ||
      (typeof value.access.remaining_uses === 'number' &&
        value.access.remaining_uses >= 0))
  )
}

function isRetrievalMetadata(value: unknown): boolean {
  if (value === undefined || value === null) return true
  return (
    isRecord(value) &&
    typeof value.knowledge_source_id === 'string' &&
    typeof value.knowledge_source_version === 'string' &&
    typeof value.planner_model === 'string' &&
    typeof value.planner_prompt_version === 'string' &&
    typeof value.planner_attempts === 'number' &&
    typeof value.embedding_model === 'string' &&
    typeof value.reranker_model === 'string' &&
    typeof value.latency_ms === 'number' &&
    Array.isArray(value.retrieved_chunk_ids) &&
    value.retrieved_chunk_ids.every((item) => typeof item === 'string')
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
