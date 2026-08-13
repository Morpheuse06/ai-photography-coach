export type DimensionAssessment = {
  rating: number
  summary: string
  visual_evidence: string[]
  strengths: string[]
  main_issue: string
  improvement_suggestions: string[]
}

export type PhotographyDimensions = {
  composition: DimensionAssessment
  lighting: DimensionAssessment
  color: DimensionAssessment
  subject_expression: DimensionAssessment
  visual_storytelling: DimensionAssessment
}

export type PriorityAction = {
  priority: 1 | 2 | 3
  action: string
  reason: string
}

export type ShootingExercise = {
  title: string
  objective: string
  steps: string[]
  success_criteria: string[]
}

export type PhotographyReport = {
  dimensions: PhotographyDimensions
  priority_actions: PriorityAction[]
  next_shooting_exercise: ShootingExercise
}

export type AnalysisMetadata = {
  provider: string
  model: string
  prompt_version: string
  latency_ms: number
  image: {
    media_type: string
    width: number
    height: number
    size_bytes: number
  }
  usage: {
    input_tokens: number | null
    output_tokens: number | null
    total_tokens: number | null
  }
}

export type AnalysisResponse = {
  report: PhotographyReport
  metadata: AnalysisMetadata
}

export type ApiErrorResponse = {
  error: {
    code: string
    message: string
  }
}
