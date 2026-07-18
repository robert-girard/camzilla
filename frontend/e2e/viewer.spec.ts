import { expect, test, type Page } from '@playwright/test'

type MockOptions = {
  videoFailure?: boolean
  selectionFailure?: boolean
  switchDelayMs?: number
  ptzAvailable?: boolean
  ptzFailure?: boolean
}

function detectionMessage() {
  return {
    version: 'v1', sequence: 7, capture_timestamp: new Date().toISOString(),
    result_timestamp: new Date().toISOString(), source_width: 1280, source_height: 720,
    backend_id: 'fake', model_id: 'yolov8n', target: 'cpu', device: 'synthetic', inference_ms: 4.5, inference_fps: 5,
    detections: [{ class_name: 'person', confidence: 0.91, box: { x: 0.25, y: 0.2, width: 0.5, height: 0.5 } }],
  }
}

function inferenceState() {
  const capabilities = [
    { id: 'fake:yolov8n:cpu', backend_id: 'fake', model_id: 'yolov8n', target: 'cpu', device: 'synthetic', compatible: true, available: true, active: true },
    { id: 'ultralytics:yolo11s:cpu', backend_id: 'ultralytics', model_id: 'yolo11s', target: 'cpu', device: 'cpu', compatible: true, available: true, active: false },
    { id: 'ultralytics:yolo11s:gpu', backend_id: 'ultralytics', model_id: 'yolo11s', target: 'gpu', device: 'cuda', compatible: true, available: false, unavailable_reason: 'CUDA device is not available', active: false },
    { id: 'rknn:unconfigured:npu', backend_id: 'rknn', model_id: 'unconfigured', target: 'npu', device: 'npu', compatible: false, available: false, unavailable_reason: 'RKNN NPU support is delivered in Phase 4b', active: false },
    { id: 'tpu:unconfigured:tpu', backend_id: 'tpu', model_id: 'unconfigured', target: 'tpu', device: 'tpu', compatible: false, available: false, unavailable_reason: 'TPU hardware and runtime are not configured', active: false },
  ]
  return {
    active: { capability_id: 'fake:yolov8n:cpu', backend_id: 'fake', model_id: 'yolov8n', target: 'cpu', device: 'synthetic' },
    transition_state: 'ready', runtime_only: true, capabilities,
  }
}

async function installMocks(page: Page, options: MockOptions = {}) {
  await page.addInitScript(({ message, settings, inferenceState }) => {
    const sockets: MockSocket[] = []
    const inference = inferenceState
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
    Object.defineProperty(window, '__camzillaPtzMoves', { value: [] as string[] })
    const health = { status: 'ready', camera: 'not_configured', inference: 'ready' }
    Object.defineProperty(window, '__camzillaSetHealth', {
      value: (status: string, camera: string, inference: string) => {
        health.status = status
        health.camera = camera
        health.inference = inference
      },
    })
    window.fetch = async (input, init) => {
      const url = String(input)
      if (url.includes('/api/v1/stream')) {
        return new Response(JSON.stringify({ camera_name: 'front-door', webrtc_path: '/api/v1/webrtc', diagnostic_fallback: 'hls' }))
      }
      if (url.includes('/api/v1/inference/selection')) {
        if (settings.selectionFailure) {
          return new Response(JSON.stringify({ detail: 'switch failed; previous inference remains active' }), {
            status: 503, headers: { 'content-type': 'application/json' },
          })
        }
        if (settings.switchDelayMs) await new Promise((resolve) => setTimeout(resolve, settings.switchDelayMs))
        const body = JSON.parse(String(init?.body)) as { capability_id: string }
        const selected = inference.capabilities.find((item) => item.id === body.capability_id)
        if (!selected?.available) return new Response(JSON.stringify({ detail: 'inference capability is unavailable' }), { status: 409 })
        inference.active = {
          capability_id: selected.id, backend_id: selected.backend_id, model_id: selected.model_id,
          target: selected.target, device: selected.device,
        }
        inference.capabilities = inference.capabilities.map((item) => ({ ...item, active: item.id === selected.id }))
        sockets.at(-1)?.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ type: 'reset' }) }))
        setTimeout(() => sockets.at(-1)?.onmessage?.(new MessageEvent('message', {
          data: JSON.stringify({
            ...message, backend_id: selected.backend_id, model_id: selected.model_id,
            target: selected.target, device: selected.device, result_timestamp: new Date().toISOString(),
          }),
        })), 25)
        return new Response(JSON.stringify(inference), { headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/api/v1/inference')) {
        return new Response(JSON.stringify(inference), { headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/capabilities/ptz')) {
        const available = settings.ptzAvailable !== false
        return new Response(JSON.stringify({
          camera_name: 'front-door', available, verified: available,
          unavailable_reason: available ? null : 'PTZ is configured but not operation-verified',
          supports_continuous_move: available, supports_stop: false,
          max_speed: 0.3, max_duration_seconds: 1,
        }), { headers: { 'content-type': 'application/json' } })
      }
      if (url.endsWith('/ptz')) {
        if (settings.ptzFailure) {
          return new Response(JSON.stringify({ detail: 'PTZ command failed' }), {
            status: 503, headers: { 'content-type': 'application/json' },
          })
        }
        const body = JSON.parse(String(init?.body)) as { direction: string; duration_seconds: number }
        const testWindow = window as typeof window & { __camzillaPtzMoves: string[] }
        testWindow.__camzillaPtzMoves.push(body.direction)
        return new Response(JSON.stringify({
          status: 'accepted', direction: body.direction, duration_seconds: body.duration_seconds,
        }), { headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/api/v1/alerts/status')) {
        return new Response(JSON.stringify({
          rule: {
            id: 'person-detected', camera_name: 'front-door', target_classes: ['person'],
            confidence_threshold: 0.6, debounce_seconds: 300, enabled: true,
          },
          requested_notifier: 'dry-run', effective_notifier: 'dry-run',
          external_delivery_configured: false,
          configuration_reason: 'Dry-run mode does not send external notifications',
          queued_events: 0, delivered_events: 2, dry_run_events: 2, failed_events: 0,
          dropped_events: 0, suppressed_events: 1, stream_state: 'ready',
          stream_down_events: 0, stream_recovery_events: 0,
        }), { headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/health/ready')) {
        return new Response(JSON.stringify({
          status: health.status,
          camera: { configured: false, state: health.camera },
          inference: { state: health.inference },
          alerts: {}, bridge: { state: health.camera },
        }), { headers: { 'content-type': 'application/json' } })
      }
      if (settings.videoFailure) return new Response('unavailable', { status: 503 })
      return new Response('v=0', { headers: { 'content-type': 'application/sdp' } })
    }
  }, { message: detectionMessage(), settings: options, inferenceState: inferenceState() })
}

test('shows accessible connected diagnostics and a source-coordinate overlay', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  await expect(page.getByRole('status').first()).toHaveText('Metadata connection: connected')
  await expect(page.getByText('person 91%')).toBeVisible()
  await expect(page.getByLabel('Detection overlay')).toHaveAttribute('viewBox', '0 0 1280 720')
  await expect(page.getByLabel('Diagnostics')).toContainText('Backend/model: fake/yolov8n')
  await expect(page.getByLabel('Diagnostics')).toContainText('Target/device: cpu/synthetic')
  await expect(page.getByLabel('Diagnostics')).toContainText('Video: connected')
  await expect(page.getByRole('button', { name: 'Fullscreen' })).toBeVisible()
})

test('switches to an available CPU model only after explicit apply', async ({ page }) => {
  await installMocks(page, { switchDelayMs: 100 })
  await page.goto('/')
  await expect(page.getByText('person 91%')).toBeVisible()
  await page.getByRole('radio', { name: 'yolo11s', exact: true }).check()
  await page.getByRole('button', { name: 'Apply inference selection' }).click()
  await expect(page.getByRole('button', { name: 'Switching inference…' })).toBeDisabled()
  await expect(page.getByText('person 91%')).toBeHidden()
  await expect(page.getByText('Active: yolo11s on CPU')).toBeVisible()
  await expect(page.getByLabel('Diagnostics')).toContainText('Backend/model: ultralytics/yolo11s')
  await expect(page.getByText('person 91%')).toBeVisible()
})

test('explains unavailable GPU NPU and TPU targets', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'GPU' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'NPU' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'TPU' })).toBeVisible()
  await expect(page.getByText('CUDA device is not available')).toBeVisible()
  await expect(page.getByText('RKNN NPU support is delivered in Phase 4b')).toBeVisible()
  await expect(page.getByText('TPU hardware and runtime are not configured')).toBeVisible()
  await expect(page.getByRole('radio', { name: /yolo11s CUDA device/ })).toBeDisabled()
})

test('keeps the confirmed selection and reports a failed switch', async ({ page }) => {
  await installMocks(page, { selectionFailure: true })
  await page.goto('/')
  await page.getByRole('radio', { name: 'yolo11s', exact: true }).check()
  await page.getByRole('button', { name: 'Apply inference selection' }).click()
  await expect(page.getByRole('alert')).toHaveText('switch failed; previous inference remains active')
  await expect(page.getByText('Active: yolov8n on CPU')).toBeVisible()
  await expect(page.getByLabel('Diagnostics')).toContainText('Backend/model: fake/yolov8n')
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

test('sends one bounded PTZ command and reports acceptance', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const panLeft = page.getByRole('button', { name: 'Pan left' })
  await expect(panLeft).toBeEnabled()
  await panLeft.click()
  await expect(page.getByText('left movement accepted')).toBeVisible()
  const moves = await page.evaluate(() => {
    const testWindow = window as typeof window & { __camzillaPtzMoves: string[] }
    return testWindow.__camzillaPtzMoves
  })
  expect(moves).toEqual(['left'])
})

test('keeps PTZ controls disabled until operation verification', async ({ page }) => {
  await installMocks(page, { ptzAvailable: false })
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Pan left' })).toBeDisabled()
  await expect(page.getByText('PTZ unavailable: PTZ is configured but not operation-verified')).toBeVisible()
})

test('reports a PTZ command failure without exposing adapter details', async ({ page }) => {
  await installMocks(page, { ptzFailure: true })
  await page.goto('/')
  await page.getByRole('button', { name: 'Zoom in' }).click()
  await expect(page.getByRole('alert')).toHaveText('PTZ command failed')
  await expect(page.getByRole('button', { name: 'Zoom in' })).toBeEnabled()
})

test('shows the alert rule and external-delivery-safe dry-run state', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const status = page.getByRole('region', { name: 'Alerts and reliability' })
  await expect(status).toContainText('person at 60%')
  await expect(status).toContainText('Notifierdry-run')
  await expect(status).toContainText('2 (2 dry-run)')
  await expect(status).toContainText('Dry-run mode does not send external notifications')
})

test('shows system degradation and recovery from health polling', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const status = page.getByRole('region', { name: 'Alerts and reliability' })
  await expect(status).toContainText('System: ready')
  await page.evaluate(() => {
    const testWindow = window as typeof window & {
      __camzillaSetHealth: (status: string, camera: string, inference: string) => void
    }
    testWindow.__camzillaSetHealth('degraded', 'degraded', 'degraded')
  })
  await expect(status).toContainText('System: degraded', { timeout: 2_000 })
  await expect(status).toContainText('Camera streamdegraded')
  await page.evaluate(() => {
    const testWindow = window as typeof window & {
      __camzillaSetHealth: (status: string, camera: string, inference: string) => void
    }
    testWindow.__camzillaSetHealth('ready', 'ready', 'ready')
  })
  await expect(status).toContainText('System: ready', { timeout: 2_000 })
  await expect(status).toContainText('Camera streamready')
})
