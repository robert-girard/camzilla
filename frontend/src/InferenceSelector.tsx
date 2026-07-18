import { useEffect, useMemo, useState } from 'react'

import {
  applyInferenceSelection,
  getInferenceCapabilities,
  getInferenceCompatibility,
} from './api'
import type {
  CategoryCompatibility,
  InferenceCapabilitiesResponse,
  InferenceSelection,
  InferenceTarget,
} from './types'

const targets: InferenceTarget[] = ['cpu', 'gpu', 'npu', 'tpu']

type Props = {
  onResetDetections: () => void
  onSelectionChange: (selection: InferenceSelection) => void
}

export function InferenceSelector({ onResetDetections, onSelectionChange }: Props) {
  const [state, setState] = useState<InferenceCapabilitiesResponse>()
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string>()
  const [compatibility, setCompatibility] = useState<CategoryCompatibility>()
  const [checkingCompatibility, setCheckingCompatibility] = useState(false)

  useEffect(() => {
    let cancelled = false
    void getInferenceCapabilities()
      .then((response) => {
        if (cancelled) return
        setState(response)
        setSelectedId(response.active.capability_id)
        onSelectionChange(response.active)
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : 'inference capabilities unavailable')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [onSelectionChange])

  const selected = useMemo(
    () => state?.capabilities.find((capability) => capability.id === selectedId),
    [selectedId, state],
  )

  useEffect(() => {
    if (!selected?.available || selected.id === state?.active.capability_id) {
      setCompatibility(undefined)
      setCheckingCompatibility(false)
      return
    }
    let cancelled = false
    setCheckingCompatibility(true)
    void getInferenceCompatibility(selected.id)
      .then((value) => { if (!cancelled) setCompatibility(value) })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : 'category compatibility unavailable')
      })
      .finally(() => { if (!cancelled) setCheckingCompatibility(false) })
    return () => { cancelled = true }
  }, [selected, state?.active.capability_id])

  const apply = async () => {
    if (!selected?.available || applying || selected.id === state?.active.capability_id || !compatibility?.compatible) return
    setApplying(true)
    setError(undefined)
    onResetDetections()
    try {
      const response = await applyInferenceSelection(selected.id)
      setState(response)
      setSelectedId(response.active.capability_id)
      onSelectionChange(response.active)
      window.dispatchEvent(new Event('camzilla:inference-changed'))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'inference switch failed')
    } finally {
      setApplying(false)
    }
  }

  return (
    <section className="inference-selector" aria-labelledby="inference-selector-heading">
      <div className="selector-heading">
        <div>
          <h2 id="inference-selector-heading">Inference model and target</h2>
          <p>
            This global selection is persisted. Category compatibility is checked before a model is loaded.
          </p>
        </div>
        {state && (
          <span className="active-selection">
            Active: {state.active.model_id} on {state.active.target.toUpperCase()}
          </span>
        )}
      </div>
      {loading && <p role="status">Loading inference capabilities…</p>}
      {error && <p role="alert" className="selector-error">{error}</p>}
      {state && (
        <>
          <fieldset disabled={applying}>
            <legend className="sr-only">Available inference combinations</legend>
            <div className="target-grid">
              {targets.map((target) => (
                <section key={target} className="target-group" aria-labelledby={`target-${target}`}>
                  <h3 id={`target-${target}`}>{target.toUpperCase()}</h3>
                  {state.capabilities.filter((item) => item.target === target).map((capability) => (
                    <label key={capability.id} className={`capability ${capability.available ? '' : 'unavailable'}`}>
                      <span>
                        <input
                          type="radio"
                          name="inference-capability"
                          value={capability.id}
                          checked={selectedId === capability.id}
                          disabled={!capability.available}
                          onChange={() => setSelectedId(capability.id)}
                        />
                        {capability.model_id}
                        {capability.active && <strong> active</strong>}
                      </span>
                      {!capability.available && <small>{capability.unavailable_reason}</small>}
                    </label>
                  ))}
                </section>
              ))}
            </div>
          </fieldset>
          <div className="selector-actions">
            <button
              type="button"
              disabled={!selected?.available || selected.id === state.active.capability_id || applying || checkingCompatibility || !compatibility?.compatible}
              onClick={() => void apply()}
            >
              {applying ? 'Switching inference…' : 'Apply inference selection'}
            </button>
            <span role="status">
              {applying ? 'Video remains available while the new backend warms up.' : `State: ${state.transition_state}`}
            </span>
          </div>
          {checkingCompatibility && <p role="status">Checking saved category compatibility…</p>}
          {compatibility && !compatibility.compatible && (
            <div className="compatibility-warning" role="alert">
              <strong>Resolve category conflicts before switching.</strong>
              <span>Missing: {compatibility.missing_category_ids.join(', ')}</span>
              <span>Affected cameras: {compatibility.affected_camera_ids.join(', ') || 'none'}</span>
              <span>Affected rules: {compatibility.affected_rule_ids.join(', ') || 'none'}</span>
              <span>Compatible choices: {compatibility.available_category_ids.join(', ')}</span>
            </div>
          )}
          <p className="selector-note">
            Unavailable hardware needs its server-side runtime and verified model artifact; it cannot be enabled from the browser.
          </p>
        </>
      )}
    </section>
  )
}
