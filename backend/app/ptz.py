"""Optional bounded PTZ capability and ONVIF adapter."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol
from xml.sax.saxutils import escape

import httpx

from .config import Settings
from .contracts import PtzCapabilityResponse, PtzDirection, PtzMoveRequest

WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"


class PtzController(Protocol):
    async def continuous_move(self, request: PtzMoveRequest) -> None: ...


class PtzUnavailableError(Exception):
    pass


class PtzBusyError(Exception):
    pass


@dataclass(frozen=True)
class OnvifPtzConfig:
    endpoint: str
    username: str
    password: str
    profile: str


def direction_velocity(direction: PtzDirection, speed: float) -> tuple[float, float, float]:
    return {
        "left": (-speed, 0.0, 0.0),
        "right": (speed, 0.0, 0.0),
        "up": (0.0, speed, 0.0),
        "down": (0.0, -speed, 0.0),
        "in": (0.0, 0.0, speed),
        "out": (0.0, 0.0, -speed),
    }[direction]


def onvif_envelope(config: OnvifPtzConfig, request: PtzMoveRequest) -> bytes:
    nonce = os.urandom(16)
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + config.password.encode()).digest()
    ).decode()
    pan, tilt, zoom = direction_velocity(request.direction, request.speed)
    timeout = f"PT{request.duration_seconds:g}S"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
 xmlns:tt="http://www.onvif.org/ver10/schema" xmlns:wsse="{WSSE}" xmlns:wsu="{WSU}">
 <s:Header><wsse:Security s:mustUnderstand="1"><wsse:UsernameToken>
  <wsse:Username>{escape(config.username)}</wsse:Username>
  <wsse:Password Type="{WSSE}#PasswordDigest">{digest}</wsse:Password>
  <wsse:Nonce EncodingType="{WSSE}#Base64Binary">{base64.b64encode(nonce).decode()}</wsse:Nonce>
  <wsu:Created>{created}</wsu:Created>
 </wsse:UsernameToken></wsse:Security></s:Header>
 <s:Body><tptz:ContinuousMove>
  <tptz:ProfileToken>{escape(config.profile)}</tptz:ProfileToken>
  <tptz:Velocity><tt:PanTilt x="{pan:g}" y="{tilt:g}"/><tt:Zoom x="{zoom:g}"/></tptz:Velocity>
  <tptz:Timeout>{timeout}</tptz:Timeout>
 </tptz:ContinuousMove></s:Body>
</s:Envelope>""".encode()


class OnvifPtzController:
    def __init__(
        self,
        config: OnvifPtzConfig,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.config = config
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=5))

    async def continuous_move(self, request: PtzMoveRequest) -> None:
        async with self.client_factory() as client:
            response = await client.post(
                self.config.endpoint,
                content=onvif_envelope(self.config, request),
                headers={"content-type": "application/soap+xml; charset=utf-8"},
            )
        if response.status_code >= 400:
            raise RuntimeError("ONVIF PTZ command failed")


class PtzService:
    def __init__(
        self,
        capability: PtzCapabilityResponse,
        controller: PtzController | None,
        minimum_interval_seconds: float = 0.25,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.capability = capability
        self.controller = controller
        self.minimum_interval_seconds = minimum_interval_seconds
        self.clock = clock
        self._last_move_at: float | None = None
        self._lock = asyncio.Lock()

    async def move(self, request: PtzMoveRequest) -> None:
        if not self.capability.available or self.controller is None:
            raise PtzUnavailableError("PTZ is unavailable")
        now = self.clock()
        if self._lock.locked() or (
            self._last_move_at is not None
            and now - self._last_move_at < self.minimum_interval_seconds
        ):
            raise PtzBusyError("PTZ command is throttled")
        async with self._lock:
            self._last_move_at = now
            await self.controller.continuous_move(request)


def build_ptz_service(settings: Settings) -> PtzService:
    configured = settings.ptz_enabled and settings.ptz_configuration_complete
    available = configured and settings.ptz_verified
    if not settings.ptz_enabled:
        reason = "PTZ is not enabled"
    elif not settings.ptz_configuration_complete:
        reason = "PTZ configuration is incomplete"
    elif not settings.ptz_verified:
        reason = "PTZ is configured but not operation-verified"
    else:
        reason = None
    capability = PtzCapabilityResponse(
        camera_name=settings.camera_name,
        available=available,
        verified=available,
        unavailable_reason=reason,
        supports_continuous_move=available,
    )
    controller = None
    if available:
        controller = OnvifPtzController(
            OnvifPtzConfig(
                endpoint=f"http://{settings.onvif_host}:{settings.onvif_port}/onvif/PTZ",
                username=settings.onvif_user or "",
                password=settings.onvif_password or "",
                profile=settings.onvif_profile,
            )
        )
    return PtzService(capability, controller)
