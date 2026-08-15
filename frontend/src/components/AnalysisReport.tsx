import { forwardRef } from 'react'
import type { AnalysisResponse, RatingTarget } from '../types'
import { DimensionCard } from './DimensionCard'
import { RatingButtons } from './RatingButtons'

const dimensionLabels = {
  composition: '构图',
  lighting: '光影',
  color: '色彩',
  subject_expression: '主体表达',
  visual_storytelling: '视觉叙事',
} as const

type AnalysisReportProps = {
  analysis: AnalysisResponse
  previewUrl: string
  intent: string
  onAnalyzeAnother: () => void
}

export const AnalysisReport = forwardRef<HTMLElement, AnalysisReportProps>(
  function AnalysisReport({ analysis, previewUrl, intent, onAnalyzeAnother }, ref) {
    const { report, metadata } = analysis
    const exercise = report.next_shooting_exercise
    const interaction = analysis.interaction ?? null
    const feedbackFor = (target: RatingTarget, label: string) =>
      interaction === null ? null : (
        <RatingButtons
          analysisId={interaction.analysis_id}
          feedbackToken={interaction.feedback_token}
          target={target}
          label={label}
        />
      )

    return (
      <section className="report" aria-labelledby="report-title" ref={ref} tabIndex={-1}>
        <div className="report-intro">
          <div>
            <p className="eyebrow">分析完成</p>
            <h2 id="report-title">你的摄影指导报告</h2>
            <p>
              {intent
                ? `拍摄意图：${intent}`
                : '本次未填写拍摄意图，报告仅依据画面可见内容生成。'}
            </p>
          </div>
          <button className="secondary-button" type="button" onClick={onAnalyzeAnother}>
            分析另一张
          </button>
        </div>

        <div className="report-photo-wrap">
          <img className="report-photo" src={previewUrl} alt="本次分析的照片" />
          <dl className="report-summary">
            <div>
              <dt>模型</dt>
              <dd>{metadata.model}</dd>
            </div>
            <div>
              <dt>耗时</dt>
              <dd>{(metadata.latency_ms / 1000).toFixed(1)} 秒</dd>
            </div>
            <div>
              <dt>图片</dt>
              <dd>{metadata.image.width} × {metadata.image.height}</dd>
            </div>
            {interaction?.access.remaining_uses !== null &&
              interaction?.access.remaining_uses !== undefined && (
                <div>
                  <dt>剩余次数</dt>
                  <dd>{interaction.access.remaining_uses}</dd>
                </div>
              )}
          </dl>
        </div>

        {interaction !== null && (
          <p className="feedback-note">
            你的反馈完全匿名。反馈凭据只保存在当前页面中，关闭页面后无法找回。
          </p>
        )}

        <div className="dimensions-grid">
          {Object.entries(dimensionLabels).map(([key, label], index) => (
            <DimensionCard
              key={key}
              index={index + 1}
              title={label}
              assessment={report.dimensions[key as keyof typeof dimensionLabels]}
              feedback={feedbackFor(key as RatingTarget, label)}
            />
          ))}
        </div>

        <section className="action-section" aria-labelledby="actions-title">
          <p className="eyebrow">优先改进</p>
          <h2 id="actions-title">先做这三件事</h2>
          <ol className="action-list">
            {report.priority_actions.map((item) => (
              <li key={item.priority}>
                <span className="action-number">{item.priority}</span>
                <div>
                  <h3>{item.action}</h3>
                  <p>{item.reason}</p>
                </div>
              </li>
            ))}
          </ol>
          {feedbackFor('priority_actions', '优先动作')}
        </section>

        <section className="exercise" aria-labelledby="exercise-title">
          <p className="eyebrow">下一次拍摄练习</p>
          <h2 id="exercise-title">{exercise.title}</h2>
          <p className="exercise-objective">{exercise.objective}</p>
          <div className="exercise-columns">
            <div>
              <h3>练习步骤</h3>
              <ol>
                {exercise.steps.map((step) => <li key={step}>{step}</li>)}
              </ol>
            </div>
            <div>
              <h3>完成标准</h3>
              <ul>
                {exercise.success_criteria.map((criterion) => (
                  <li key={criterion}>{criterion}</li>
                ))}
              </ul>
            </div>
          </div>
          {feedbackFor('shooting_exercise', '拍摄练习')}
        </section>

        <section className="overall-rating" aria-label="总体评价">
          {feedbackFor('overall', '整份报告')}
        </section>

        <details className="metadata">
          <summary>查看分析技术信息</summary>
          <dl>
            <div><dt>Provider</dt><dd>{metadata.provider}</dd></div>
            <div><dt>模型</dt><dd>{metadata.model}</dd></div>
            <div><dt>Prompt 版本</dt><dd>{metadata.prompt_version}</dd></div>
            <div><dt>耗时</dt><dd>{metadata.latency_ms} ms</dd></div>
            <div><dt>文件大小</dt><dd>{formatBytes(metadata.image.size_bytes)}</dd></div>
            <div><dt>输入 Token</dt><dd>{formatUsage(metadata.usage.input_tokens)}</dd></div>
            <div><dt>输出 Token</dt><dd>{formatUsage(metadata.usage.output_tokens)}</dd></div>
            <div><dt>总 Token</dt><dd>{formatUsage(metadata.usage.total_tokens)}</dd></div>
            {metadata.retrieval && (
              <>
                <div>
                  <dt>知识库</dt>
                  <dd>{metadata.retrieval.knowledge_source_id} v{metadata.retrieval.knowledge_source_version}</dd>
                </div>
                <div><dt>检索规划</dt><dd>{metadata.retrieval.planner_model}</dd></div>
                <div><dt>Embedding</dt><dd>{metadata.retrieval.embedding_model}</dd></div>
                <div><dt>Reranker</dt><dd>{metadata.retrieval.reranker_model}</dd></div>
                <div><dt>检索耗时</dt><dd>{metadata.retrieval.latency_ms} ms</dd></div>
                <div><dt>命中知识块</dt><dd>{metadata.retrieval.retrieved_chunk_ids.length} 个</dd></div>
              </>
            )}
          </dl>
        </details>
      </section>
    )
  },
)

function formatUsage(value: number | null): string {
  return value === null ? '未提供' : value.toLocaleString('zh-CN')
}

function formatBytes(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
}
