export type Detection = {
  class_name: string
  confidence: number
  box: { x: number; y: number; width: number; height: number }
}

export type DetectionMessage = {
  version: 'v1'
  sequence: number
  capture_timestamp: string
  result_timestamp: string
  source_width: number
  source_height: number
  backend_id: string
  model_id: string
  target: InferenceTarget
  device: string
  inference_ms: number
  inference_fps: number
  detections: Detection[]
}

export type StreamDescriptor = { camera_name: string; webrtc_path: string; diagnostic_fallback: 'hls' | 'mjpeg' }

export type PtzDirection = 'left' | 'right' | 'up' | 'down' | 'in' | 'out'

export type PtzCapability = {
  camera_name: string
  available: boolean
  verified: boolean
  unavailable_reason?: string
  supports_continuous_move: boolean
  supports_stop: boolean
  max_speed: number
  max_duration_seconds: number
}

export type PtzMoveResponse = {
  status: 'accepted'
  direction: PtzDirection
  duration_seconds: number
}

export type AlertRule = {
  id: string
  camera_name: string
  target_classes: string[]
  confidence_threshold: number
  debounce_seconds: number
  enabled: boolean
}

export type AlertRuntimeStatus = {
  rule: AlertRule
  requested_notifier: 'dry-run' | 'discord'
  effective_notifier: 'dry-run' | 'discord'
  external_delivery_configured: boolean
  configuration_reason?: string
  queued_events: number
  delivered_events: number
  dry_run_events: number
  failed_events: number
  dropped_events: number
  suppressed_events: number
  stream_state: 'connecting' | 'ready' | 'degraded'
  stream_down_events: number
  stream_recovery_events: number
  last_event_at?: string
  last_error?: string
}

export type HealthStatus = {
  status: 'ready' | 'degraded'
  camera: { configured: boolean; state: string }
  inference: { state: 'ready' | 'degraded'; last_error?: string }
  alerts: AlertRuntimeStatus
  bridge: { state: string }
}

export type ZonePoint = { x: number; y: number }

export type CameraConfiguration = {
  id: string
  name: string
  enabled: boolean
  capabilities: Record<string, unknown>
  allowed_categories: string[]
  catalog_revision: string
  version: number
}

export type AlertRuleConfiguration = {
  id: string
  camera_id: string
  enabled: boolean
  target_categories: string[]
  confidence_threshold: number
  debounce_seconds: number
  schedule_start?: string
  schedule_end?: string
  zone?: { points: ZonePoint[] }
  version: number
}

export type GlobalConfiguration = {
  version: number
  active_capability_id: string
  cameras: CameraConfiguration[]
  alert_rules: AlertRuleConfiguration[]
}

export type AlertRuleUpdate = {
  expected_config_version: number
  confidence_threshold: number
  debounce_seconds: number
  schedule_start?: string
  schedule_end?: string
  zone?: { points: ZonePoint[] }
  target_categories: string[]
}

export type EventSummary = {
  id: string
  camera_id: string
  rule_id?: string
  event_type: string
  triggered_at: string
  categories: string[]
  has_snapshot: boolean
  has_clip: boolean
}

export type EventPage = {
  items: EventSummary[]
  page: number
  page_size: number
  total: number
  pages: number
}

export type RecordingResponse = { id: string; status: 'recording' | 'processing' }

export type InferenceTarget = 'cpu' | 'gpu' | 'npu' | 'tpu'

export type InferenceCapability = {
  id: string
  backend_id: string
  model_id: string
  target: InferenceTarget
  device: string
  compatible: boolean
  available: boolean
  unavailable_reason?: string
  active: boolean
}

export type InferenceSelection = {
  capability_id: string
  backend_id: string
  model_id: string
  target: InferenceTarget
  device: string
}

export type InferenceCapabilitiesResponse = {
  active: InferenceSelection
  transition_state: 'ready' | 'switching' | 'degraded'
  transition_error?: string
  runtime_only: boolean
  capabilities: InferenceCapability[]
}
