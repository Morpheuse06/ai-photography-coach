import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RatingButtons } from './RatingButtons'

describe('RatingButtons', () => {
  const analysisId = '8d81ac6b-c3a5-4dad-912d-7635725a459f'
  const token = '7B1DgR5NwP2kL9xQa4Vm8Yc3Hs6Jt0UfEeZiKpAo'

  it('submits a down vote with reasons and comment', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          rating_id: 'rating-1',
          analysis_id: analysisId,
          target: 'lighting',
          vote: 'down',
          created_at: '2026-08-15T00:00:00Z',
          updated_at: '2026-08-15T00:00:00Z',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    render(
      <RatingButtons
        analysisId={analysisId}
        feedbackToken={token}
        target="lighting"
        label="光影"
      />,
    )

    await user.click(screen.getByRole('button', { name: '👎 没帮助' }))
    await user.click(screen.getByLabelText('建议太笼统'))
    await user.type(screen.getByPlaceholderText(/补充说明/), '建议不够具体。')
    await user.click(screen.getByRole('button', { name: '提交评价' }))

    await waitFor(() => {
      expect(screen.getByText('感谢反馈，我们会改进。')).toBeTruthy()
    })
    const call = fetchMock.mock.calls[0]
    expect(call[0]).toBe(`/api/v2/analyses/${analysisId}/ratings/lighting`)
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({
      vote: 'down',
      reason_codes: ['generic_advice'],
      comment: '建议不够具体。',
    })
  })

  it('clicking an active vote removes the rating', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 }),
    )

    render(
      <RatingButtons
        analysisId={analysisId}
        feedbackToken={token}
        target="color"
        label="色彩"
      />,
    )

    await user.click(screen.getByRole('button', { name: '👍 有帮助' }))
    await waitFor(() => {
      expect(screen.getByText('感谢你的认可！')).toBeTruthy()
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: '👍 有帮助' }))
    await waitFor(() => {
      expect(screen.getByText('已删除评价')).toBeTruthy()
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][1]?.method).toBe('DELETE')
  })
})
