import { useMemo, useState } from 'react'

import type { MetricBucket } from '../types'

interface TrendChartProps {
  series: MetricBucket[]
}

interface TooltipState {
  x: number
  y: number
  bucket: MetricBucket
}

const CHART_HEIGHT = 220
const CHART_PADDING_X = 40
const CHART_PADDING_Y = 18

function dayLabel(value: string): string {
  const date = new Date(value)
  return `${date.getUTCMonth() + 1}/${date.getUTCDate()}`
}

/**
 * Stacked bar chart for succeeded/failed analyses per bucket.
 * Series colors are CSS variables (see admin.css) so light and dark
 * surfaces select their own validated steps. Segments keep a 2 px surface
 * gap, bars are thin, and every mark carries a hover tooltip.
 */
export default function TrendChart({ series }: TrendChartProps) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)

  const geometry = useMemo(() => {
    const width = Math.max(320, Math.min(880, series.length * 34 + CHART_PADDING_X * 2))
    const plotWidth = width - CHART_PADDING_X * 2
    const plotHeight = CHART_HEIGHT - CHART_PADDING_Y * 2
    const maxTotal = Math.max(1, ...series.map((item) => item.analyses_total))
    const slot = plotWidth / Math.max(series.length, 1)
    const barWidth = Math.min(28, slot * 0.62)
    const yFor = (value: number) =>
      CHART_PADDING_Y + plotHeight * (1 - value / maxTotal)
    return { width, plotHeight, maxTotal, yFor, slot, barWidth }
  }, [series])

  if (series.length === 0) {
    return <p className="admin-empty">该时间范围内暂无分析数据。</p>
  }

  const { width, plotHeight, maxTotal, yFor, slot, barWidth } = geometry
  const ticks = Array.from(
    new Set([0, 0.5, 1].map((fraction) => Math.round(maxTotal * fraction))),
  )

  return (
    <figure className="trend-chart">
      <div className="trend-chart-legend" aria-hidden="true">
        <span className="legend-item">
          <i className="legend-swatch legend-succeeded" /> 成功
        </span>
        <span className="legend-item">
          <i className="legend-swatch legend-failed" /> 失败
        </span>
      </div>
      <div className="trend-chart-scroll">
        <svg
          className="trend-chart-svg"
          width={width}
          height={CHART_HEIGHT}
          role="img"
          aria-label="分析趋势图：按时间分桶的成功与失败分析数量"
        >
          {ticks.map((tick) => {
            const y = yFor(tick)
            return (
              <g key={tick}>
                <line
                  className="trend-gridline"
                  x1={CHART_PADDING_X}
                  x2={width - CHART_PADDING_X}
                  y1={y}
                  y2={y}
                />
                <text
                  className="trend-axis-label"
                  x={CHART_PADDING_X - 8}
                  y={y + 4}
                  textAnchor="end"
                >
                  {tick}
                </text>
              </g>
            )
          })}
          {series.map((bucket, index) => {
            const x = CHART_PADDING_X + slot * index + (slot - barWidth) / 2
            const succeededHeight = plotHeight * (bucket.analyses_succeeded / maxTotal)
            const failedTop = yFor(bucket.analyses_succeeded)
            const failedHeight = plotHeight * (bucket.analyses_failed / maxTotal)
            const labelStep = Math.max(1, Math.ceil(series.length / 16))
            return (
              <g
                key={bucket.bucket_started_at}
                onMouseEnter={(event) =>
                  setTooltip({
                    x: event.clientX,
                    y: event.clientY,
                    bucket,
                  })
                }
                onMouseLeave={() => setTooltip(null)}
              >
                <rect
                  className="trend-bar trend-bar-succeeded"
                  x={x}
                  y={yFor(bucket.analyses_succeeded)}
                  width={barWidth}
                  height={succeededHeight}
                  rx={bucket.analyses_failed === 0 ? 4 : 0}
                />
                {bucket.analyses_failed > 0 && (
                  <rect
                    className="trend-bar trend-bar-failed"
                    x={x}
                    y={failedTop - failedHeight + 2}
                    width={barWidth}
                    height={Math.max(failedHeight - 2, 0)}
                    rx={4}
                  />
                )}
                {index % labelStep === 0 && (
                  <text
                    className="trend-axis-label"
                    x={x + barWidth / 2}
                    y={CHART_HEIGHT - 4}
                    textAnchor="middle"
                  >
                    {dayLabel(bucket.bucket_started_at)}
                  </text>
                )}
                <title>{`${dayLabel(bucket.bucket_started_at)}：成功 ${bucket.analyses_succeeded}，失败 ${bucket.analyses_failed}`}</title>
              </g>
            )
          })}
        </svg>
      </div>
      {tooltip !== null && (
        <div
          className="trend-tooltip"
          style={{ left: tooltip.x + 12, top: tooltip.y - 40 }}
          role="status"
        >
          <strong>{dayLabel(tooltip.bucket.bucket_started_at)}</strong>
          <div>成功 {tooltip.bucket.analyses_succeeded}</div>
          <div>失败 {tooltip.bucket.analyses_failed}</div>
          <div>Token {tooltip.bucket.total_tokens}</div>
        </div>
      )}
      <figcaption className="trend-caption">
        每根柱子代表一天内的分析次数；下方表格提供同样的数据视图。
      </figcaption>
    </figure>
  )
}
