export type NormalizedBox = { x: number; y: number; width: number; height: number }

export type Rect = { x: number; y: number; width: number; height: number }

/** Maps source-normalized coordinates into the displayed video content rectangle. */
export function overlayRect(box: NormalizedBox, content: Rect): Rect {
  return {
    x: content.x + box.x * content.width,
    y: content.y + box.y * content.height,
    width: box.width * content.width,
    height: box.height * content.height,
  }
}

export function sourceRect(box: NormalizedBox, sourceWidth: number, sourceHeight: number): Rect {
  return {
    x: box.x * sourceWidth,
    y: box.y * sourceHeight,
    width: box.width * sourceWidth,
    height: box.height * sourceHeight,
  }
}

export function isStale(resultTimestamp: string, ttlSeconds: number, now = Date.now()): boolean {
  return now - Date.parse(resultTimestamp) > ttlSeconds * 1_000
}
