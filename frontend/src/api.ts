import type {
  InferenceCapabilitiesResponse,
  AlertRuntimeStatus,
  HealthStatus,
  PtzCapability,
  PtzDirection,
  PtzMoveResponse,
  StreamDescriptor,
} from './types'

async function responseError(response: Response, fallback: string): Promise<Error> {
  try {
    const payload = await response.json() as { detail?: string }
    return new Error(payload.detail ?? fallback)
  } catch {
    return new Error(fallback)
  }
}

export async function getStreamDescriptor(): Promise<StreamDescriptor> {
  const response = await fetch('/api/v1/stream')
  if (!response.ok) throw new Error('stream descriptor unavailable')
  return response.json() as Promise<StreamDescriptor>
}

export async function exchangeWebRtcOffer(path: string, offer: string): Promise<string> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/sdp' },
    body: offer,
  })
  if (!response.ok) throw new Error('WHEP offer rejected')
  return response.text()
}

export async function getInferenceCapabilities(): Promise<InferenceCapabilitiesResponse> {
  const response = await fetch('/api/v1/inference')
  if (!response.ok) throw await responseError(response, 'inference capabilities unavailable')
  return response.json() as Promise<InferenceCapabilitiesResponse>
}

export async function applyInferenceSelection(capabilityId: string): Promise<InferenceCapabilitiesResponse> {
  const response = await fetch('/api/v1/inference/selection', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ capability_id: capabilityId }),
  })
  if (!response.ok) throw await responseError(response, 'inference switch failed')
  return response.json() as Promise<InferenceCapabilitiesResponse>
}

export async function getPtzCapability(cameraName: string): Promise<PtzCapability> {
  const response = await fetch(`/api/v1/cameras/${encodeURIComponent(cameraName)}/capabilities/ptz`)
  if (!response.ok) throw await responseError(response, 'PTZ capability unavailable')
  return response.json() as Promise<PtzCapability>
}

export async function movePtz(cameraName: string, direction: PtzDirection): Promise<PtzMoveResponse> {
  const response = await fetch(`/api/v1/cameras/${encodeURIComponent(cameraName)}/ptz`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ direction, speed: 0.15, duration_seconds: 1 }),
  })
  if (!response.ok) throw await responseError(response, 'PTZ command failed')
  return response.json() as Promise<PtzMoveResponse>
}

export async function getAlertStatus(): Promise<AlertRuntimeStatus> {
  const response = await fetch('/api/v1/alerts/status')
  if (!response.ok) throw await responseError(response, 'alert status unavailable')
  return response.json() as Promise<AlertRuntimeStatus>
}

export async function getHealthStatus(): Promise<HealthStatus> {
  const response = await fetch('/health/ready')
  if (!response.ok) throw await responseError(response, 'system health unavailable')
  return response.json() as Promise<HealthStatus>
}
