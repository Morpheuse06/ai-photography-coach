/** TypeScript contracts mirroring src/photography_coach/schemas/admin.py. */

import type { AnalysisMetadata, PhotographyReport } from '../types'

export type AccessMode = 'open' | 'code_required' | 'closed'

export interface ErrorBody {
  error: { code: string; message: string }
}

export interface PageInfo {
  page: number
  page_size: number
  total_items: number
  total_pages: number
}

export interface AdminSessionCreated {
  access_token: string
  token_type: string
  expires_at: string
}

export interface AccessPolicyView {
  mode: AccessMode
  per_source_hour_limit: number | null
  global_daily_limit: number | null
  concurrent_analysis_limit: number
  updated_at: string
}

export type AccessCodeStatus =
  | 'active'
  | 'exhausted'
  | 'expired'
  | 'revoked'

export interface GeneratedAccessCode {
  code_id: string
  code: string
  prefix: string
  uses_total: number
  expires_at: string | null
}

export interface AccessCodeBatchCreated {
  batch_id: string
  created_at: string
  codes: GeneratedAccessCode[]
}

export interface AccessCodeRecord {
  code_id: string
  batch_id: string
  prefix: string
  label: string | null
  status: AccessCodeStatus
  uses_total: number
  uses_consumed: number
  uses_reserved: number
  expires_at: string | null
  created_at: string
  updated_at: string
}

export interface AccessCodePage {
  items: AccessCodeRecord[]
  page: PageInfo
}

export interface AccessCodeUsageEvent {
  usage_event_id: string
  code_id: string
  analysis_id: string
  status: 'reserved' | 'consumed' | 'released'
  occurred_at: string
  release_reason: string | null
}

export interface AccessCodeUsageEventPage {
  items: AccessCodeUsageEvent[]
  page: PageInfo
}

export type AnalysisRunStatus =
  | 'reserved'
  | 'running'
  | 'succeeded'
  | 'failed'

export interface AnalysisRunSummary {
  analysis_id: string
  status: AnalysisRunStatus
  api_version: string
  started_at: string
  completed_at: string | null
  access_code_prefix: string | null
  provider: string | null
  model: string | null
  prompt_version: string | null
  latency_ms: number | null
  total_tokens: number | null
  error_code: string | null
  up_votes: number
  down_votes: number
}

export interface AnalysisRunDetail extends AnalysisRunSummary {
  shooting_intent: string | null
  metadata: AnalysisMetadata | null
  report: PhotographyReport | null
  report_retained_until: string | null
  sanitized_diagnostic: string | null
}

export interface AnalysisRunPage {
  items: AnalysisRunSummary[]
  page: PageInfo
}

export type RatingTarget =
  | 'composition'
  | 'lighting'
  | 'color'
  | 'subject_expression'
  | 'visual_storytelling'
  | 'priority_actions'
  | 'shooting_exercise'
  | 'overall'

export interface RatingTargetSummary {
  target: RatingTarget
  up_votes: number
  down_votes: number
}

export interface RatingSummary {
  items: RatingTargetSummary[]
}

export interface RatingRecord {
  rating_id: string
  analysis_id: string
  target: RatingTarget
  vote: 'up' | 'down'
  reason_codes: string[]
  comment: string | null
  created_at: string
  updated_at: string
}

export interface RatingPage {
  items: RatingRecord[]
  page: PageInfo
}

export type ProblemStatus = 'new' | 'in_progress' | 'resolved' | 'ignored'
export type ProblemPriority = 'low' | 'normal' | 'high' | 'urgent'

export interface ProblemReportRecord {
  problem_report_id: string
  analysis_id: string | null
  category: string
  message: string
  status: ProblemStatus
  priority: ProblemPriority
  tags: string[]
  admin_note: string | null
  created_at: string
  updated_at: string
}

export interface ProblemReportPage {
  items: ProblemReportRecord[]
  page: PageInfo
}

export interface OverviewMetrics {
  period_started_at: string
  period_ended_at: string
  analyses_total: number
  analyses_succeeded: number
  analyses_failed: number
  model_timeouts: number
  total_tokens: number
  average_latency_ms: number | null
  up_votes: number
  down_votes: number
  open_problem_reports: number
}

export interface MetricBucket {
  bucket_started_at: string
  analyses_total: number
  analyses_succeeded: number
  analyses_failed: number
  total_tokens: number
  up_votes: number
  down_votes: number
}

export interface OverviewResponse {
  totals: OverviewMetrics
  series: MetricBucket[]
}

export interface SystemStatus {
  status: string
  application_version: string
  started_at: string
  access_mode: AccessMode
  rag_enabled: boolean
  knowledge_index_ready: boolean
  recent_error_rate: number
}

export interface SystemVersions {
  provider: string
  model: string
  report_prompt_version: string
  retrieval_prompt_version: string | null
  knowledge_source_id: string | null
  knowledge_source_version: string | null
  embedding_model: string | null
  reranker_model: string | null
}

export interface AuditEvent {
  audit_event_id: string
  admin_subject: string
  action: string
  resource_type: string
  resource_id: string | null
  occurred_at: string
  details: Record<string, string | number | boolean | null>
}
