#!/usr/bin/env python3
import argparse
import base64
import hashlib
import os
import time
from datetime import datetime, timezone

import requests


WSSE = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-wssecurity-secext-1.0.xsd"
)
WSU = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-wssecurity-utility-1.0.xsd"
)


def load_env_file(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def xml_escape(value):
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def security_header(username, password):
    nonce = os.urandom(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + password.encode()).digest()
    ).decode()
    return f"""
    <s:Header>
      <wsse:Security s:mustUnderstand="1">
        <wsse:UsernameToken>
          <wsse:Username>{xml_escape(username)}</wsse:Username>
          <wsse:Password Type="{WSSE}#PasswordDigest">{digest}</wsse:Password>
          <wsse:Nonce EncodingType="{WSSE}#Base64Binary">{base64.b64encode(nonce).decode()}</wsse:Nonce>
          <wsu:Created>{created}</wsu:Created>
        </wsse:UsernameToken>
      </wsse:Security>
    </s:Header>"""


def envelope(username, password, body):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope
  xmlns:s="http://www.w3.org/2003/05/soap-envelope"
  xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
  xmlns:tt="http://www.onvif.org/ver10/schema"
  xmlns:wsse="{WSSE}"
  xmlns:wsu="{WSU}">
  {security_header(username, password)}
  <s:Body>{body}</s:Body>
</s:Envelope>"""


def continuous_move(url, username, password, profile, pan, tilt, zoom, seconds):
    timeout = f"PT{max(seconds, 1):.0f}S"
    body = f"""
    <tptz:ContinuousMove>
      <tptz:ProfileToken>{xml_escape(profile)}</tptz:ProfileToken>
      <tptz:Velocity>
        <tt:PanTilt x="{pan}" y="{tilt}"/>
        <tt:Zoom x="{zoom}"/>
      </tptz:Velocity>
      <tptz:Timeout>{timeout}</tptz:Timeout>
    </tptz:ContinuousMove>"""
    response = requests.post(
        url,
        data=envelope(username, password, body).encode(),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        timeout=10,
    )
    print(f"ContinuousMove HTTP {response.status_code}")
    print(response.text)
    response.raise_for_status()


def main():
    load_env_file()

    parser = argparse.ArgumentParser(description="Send a short ONVIF PTZ move.")
    parser.add_argument("direction", choices=["left", "right", "up", "down", "in", "out"])
    parser.add_argument("--host", default="192.168.0.41")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--user", default=os.getenv("ONVIF_USER", ""))
    parser.add_argument("--password", default=os.getenv("ONVIF_PASSWORD", ""))
    parser.add_argument("--profile", default="PROFILE_000")
    parser.add_argument("--speed", type=float, default=0.2)
    parser.add_argument("--seconds", type=int, default=1)
    args = parser.parse_args()

    if not args.user or not args.password:
        parser.error("ONVIF_USER and ONVIF_PASSWORD must be set in .env or passed as arguments")

    pan = tilt = zoom = 0.0
    if args.direction == "left":
        pan = -args.speed
    elif args.direction == "right":
        pan = args.speed
    elif args.direction == "up":
        tilt = args.speed
    elif args.direction == "down":
        tilt = -args.speed
    elif args.direction == "in":
        zoom = args.speed
    elif args.direction == "out":
        zoom = -args.speed

    url = f"http://{args.host}:{args.port}/onvif/PTZ"
    continuous_move(url, args.user, args.password, args.profile, pan, tilt, zoom, args.seconds)
    time.sleep(args.seconds)


if __name__ == "__main__":
    main()
