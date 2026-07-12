import { describe, expect, it } from 'vitest'

import { isStale, overlayRect } from './overlay'

describe('overlay geometry', () => {
  it('places normalized coordinates inside letterboxed video content', () => {
    expect(overlayRect({ x: 0.25, y: 0.5, width: 0.5, height: 0.25 }, { x: 100, y: 20, width: 800, height: 450 })).toEqual({
      x: 300, y: 245, width: 400, height: 112.5,
    })
  })

  it('expires a result after its TTL', () => {
    expect(isStale('2026-07-11T12:00:00.000Z', 2, Date.parse('2026-07-11T12:00:02.001Z'))).toBe(true)
  })
})
