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
