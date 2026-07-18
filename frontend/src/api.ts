import type { StreamDescriptor } from './types'

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
