import { useCallback, useEffect, useState } from 'react'

import { adminRequest, queryString } from '../api'
import { Pagination } from './InviteCodesPage'
import type {
  ProblemPriority,
  ProblemReportPage,
  ProblemReportRecord,
  ProblemStatus,
} from '../types'

const STATUS_LABELS: Record<ProblemStatus, string> = {
  new: '新反馈',
  in_progress: '处理中',
  resolved: '已解决',
  ignored: '已忽略',
}

const PRIORITY_LABELS: Record<ProblemPriority, string> = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
}

export default function ProblemReportsPage() {
  const [page, setPage] = useState<ProblemReportPage | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [status, setStatus] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [editStatus, setEditStatus] = useState<ProblemStatus>('new')
  const [editPriority, setEditPriority] = useState<ProblemPriority>('normal')
  const [editNote, setEditNote] = useState('')

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await adminRequest<ProblemReportPage>(
        `/api/admin/v1/problem-reports${queryString({
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

  const openEdit = (report: ProblemReportRecord) => {
    setExpanded(report.problem_report_id)
    setEditStatus(report.status)
    setEditPriority(report.priority)
    setEditNote(report.admin_note ?? '')
  }

  const save = async (reportId: string) => {
    setError(null)
    try {
      await adminRequest<ProblemReportRecord>(
        `/api/admin/v1/problem-reports/${reportId}`,
        {
          method: 'PATCH',
          body: JSON.stringify({
            status: editStatus,
            priority: editPriority,
            admin_note: editNote || null,
          }),
        },
      )
      setExpanded(null)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '保存失败。')
    }
  }

  return (
    <section>
      <header className="admin-page-header">
        <h2>问题反馈</h2>
      </header>

      {error !== null && (
        <p className="admin-error" role="alert">
          {error}
        </p>
      )}

      <div className="admin-filter-row">
        <label>
          状态
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value)
              setCurrentPage(1)
            }}
          >
            <option value="">全部</option>
            <option value="new">新反馈</option>
            <option value="in_progress">处理中</option>
            <option value="resolved">已解决</option>
            <option value="ignored">已忽略</option>
          </select>
        </label>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>分类</th>
            <th>内容</th>
            <th>状态</th>
            <th>优先级</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {(page?.items ?? []).map((report) => (
            <ReportRow
              key={report.problem_report_id}
              report={report}
              expanded={expanded === report.problem_report_id}
              editStatus={editStatus}
              editPriority={editPriority}
              editNote={editNote}
              onOpen={() => openEdit(report)}
              onClose={() => setExpanded(null)}
              onStatusChange={setEditStatus}
              onPriorityChange={setEditPriority}
              onNoteChange={setEditNote}
              onSave={() => void save(report.problem_report_id)}
            />
          ))}
          {(page?.items.length ?? 0) === 0 && (
            <tr>
              <td colSpan={6} className="admin-empty-cell">
                暂无问题反馈。
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <Pagination page={page} onPage={setCurrentPage} />
    </section>
  )
}

interface ReportRowProps {
  report: ProblemReportRecord
  expanded: boolean
  editStatus: ProblemStatus
  editPriority: ProblemPriority
  editNote: string
  onOpen: () => void
  onClose: () => void
  onStatusChange: (value: ProblemStatus) => void
  onPriorityChange: (value: ProblemPriority) => void
  onNoteChange: (value: string) => void
  onSave: () => void
}

function ReportRow({
  report,
  expanded,
  editStatus,
  editPriority,
  editNote,
  onOpen,
  onClose,
  onStatusChange,
  onPriorityChange,
  onNoteChange,
  onSave,
}: ReportRowProps) {
  return (
    <>
      <tr>
        <td>{new Date(report.created_at).toLocaleString()}</td>
        <td>{report.category}</td>
        <td className="admin-report-message">{report.message}</td>
        <td>{STATUS_LABELS[report.status]}</td>
        <td>{PRIORITY_LABELS[report.priority]}</td>
        <td>
          <button
            className="admin-button admin-button-small"
            type="button"
            onClick={expanded ? onClose : onOpen}
          >
            {expanded ? '收起' : '处理'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="admin-row-actions">
          <td colSpan={6}>
            <dl className="admin-key-values">
              <dt>关联分析</dt>
              <dd>{report.analysis_id ?? '—'}</dd>
              <dt>标签</dt>
              <dd>{report.tags.join('、') || '—'}</dd>
              <dt>管理员备注</dt>
              <dd>{report.admin_note ?? '—'}</dd>
            </dl>
            <div className="admin-form-row">
              <label>
                状态
                <select
                  value={editStatus}
                  onChange={(event) =>
                    onStatusChange(event.target.value as ProblemStatus)
                  }
                >
                  <option value="new">新反馈</option>
                  <option value="in_progress">处理中</option>
                  <option value="resolved">已解决</option>
                  <option value="ignored">已忽略</option>
                </select>
              </label>
              <label>
                优先级
                <select
                  value={editPriority}
                  onChange={(event) =>
                    onPriorityChange(event.target.value as ProblemPriority)
                  }
                >
                  <option value="low">低</option>
                  <option value="normal">普通</option>
                  <option value="high">高</option>
                  <option value="urgent">紧急</option>
                </select>
              </label>
              <label>
                备注
                <input
                  value={editNote}
                  onChange={(event) => onNoteChange(event.target.value)}
                />
              </label>
              <button
                className="admin-button admin-button-primary"
                type="button"
                onClick={onSave}
              >
                保存
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
