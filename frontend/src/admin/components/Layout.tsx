import type { ReactNode } from 'react'

import { adminRequest, clearToken } from '../api'
import type { AdminRoute } from '../AdminApp'

interface LayoutProps {
  routes: { route: AdminRoute; label: string }[]
  active: AdminRoute
  onSessionExpired: () => void
  children: ReactNode
}

export default function Layout({
  routes,
  active,
  onSessionExpired,
  children,
}: LayoutProps) {
  const handleLogout = async () => {
    try {
      await adminRequest('/api/admin/v1/sessions/current', { method: 'DELETE' })
    } catch {
      // The session is gone either way; continue clearing local state.
    }
    clearToken()
    onSessionExpired()
  }

  return (
    <div className="admin-shell">
      <header className="admin-topbar">
        <a className="admin-brand" href="#/dashboard">
          摄影教练 · 管理控制台
        </a>
        <button className="admin-button admin-button-ghost" type="button" onClick={handleLogout}>
          退出登录
        </button>
      </header>
      <nav className="admin-nav" aria-label="管理导航">
        {routes.map((entry) => (
          <a
            key={entry.route}
            className={entry.route === active ? 'admin-nav-active' : ''}
            href={`#/${entry.route}`}
          >
            {entry.label}
          </a>
        ))}
      </nav>
      <main className="admin-main">{children}</main>
    </div>
  )
}
