import { useEffect, useRef, useState } from 'react'

import { exchangeWebRtcOffer, getStreamDescriptor } from './api'
import { AlertStatus } from './AlertStatus'
import { HistoryAndRules } from './HistoryAndRules'
import { InferenceSelector } from './InferenceSelector'
import { isStale, sourceRect } from './overlay'
import { PtzControls } from './PtzControls'
import type { DetectionMessage, InferenceSelection, StreamDescriptor } from './types'

type ConnectionState = 'loading' | 'connected' | 'degraded' | 'disconnected'
type VideoState = 'loading' | 'connected' | 'degraded'

const ttlSeconds = 2

function socketUrl(cameraId: string): string {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}/api/v1/detections?camera_id=${encodeURIComponent(cameraId)}`
}

export function App() {
  const [connection, setConnection] = useState<ConnectionState>('loading')
  const [stream, setStream] = useState<StreamDescriptor>()
  const [result, setResult] = useState<DetectionMessage>()
  const [videoState, setVideoState] = useState<VideoState>('loading')
  const [now, setNow] = useState(Date.now())
  const videoRef = useRef<HTMLVideoElement>(null)
  const viewerRef = useRef<HTMLElement>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [confirmedInference, setConfirmedInference] = useState<InferenceSelection>()

  useEffect(() => {
    let metadataRetry: number | undefined
    let videoRetry: number | undefined
    let descriptorRetry: number | undefined
    let socket: WebSocket | undefined
    let peer: RTCPeerConnection | undefined
    let stopped = false

    const scheduleVideoRetry = (descriptor: StreamDescriptor) => {
      if (stopped || videoRetry) return
      setVideoState('degraded')
      peer?.close()
      videoRetry = window.setTimeout(() => {
        videoRetry = undefined
        void connectVideo(descriptor)
      }, 1_000)
    }

    const connectVideo = async (descriptor: StreamDescriptor) => {
      try {
        peer?.close()
        peer = new RTCPeerConnection()
        peer.addTransceiver('video', { direction: 'recvonly' })
        peer.ontrack = ({ streams }) => {
          if (videoRef.current) videoRef.current.srcObject = streams[0]
          setVideoState('connected')
        }
        peer.onconnectionstatechange = () => {
          if (peer?.connectionState === 'connected') setVideoState('connected')
          if (peer?.connectionState === 'disconnected' || peer?.connectionState === 'failed') {
            scheduleVideoRetry(descriptor)
          }
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
        const answer = await exchangeWebRtcOffer(descriptor.webrtc_path, peer.localDescription?.sdp ?? '')
        await peer.setRemoteDescription({ type: 'answer', sdp: answer })
      } catch {
        scheduleVideoRetry(descriptor)
      }
    }

    const loadVideo = () => {
      void getStreamDescriptor()
        .then((descriptor) => {
          setStream(descriptor)
          connectMetadata(descriptor.camera_name)
          return connectVideo(descriptor)
        })
        .catch(() => {
          if (!stopped) {
            setVideoState('degraded')
            descriptorRetry = window.setTimeout(loadVideo, 1_000)
          }
        })
    }
    const connectMetadata = (cameraId: string) => {
      socket = new WebSocket(socketUrl(cameraId))
      socket.onopen = () => setConnection('connected')
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as DetectionMessage | { type: 'heartbeat' | 'reset' }
        if ('version' in message) {
          if (message.camera_id === cameraId) setResult(message)
        } else if (message.type === 'reset') setResult(undefined)
      }
      socket.onclose = () => {
        if (!stopped) {
          setConnection((previous) => previous === 'connected' ? 'degraded' : 'disconnected')
          metadataRetry = window.setTimeout(() => connectMetadata(cameraId), 1_000)
        }
      }
      socket.onerror = () => socket?.close()
    }
    loadVideo()
    return () => {
      stopped = true
      socket?.close()
      peer?.close()
      if (metadataRetry) clearTimeout(metadataRetry)
      if (videoRetry) clearTimeout(videoRetry)
      if (descriptorRetry) clearTimeout(descriptorRetry)
    }
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    const updateFullscreen = () => setFullscreen(document.fullscreenElement === viewerRef.current)
    document.addEventListener('fullscreenchange', updateFullscreen)
    return () => document.removeEventListener('fullscreenchange', updateFullscreen)
  }, [])

  const toggleFullscreen = async () => {
    if (document.fullscreenElement === viewerRef.current) await document.exitFullscreen()
    else await viewerRef.current?.requestFullscreen()
  }

  const stale = result ? isStale(result.result_timestamp, ttlSeconds, now) : false
  const visible = result && !stale ? result.detections : []
  const age = result ? Math.max(0, (Date.now() - Date.parse(result.result_timestamp)) / 1_000) : undefined
  const sourceWidth = result?.source_width ?? 1
  const sourceHeight = result?.source_height ?? 1

  return (
    <main>
      <h1>Camzilla</h1>
      <p role="status" data-state={connection}>Metadata connection: {connection}</p>
      <section ref={viewerRef} aria-label="Live camera" className="viewer">
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
          <p className="video-placeholder" role="status">
            {videoState === 'degraded'
              ? <><span>Video connection is unavailable. </span><a href="/api/v1/diagnostics/hls/stream.m3u8">Open HLS diagnostic fallback</a></>
              : `Connecting to ${stream?.camera_name ?? 'camera'}…`}
          </p>
        )}
        <button className="fullscreen" type="button" onClick={() => void toggleFullscreen()}>
          {fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
        </button>
      </section>
      <aside aria-label="Diagnostics" className="diagnostics">
        <span>Video: {videoState}</span>
        <span>Metadata: {stale ? 'stale' : connection}</span>
        <span>Backend/model: {result
          ? `${result.backend_id}/${result.model_id}`
          : confirmedInference ? `${confirmedInference.backend_id}/${confirmedInference.model_id}` : '—'}</span>
        <span>Target/device: {result
          ? `${result.target}/${result.device}`
          : confirmedInference ? `${confirmedInference.target}/${confirmedInference.device}` : '—'}</span>
        <span>Inference: {result ? `${result.inference_ms.toFixed(1)} ms` : '—'}</span>
        <span>Inference FPS: {result ? result.inference_fps.toFixed(1) : '—'}</span>
        <span>Result age: {age === undefined ? '—' : `${age.toFixed(1)} s`}</span>
      </aside>
      {stream && <PtzControls cameraName={stream.camera_name} />}
      <AlertStatus />
      <InferenceSelector
        onResetDetections={() => setResult(undefined)}
        onSelectionChange={setConfirmedInference}
      />
      <HistoryAndRules />
    </main>
  )
}
