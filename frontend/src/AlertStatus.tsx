import { useEffect, useState } from 'react'

import { getAlertStatus, getHealthStatus } from './api'
import type { AlertRuntimeStatus, HealthStatus } from './types'

export function AlertStatus() {
  const [alerts, setAlerts] = useState<AlertRuntimeStatus>()
  const [health, setHealth] = useState<HealthStatus>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const [nextAlerts, nextHealth] = await Promise.all([getAlertStatus(), getHealthStatus()])
        if (!active) return
        setAlerts(nextAlerts)
        setHealth(nextHealth)
        setError(undefined)
      } catch (failure) {
        if (active) setError(failure instanceof Error ? failure.message : 'system status unavailable')
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 1_000)
    return () => { active = false; clearInterval(timer) }
  }, [])

  const degraded = error !== undefined || health?.status === 'degraded' || alerts?.last_error
  const classes = alerts ? [...alerts.rule.target_classes].sort().join(', ') : '—'

  return (
    <section aria-labelledby="alert-status-heading" className="alert-status" data-state={degraded ? 'degraded' : 'ready'}>
      <div className="status-heading">
        <div>
          <h2 id="alert-status-heading">Alerts and reliability</h2>
          <p>Current runtime rule and delivery state. Editing arrives with persistent configuration.</p>
        </div>
        <span className="health-pill" role="status">System: {degraded ? 'degraded' : health ? 'ready' : 'checking…'}</span>
      </div>
      {alerts && (
        <dl className="status-grid">
          <div><dt>Rule</dt><dd>{classes} at {Math.round(alerts.rule.confidence_threshold * 100)}%</dd></div>
          <div><dt>Debounce</dt><dd>{alerts.rule.debounce_seconds} seconds</dd></div>
          <div><dt>Notifier</dt><dd>{alerts.effective_notifier}</dd></div>
          <div><dt>Camera stream</dt><dd>{health?.camera.state ?? alerts.stream_state}</dd></div>
          <div><dt>Inference</dt><dd>{health?.inference.state ?? '—'}</dd></div>
          <div><dt>Evaluated</dt><dd>{alerts.delivered_events} ({alerts.dry_run_events} dry-run)</dd></div>
        </dl>
      )}
      {alerts?.configuration_reason && <p className="status-note">{alerts.configuration_reason}</p>}
      {(error || alerts?.last_error) && <p className="selector-error" role="alert">{error ?? alerts?.last_error}</p>}
    </section>
  )
}
