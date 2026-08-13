import { describe, expect, it, vi } from 'vitest'
import { analyzePhoto } from './api'
import { analysisFixture } from './test/fixtures'

describe('analyzePhoto', () => {
  it('sends the FastAPI multipart field names', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(analysisFixture), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const photo = new File(['photo'], 'street.jpg', { type: 'image/jpeg' })

    await analyzePhoto(photo, '  表现雨天的安静  ')

    const request = fetchMock.mock.calls[0]
    expect(request[0]).toBe('/api/v1/analyze')
    expect(request[1]?.method).toBe('POST')
    const body = request[1]?.body as FormData
    expect(body.get('photo')).toBe(photo)
    expect(body.get('intent')).toBe('表现雨天的安静')
  })

  it('translates a model timeout into a recoverable Chinese message', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: 'model_timeout', message: 'timed out' } }),
        { status: 504, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(
      analyzePhoto(new File(['x'], 'x.jpg', { type: 'image/jpeg' }), ''),
    ).rejects.toMatchObject({
      code: 'model_timeout',
      message: '本次分析超时，请稍后重试。',
      status: 504,
    })
  })

  it('rejects a successful response with the wrong structure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ report: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(
      analyzePhoto(new File(['x'], 'x.jpg', { type: 'image/jpeg' }), ''),
    ).rejects.toMatchObject({ code: 'invalid_response' })
  })
})
