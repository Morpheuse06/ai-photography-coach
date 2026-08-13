import type { AnalysisResponse, DimensionAssessment } from '../types'

const dimension = (name: string, rating: number): DimensionAssessment => ({
  rating,
  summary: `${name}判断清晰。`,
  visual_evidence: [`${name}画面证据`],
  strengths: [`${name}优点`],
  main_issue: `${name}主要问题`,
  improvement_suggestions: [`${name}改进建议`],
})

export const analysisFixture: AnalysisResponse = {
  report: {
    dimensions: {
      composition: dimension('构图', 4),
      lighting: dimension('光影', 3),
      color: dimension('色彩', 4),
      subject_expression: dimension('主体表达', 5),
      visual_storytelling: dimension('视觉叙事', 3),
    },
    priority_actions: [
      { priority: 1, action: '清理背景', reason: '减少干扰。' },
      { priority: 2, action: '控制高光', reason: '保留细节。' },
      { priority: 3, action: '调整机位', reason: '强化主体。' },
    ],
    next_shooting_exercise: {
      title: '窗边人像练习',
      objective: '练习控制窗边明暗反差。',
      steps: ['选择一扇窗', '移动人物位置'],
      success_criteria: ['面部有层次', '高光保留细节'],
    },
  },
  metadata: {
    provider: 'mock',
    model: 'mock-photography-coach-v1',
    prompt_version: 'photography-coach-v1.0',
    latency_ms: 1200,
    image: {
      media_type: 'image/jpeg',
      width: 1200,
      height: 800,
      size_bytes: 512000,
    },
    usage: {
      input_tokens: null,
      output_tokens: null,
      total_tokens: null,
    },
  },
}
