import type {
  InferenceCapabilitiesResponse,
  AlertRuntimeStatus,
  AlertRuleUpdate,
  EventPage,
  GlobalConfiguration,
  RecordingResponse,
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

export async function getConfiguration(): Promise<GlobalConfiguration> {
  const response = await fetch('/api/v1/config')
  if (!response.ok) throw await responseError(response, 'configuration unavailable')
  return response.json() as Promise<GlobalConfiguration>
}

export async function updateAlertRule(ruleId: string, update: AlertRuleUpdate): Promise<GlobalConfiguration> {
  const response = await fetch(`/api/v1/alert-rules/${encodeURIComponent(ruleId)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(update),
  })
  if (!response.ok) throw await responseError(response, 'rule update failed')
  return response.json() as Promise<GlobalConfiguration>
}

export async function getEvents(options: {
  page: number; eventType: string; sort: 'asc' | 'desc'
}): Promise<EventPage> {
  const params = new URLSearchParams({
    page: String(options.page), page_size: '10', sort: options.sort,
  })
  if (options.eventType) params.set('event_type', options.eventType)
  const response = await fetch(`/api/v1/events?${params}`)
  if (!response.ok) throw await responseError(response, 'event history unavailable')
  return response.json() as Promise<EventPage>
}

export async function deleteEvent(eventId: string): Promise<void> {
  const response = await fetch(`/api/v1/events/${encodeURIComponent(eventId)}`, { method: 'DELETE' })
  if (!response.ok) throw await responseError(response, 'event deletion failed')
}

export async function startRecording(cameraId: string): Promise<RecordingResponse> {
  const response = await fetch(`/api/v1/cameras/${encodeURIComponent(cameraId)}/recordings`, {
    method: 'POST',
  })
  if (!response.ok) throw await responseError(response, 'recording could not start')
  return response.json() as Promise<RecordingResponse>
}

export async function stopRecording(recordingId: string): Promise<RecordingResponse> {
  const response = await fetch(`/api/v1/recordings/${encodeURIComponent(recordingId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw await responseError(response, 'recording could not stop')
  return response.json() as Promise<RecordingResponse>
}
