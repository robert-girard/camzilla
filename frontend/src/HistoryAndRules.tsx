import { useEffect, useState, type MouseEvent } from 'react'

import { deleteEvent, getConfiguration, getEvents, updateAlertRule } from './api'
import type { AlertRuleConfiguration, EventPage, GlobalConfiguration, ZonePoint } from './types'

type RuleDraft = {
  confidence: number
  debounce: number
  scheduleEnabled: boolean
  scheduleStart: string
  scheduleEnd: string
  zone: ZonePoint[]
}

function draftFrom(rule: AlertRuleConfiguration): RuleDraft {
  return {
    confidence: rule.confidence_threshold,
    debounce: rule.debounce_seconds,
    scheduleEnabled: Boolean(rule.schedule_start && rule.schedule_end),
    scheduleStart: rule.schedule_start ?? '22:00',
    scheduleEnd: rule.schedule_end ?? '06:00',
    zone: rule.zone?.points ?? [],
  }
}

export function HistoryAndRules() {
  const [configuration, setConfiguration] = useState<GlobalConfiguration>()
  const [draft, setDraft] = useState<RuleDraft>()
  const [events, setEvents] = useState<EventPage>()
  const [eventType, setEventType] = useState('')
  const [sort, setSort] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string>()
  const [notice, setNotice] = useState<string>()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    void getConfiguration()
      .then((value) => {
        setConfiguration(value)
        if (value.alert_rules[0]) setDraft(draftFrom(value.alert_rules[0]))
      })
      .catch((failure: unknown) => setError(failure instanceof Error ? failure.message : 'configuration unavailable'))
  }, [])

  useEffect(() => {
    void getEvents({ page, eventType, sort })
      .then(setEvents)
      .catch((failure: unknown) => setError(failure instanceof Error ? failure.message : 'event history unavailable'))
  }, [eventType, page, sort])

  const addZonePoint = (event: MouseEvent<SVGSVGElement>) => {
    if (!draft || draft.zone.length >= 16) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const point = {
      x: Math.round(((event.clientX - bounds.left) / bounds.width) * 1000) / 1000,
      y: Math.round(((event.clientY - bounds.top) / bounds.height) * 1000) / 1000,
    }
    setDraft({ ...draft, zone: [...draft.zone, point] })
  }

  const save = async () => {
    const rule = configuration?.alert_rules[0]
    if (!configuration || !rule || !draft) return
    if (draft.zone.length > 0 && draft.zone.length < 3) {
      setError('A zone needs at least three points or must be cleared.')
      return
    }
    setSaving(true)
    setError(undefined)
    setNotice(undefined)
    try {
      const changed = await updateAlertRule(rule.id, {
        expected_config_version: configuration.version,
        confidence_threshold: draft.confidence,
        debounce_seconds: draft.debounce,
        schedule_start: draft.scheduleEnabled ? draft.scheduleStart : undefined,
        schedule_end: draft.scheduleEnabled ? draft.scheduleEnd : undefined,
        zone: draft.zone.length ? { points: draft.zone } : undefined,
        target_categories: rule.target_categories,
      })
      setConfiguration(changed)
      setDraft(draftFrom(changed.alert_rules[0]))
      setNotice('Rule saved')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'rule update failed')
    } finally {
      setSaving(false)
    }
  }

  const removeEvent = async (eventId: string) => {
    try {
      await deleteEvent(eventId)
      setEvents((current) => current ? {
        ...current,
        total: current.total - 1,
        items: current.items.filter((item) => item.id !== eventId),
      } : current)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'event deletion failed')
    }
  }

  const rule = configuration?.alert_rules[0]
  const polygon = draft?.zone.map((point) => `${point.x * 100},${point.y * 100}`).join(' ')

  return (
    <section aria-labelledby="history-heading" className="history-rules">
      <h2 id="history-heading">Configuration and alert history</h2>
      <div className="camera-list" aria-label="Configured cameras">
        {configuration?.cameras.map((camera) => (
          <article key={camera.id}>
            <h3>{camera.name}</h3>
            <span>{camera.enabled ? 'enabled' : 'disabled'}</span>
          </article>
        ))}
      </div>
      {rule && draft && (
        <form onSubmit={(event) => { event.preventDefault(); void save() }} className="rule-editor">
          <h3>Edit {rule.target_categories.join(', ')} rule</h3>
          <label>Confidence (%)
            <input type="number" min="0" max="100" value={Math.round(draft.confidence * 100)} onChange={(event) => setDraft({ ...draft, confidence: Number(event.target.value) / 100 })} />
          </label>
          <label>Debounce (seconds)
            <input type="number" min="1" max="86400" value={draft.debounce} onChange={(event) => setDraft({ ...draft, debounce: Number(event.target.value) })} />
          </label>
          <label className="check"><input type="checkbox" checked={draft.scheduleEnabled} onChange={(event) => setDraft({ ...draft, scheduleEnabled: event.target.checked })} /> Enable schedule</label>
          <label>Start<input aria-label="Schedule start" type="time" disabled={!draft.scheduleEnabled} value={draft.scheduleStart} onChange={(event) => setDraft({ ...draft, scheduleStart: event.target.value })} /></label>
          <label>End<input aria-label="Schedule end" type="time" disabled={!draft.scheduleEnabled} value={draft.scheduleEnd} onChange={(event) => setDraft({ ...draft, scheduleEnd: event.target.value })} /></label>
          <div className="zone-editor">
            <span>Detection zone ({draft.zone.length} points)</span>
            <svg aria-label="Detection zone editor" viewBox="0 0 100 100" onClick={addZonePoint}>
              <rect x="0" y="0" width="100" height="100" />
              {polygon && <polygon points={polygon} />}
              {draft.zone.map((point, index) => <circle key={index} cx={point.x * 100} cy={point.y * 100} r="2" />)}
            </svg>
            <button type="button" onClick={() => setDraft({ ...draft, zone: [] })}>Clear zone</button>
          </div>
          <button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save rule'}</button>
        </form>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && <p className="selector-error" role="alert">{error}</p>}
      <div className="history-toolbar">
        <label>Event type<select value={eventType} onChange={(event) => { setEventType(event.target.value); setPage(1) }}><option value="">All</option><option value="detection">Detection</option><option value="stream-down">Stream down</option><option value="stream-recovered">Recovery</option></select></label>
        <label>Sort<select value={sort} onChange={(event) => setSort(event.target.value as 'asc' | 'desc')}><option value="desc">Newest</option><option value="asc">Oldest</option></select></label>
      </div>
      <div className="history-table-wrap">
        <table><thead><tr><th>Time</th><th>Camera</th><th>Type</th><th>Categories</th><th>Media</th><th /></tr></thead>
          <tbody>{events?.items.map((item) => <tr key={item.id}>
            <td>{new Date(item.triggered_at).toLocaleString()}</td><td>{item.camera_id}</td><td>{item.event_type}</td><td>{item.categories.join(', ')}</td>
            <td>{item.has_snapshot ? <a href={`/api/v1/events/${item.id}/snapshot`}>Snapshot</a> : '—'} {item.has_clip && <a href={`/api/v1/events/${item.id}/clip`}>Clip</a>}</td>
            <td><button type="button" onClick={() => void removeEvent(item.id)}>Delete</button></td>
          </tr>)}</tbody>
        </table>
        {events?.total === 0 && <p>No alert events match this filter.</p>}
      </div>
      <nav aria-label="History pages"><button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {Math.max(events?.pages ?? 1, 1)}</span><button type="button" disabled={!events || page >= events.pages} onClick={() => setPage(page + 1)}>Next</button></nav>
    </section>
  )
}
