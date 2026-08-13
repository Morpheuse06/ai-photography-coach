import { useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from 'react'
import { validateFile } from '../fileValidation'

type PhotoFormProps = {
  file: File | null
  previewUrl: string
  intent: string
  consent: boolean
  isLoading: boolean
  elapsedSeconds: number
  error: string | null
  onFileChange: (file: File | null) => void
  onIntentChange: (intent: string) => void
  onConsentChange: (consent: boolean) => void
  onSubmit: () => void
}

export function PhotoForm({
  file,
  previewUrl,
  intent,
  consent,
  isLoading,
  elapsedSeconds,
  error,
  onFileChange,
  onIntentChange,
  onConsentChange,
  onSubmit,
}: PhotoFormProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)

  const selectFile = (candidate: File | undefined) => {
    if (!candidate) return
    const validationError = validateFile(candidate)
    setFileError(validationError)
    if (validationError) {
      onFileChange(null)
      if (inputRef.current) inputRef.current.value = ''
      return
    }
    onFileChange(candidate)
  }

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    selectFile(event.target.files?.[0])
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
    if (!isLoading) selectFile(event.dataTransfer.files[0])
  }

  const removeFile = () => {
    setFileError(null)
    onFileChange(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit()
  }

  return (
    <form className="analysis-form" onSubmit={handleSubmit}>
      <div
        className={`drop-zone${isDragging ? ' is-dragging' : ''}${file ? ' has-photo' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setIsDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        {file && previewUrl ? (
          <div className="photo-preview">
            <img src={previewUrl} alt="待分析照片预览" />
            <div className="photo-overlay">
              <div>
                <strong>{file.name}</strong>
                <span>{formatFileSize(file.size)}</span>
              </div>
              <button type="button" onClick={removeFile} disabled={isLoading}>移除照片</button>
            </div>
          </div>
        ) : (
          <div className="drop-copy">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 16.5V19a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2.5M8 8l4-4 4 4M12 4v12" />
            </svg>
            <h2>选择一张照片</h2>
            <p>拖放到这里，或点击浏览文件</p>
            <span>JPEG、PNG、WebP · 最大 10 MiB</span>
          </div>
        )}
        <input
          ref={inputRef}
          className="file-input"
          type="file"
          accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
          aria-label="选择待分析照片"
          onChange={handleInputChange}
          disabled={isLoading}
        />
      </div>

      {fileError && <p className="field-error" role="alert">{fileError}</p>}

      <div className="intent-field">
        <div className="field-heading">
          <label htmlFor="intent">拍摄意图 <span>选填</span></label>
          <span>{intent.length} / 1000</span>
        </div>
        <textarea
          id="intent"
          value={intent}
          maxLength={1000}
          rows={4}
          placeholder="例如：我想表现雨天街道的孤独感"
          onChange={(event) => onIntentChange(event.target.value)}
          disabled={isLoading}
        />
      </div>

      <label className="consent-field">
        <input
          type="checkbox"
          checked={consent}
          onChange={(event) => onConsentChange(event.target.checked)}
          disabled={isLoading}
        />
        <span>
          我同意将照片发送给配置的模型服务商进行本次分析。
          <small>照片不会由本项目保存，但模型服务商可能按其政策处理请求。</small>
        </span>
      </label>

      {error && (
        <div className="error-banner" role="alert">
          <strong>分析没有完成</strong>
          <p>{error}</p>
        </div>
      )}

      <button
        className="primary-button"
        type="submit"
        disabled={!file || !consent || isLoading}
      >
        {isLoading ? `正在分析 · ${elapsedSeconds} 秒` : '开始分析'}
      </button>
      {isLoading && (
        <p className="loading-note" role="status">
          正在观察构图、光影和叙事，请保持页面打开。模型分析可能需要一分钟。
        </p>
      )}
    </form>
  )
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KiB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`
}
