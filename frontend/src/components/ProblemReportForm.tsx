import { useState } from 'react'

import { submitProblemReport } from '../api'
import type { ProblemCategory } from '../types'

type ProblemReportFormProps = {
  analysisId: string | null
}

const CATEGORY_OPTIONS: { value: ProblemCategory; label: string }[] = [
  { value: 'bug', label: '功能异常' },
  { value: 'report_quality', label: '报告质量问题' },
  { value: 'performance', label: '速度太慢' },
  { value: 'usability', label: '使用体验' },
  { value: 'privacy', label: '隐私疑虑' },
  { value: 'other', label: '其他' },
]

export function ProblemReportForm({ analysisId }: ProblemReportFormProps) {
  const [category, setCategory] = useState<ProblemCategory>('report_quality')
  const [message, setMessage] = useState('')
  const [includeMetadata, setIncludeMetadata] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (message.trim().length < 10) {
      setError('请至少写 10 个字，方便我们理解问题。')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await submitProblemReport({
        analysis_id: analysisId,
        category,
        message: message.trim(),
        include_runtime_metadata: includeMetadata,
      })
      setSent(true)
      setMessage('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '提交失败，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <div className="problem-report-sent" role="status">
        <strong>反馈已提交，感谢你的帮助！</strong>
        <button
          type="button"
          className="secondary-button"
          onClick={() => setSent(false)}
        >
          再提交一条
        </button>
      </div>
    )
  }

  return (
    <form className="problem-report" onSubmit={handleSubmit}>
      <p className="eyebrow">遇到问题？</p>
      <h2>告诉我们</h2>
      <p className="problem-report-hint">
        不需要姓名或联系方式。反馈会匿名进入待处理队列，帮助改进报告质量。
      </p>
      <div className="problem-report-row">
        <label>
          问题类型
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value as ProblemCategory)}
          >
            {CATEGORY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="problem-report-checkbox">
          <input
            type="checkbox"
            checked={includeMetadata}
            onChange={(event) => setIncludeMetadata(event.target.checked)}
          />
          附带本次分析的运行信息（模型、版本、耗时，不含照片）
        </label>
      </div>
      <textarea
        rows={3}
        maxLength={2000}
        placeholder="描述你遇到的问题（10～2000 字）"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
      />
      <div className="problem-report-actions">
        <span className="problem-report-count">{message.length} / 2000</span>
        <button className="secondary-button" type="submit" disabled={busy}>
          {busy ? '正在提交…' : '提交反馈'}
        </button>
      </div>
      {error !== null && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
