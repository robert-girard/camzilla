import { useEffect, useState } from 'react'

import { isStale } from './overlay'
import type { DetectionMessage, StreamDescriptor } from './types'

type ConnectionState = 'loading' | 'connected' | 'degraded' | 'disconnected'

const ttlSeconds = 2

function socketUrl(): string {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}/api/v1/detections`
}

export function App() {
  const [connection, setConnection] = useState<ConnectionState>('loading')
  const [stream, setStream] = useState<StreamDescriptor>()
  const [result, setResult] = useState<DetectionMessage>()

  useEffect(() => {
    let retry: number | undefined
    let socket: WebSocket | undefined
    let stopped = false

    void fetch('/api/v1/stream')
      .then((response) => response.ok ? response.json() as Promise<StreamDescriptor> : Promise.reject())
      .then(setStream)
      .catch(() => setConnection('degraded'))

    const connect = () => {
      socket = new WebSocket(socketUrl())
      socket.onopen = () => setConnection('connected')
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as DetectionMessage | { type: 'heartbeat' }
        if ('version' in message) setResult(message)
      }
      socket.onclose = () => {
        if (!stopped) {
          setConnection('disconnected')
          retry = window.setTimeout(connect, 1_000)
        }
      }
      socket.onerror = () => socket?.close()
    }
    connect()
    return () => { stopped = true; socket?.close(); if (retry) clearTimeout(retry) }
  }, [])

  const stale = result ? isStale(result.result_timestamp, ttlSeconds) : false
  const visible = result && !stale ? result.detections : []
  const age = result ? Math.max(0, (Date.now() - Date.parse(result.result_timestamp)) / 1_000) : undefined

  return (
    <main>
      <h1>Camzilla</h1>
      <p role="status" data-state={connection}>Metadata connection: {connection}</p>
      <section aria-label="Live camera" className="viewer">
        <video className="video" aria-label="Live camera video" controls muted playsInline />
        <svg className="overlay" aria-label="Detection overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
          {visible.map((detection, index) => (
            <g key={`${result?.sequence ?? 'none'}-${index}`}>
              <rect {...detection.box} className="box" />
              <text x={detection.box.x} y={Math.max(0.03, detection.box.y - 0.01)} className="label">
                {detection.class_name} {Math.round(detection.confidence * 100)}%
              </text>
            </g>
          ))}
        </svg>
        <p className="video-placeholder">WebRTC video connects through the sanitized stream descriptor{stream ? ` for ${stream.camera_name}` : ''}.</p>
      </section>
      <aside aria-label="Diagnostics" className="diagnostics">
        <span>Video: awaiting WebRTC</span>
        <span>Metadata: {stale ? 'stale' : connection}</span>
        <span>Backend/model: {result ? `${result.backend_id}/${result.model_id}` : '—'}</span>
        <span>Inference: {result ? `${result.inference_ms.toFixed(1)} ms` : '—'}</span>
        <span>Result age: {age === undefined ? '—' : `${age.toFixed(1)} s`}</span>
      </aside>
    </main>
  )
}
