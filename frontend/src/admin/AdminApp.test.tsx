import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AdminApp from './AdminApp'
import { clearToken, storeToken } from './api'
import type { OverviewResponse } from './types'

const overviewFixture: OverviewResponse = {
  totals: {
    period_started_at: '2026-08-15T00:00:00Z',
    period_ended_at: '2026-08-15T23:59:59Z',
    analyses_total: 2,
    analyses_succeeded: 1,
    analyses_failed: 1,
    model_timeouts: 0,
    total_tokens: 100,
    average_latency_ms: 500,
    up_votes: 1,
    down_votes: 1,
    open_problem_reports: 0,
  },
  series: [
    {
      bucket_started_at: '2026-08-14T00:00:00Z',
      analyses_total: 1,
      analyses_succeeded: 1,
      analyses_failed: 0,
      total_tokens: 60,
      up_votes: 1,
      down_votes: 0,
    },
    {
      bucket_started_at: '2026-08-15T00:00:00Z',
      analyses_total: 1,
      analyses_succeeded: 0,
      analyses_failed: 1,
      total_tokens: 40,
      up_votes: 0,
      down_votes: 1,
    },
  ],
}

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

describe('AdminApp', () => {
  beforeEach(() => {
    clearToken()
    window.location.hash = '#/dashboard'
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the login page when no session token exists', () => {
    render(<AdminApp />)
    expect(screen.getByText('摄影教练 · 管理控制台')).toBeTruthy()
    expect(screen.getByLabelText('用户名')).toBeTruthy()
  })

  it('logs in and shows the dashboard', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async (input) => {
        const path = String(input)
        if (path.includes('/sessions') && path.includes('/api/admin')) {
          return jsonResponse(
            {
              access_token: 'test-admin-token-0123456789012345678901234567',
              token_type: 'bearer',
              expires_at: '2026-08-16T00:00:00Z',
            },
            201,
          )
        }
        if (path.includes('/overview')) return jsonResponse(overviewFixture)
        if (path.includes('/access-policy'))
          return jsonResponse({
            mode: 'open',
            per_source_hour_limit: 60,
            global_daily_limit: 500,
            concurrent_analysis_limit: 4,
            updated_at: '2026-08-15T00:00:00Z',
          })
        if (path.includes('/analysis-runs'))
          return jsonResponse({ items: [], page: { page: 1, page_size: 8, total_items: 0, total_pages: 0 } })
        return new Response('{}', { status: 404 })
      })

    render(<AdminApp />)
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'owner' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'correct horse battery staple' },
    })
    fireEvent.click(screen.getByRole('button', { name: /登录/ }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '数据总览' })).toBeTruthy()
    })
    expect(screen.getByText('访问策略')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalled()
  })

  it('returns to login when a request reports 401', async () => {
    storeToken('expired-token-0123456789012345678901234567890')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ error: { code: 'admin_authentication_required', message: 'x' } }, 401),
    )

    render(<AdminApp />)

    await waitFor(() => {
      expect(screen.getByLabelText('用户名')).toBeTruthy()
    })
  })
})
