import type { DimensionAssessment } from '../types'
import { Rating } from './Rating'

type DimensionCardProps = {
  index: number
  title: string
  assessment: DimensionAssessment
}

function TextList({ items }: { items: string[] }) {
  return (
    <ul>
      {items.map((item, index) => (
        <li key={`${index}-${item}`}>{item}</li>
      ))}
    </ul>
  )
}

export function DimensionCard({ index, title, assessment }: DimensionCardProps) {
  return (
    <article className="dimension-card">
      <div className="dimension-heading">
        <div>
          <p className="section-number">0{index}</p>
          <h3>{title}</h3>
        </div>
        <Rating value={assessment.rating} />
      </div>
      <p className="dimension-summary">{assessment.summary}</p>
      <div className="dimension-details">
        <section>
          <h4>画面证据</h4>
          <TextList items={assessment.visual_evidence} />
        </section>
        <section>
          <h4>做得好的地方</h4>
          <TextList items={assessment.strengths} />
        </section>
        <section className="issue-block">
          <h4>主要问题</h4>
          <p>{assessment.main_issue}</p>
        </section>
        <section>
          <h4>改进建议</h4>
          <TextList items={assessment.improvement_suggestions} />
        </section>
      </div>
    </article>
  )
}
