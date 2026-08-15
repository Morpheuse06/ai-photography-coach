import { useEffect, useRef, useState } from 'react'
import { analyzePhoto } from './api'
import './App.css'
import { AnalysisReport } from './components/AnalysisReport'
import { PhotoForm } from './components/PhotoForm'
import { ProblemReportForm } from './components/ProblemReportForm'
import type { AnalysisResponse } from './types'

type AppStatus = 'idle' | 'selected' | 'loading' | 'success' | 'error'

const coachingDimensions = ['构图', '光影', '色彩', '主体表达', '视觉叙事']

function App() {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [intent, setIntent] = useState('')
  const [accessCode, setAccessCode] = useState('')
  const [consent, setConsent] = useState(false)
  const [status, setStatus] = useState<AppStatus>('idle')
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const reportRef = useRef<HTMLElement>(null)
  // One idempotency key per user operation: created on the first submit and
  // reused for retries, so the backend never runs the same analysis twice.
  // Any change to the photo, intent, or access code starts a new operation.
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null)

  useEffect(() => {
    if (!file) {
      setPreviewUrl('')
      return
    }
    const objectUrl = URL.createObjectURL(file)
    setPreviewUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [file])

  useEffect(() => {
    if (status !== 'loading') return
    setElapsedSeconds(0)
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [status])

  useEffect(() => {
    if (status === 'success') reportRef.current?.focus()
  }, [status])

  const handleFileChange = (nextFile: File | null) => {
    setFile(nextFile)
    setAnalysis(null)
    setError(null)
    setConsent(false)
    setIdempotencyKey(null)
    setStatus(nextFile ? 'selected' : 'idle')
  }

  const handleIntentChange = (value: string) => {
    setIntent(value)
    setIdempotencyKey(null)
  }

  const handleAccessCodeChange = (value: string) => {
    setAccessCode(value)
    setIdempotencyKey(null)
  }

  const handleSubmit = async () => {
    if (!file || !consent || status === 'loading') return
    setStatus('loading')
    setError(null)
    setAnalysis(null)
    const key = idempotencyKey ?? crypto.randomUUID()
    setIdempotencyKey(key)
    try {
      const response = await analyzePhoto(file, intent, accessCode, key)
      setAnalysis(response)
      setStatus('success')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '分析失败，请稍后重试。')
      setStatus('error')
    }
  }

  const reset = () => {
    setFile(null)
    setIntent('')
    setAccessCode('')
    setConsent(false)
    setAnalysis(null)
    setError(null)
    setIdempotencyKey(null)
    setStatus('idle')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="AI 摄影教练首页">AI Photography Coach</a>
        <span className="privacy-note">单图分析 · 不保存照片</span>
      </header>

      <section className="hero" id="top" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow">你的私人摄影复盘伙伴</p>
          <h1 id="hero-title">拍好下一张</h1>
          <p className="intro">
            上传一张照片，获得基于真实画面证据的摄影指导，以及下一次拍摄可以立刻执行的练习。
          </p>
          <div className="dimension-list" aria-label="摄影分析维度">
            {coachingDimensions.map((dimension) => <span key={dimension}>{dimension}</span>)}
          </div>
        </div>

        <PhotoForm
          file={file}
          previewUrl={previewUrl}
          intent={intent}
          accessCode={accessCode}
          consent={consent}
          isLoading={status === 'loading'}
          elapsedSeconds={elapsedSeconds}
          error={error}
          onFileChange={handleFileChange}
          onIntentChange={handleIntentChange}
          onAccessCodeChange={handleAccessCodeChange}
          onConsentChange={setConsent}
          onSubmit={handleSubmit}
        />
      </section>

      <div className="sr-only" aria-live="polite">
        {status === 'loading' && '照片正在分析。'}
        {status === 'success' && '分析完成，摄影指导报告已生成。'}
        {status === 'error' && `分析失败。${error ?? ''}`}
      </div>

      {analysis && previewUrl && (
        <AnalysisReport
          ref={reportRef}
          analysis={analysis}
          previewUrl={previewUrl}
          intent={intent.trim()}
          onAnalyzeAnother={reset}
        />
      )}

      <section className="problem-report-section">
        <ProblemReportForm
          analysisId={analysis?.interaction?.analysis_id ?? null}
        />
      </section>

      <footer>
        <p>AI Photography Coach · V2</p>
        <p>建议仅基于画面可见信息，不推测 EXIF、器材或现场条件。</p>
      </footer>
    </main>
  )
}

export default App
