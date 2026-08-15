import { useCallback, useEffect, useState } from 'react'

import { adminRequest, queryString } from '../api'
import type {
  AccessCodeBatchCreated,
  AccessCodePage,
  AccessCodeRecord,
  AccessCodeStatus,
  GeneratedAccessCode,
} from '../types'

const STATUS_LABELS: Record<AccessCodeStatus, string> = {
  active: '可用',
  exhausted: '已用尽',
  expired: '已过期',
  revoked: '已撤销',
}

export default function InviteCodesPage() {
  const [page, setPage] = useState<AccessCodePage | null>(null)
  const [status, setStatus] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [createdCodes, setCreatedCodes] = useState<GeneratedAccessCode[] | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [grantValue, setGrantValue] = useState('')
  const [revokeReason, setRevokeReason] = useState('')
  const [labelValue, setLabelValue] = useState('')

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await adminRequest<AccessCodePage>(
        `/api/admin/v1/access-codes${queryString({
          page: currentPage,
          page_size: 20,
          status: status || undefined,
        })}`,
      )
      setPage(data)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败。')
    }
  }, [currentPage, status])

  useEffect(() => {
    void load()
  }, [load])

  const handleCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setError(null)
    try {
      const created = await adminRequest<AccessCodeBatchCreated>(
        '/api/admin/v1/access-code-batches',
        {
          method: 'POST',
          body: JSON.stringify({
            quantity: Number(form.get('quantity')),
            uses_per_code: Number(form.get('uses_per_code')),
            label: form.get('label') || null,
            expires_at: form.get('expires_at') || null,
          }),
        },
      )
      setCreatedCodes(created.codes)
      setNotice('邀请码已创建。请立即复制保存，离开后无法再次查看原文。')
      event.currentTarget.reset()
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '创建失败。')
    }
  }

  const handleAction = async (
    codeId: string,
    action: 'grant' | 'revoke' | 'update-label',
  ) => {
    setError(null)
    try {
      if (action === 'grant') {
        await adminRequest<AccessCodeRecord>(
          `/api/admin/v1/access-codes/${codeId}/grants`,
          {
            method: 'POST',
            body: JSON.stringify({
              additional_uses: Number(grantValue),
              reason: '管理控制台追加次数',
            }),
          },
        )
      } else if (action === 'revoke') {
        await adminRequest<AccessCodeRecord>(
          `/api/admin/v1/access-codes/${codeId}/revoke`,
          {
            method: 'POST',
            body: JSON.stringify({ reason: revokeReason || '管理控制台撤销' }),
          },
        )
      } else {
        await adminRequest<AccessCodeRecord>(
          `/api/admin/v1/access-codes/${codeId}`,
          {
            method: 'PATCH',
            body: JSON.stringify({ label: labelValue || null }),
          },
        )
      }
      setExpanded(null)
      setGrantValue('')
      setRevokeReason('')
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '操作失败。')
    }
  }

  const copyCodes = async () => {
    if (createdCodes === null) return
    try {
      await navigator.clipboard.writeText(
        createdCodes.map((code) => code.code).join('\n'),
      )
      setNotice('已复制到剪贴板。')
    } catch {
      setNotice('复制失败，请手动选择文本复制。')
    }
  }

  return (
    <section>
      <header className="admin-page-header">
        <h2>邀请码</h2>
      </header>

      {notice !== null && (
        <p className="admin-notice" role="status">
          {notice}
        </p>
      )}
      {error !== null && (
        <p className="admin-error" role="alert">
          {error}
        </p>
      )}

      <form className="admin-form admin-form-row" onSubmit={handleCreate}>
        <label>
          数量
          <input name="quantity" type="number" min={1} max={100} defaultValue={10} required />
        </label>
        <label>
          每码次数
          <input name="uses_per_code" type="number" min={1} max={10000} defaultValue={10} required />
        </label>
        <label>
          标签
          <input name="label" maxLength={100} />
        </label>
        <label>
          过期时间（可选）
          <input name="expires_at" type="datetime-local" />
        </label>
        <button className="admin-button admin-button-primary" type="submit">
          批量创建
        </button>
      </form>

      {createdCodes !== null && (
        <div className="admin-code-reveal" role="region" aria-label="新建邀请码原文">
          <header>
            <strong>邀请码原文（仅此一次）</strong>
            <button className="admin-button" type="button" onClick={copyCodes}>
              全部复制
            </button>
          </header>
          <ol>
            {createdCodes.map((code) => (
              <li key={code.code_id}>
                <code>{code.code}</code>
                <span className="admin-muted">
                  次数 {code.uses_total}
                  {code.expires_at !== null &&
                    ` · 过期 ${new Date(code.expires_at).toLocaleString()}`}
                </span>
              </li>
            ))}
          </ol>
          <button
            className="admin-button admin-button-ghost"
            type="button"
            onClick={() => setCreatedCodes(null)}
          >
            我已保存，关闭
          </button>
        </div>
      )}

      <div className="admin-filter-row">
        <label>
          状态
          <select value={status} onChange={(event) => { setStatus(event.target.value); setCurrentPage(1) }}>
            <option value="">全部</option>
            <option value="active">可用</option>
            <option value="exhausted">已用尽</option>
            <option value="expired">已过期</option>
            <option value="revoked">已撤销</option>
          </select>
        </label>
        <button className="admin-button admin-button-ghost" type="button" onClick={() => void load()}>
          刷新
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>前缀</th>
            <th>标签</th>
            <th>状态</th>
            <th>已用 / 预占 / 总数</th>
            <th>过期时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {(page?.items ?? []).map((code) => (
            <CodeRow
              key={code.code_id}
              code={code}
              expanded={expanded === code.code_id}
              grantValue={grantValue}
              revokeReason={revokeReason}
              labelValue={labelValue}
              onToggle={() =>
                setExpanded(expanded === code.code_id ? null : code.code_id)
              }
              onGrantChange={setGrantValue}
              onRevokeReasonChange={setRevokeReason}
              onLabelChange={setLabelValue}
              onAction={(action) => void handleAction(code.code_id, action)}
            />
          ))}
          {(page?.items.length ?? 0) === 0 && (
            <tr>
              <td colSpan={6} className="admin-empty-cell">
                暂无邀请码。
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <Pagination
        page={page}
        onPage={(next) => setCurrentPage(next)}
      />
    </section>
  )
}

interface CodeRowProps {
  code: AccessCodeRecord
  expanded: boolean
  grantValue: string
  revokeReason: string
  labelValue: string
  onToggle: () => void
  onGrantChange: (value: string) => void
  onRevokeReasonChange: (value: string) => void
  onLabelChange: (value: string) => void
  onAction: (action: 'grant' | 'revoke' | 'update-label') => void
}

function CodeRow({
  code,
  expanded,
  grantValue,
  revokeReason,
  labelValue,
  onToggle,
  onGrantChange,
  onRevokeReasonChange,
  onLabelChange,
  onAction,
}: CodeRowProps) {
  return (
    <>
      <tr>
        <td>
          <code>{code.prefix}</code>
        </td>
        <td>{code.label ?? '—'}</td>
        <td>{STATUS_LABELS[code.status]}</td>
        <td>
          {code.uses_consumed} / {code.uses_reserved} / {code.uses_total}
        </td>
        <td>
          {code.expires_at === null
            ? '不过期'
            : new Date(code.expires_at).toLocaleString()}
        </td>
        <td>
          <button className="admin-button admin-button-small" type="button" onClick={onToggle}>
            {expanded ? '收起' : '操作'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="admin-row-actions">
          <td colSpan={6}>
            <div className="admin-form-row">
              <label>
                追加次数
                <input
                  type="number"
                  min={1}
                  value={grantValue}
                  onChange={(event) => onGrantChange(event.target.value)}
                />
              </label>
              <button
                className="admin-button"
                type="button"
                disabled={code.status === 'revoked' || grantValue === ''}
                onClick={() => onAction('grant')}
              >
                追加
              </button>
              <label>
                修改标签
                <input
                  maxLength={100}
                  value={labelValue}
                  onChange={(event) => onLabelChange(event.target.value)}
                />
              </label>
              <button
                className="admin-button"
                type="button"
                onClick={() => onAction('update-label')}
              >
                保存标签
              </button>
              <label>
                撤销原因
                <input
                  value={revokeReason}
                  onChange={(event) => onRevokeReasonChange(event.target.value)}
                />
              </label>
              <button
                className="admin-button admin-button-danger"
                type="button"
                disabled={code.status === 'revoked'}
                onClick={() => onAction('revoke')}
              >
                撤销
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export function Pagination({
  page,
  onPage,
}: {
  page: { page: { total_pages: number; page: number } } | null
  onPage: (page: number) => void
}) {
  if (page === null || page.page.total_pages <= 1) return null
  return (
    <nav className="admin-pagination" aria-label="分页">
      <button
        className="admin-button admin-button-small"
        type="button"
        disabled={page.page.page <= 1}
        onClick={() => onPage(page.page.page - 1)}
      >
        上一页
      </button>
      <span>
        第 {page.page.page} / {page.page.total_pages} 页
      </span>
      <button
        className="admin-button admin-button-small"
        type="button"
        disabled={page.page.page >= page.page.total_pages}
        onClick={() => onPage(page.page.page + 1)}
      >
        下一页
      </button>
    </nav>
  )
}
