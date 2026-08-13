const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_FILE_BYTES = 10 * 1024 * 1024

export function validateFile(file: File): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) {
    return '请选择 JPEG、PNG 或 WebP 图片。'
  }
  if (file.size > MAX_FILE_BYTES) {
    return '图片超过 10 MiB，请压缩后重新选择。'
  }
  return null
}
