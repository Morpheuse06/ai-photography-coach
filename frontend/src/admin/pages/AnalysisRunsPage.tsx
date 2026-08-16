import { useCallback, useEffect, useState } from 'react'

import { adminRequest, queryString } from '../api'
import { Pagination } from './InviteCodesPage'
import type {
  AnalysisRunDetail,
  AnalysisRunPage,
  AnalysisRunStatus,
} from '../types'
import type { PhotographyDimensions } from '../../types'

const STATUS_LABELS: Record<AnalysisRunStatus, string> = {
  reserved: '已预占',
  running: '进行中',
  succeeded: '成功',
  failed: '失败',
}

interface Filters {
  status: string
  provider: string
  model: string
  prompt_version: string
  access_code_prefix: string
  error_code: string
  has_down_vote: boolean
}

const EMPTY_FILTERS: Filters = {
  status: '',
  provider: '',
  model: '',
  prompt_version: '',
  access_code_prefix: '',
  error_code: '',
  has_down_vote: false,
}

const DIMENSION_ROWS: {
  key: keyof PhotographyDimensions
  label: string
}[] = [
  { key: 'composition', label: '构图' },
  { key: 'lighting', label: '光影' },
  { key: 'color', label: '色彩' },
  { key: 'subject_expression', label: '主体表达' },
  { key: 'visual_storytelling', label: '视觉叙事' },
]

export default function AnalysisRunsPage() {
  const [page, setPage] = useState<AnalysisRunPage | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [detail, setDetail] = useState<AnalysisRunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await adminRequest<AnalysisRunPage>(
        `/api/admin/v1/analysis-runs${queryString({
          page: currentPage,
          page_size: 20,
          status: filters.status || undefined,
          provider: filters.provider || undefined,
          model: filters.model || undefined,
          prompt_version: filters.prompt_version || undefined,
          access_code_prefix: filters.access_code_prefix || undefined,
          error_code: filters.error_code || undefined,
          has_down_vote: filters.has_down_vote || undefined,
        })}`,
      )
      setPage(data)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败。')
    }
  }, [currentPage, filters])

  useEffect(() => {
    void load()
  }, [load])

  const openDetail = async (analysisId: string) => {
    setError(null)
    try {
      const data = await adminRequest<AnalysisRunDetail>(
        `/api/admin/v1/analysis-runs/${analysisId}`,
      )
      setDetail(data)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载详情失败。')
    }
  }

  return (
    <section>
      <header className="admin-page-header">
        <h2>分析记录</h2>
      </header>

      {error !== null && (
        <p className="admin-error" role="alert">
          {error}
        </p>
      )}

      <form
        className="admin-form-row admin-filter-row"
        onSubmit={(event) => {
          event.preventDefault()
          setCurrentPage(1)
          void load()
        }}
      >
        <label>
          状态
          <select
            value={filters.status}
            onChange={(event) =>
              setFilters({ ...filters, status: event.target.value })
            }
          >
            <option value="">全部</option>
            <option value="succeeded">成功</option>
            <option value="failed">失败</option>
            <option value="running">进行中</option>
          </select>
        </label>
        <label>
          Provider
          <input
            value={filters.provider}
            onChange={(event) =>
              setFilters({ ...filters, provider: event.target.value })
            }
          />
        </label>
        <label>
          模型
          <input
            value={filters.model}
            onChange={(event) =>
              setFilters({ ...filters, model: event.target.value })
            }
          />
        </label>
        <label>
          错误码
          <input
            value={filters.error_code}
            onChange={(event) =>
              setFilters({ ...filters, error_code: event.target.value })
            }
          />
        </label>
        <label>
          邀请码前缀
          <input
            value={filters.access_code_prefix}
            onChange={(event) =>
              setFilters({ ...filters, access_code_prefix: event.target.value })
            }
          />
        </label>
        <label className="admin-checkbox">
          <input
            type="checkbox"
            checked={filters.has_down_vote}
            onChange={(event) =>
              setFilters({ ...filters, has_down_vote: event.target.checked })
            }
          />
          仅看有点踩
        </label>
        <button className="admin-button admin-button-primary" type="submit">
          筛选
        </button>
      </form>

      <table className="admin-table">
        <thead>
          <tr>
            <th>开始时间</th>
            <th>状态</th>
            <th>模型</th>
            <th>Prompt</th>
            <th>耗时</th>
            <th>Token</th>
            <th>赞/踩</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          {(page?.items ?? []).map((run) => (
            <tr key={run.analysis_id}>
              <td>{new Date(run.started_at).toLocaleString()}</td>
              <td>{STATUS_LABELS[run.status]}</td>
              <td>{run.model ?? '—'}</td>
              <td>{run.prompt_version ?? '—'}</td>
              <td>{run.latency_ms === null ? '—' : `${run.latency_ms} ms`}</td>
              <td>{run.total_tokens ?? '—'}</td>
              <td>
                {run.up_votes}/{run.down_votes}
              </td>
              <td>
                <button
                  className="admin-button admin-button-small"
                  type="button"
                  onClick={() => void openDetail(run.analysis_id)}
                >
                  查看
                </button>
              </td>
            </tr>
          ))}
          {(page?.items.length ?? 0) === 0 && (
            <tr>
              <td colSpan={8} className="admin-empty-cell">
                没有符合条件的分析记录。
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <Pagination page={page} onPage={setCurrentPage} />

      {detail !== null && (
        <section className="admin-detail" aria-label="分析详情">
          <header className="admin-page-header">
            <h3>分析详情</h3>
            <button
              className="admin-button admin-button-ghost"
              type="button"
              onClick={() => setDetail(null)}
            >
              关闭
            </button>
          </header>
          <dl className="admin-key-values">
            <dt>状态</dt>
            <dd>{STATUS_LABELS[detail.status]}</dd>
            <dt>拍摄意图</dt>
            <dd>{detail.shooting_intent ?? '（已按保留期清理）'}</dd>
            <dt>错误码</dt>
            <dd>{detail.error_code ?? '—'}</dd>
            <dt>诊断信息</dt>
            <dd>{detail.sanitized_diagnostic ?? '—'}</dd>
            <dt>邀请码前缀</dt>
            <dd>{detail.access_code_prefix ?? '—'}</dd>
            <dt>报告保留至</dt>
            <dd>
              {detail.report_retained_until === null
                ? '—'
                : new Date(detail.report_retained_until).toLocaleString()}
            </dd>
          </dl>
          {detail.report !== null && (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>维度</th>
                  <th>评分</th>
                  <th>判断</th>
                </tr>
              </thead>
              <tbody>
                {DIMENSION_ROWS.map(({ key, label }) => {
                  const dimension = detail.report?.dimensions[key]
                  return (
                    <tr key={key}>
                      <td>{label}</td>
                      <td>{dimension?.rating ?? '—'}</td>
                      <td>{dimension?.summary ?? '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          {detail.report === null && (
            <p className="admin-muted">报告内容已按保留期清理。</p>
          )}
        </section>
      )}
    </section>
  )
}
