import { useEffect, useMemo, useState } from 'react'

import { applyInferenceSelection, getInferenceCapabilities } from './api'
import type {
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

  const apply = async () => {
    if (!selected?.available || applying || selected.id === state?.active.capability_id) return
    setApplying(true)
    setError(undefined)
    onResetDetections()
    try {
      const response = await applyInferenceSelection(selected.id)
      setState(response)
      setSelectedId(response.active.capability_id)
      onSelectionChange(response.active)
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
            This selection is global and runtime-only. Restarting Camzilla restores the deployment default.
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
              disabled={!selected?.available || selected.id === state.active.capability_id || applying}
              onClick={() => void apply()}
            >
              {applying ? 'Switching inference…' : 'Apply inference selection'}
            </button>
            <span role="status">
              {applying ? 'Video remains available while the new backend warms up.' : `State: ${state.transition_state}`}
            </span>
          </div>
          <p className="selector-note">
            Unavailable hardware needs its server-side runtime and verified model artifact; it cannot be enabled from the browser.
          </p>
        </>
      )}
    </section>
  )
}
