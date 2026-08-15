import { useCallback, useEffect, useState } from 'react'

import { adminRequest, queryString } from '../api'
import { Pagination } from './InviteCodesPage'
import type { RatingPage, RatingSummary, RatingTarget } from '../types'

const TARGET_LABELS: Record<RatingTarget, string> = {
  composition: '构图',
  lighting: '光影',
  color: '色彩',
  subject_expression: '主体表达',
  visual_storytelling: '视觉叙事',
  priority_actions: '优先动作',
  shooting_exercise: '拍摄练习',
  overall: '总体',
}

export default function RatingsPage() {
  const [summary, setSummary] = useState<RatingSummary | null>(null)
  const [page, setPage] = useState<RatingPage | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [vote, setVote] = useState('')
  const [target, setTarget] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [summaryData, pageData] = await Promise.all([
        adminRequest<RatingSummary>('/api/admin/v1/ratings/summary'),
        adminRequest<RatingPage>(
          `/api/admin/v1/ratings${queryString({
            page: currentPage,
            page_size: 20,
            vote: vote || undefined,
            target: target || undefined,
          })}`,
        ),
      ])
      setSummary(summaryData)
      setPage(pageData)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败。')
    }
  }, [currentPage, vote, target])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section>
      <header className="admin-page-header">
        <h2>模块评价</h2>
      </header>

      {error !== null && (
        <p className="admin-error" role="alert">
          {error}
        </p>
      )}

      <div className="admin-stat-grid admin-rating-summary">
        {(summary?.items ?? []).map((item) => (
          <div className="admin-stat" key={item.target}>
            <div className="admin-stat-label">{TARGET_LABELS[item.target]}</div>
            <div className="admin-stat-value">
              {item.up_votes} / {item.down_votes}
            </div>
            <div className="admin-muted">赞 / 踩</div>
          </div>
        ))}
      </div>

      <div className="admin-filter-row">
        <label>
          目标
          <select
            value={target}
            onChange={(event) => {
              setTarget(event.target.value)
              setCurrentPage(1)
            }}
          >
            <option value="">全部</option>
            {Object.entries(TARGET_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          评价
          <select
            value={vote}
            onChange={(event) => {
              setVote(event.target.value)
              setCurrentPage(1)
            }}
          >
            <option value="">全部</option>
            <option value="up">赞</option>
            <option value="down">踩</option>
          </select>
        </label>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>目标</th>
            <th>评价</th>
            <th>原因</th>
            <th>评论</th>
            <th>分析</th>
          </tr>
        </thead>
        <tbody>
          {(page?.items ?? []).map((rating) => (
            <tr key={rating.rating_id}>
              <td>{new Date(rating.created_at).toLocaleString()}</td>
              <td>{TARGET_LABELS[rating.target]}</td>
              <td>{rating.vote === 'up' ? '赞' : '踩'}</td>
              <td>{rating.reason_codes.join('、') || '—'}</td>
              <td>{rating.comment ?? '—'}</td>
              <td>
                <code>{rating.analysis_id.slice(0, 8)}</code>
              </td>
            </tr>
          ))}
          {(page?.items.length ?? 0) === 0 && (
            <tr>
              <td colSpan={6} className="admin-empty-cell">
                暂无评价记录。
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <Pagination page={page} onPage={setCurrentPage} />
    </section>
  )
}
