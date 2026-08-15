import { useState } from 'react'

import { adminRequest, storeToken } from '../api'
import type { AdminSessionCreated } from '../types'

interface LoginPageProps {
  onLoggedIn: () => void
}

export default function LoginPage({ onLoggedIn }: LoginPageProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const session = await adminRequest<AdminSessionCreated>(
        '/api/admin/v1/sessions',
        {
          method: 'POST',
          body: JSON.stringify({ username, password }),
        },
      )
      storeToken(session.access_token)
      onLoggedIn()
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : '登录失败，请稍后重试。',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="admin-login">
      <form className="admin-login-card" onSubmit={handleSubmit}>
        <h1>摄影教练 · 管理控制台</h1>
        <p className="admin-login-hint">
          请使用管理员账号登录。会话会在关闭浏览器或注销后失效。
        </p>
        <label>
          用户名
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label>
          密码
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error !== null && (
          <p className="admin-error" role="alert">
            {error}
          </p>
        )}
        <button
          className="admin-button admin-button-primary"
          type="submit"
          disabled={busy}
        >
          {busy ? '正在登录…' : '登录'}
        </button>
      </form>
    </main>
  )
}
