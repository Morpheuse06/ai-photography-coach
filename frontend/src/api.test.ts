import { describe, expect, it, vi } from 'vitest'
import {
  analyzePhoto,
  deleteRating,
  submitProblemReport,
  upsertRating,
} from './api'
import { analysisFixture } from './test/fixtures'

describe('analyzePhoto', () => {
  it('sends the FastAPI multipart field names and control-plane headers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(analysisFixture), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const photo = new File(['photo'], 'street.jpg', { type: 'image/jpeg' })

    await analyzePhoto(photo, '  表现雨天的安静  ', '  PXC-AAAA-BBBB-CCCC-DDDD  ', 'test-key-1')

    const request = fetchMock.mock.calls[0]
    expect(request[0]).toBe('/api/v2/analyze')
    expect(request[1]?.method).toBe('POST')
    const body = request[1]?.body as FormData
    expect(body.get('photo')).toBe(photo)
    expect(body.get('intent')).toBe('表现雨天的安静')
    const headers = request[1]?.headers as Record<string, string>
    expect(headers['Idempotency-Key']).toBe('test-key-1')
    expect(headers['X-Access-Code']).toBe('PXC-AAAA-BBBB-CCCC-DDDD')
  })

  it('omits the access code header when no code is entered', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(analysisFixture), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await analyzePhoto(new File(['x'], 'x.jpg', { type: 'image/jpeg' }), '', '', 'test-key-2')

    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>
    expect(headers['X-Access-Code']).toBeUndefined()
  })

  it('translates a model timeout into a recoverable Chinese message', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: 'model_timeout', message: 'timed out' } }),
        { status: 504, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(
      analyzePhoto(new File(['x'], 'x.jpg', { type: 'image/jpeg' }), '', '', 'test-key-2'),
    ).rejects.toMatchObject({
      code: 'model_timeout',
      message: '本次分析超时，请稍后重试。',
      status: 504,
    })
  })

  it('translates access-code errors for the user', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: 'access_quota_exhausted', message: 'no uses' },
        }),
        { status: 429, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(
      analyzePhoto(new File(['x'], 'x.jpg', { type: 'image/jpeg' }), '', '', 'test-key-2'),
    ).rejects.toMatchObject({
      code: 'access_quota_exhausted',
      message: '该邀请码的次数已用完。',
      status: 429,
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
      analyzePhoto(new File(['x'], 'x.jpg', { type: 'image/jpeg' }), '', '', 'test-key-2'),
    ).rejects.toMatchObject({ code: 'invalid_response' })
  })
})

describe('anonymous feedback', () => {
  const analysisId = '8d81ac6b-c3a5-4dad-912d-7635725a459f'
  const token = '7B1DgR5NwP2kL9xQa4Vm8Yc3Hs6Jt0UfEeZiKpAo'

  it('upserts a rating with the feedback bearer token', async () => {
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

    await upsertRating(analysisId, token, 'lighting', 'down', ['generic_advice'], '建议不够具体。')

    const request = fetchMock.mock.calls[0]
    expect(request[0]).toBe(`/api/v2/analyses/${analysisId}/ratings/lighting`)
    expect(request[1]?.method).toBe('PUT')
    const headers = request[1]?.headers as Record<string, string>
    expect(headers.Authorization).toBe(`Bearer ${token}`)
    expect(JSON.parse(String(request[1]?.body))).toMatchObject({
      vote: 'down',
      reason_codes: ['generic_advice'],
      comment: '建议不够具体。',
    })
  })

  it('deletes a rating and treats 204 as success', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 }),
    )

    await expect(
      deleteRating(analysisId, token, 'color'),
    ).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[0][1]?.method).toBe('DELETE')
  })

  it('submits a problem report without a bearer token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          problem_report_id: 'problem-1',
          status: 'new',
          created_at: '2026-08-15T00:00:00Z',
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const receipt = await submitProblemReport({
      analysis_id: analysisId,
      category: 'report_quality',
      message: '光影建议没有考虑画面中主体已经处于剪影状态。',
      include_runtime_metadata: true,
    })

    expect(receipt.problem_report_id).toBe('problem-1')
    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>
    expect(headers.Authorization).toBeUndefined()
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      include_runtime_metadata: true,
    })
  })

  it('translates feedback errors into Chinese messages', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: 'feedback_forbidden', message: 'no' },
        }),
        { status: 403, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(
      upsertRating(analysisId, token, 'overall', 'up'),
    ).rejects.toMatchObject({
      code: 'feedback_forbidden',
      message: '反馈凭据无效，请重新分析后再评价。',
    })
  })
})
