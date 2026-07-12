import { useEffect, useRef, useState } from 'react'

import { isStale, sourceRect } from './overlay'
import type { DetectionMessage, StreamDescriptor } from './types'

type ConnectionState = 'loading' | 'connected' | 'degraded' | 'disconnected'
type VideoState = 'loading' | 'connected' | 'degraded'

const ttlSeconds = 2

function socketUrl(): string {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}/api/v1/detections`
}

export function App() {
  const [connection, setConnection] = useState<ConnectionState>('loading')
  const [stream, setStream] = useState<StreamDescriptor>()
  const [result, setResult] = useState<DetectionMessage>()
  const [videoState, setVideoState] = useState<VideoState>('loading')
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    let retry: number | undefined
    let socket: WebSocket | undefined
    let peer: RTCPeerConnection | undefined
    let stopped = false

    const connectVideo = async (descriptor: StreamDescriptor) => {
      try {
        peer = new RTCPeerConnection()
        peer.addTransceiver('video', { direction: 'recvonly' })
        peer.ontrack = ({ streams }) => {
          if (videoRef.current) videoRef.current.srcObject = streams[0]
          setVideoState('connected')
        }
        const offer = await peer.createOffer()
        await peer.setLocalDescription(offer)
        await new Promise<void>((resolve) => {
          if (peer?.iceGatheringState === 'complete') return resolve()
          peer?.addEventListener('icegatheringstatechange', () => {
            if (peer?.iceGatheringState === 'complete') resolve()
          }, { once: true })
          window.setTimeout(resolve, 1_000)
        })
        const answer = await fetch(descriptor.webrtc_path, {
          method: 'POST',
          headers: { 'content-type': 'application/sdp' },
          body: peer.localDescription?.sdp,
        })
        if (!answer.ok) throw new Error('WHEP offer rejected')
        await peer.setRemoteDescription({ type: 'answer', sdp: await answer.text() })
      } catch {
        if (!stopped) setVideoState('degraded')
      }
    }

    void fetch('/api/v1/stream')
      .then((response) => response.ok ? response.json() as Promise<StreamDescriptor> : Promise.reject())
      .then((descriptor) => { setStream(descriptor); return connectVideo(descriptor) })
      .catch(() => setVideoState('degraded'))

    const connectMetadata = () => {
      socket = new WebSocket(socketUrl())
      socket.onopen = () => setConnection('connected')
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as DetectionMessage | { type: 'heartbeat' }
        if ('version' in message) setResult(message)
      }
      socket.onclose = () => {
        if (!stopped) {
          setConnection('disconnected')
          retry = window.setTimeout(connectMetadata, 1_000)
        }
      }
      socket.onerror = () => socket?.close()
    }
    connectMetadata()
    return () => {
      stopped = true
      socket?.close()
      peer?.close()
      if (retry) clearTimeout(retry)
    }
  }, [])

  const stale = result ? isStale(result.result_timestamp, ttlSeconds) : false
  const visible = result && !stale ? result.detections : []
  const age = result ? Math.max(0, (Date.now() - Date.parse(result.result_timestamp)) / 1_000) : undefined
  const sourceWidth = result?.source_width ?? 1
  const sourceHeight = result?.source_height ?? 1

  return (
    <main>
      <h1>Camzilla</h1>
      <p role="status" data-state={connection}>Metadata connection: {connection}</p>
      <section aria-label="Live camera" className="viewer">
        <video ref={videoRef} className="video" aria-label="Live camera video" controls muted playsInline />
        <svg className="overlay" aria-label="Detection overlay" viewBox={`0 0 ${sourceWidth} ${sourceHeight}`} preserveAspectRatio="xMidYMid meet">
          {visible.map((detection, index) => {
            const box = sourceRect(detection.box, sourceWidth, sourceHeight)
            return <g key={`${result?.sequence ?? 'none'}-${index}`}>
              <rect {...box} className="box" />
              <text x={box.x} y={Math.max(20, box.y - 8)} className="label">
                {detection.class_name} {Math.round(detection.confidence * 100)}%
              </text>
            </g>
          })}
        </svg>
        {videoState !== 'connected' && (
          <p className="video-placeholder">
            {videoState === 'degraded'
              ? <><span>Video connection is unavailable. </span><a href="/api/v1/diagnostics/hls/stream.m3u8">Open HLS diagnostic fallback</a></>
              : `Connecting to ${stream?.camera_name ?? 'camera'}…`}
          </p>
        )}
      </section>
      <aside aria-label="Diagnostics" className="diagnostics">
        <span>Video: {videoState}</span>
        <span>Metadata: {stale ? 'stale' : connection}</span>
        <span>Backend/model: {result ? `${result.backend_id}/${result.model_id}` : '—'}</span>
        <span>Inference: {result ? `${result.inference_ms.toFixed(1)} ms` : '—'}</span>
        <span>Inference FPS: {result ? result.inference_fps.toFixed(1) : '—'}</span>
        <span>Result age: {age === undefined ? '—' : `${age.toFixed(1)} s`}</span>
      </aside>
    </main>
  )
}
