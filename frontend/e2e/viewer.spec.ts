import { expect, test } from '@playwright/test'

const detection = {
  version: 'v1', sequence: 7, capture_timestamp: '2026-07-12T00:00:00.000Z',
  result_timestamp: new Date().toISOString(), source_width: 1280, source_height: 720,
  backend_id: 'fake', model_id: 'fake-person-v1', inference_ms: 4.5, inference_fps: 5,
  detections: [{ class_name: 'person', confidence: 0.91, box: { x: 0.25, y: 0.2, width: 0.5, height: 0.5 } }],
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript((message) => {
    class MockSocket {
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: MessageEvent) => void) | null = null
      onclose: ((event: CloseEvent) => void) | null = null
      constructor() {
        setTimeout(() => this.onopen?.(new Event('open')), 0)
        setTimeout(() => this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(message) })), 10)
      }
      close() { this.onclose?.(new CloseEvent('close')) }
    }
    class MockPeer {
      iceGatheringState: RTCIceGatheringState = 'complete'
      addTransceiver() { return {} as RTCRtpTransceiver }
      async createOffer() { return { type: 'offer' as RTCSdpType, sdp: 'v=0' } }
      async setLocalDescription() {}
      async setRemoteDescription() {}
      addEventListener() {}
      close() {}
    }
    Object.defineProperty(window, 'WebSocket', { value: MockSocket })
    Object.defineProperty(window, 'RTCPeerConnection', { value: MockPeer })
    window.fetch = async (input) => {
      const url = String(input)
      if (url.includes('/api/v1/stream')) {
        return new Response(JSON.stringify({ camera_name: 'front-door', webrtc_path: '/api/v1/webrtc', diagnostic_fallback: 'hls' }))
      }
      return new Response('v=0', { headers: { 'content-type': 'application/sdp' } })
    }
  }, detection)
})

test('shows deterministic detection diagnostics and source-coordinate overlay', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('status')).toHaveText('Metadata connection: connected')
  await expect(page.getByText('person 91%')).toBeVisible()
  await expect(page.getByLabel('Detection overlay')).toHaveAttribute('viewBox', '0 0 1280 720')
  await expect(page.getByLabel('Diagnostics')).toContainText('Backend/model: fake/fake-person-v1')
})

test('keeps source geometry during viewport resize', async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 480 })
  await page.goto('/')
  await expect(page.getByLabel('Detection overlay')).toHaveAttribute('viewBox', '0 0 1280 720')
  await page.setViewportSize({ width: 1280, height: 720 })
  await expect(page.getByLabel('Detection overlay')).toHaveAttribute('viewBox', '0 0 1280 720')
})
