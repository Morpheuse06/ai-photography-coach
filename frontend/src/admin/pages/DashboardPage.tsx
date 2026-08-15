import { useCallback, useEffect, useState } from 'react'

import { adminRequest, queryString } from '../api'
import TrendChart from '../components/TrendChart'
import type {
  AccessPolicyView,
  AccessMode,
  AnalysisRunPage,
  OverviewResponse,
} from '../types'

const RANGE_DAYS = [7, 30, 90]

export default function DashboardPage() {
  const [days, setDays] = useState(30)
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [policy, setPolicy] = useState<AccessPolicyView | null>(null)
  const [recentRuns, setRecentRuns] = useState<AnalysisRunPage | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const from = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString()
      const to = new Date().toISOString()
      const [overviewData, policyData, runsData] = await Promise.all([
        adminRequest<OverviewResponse>(
          `/api/admin/v1/overview${queryString({ from, to, bucket: 'day' })}`,
        ),
        adminRequest<AccessPolicyView>('/api/admin/v1/access-policy'),
        adminRequest<AnalysisRunPage>(
          `/api/admin/v1/analysis-runs${queryString({ page: 1, page_size: 8 })}`,
        ),
      ])
      setOverview(overviewData)
      setPolicy(policyData)
      setRecentRuns(runsData)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败。')
    }
  }, [days])

  useEffect(() => {
    void load()
  }, [load])

  const patchPolicy = async (field: string, value: string | number | null) => {
    try {
      const updated = await adminRequest<AccessPolicyView>(
        '/api/admin/v1/access-policy',
        {
          method: 'PATCH',
          body: JSON.stringify({ [field]: value }),
        },
      )
      setPolicy(updated)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '更新策略失败。')
    }
  }

  const totals = overview?.totals

  return (
    <section>
      <header className="admin-page-header">
        <h2>数据总览</h2>
        <div className="admin-range-picker" role="group" aria-label="时间范围">
          {RANGE_DAYS.map((range) => (
            <button
              key={range}
              type="button"
              className={range === days ? 'admin-range-active' : ''}
              onClick={() => setDays(range)}
            >
              近 {range} 天
            </button>
          ))}
        </div>
      </header>

      {error !== null && (
        <p className="admin-error" role="alert">
          {error}
        </p>
      )}

      {totals !== undefined && (
        <div className="admin-stat-grid">
          <div className="admin-stat">
            <div className="admin-stat-value">{totals.analyses_total}</div>
            <div className="admin-stat-label">分析总数</div>
          </div>
          <div className="admin-stat">
            <div className="admin-stat-value">{totals.analyses_succeeded}</div>
            <div className="admin-stat-label">成功</div>
          </div>
          <div className="admin-stat">
            <div className="admin-stat-value">{totals.analyses_failed}</div>
            <div className="admin-stat-label">失败</div>
          </div>
          <div className="admin-stat">
            <div className="admin-stat-value">
              {totals.average_latency_ms === null
                ? '—'
                : `${Math.round(totals.average_latency_ms / 1000)}s`}
            </div>
            <div className="admin-stat-label">平均耗时</div>
          </div>
          <div className="admin-stat">
            <div className="admin-stat-value">{totals.total_tokens}</div>
            <div className="admin-stat-label">Token 用量</div>
          </div>
          <div className="admin-stat">
            <div className="admin-stat-value">
              {totals.up_votes}/{totals.down_votes}
            </div>
            <div className="admin-stat-label">赞 / 踩</div>
          </div>
          <div className="admin-stat">
            <div className="admin-stat-value">
              {totals.open_problem_reports}
            </div>
            <div className="admin-stat-label">未处理反馈</div>
          </div>
        </div>
      )}

      {overview !== null && <TrendChart series={overview.series} />}

      <h3>访问策略</h3>
      {policy !== null && (
        <form
          className="admin-policy"
          onSubmit={(event) => event.preventDefault()}
        >
          <label>
            访问模式
            <select
              value={policy.mode}
              onChange={(event) =>
                void patchPolicy('mode', event.target.value as AccessMode)
              }
            >
              <option value="open">开放（无需邀请码）</option>
              <option value="code_required">需要邀请码</option>
              <option value="closed">关闭新分析</option>
            </select>
          </label>
          <label>
            单来源每小时上限
            <input
              type="number"
              min={1}
              value={policy.per_source_hour_limit ?? ''}
              placeholder="不限制"
              onChange={(event) => {
                const value = event.target.value
                void patchPolicy(
                  'per_source_hour_limit',
                  value === '' ? null : Number(value),
                )
              }}
            />
          </label>
          <label>
            全站每日上限
            <input
              type="number"
              min={1}
              value={policy.global_daily_limit ?? ''}
              placeholder="不限制"
              onChange={(event) => {
                const value = event.target.value
                void patchPolicy(
                  'global_daily_limit',
                  value === '' ? null : Number(value),
                )
              }}
            />
          </label>
          <label>
            并发分析上限
            <input
              type="number"
              min={1}
              value={policy.concurrent_analysis_limit}
              onChange={(event) =>
                void patchPolicy(
                  'concurrent_analysis_limit',
                  Number(event.target.value),
                )
              }
            />
          </label>
        </form>
      )}

      <h3>最近分析</h3>
      <table className="admin-table">
        <thead>
          <tr>
            <th>开始时间</th>
            <th>状态</th>
            <th>模型</th>
            <th>耗时</th>
            <th>赞/踩</th>
          </tr>
        </thead>
        <tbody>
          {(recentRuns?.items ?? []).map((run) => (
            <tr key={run.analysis_id}>
              <td>{new Date(run.started_at).toLocaleString()}</td>
              <td>{run.status}</td>
              <td>{run.model ?? '—'}</td>
              <td>
                {run.latency_ms === null ? '—' : `${run.latency_ms} ms`}
              </td>
              <td>
                {run.up_votes}/{run.down_votes}
              </td>
            </tr>
          ))}
          {(recentRuns?.items.length ?? 0) === 0 && (
            <tr>
              <td colSpan={5} className="admin-empty-cell">
                暂无分析记录。
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
