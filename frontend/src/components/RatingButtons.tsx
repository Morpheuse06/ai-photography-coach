import { useState } from 'react'

import { deleteRating, upsertRating } from '../api'
import type {
  RatingReasonCode,
  RatingTarget,
  RatingVote,
} from '../types'

type RatingButtonsProps = {
  analysisId: string
  feedbackToken: string
  target: RatingTarget
  label: string
}

const REASON_OPTIONS: { value: RatingReasonCode; label: string }[] = [
  { value: 'not_grounded', label: '缺少画面依据' },
  { value: 'generic_advice', label: '建议太笼统' },
  { value: 'inaccurate', label: '与画面不符' },
  { value: 'not_actionable', label: '难以执行' },
  { value: 'contradictory', label: '前后矛盾' },
  { value: 'invented_detail', label: '虚构细节' },
  { value: 'hard_to_understand', label: '难以理解' },
  { value: 'other', label: '其他' },
]

export function RatingButtons({
  analysisId,
  feedbackToken,
  target,
  label,
}: RatingButtonsProps) {
  const [currentVote, setCurrentVote] = useState<RatingVote | null>(null)
  const [showDownForm, setShowDownForm] = useState(false)
  const [reasonCodes, setReasonCodes] = useState<RatingReasonCode[]>([])
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [feedbackError, setFeedbackError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState<string | null>(null)

  const submit = async (vote: RatingVote) => {
    setBusy(true)
    setFeedbackError(null)
    setConfirmed(null)
    try {
      await upsertRating(
        analysisId,
        feedbackToken,
        target,
        vote,
        vote === 'down' ? reasonCodes : [],
        comment.trim() || null,
      )
      setCurrentVote(vote)
      setShowDownForm(false)
      setConfirmed(vote === 'up' ? '感谢你的认可！' : '感谢反馈，我们会改进。')
    } catch (caught) {
      setFeedbackError(
        caught instanceof Error ? caught.message : '评价提交失败，请稍后重试。',
      )
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    setFeedbackError(null)
    setConfirmed(null)
    try {
      await deleteRating(analysisId, feedbackToken, target)
      setCurrentVote(null)
      setShowDownForm(false)
      setReasonCodes([])
      setComment('')
      setConfirmed('已删除评价')
    } catch (caught) {
      setFeedbackError(
        caught instanceof Error ? caught.message : '评价删除失败，请稍后重试。',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rating-widget">
      <p className="rating-question">「{label}」对你有帮助吗？</p>
      <div className="rating-controls">
        <button
          type="button"
          className={`rating-button${currentVote === 'up' ? ' is-active' : ''}`}
          aria-pressed={currentVote === 'up'}
          disabled={busy}
          onClick={() =>
            void (currentVote === 'up' ? remove() : submit('up'))
          }
        >
          👍 有帮助
        </button>
        <button
          type="button"
          className={`rating-button${currentVote === 'down' ? ' is-active' : ''}`}
          aria-pressed={currentVote === 'down'}
          disabled={busy}
          onClick={() =>
            void (currentVote === 'down' ? remove() : setShowDownForm(true))
          }
        >
          👎 没帮助
        </button>
      </div>

      {showDownForm && (
        <div className="rating-detail">
          <p>哪里可以改进？（可多选，最多 5 项）</p>
          <div className="rating-reasons">
            {REASON_OPTIONS.map((option) => (
              <label key={option.value} className="rating-reason">
                <input
                  type="checkbox"
                  checked={reasonCodes.includes(option.value)}
                  onChange={(event) => {
                    setReasonCodes((previous) =>
                      event.target.checked
                        ? [...previous, option.value].slice(0, 5)
                        : previous.filter((code) => code !== option.value),
                    )
                  }}
                />
                {option.label}
              </label>
            ))}
          </div>
          <textarea
            className="rating-comment"
            rows={2}
            maxLength={500}
            placeholder="补充说明（选填，最多 500 字）"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <div className="rating-controls">
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={() => void submit('down')}
            >
              提交评价
            </button>
            <button
              type="button"
              className="rating-button"
              disabled={busy}
              onClick={() => setShowDownForm(false)}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {confirmed !== null && (
        <p className="rating-confirmed" role="status">
          {confirmed}
        </p>
      )}
      {feedbackError !== null && (
        <p className="rating-error" role="alert">
          {feedbackError}
        </p>
      )}
    </div>
  )
}
