import { useCallback, useEffect, useState } from 'react'

import { adminRequest, queryString } from '../api'
import { Pagination } from './InviteCodesPage'
import type { AuditEvent } from '../types'

interface AuditPageResponse {
  items: AuditEvent[]
  page: { total_pages: number; page: number; page_size: number; total_items: number }
}

export default function AuditPage() {
  const [page, setPage] = useState<AuditPageResponse | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [action, setAction] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await adminRequest<AuditPageResponse>(
        `/api/admin/v1/audit-events${queryString({
          page: currentPage,
          page_size: 20,
          action: action || undefined,
        })}`,
      )
      setPage(data)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败。')
    }
  }, [currentPage, action])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section>
      <header className="admin-page-header">
        <h2>审计日志</h2>
      </header>

      {error !== null && (
        <p className="admin-error" role="alert">
          {error}
        </p>
      )}

      <div className="admin-filter-row">
        <label>
          动作
          <input
            value={action}
            placeholder="例如 access_policy.updated"
            onChange={(event) => setAction(event.target.value)}
          />
        </label>
        <button
          className="admin-button admin-button-primary"
          type="button"
          onClick={() => {
            setCurrentPage(1)
            void load()
          }}
        >
          筛选
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>管理员</th>
            <th>动作</th>
            <th>资源</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          {(page?.items ?? []).map((event) => (
            <tr key={event.audit_event_id}>
              <td>{new Date(event.occurred_at).toLocaleString()}</td>
              <td>{event.admin_subject}</td>
              <td>
                <code>{event.action}</code>
              </td>
              <td>
                {event.resource_type}
                {event.resource_id !== null && ` (${event.resource_id.slice(0, 8)})`}
              </td>
              <td className="admin-muted">{JSON.stringify(event.details)}</td>
            </tr>
          ))}
          {(page?.items.length ?? 0) === 0 && (
            <tr>
              <td colSpan={5} className="admin-empty-cell">
                暂无审计事件。
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <Pagination page={page} onPage={setCurrentPage} />
    </section>
  )
}
