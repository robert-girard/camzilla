import { expect, test, type Page } from '@playwright/test'

type MockOptions = {
  videoFailure?: boolean
}

function detectionMessage() {
  return {
    version: 'v1', sequence: 7, capture_timestamp: new Date().toISOString(),
    result_timestamp: new Date().toISOString(), source_width: 1280, source_height: 720,
    backend_id: 'fake', model_id: 'yolov8n', inference_ms: 4.5, inference_fps: 5,
    detections: [{ class_name: 'person', confidence: 0.91, box: { x: 0.25, y: 0.2, width: 0.5, height: 0.5 } }],
  }
}

async function installMocks(page: Page, options: MockOptions = {}) {
  await page.addInitScript(({ message, settings }) => {
    const sockets: MockSocket[] = []
    class MockSocket {
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: MessageEvent) => void) | null = null
      onclose: ((event: CloseEvent) => void) | null = null
      constructor() {
        sockets.push(this)
        setTimeout(() => this.onopen?.(new Event('open')), 0)
        setTimeout(() => this.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ ...message, result_timestamp: new Date().toISOString() }) })), 10)
      }
      close() { this.onclose?.(new CloseEvent('close')) }
    }
    class MockPeer {
      iceGatheringState: RTCIceGatheringState = 'complete'
      connectionState: RTCPeerConnectionState = 'new'
      localDescription = { type: 'offer' as RTCSdpType, sdp: 'v=0' }
      ontrack: ((event: RTCTrackEvent) => void) | null = null
      onconnectionstatechange: (() => void) | null = null
      addTransceiver() { return {} as RTCRtpTransceiver }
      async createOffer() { return this.localDescription }
      async setLocalDescription() {}
      async setRemoteDescription() {
        this.connectionState = 'connected'
        this.onconnectionstatechange?.()
        this.ontrack?.({ streams: [new MediaStream()] } as RTCTrackEvent)
      }
      addEventListener() {}
      close() { this.connectionState = 'closed' }
    }
    Object.defineProperty(window, 'WebSocket', { value: MockSocket })
    Object.defineProperty(window, 'RTCPeerConnection', { value: MockPeer })
    Object.defineProperty(window, '__camzillaCloseMetadata', {
      value: () => sockets.at(-1)?.onclose?.(new CloseEvent('close')),
    })
    window.fetch = async (input) => {
      const url = String(input)
      if (url.includes('/api/v1/stream')) {
        return new Response(JSON.stringify({ camera_name: 'front-door', webrtc_path: '/api/v1/webrtc', diagnostic_fallback: 'hls' }))
      }
      if (settings.videoFailure) return new Response('unavailable', { status: 503 })
      return new Response('v=0', { headers: { 'content-type': 'application/sdp' } })
    }
  }, { message: detectionMessage(), settings: options })
}

test('shows accessible connected diagnostics and a source-coordinate overlay', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  await expect(page.getByRole('status').first()).toHaveText('Metadata connection: connected')
  await expect(page.getByText('person 91%')).toBeVisible()
  await expect(page.getByLabel('Detection overlay')).toHaveAttribute('viewBox', '0 0 1280 720')
  await expect(page.getByLabel('Diagnostics')).toContainText('Backend/model: fake/yolov8n')
  await expect(page.getByLabel('Diagnostics')).toContainText('Video: connected')
  await expect(page.getByRole('button', { name: 'Fullscreen' })).toBeVisible()
})

test('keeps the overlay with the video during resize and fullscreen', async ({ page }) => {
  await installMocks(page)
  await page.setViewportSize({ width: 640, height: 480 })
  await page.goto('/')
  const overlay = page.getByLabel('Detection overlay')
  await expect(overlay).toHaveAttribute('viewBox', '0 0 1280 720')
  await page.setViewportSize({ width: 1280, height: 720 })
  await expect(overlay).toHaveAttribute('viewBox', '0 0 1280 720')
  await page.getByRole('button', { name: 'Fullscreen' }).click()
  await expect(page.getByRole('button', { name: 'Exit fullscreen' })).toBeVisible()
  await expect(overlay).toBeVisible()
  await expect(overlay).toHaveAttribute('viewBox', '0 0 1280 720')
})

test('expires stale detections without waiting for another message', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  await expect(page.getByText('person 91%')).toBeVisible()
  await expect(page.getByText('person 91%')).toBeHidden({ timeout: 3_000 })
  await expect(page.getByLabel('Diagnostics')).toContainText('Metadata: stale')
})

test('reports metadata degradation and reconnects', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const status = page.getByRole('status').first()
  await expect(status).toHaveText('Metadata connection: connected')
  await page.evaluate(() => {
    const mockWindow = window as typeof window & { __camzillaCloseMetadata: () => void }
    mockWindow.__camzillaCloseMetadata()
  })
  await expect(status).toHaveText('Metadata connection: degraded')
  await expect(status).toHaveText('Metadata connection: connected', { timeout: 2_000 })
  await expect(page.getByText('person 91%')).toBeVisible()
})

test('shows the proxied diagnostic fallback when video signaling fails', async ({ page }) => {
  await installMocks(page, { videoFailure: true })
  await page.goto('/')
  await expect(page.getByText('Video connection is unavailable.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open HLS diagnostic fallback' })).toHaveAttribute(
    'href', '/api/v1/diagnostics/hls/stream.m3u8',
  )
  await expect(page.getByLabel('Diagnostics')).toContainText('Video: degraded')
})
