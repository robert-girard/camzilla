import { useEffect, useState } from 'react'

import { getPtzCapability, movePtz } from './api'
import type { PtzCapability, PtzDirection } from './types'

const controls: Array<{ direction: PtzDirection; label: string; glyph: string }> = [
  { direction: 'up', label: 'Pan up', glyph: '↑' },
  { direction: 'left', label: 'Pan left', glyph: '←' },
  { direction: 'right', label: 'Pan right', glyph: '→' },
  { direction: 'down', label: 'Pan down', glyph: '↓' },
  { direction: 'in', label: 'Zoom in', glyph: '+' },
  { direction: 'out', label: 'Zoom out', glyph: '−' },
]

export function PtzControls({ cameraName }: { cameraName: string }) {
  const [capability, setCapability] = useState<PtzCapability>()
  const [loadingError, setLoadingError] = useState<string>()
  const [moveError, setMoveError] = useState<string>()
  const [moving, setMoving] = useState<PtzDirection>()
  const [lastMove, setLastMove] = useState<PtzDirection>()

  useEffect(() => {
    let active = true
    void getPtzCapability(cameraName)
      .then((value) => {
        if (active) setCapability(value)
      })
      .catch((error: unknown) => {
        if (active) setLoadingError(error instanceof Error ? error.message : 'PTZ capability unavailable')
      })
    return () => { active = false }
  }, [cameraName])

  const move = async (direction: PtzDirection) => {
    setMoving(direction)
    setMoveError(undefined)
    try {
      await movePtz(cameraName, direction)
      setLastMove(direction)
    } catch (error) {
      setMoveError(error instanceof Error ? error.message : 'PTZ command failed')
    } finally {
      setMoving(undefined)
    }
  }

  const unavailableReason = loadingError ?? capability?.unavailable_reason
  const disabled = !capability?.available || moving !== undefined

  return (
    <section aria-labelledby="ptz-heading" className="ptz-controls">
      <div>
        <h2 id="ptz-heading">Camera controls</h2>
        <p>Each press sends one short, bounded movement command.</p>
      </div>
      <div className="ptz-grid">
        {controls.map(({ direction, label, glyph }) => (
          <button
            aria-label={label}
            className={`ptz-${direction}`}
            disabled={disabled}
            key={direction}
            onClick={() => void move(direction)}
            type="button"
          >
            {moving === direction ? '…' : glyph}
          </button>
        ))}
      </div>
      {!capability && !loadingError && <p role="status">Checking PTZ capability…</p>}
      {unavailableReason && <p className="ptz-note" role="status">PTZ unavailable: {unavailableReason}</p>}
      {moveError && <p className="selector-error" role="alert">{moveError}</p>}
      {lastMove && !moveError && <p className="ptz-note" role="status">{lastMove} movement accepted</p>}
    </section>
  )
}
