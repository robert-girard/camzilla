import { expect, test, type Page } from '@playwright/test'

type MockOptions = {
  videoFailure?: boolean
  selectionFailure?: boolean
  switchDelayMs?: number
  ptzAvailable?: boolean
  ptzFailure?: boolean
  ruleConflict?: boolean
  incompatibleSwitch?: boolean
}

function detectionMessage() {
  return {
    version: 'v1', sequence: 7, capture_timestamp: new Date().toISOString(),
    result_timestamp: new Date().toISOString(), source_width: 1280, source_height: 720,
    backend_id: 'fake', model_id: 'yolov8n', target: 'cpu', device: 'synthetic', inference_ms: 4.5, inference_fps: 5,
    detections: [{ class_name: 'person', semantic_id: 'coco:person', native_class_id: 0, confidence: 0.91, box: { x: 0.25, y: 0.2, width: 0.5, height: 0.5 } }],
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
  await page.route('**/api/v1/events/*/clip', (route) => route.fulfill({
    status: 200, contentType: 'video/mp4', body: 'fixture clip',
  }))
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
    Object.defineProperty(window, '__camzillaLastRuleUpdate', { value: null, writable: true })
    const catalog = {
      revision: 'coco-person-car-dog-v1', backend_id: 'fake', model_id: 'yolov8n',
      categories: [
        { semantic_id: 'coco:person', native_class_id: 0, display_label: 'person', description: 'People visible in the camera frame.' },
        { semantic_id: 'coco:car', native_class_id: 1, display_label: 'car', description: 'Passenger cars recognized by the active model.' },
        { semantic_id: 'coco:dog', native_class_id: 2, display_label: 'dog', description: 'Dogs recognized by the active model.' },
      ],
    }
    const defaultConfiguration = {
      version: 3, active_capability_id: 'fake:yolov8n:cpu',
      cameras: [{
        id: 'front-door', name: 'front-door', enabled: true, capabilities: { runtime_state: 'synthetic' },
        allowed_categories: ['coco:person'], catalog_revision: catalog.revision, version: 1,
      }, {
        id: 'side-door', name: 'side-door', enabled: true, capabilities: { runtime_state: 'degraded' },
        allowed_categories: ['coco:person'], catalog_revision: catalog.revision, version: 1,
      }],
      alert_rules: [{
        id: 'person-detected', camera_id: 'front-door', enabled: true,
        target_categories: ['coco:person'], confidence_threshold: 0.6, debounce_seconds: 300,
        schedule_start: null, schedule_end: null, zone: null, version: 1,
      }],
    }
    const configuration = JSON.parse(
      sessionStorage.getItem('camzilla-test-configuration') ?? JSON.stringify(defaultConfiguration),
    ) as typeof defaultConfiguration
    const persistConfiguration = () => sessionStorage.setItem(
      'camzilla-test-configuration', JSON.stringify(configuration),
    )
    let events = [{
      id: '11111111-1111-4111-8111-111111111111', camera_id: 'front-door',
      rule_id: 'person-detected', event_type: 'detection',
      triggered_at: new Date().toISOString(), categories: ['coco:person'], catalog_revision: catalog.revision,
      has_snapshot: false, has_clip: true,
    }]
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
      if (url.includes('/api/v1/inference/compatibility/')) {
        const capabilityId = decodeURIComponent(url.split('/').at(-1) ?? '')
        const incompatible = Boolean(settings.incompatibleSwitch)
        return new Response(JSON.stringify({
          capability_id: capabilityId, catalog_revision: incompatible ? 'coco-person-v1' : 'coco80-v1',
          compatible: !incompatible,
          retained_category_ids: ['coco:person'],
          missing_category_ids: incompatible ? ['coco:car'] : [],
          affected_camera_ids: incompatible ? ['front-door'] : [],
          affected_rule_ids: incompatible ? ['person-detected'] : [],
          available_category_ids: incompatible ? ['coco:person'] : ['coco:person', 'coco:car', 'coco:dog'],
        }), { headers: { 'content-type': 'application/json' } })
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
            id: 'person-detected', camera_name: 'front-door', target_classes: ['coco:person'],
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
      if (url.includes('/api/v1/alert-rules/')) {
        if (settings.ruleConflict) {
          return new Response(JSON.stringify({ detail: 'configuration version conflict' }), {
            status: 409, headers: { 'content-type': 'application/json' },
          })
        }
        const update = JSON.parse(String(init?.body))
        const testWindow = window as typeof window & { __camzillaLastRuleUpdate: unknown }
        testWindow.__camzillaLastRuleUpdate = update
        configuration.version += 1
        configuration.alert_rules[0] = {
          ...configuration.alert_rules[0], ...update,
          zone: update.zone ?? null,
          schedule_start: update.schedule_start ?? null,
          schedule_end: update.schedule_end ?? null,
          version: configuration.alert_rules[0].version + 1,
        }
        persistConfiguration()
        return new Response(JSON.stringify(configuration), { headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/api/v1/config')) {
        return new Response(JSON.stringify(configuration), { headers: { 'content-type': 'application/json' } })
      }
      if (/\/api\/v1\/cameras\/[^/]+\/categories/.test(url)) {
        const cameraId = decodeURIComponent(url.split('/').at(-2) ?? '')
        const camera = configuration.cameras.find((item) => item.id === cameraId)
        if (!camera) return new Response(JSON.stringify({ detail: 'camera not found' }), { status: 404 })
        if (init?.method === 'PUT') {
          const update = JSON.parse(String(init.body)) as { category_ids: string[]; catalog_revision: string }
          camera.allowed_categories = update.category_ids
          camera.catalog_revision = update.catalog_revision
          camera.version += 1
          configuration.version += 1
          persistConfiguration()
          if (cameraId === 'front-door') {
            const detections = update.category_ids.map((categoryId, index) => ({
              class_name: categoryId === 'coco:car' ? 'car' : categoryId === 'coco:dog' ? 'dog' : 'person',
              semantic_id: categoryId,
              native_class_id: index,
              confidence: categoryId === 'coco:car' ? 0.87 : categoryId === 'coco:dog' ? 0.82 : 0.91,
              box: { x: 0.1 + index * 0.25, y: 0.2, width: 0.2, height: 0.4 },
            }))
            sockets.at(-1)?.onmessage?.(new MessageEvent('message', { data: JSON.stringify({
              ...message, detections, result_timestamp: new Date().toISOString(),
            }) }))
          }
        }
        return new Response(JSON.stringify({
          camera_id: cameraId, config_version: configuration.version,
          catalog, selected_category_ids: camera.allowed_categories,
        }), { headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/api/v1/backup/validate')) {
        return new Response(JSON.stringify({ valid: true, errors: [] }), {
          headers: { 'content-type': 'application/json' },
        })
      }
      if (url.endsWith('/api/v1/backup')) {
        configuration.version += 1
        persistConfiguration()
        return new Response(JSON.stringify(configuration), { headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/api/v1/cameras/front-door/recordings')) {
        return new Response(JSON.stringify({
          id: '22222222-2222-4222-8222-222222222222', status: 'recording',
        }), { status: 201, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/api/v1/recordings/')) {
        return new Response(JSON.stringify({
          id: '22222222-2222-4222-8222-222222222222', status: 'processing',
        }), { headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/api/v1/events/')) {
        if (url.endsWith('/clip')) return new Response('fixture clip', { headers: { 'content-type': 'video/mp4' } })
        const eventId = url.split('/').at(-1)
        events = events.filter((item) => item.id !== eventId)
        return new Response(null, { status: 204 })
      }
      if (url.includes('/api/v1/events?')) {
        const parsed = new URL(url, location.origin)
        const type = parsed.searchParams.get('event_type')
        const selected = events.filter((item) => !type || item.event_type === type)
        return new Response(JSON.stringify({
          items: selected, page: 1, page_size: 10, total: selected.length,
          pages: selected.length ? 1 : 0,
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

test('previews affected cameras and rules before an incompatible model switch', async ({ page }) => {
  await installMocks(page, { incompatibleSwitch: true })
  await page.goto('/')
  await page.getByRole('radio', { name: 'yolo11s', exact: true }).check()
  const warning = page.getByRole('alert').filter({ hasText: 'Resolve category conflicts' })
  await expect(warning).toContainText('Missing: coco:car')
  await expect(warning).toContainText('Affected cameras: front-door')
  await expect(warning).toContainText('Affected rules: person-detected')
  await expect(page.getByRole('button', { name: 'Apply inference selection' })).toBeDisabled()
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

test('filters and deletes persistent alert history', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const history = page.getByRole('region', { name: 'Configuration and alert history' })
  await expect(history).toContainText('detection')
  await expect(history.getByLabel('Clip from front-door')).toHaveAttribute(
    'src', '/api/v1/events/11111111-1111-4111-8111-111111111111/clip',
  )
  await history.getByLabel('Event type').selectOption('stream-down')
  await expect(history).toContainText('No alert events match this filter.')
  await history.getByLabel('Event type').selectOption('')
  await history.getByRole('button', { name: 'Delete' }).click()
  await expect(history).toContainText('No alert events match this filter.')
})

test('starts and stops one manual recording from the camera card', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const history = page.getByRole('region', { name: 'Configuration and alert history' })
  await history.getByRole('button', { name: 'Start recording' }).click()
  await expect(history.getByText('Manual recording started')).toBeVisible()
  await history.getByRole('button', { name: 'Stop recording' }).click()
  await expect(history.getByText('Recording is processing')).toBeVisible()
})

test('shows multiple camera runtime states without duplicating active controls', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const cameras = page.getByLabel('Configured cameras')
  await expect(cameras).toContainText('front-doorsynthetic')
  await expect(cameras).toContainText('side-doordegraded')
  await expect(cameras.getByRole('button', { name: 'Start recording' })).toHaveCount(1)
})

test('selects non-person categories, filters overlays, and persists multi-category rules', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const history = page.getByRole('region', { name: 'Configuration and alert history' })
  const cameraCategories = history.getByRole('group', { name: 'Detection categories for front-door' })
  await expect(cameraCategories).toContainText('1 active of 3 available')
  await cameraCategories.getByLabel('Search categories').fill('car')
  await expect(cameraCategories.getByText('dog', { exact: true })).toBeHidden()
  await cameraCategories.getByRole('checkbox', { name: /car/ }).check()
  await expect(cameraCategories).toContainText('Selection preview: person, car')
  await history.getByRole('button', { name: 'Save camera categories' }).first().click()
  await expect(history.getByText('Categories saved for front-door')).toBeVisible()

  const alertCategories = history.getByRole('group', { name: 'Alert target categories' })
  await alertCategories.getByRole('checkbox', { name: /car/ }).check()
  await alertCategories.getByRole('checkbox', { name: /person/ }).uncheck()
  await history.getByRole('button', { name: 'Save rule' }).click()
  await expect(history.getByText('Rule saved')).toBeVisible()

  await cameraCategories.getByRole('button', { name: 'Clear' }).click()
  await cameraCategories.getByRole('checkbox', { name: /car/ }).check()
  await history.getByRole('button', { name: 'Save camera categories' }).first().click()
  await expect(page.getByText('car 87%')).toBeVisible()
  await expect(page.getByText('person 91%')).toBeHidden()
  const update = await page.evaluate(() => {
    const testWindow = window as typeof window & {
      __camzillaLastRuleUpdate: { target_categories: string[] }
    }
    return testWindow.__camzillaLastRuleUpdate
  })
  expect(update.target_categories).toEqual(['coco:car'])
  await page.reload()
  const restoredCameraCategories = page.getByRole('region', { name: 'Configuration and alert history' })
    .getByRole('group', { name: 'Detection categories for front-door' })
  await restoredCameraCategories.getByLabel('Search categories').fill('car')
  await expect(restoredCameraCategories.getByRole('checkbox', { name: /car/ })).toBeChecked()
})

test('validates a secret-free backup before restoring configuration', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const history = page.getByRole('region', { name: 'Configuration and alert history' })
  await expect(history.getByRole('link', { name: 'Export configuration' })).toHaveAttribute(
    'href', '/api/v1/backup',
  )
  await history.getByLabel('Backup file').setInputFiles({
    name: 'backup.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({
      schema_version: '1', exported_at: new Date().toISOString(), secrets_included: false,
      active_capability_id: 'fake:yolov8n:cpu',
      cameras: [{
        id: 'front-door', name: 'front-door', enabled: true,
        allowed_categories: ['coco:person'], catalog_revision: 'coco-person-car-dog-v1',
      }],
      alert_rules: [],
    })),
  })
  await expect(history.getByText('Backup is valid and ready to restore')).toBeVisible()
  await history.getByRole('button', { name: 'Restore validated backup' }).click()
  await expect(history.getByText('Configuration restored')).toBeVisible()
})

test('edits rule values and draws a normalized zone', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')
  const history = page.getByRole('region', { name: 'Configuration and alert history' })
  await history.getByLabel('Confidence (%)').fill('75')
  await history.getByLabel('Debounce (seconds)').fill('60')
  await history.getByLabel('Enable schedule').check()
  const zone = history.getByLabel('Detection zone editor')
  await zone.click({ position: { x: 40, y: 30 } })
  await zone.click({ position: { x: 250, y: 30 } })
  await zone.click({ position: { x: 150, y: 130 } })
  await history.getByRole('button', { name: 'Save rule' }).click()
  await expect(history.getByText('Rule saved')).toBeVisible()
  const update = await page.evaluate(() => {
    const testWindow = window as typeof window & { __camzillaLastRuleUpdate: { zone: { points: unknown[] }; confidence_threshold: number } }
    return testWindow.__camzillaLastRuleUpdate
  })
  expect(update.confidence_threshold).toBe(0.75)
  expect(update.zone.points).toHaveLength(3)
})

test('validates incomplete zones and reports optimistic conflicts', async ({ page }) => {
  await installMocks(page, { ruleConflict: true })
  await page.goto('/')
  const history = page.getByRole('region', { name: 'Configuration and alert history' })
  await history.getByLabel('Detection zone editor').click({ position: { x: 40, y: 30 } })
  await history.getByRole('button', { name: 'Save rule' }).click()
  await expect(history.getByRole('alert')).toHaveText('A zone needs at least three points or must be cleared.')
  await history.getByRole('button', { name: 'Clear zone' }).click()
  await history.getByRole('button', { name: 'Save rule' }).click()
  await expect(history.getByRole('alert')).toHaveText('configuration version conflict')
})
