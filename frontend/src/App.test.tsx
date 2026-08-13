import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { analysisFixture } from './test/fixtures'

describe('App', () => {
  it('requires a valid photo and privacy consent before analysis', async () => {
    const user = userEvent.setup()
    render(<App />)
    expect(screen.getByRole('heading', { name: '拍好下一张' })).toBeInTheDocument()
    expect(screen.queryByText('拍好下一张。')).not.toBeInTheDocument()
    const submit = screen.getByRole('button', { name: '开始分析' })
    expect(submit).toBeDisabled()

    await user.upload(
      screen.getByLabelText('选择待分析照片'),
      new File(['photo'], 'portrait.jpg', { type: 'image/jpeg' }),
    )
    expect(screen.getByAltText('待分析照片预览')).toBeInTheDocument()
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('checkbox'))
    expect(submit).toBeEnabled()
  })

  it('rejects unsupported files before making a request', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    render(<App />)

    await user.upload(
      screen.getByLabelText('选择待分析照片'),
      new File(['text'], 'notes.txt', { type: 'text/plain' }),
    )

    expect(screen.getByRole('alert')).toHaveTextContent('请选择 JPEG、PNG 或 WebP 图片')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('renders the complete report returned by the backend', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(analysisFixture), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    render(<App />)

    await user.upload(
      screen.getByLabelText('选择待分析照片'),
      new File(['photo'], 'portrait.jpg', { type: 'image/jpeg' }),
    )
    await user.type(screen.getByLabelText(/拍摄意图/), '表现安静的情绪')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: '开始分析' }))

    expect(await screen.findByRole('heading', { name: '你的摄影指导报告' })).toBeInTheDocument()
    expect(screen.getByText('构图画面证据')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '先做这三件事' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '窗边人像练习' })).toBeInTheDocument()
    expect(screen.getAllByText('mock-photography-coach-v1')).toHaveLength(2)
    expect(screen.getAllByText('未提供')).toHaveLength(3)
  })

  it('shows an error and allows retrying', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ error: { code: 'model_rate_limited', message: 'busy' } }),
          { status: 429, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(analysisFixture), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    render(<App />)

    await user.upload(
      screen.getByLabelText('选择待分析照片'),
      new File(['photo'], 'portrait.jpg', { type: 'image/jpeg' }),
    )
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: '开始分析' }))
    expect(await screen.findByText('模型服务当前请求较多，请稍后重试。')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '开始分析' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('heading', { name: '你的摄影指导报告' })).toBeInTheDocument()
  })
})
