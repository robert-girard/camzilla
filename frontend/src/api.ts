import type { InferenceCapabilitiesResponse, StreamDescriptor } from './types'

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
