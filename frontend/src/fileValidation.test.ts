import { describe, expect, it } from 'vitest'
import { validateFile } from './fileValidation'

describe('validateFile', () => {
  it('accepts the supported image media types', () => {
    expect(validateFile(new File(['x'], 'photo.jpg', { type: 'image/jpeg' }))).toBeNull()
    expect(validateFile(new File(['x'], 'photo.png', { type: 'image/png' }))).toBeNull()
    expect(validateFile(new File(['x'], 'photo.webp', { type: 'image/webp' }))).toBeNull()
  })

  it('rejects a photo over ten mebibytes', () => {
    const oversized = new File(
      [new Uint8Array(10 * 1024 * 1024 + 1)],
      'large.jpg',
      { type: 'image/jpeg' },
    )
    expect(validateFile(oversized)).toBe('图片超过 10 MiB，请压缩后重新选择。')
  })
})
