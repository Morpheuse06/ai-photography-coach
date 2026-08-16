import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AnalysisRunsPage from './AnalysisRunsPage'

const analysisId = '11111111-1111-4111-8111-111111111111'

const summary = {
  analysis_id: analysisId,
  status: 'succeeded',
  api_version: 'v2',
  started_at: '2026-08-16T10:00:00Z',
  completed_at: '2026-08-16T10:00:10Z',
  access_code_prefix: null,
  provider: 'dashscope',
  model: 'qwen3.7-plus',
  prompt_version: 'photography-coach-v1.1',
  latency_ms: 10_000,
  total_tokens: 800,
  error_code: null,
  up_votes: 1,
  down_votes: 0,
}

const assessment = (summaryText: string) => ({
  rating: 4,
  summary: summaryText,
  visual_evidence: ['画面证据'],
  strengths: ['优点'],
  main_issue: '主要问题',
  improvement_suggestions: ['改进建议'],
})

const detail = {
  ...summary,
  shooting_intent: '记录清晨街道',
  metadata: null,
  report: {
    dimensions: {
      composition: assessment('构图判断'),
      lighting: assessment('光影判断'),
      color: assessment('色彩判断'),
      subject_expression: assessment('主体判断'),
      visual_storytelling: assessment('叙事判断'),
    },
    priority_actions: [
      { priority: 1, action: '动作一', reason: '原因一' },
      { priority: 2, action: '动作二', reason: '原因二' },
      { priority: 3, action: '动作三', reason: '原因三' },
    ],
    next_shooting_exercise: {
      title: '练习',
      objective: '目标',
      steps: ['步骤'],
      success_criteria: ['标准'],
    },
  },
  report_retained_until: '2026-09-15T10:00:00Z',
  sanitized_diagnostic: null,
}

const jsonResponse = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

describe('AnalysisRunsPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders a structured report when analysis details are opened', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const path = String(input)
      if (path.endsWith(`/analysis-runs/${analysisId}`)) {
        return jsonResponse(detail)
      }
      return jsonResponse({
        items: [summary],
        page: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
      })
    })

    render(<AnalysisRunsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '查看' })).toBeTruthy()
    })
    fireEvent.click(screen.getByRole('button', { name: '查看' }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '分析详情' })).toBeTruthy()
    })
    expect(screen.getByText('构图判断')).toBeTruthy()
    expect(screen.getByText('光影判断')).toBeTruthy()
    expect(screen.getByText('视觉叙事')).toBeTruthy()
    expect(screen.getByText('叙事判断')).toBeTruthy()
  })
})
