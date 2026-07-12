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
  inference_ms: number
  detections: Detection[]
}

export type StreamDescriptor = { camera_name: string; webrtc_path: string; diagnostic_fallback: 'hls' | 'mjpeg' }
