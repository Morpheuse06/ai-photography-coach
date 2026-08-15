import { useEffect, useState } from 'react'

import { adminRequest } from '../api'
import type { SystemStatus, SystemVersions } from '../types'

const MODE_LABELS: Record<string, string> = {
  open: '开放（无需邀请码）',
  code_required: '需要邀请码',
  closed: '关闭新分析',
}

export default function SystemPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [versions, setVersions] = useState<SystemVersions | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setError(null)
      try {
        const [statusData, versionsData] = await Promise.all([
          adminRequest<SystemStatus>('/api/admin/v1/system/status'),
          adminRequest<SystemVersions>('/api/admin/v1/system/versions'),
        ])
        if (!cancelled) {
          setStatus(statusData)
          setVersions(versionsData)
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : '加载失败。')
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section>
      <header className="admin-page-header">
        <h2>系统</h2>
      </header>

      {error !== null && (
        <p className="admin-error" role="alert">
          {error}
        </p>
      )}

      <h3>运行状态</h3>
      {status !== null && (
        <dl className="admin-key-values">
          <dt>状态</dt>
          <dd>{status.status}</dd>
          <dt>应用版本</dt>
          <dd>{status.application_version}</dd>
          <dt>启动时间</dt>
          <dd>{new Date(status.started_at).toLocaleString()}</dd>
          <dt>访问模式</dt>
          <dd>{MODE_LABELS[status.access_mode]}</dd>
          <dt>RAG</dt>
          <dd>{status.rag_enabled ? '已启用' : '未启用'}</dd>
          <dt>知识索引</dt>
          <dd>{status.knowledge_index_ready ? '就绪' : '未就绪'}</dd>
          <dt>近 24 小时错误率</dt>
          <dd>{Math.round(status.recent_error_rate * 100)}%</dd>
        </dl>
      )}

      <h3>模型与知识库版本</h3>
      {versions !== null && (
        <dl className="admin-key-values">
          <dt>Provider</dt>
          <dd>{versions.provider}</dd>
          <dt>模型</dt>
          <dd>{versions.model}</dd>
          <dt>报告 Prompt</dt>
          <dd>{versions.report_prompt_version}</dd>
          <dt>检索 Prompt</dt>
          <dd>{versions.retrieval_prompt_version ?? '—'}</dd>
          <dt>知识来源</dt>
          <dd>
            {versions.knowledge_source_id === null
              ? '—'
              : `${versions.knowledge_source_id} @ ${versions.knowledge_source_version}`}
          </dd>
          <dt>Embedding</dt>
          <dd>{versions.embedding_model ?? '—'}</dd>
          <dt>Reranker</dt>
          <dd>{versions.reranker_model ?? '—'}</dd>
        </dl>
      )}

      <h3>数据导出</h3>
      <p className="admin-muted">
        导出操作会写入审计日志。CSV 中的用户文本已做公式注入防护。
      </p>
      <div className="admin-form-row">
        <a
          className="admin-button"
          href="/api/admin/v1/exports/analysis-runs.csv"
          onClick={(event) => {
            // The link would skip the Authorization header, so fetch and
            // download through the authenticated client instead.
            event.preventDefault()
            void downloadExport('/api/admin/v1/exports/analysis-runs.csv', 'analysis-runs.csv')
          }}
        >
          导出分析记录
        </a>
        <a
          className="admin-button"
          href="/api/admin/v1/exports/ratings.csv"
          onClick={(event) => {
            event.preventDefault()
            void downloadExport('/api/admin/v1/exports/ratings.csv', 'ratings.csv')
          }}
        >
          导出评价
        </a>
        <a
          className="admin-button"
          href="/api/admin/v1/exports/problem-reports.csv"
          onClick={(event) => {
            event.preventDefault()
            void downloadExport('/api/admin/v1/exports/problem-reports.csv', 'problem-reports.csv')
          }}
        >
          导出问题反馈
        </a>
      </div>
    </section>
  )
}

async function downloadExport(path: string, filename: string) {
  const token = sessionStorage.getItem('photography-admin-token')
  const response = await fetch(path, {
    headers: token === null ? {} : { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) return
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
