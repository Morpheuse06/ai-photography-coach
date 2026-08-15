import { useCallback, useEffect, useState } from 'react'

import { getStoredToken } from './api'
import Layout from './components/Layout'
import AnalysisRunsPage from './pages/AnalysisRunsPage'
import AuditPage from './pages/AuditPage'
import DashboardPage from './pages/DashboardPage'
import InviteCodesPage from './pages/InviteCodesPage'
import LoginPage from './pages/LoginPage'
import ProblemReportsPage from './pages/ProblemReportsPage'
import RatingsPage from './pages/RatingsPage'
import SystemPage from './pages/SystemPage'

export type AdminRoute =
  | 'dashboard'
  | 'invite-codes'
  | 'analysis-runs'
  | 'ratings'
  | 'problem-reports'
  | 'system'
  | 'audit'

const ROUTES: { route: AdminRoute; label: string }[] = [
  { route: 'dashboard', label: '数据总览' },
  { route: 'invite-codes', label: '邀请码' },
  { route: 'analysis-runs', label: '分析记录' },
  { route: 'ratings', label: '模块评价' },
  { route: 'problem-reports', label: '问题反馈' },
  { route: 'system', label: '系统' },
  { route: 'audit', label: '审计日志' },
]

function currentRoute(): AdminRoute {
  const hash = window.location.hash.replace(/^#\/?/, '')
  return ROUTES.some((entry) => entry.route === hash) ? (hash as AdminRoute) : 'dashboard'
}

export default function AdminApp() {
  const [loggedIn, setLoggedIn] = useState(() => getStoredToken() !== null)
  const [route, setRoute] = useState<AdminRoute>(currentRoute)

  useEffect(() => {
    const onHashChange = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    const onExpired = () => setLoggedIn(false)
    window.addEventListener('admin-session-expired', onExpired)
    return () => window.removeEventListener('admin-session-expired', onExpired)
  }, [])

  const onLoggedIn = useCallback(() => {
    setLoggedIn(true)
    window.location.hash = '#/dashboard'
  }, [])

  const onSessionExpired = useCallback(() => {
    setLoggedIn(false)
  }, [])

  if (!loggedIn) {
    return <LoginPage onLoggedIn={onLoggedIn} />
  }

  let page: React.ReactNode
  switch (route) {
    case 'invite-codes':
      page = <InviteCodesPage />
      break
    case 'analysis-runs':
      page = <AnalysisRunsPage />
      break
    case 'ratings':
      page = <RatingsPage />
      break
    case 'problem-reports':
      page = <ProblemReportsPage />
      break
    case 'system':
      page = <SystemPage />
      break
    case 'audit':
      page = <AuditPage />
      break
    default:
      page = <DashboardPage />
  }

  return (
    <Layout
      routes={ROUTES}
      active={route}
      onSessionExpired={onSessionExpired}
    >
      {page}
    </Layout>
  )
}
