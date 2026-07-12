#!/usr/bin/env python3
import argparse
import base64
import hashlib
import os
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests


SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
MEDIA = "http://www.onvif.org/ver10/media/wsdl"
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


def wait_for_port(host, port, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock = socket.socket()
        sock.settimeout(1)
        try:
            if sock.connect_ex((host, port)) == 0:
                return True
        finally:
            sock.close()
        time.sleep(1)
    return False


def ws_security_header(username, password):
    if not username:
        return ""

    nonce = os.urandom(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + password.encode()).digest()
    ).decode()
    nonce_b64 = base64.b64encode(nonce).decode()
    return f"""
      <s:Header>
        <wsse:Security s:mustUnderstand="1">
          <wsse:UsernameToken>
            <wsse:Username>{xml_escape(username)}</wsse:Username>
            <wsse:Password Type="{WSSE}#PasswordDigest">{digest}</wsse:Password>
            <wsse:Nonce EncodingType="{WSSE}#Base64Binary">{nonce_b64}</wsse:Nonce>
            <wsu:Created>{created}</wsu:Created>
          </wsse:UsernameToken>
        </wsse:Security>
      </s:Header>"""


def xml_escape(value):
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def soap_body(action_xml, username, password):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope
  xmlns:s="{SOAP_ENV}"
  xmlns:trt="{MEDIA}"
  xmlns:wsse="{WSSE}"
  xmlns:wsu="{WSU}">
  {ws_security_header(username, password)}
  <s:Body>
    {action_xml}
  </s:Body>
</s:Envelope>"""


def post_soap(url, action_xml, username, password):
    envelope = soap_body(action_xml, username, password)
    response = requests.post(
        url,
        data=envelope.encode(),
        headers={
            "Content-Type": "application/soap+xml; charset=utf-8",
            "User-Agent": "camzilla-onvif-probe",
        },
        timeout=10,
    )
    response.raise_for_status()
    return ET.fromstring(response.content)


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def find_all(root, name):
    return [node for node in root.iter() if local_name(node.tag) == name]


def node_text(root, name):
    for node in root.iter():
        if local_name(node.tag) == name:
            return node.text
    return None


def get_profiles(media_url, username, password):
    root = post_soap(
        media_url,
        "<trt:GetProfiles/>",
        username,
        password,
    )
    profiles = []
    for profile in find_all(root, "Profiles"):
        token = profile.attrib.get("token")
        name = node_text(profile, "Name") or token
        if token:
            profiles.append((token, name))
    return profiles


def get_stream_uri(media_url, username, password, profile_token):
    action = f"""
    <trt:GetStreamUri>
      <trt:StreamSetup>
        <trt:Stream xmlns:tt="http://www.onvif.org/ver10/schema">RTP-Unicast</trt:Stream>
        <trt:Transport xmlns:tt="http://www.onvif.org/ver10/schema">
          <trt:Protocol>RTSP</trt:Protocol>
        </trt:Transport>
      </trt:StreamSetup>
      <trt:ProfileToken>{xml_escape(profile_token)}</trt:ProfileToken>
    </trt:GetStreamUri>"""
    root = post_soap(media_url, action, username, password)
    return node_text(root, "Uri")


def play(uri):
    print(f"Launching GStreamer for {uri}", flush=True)
    subprocess.run(["gst-launch-1.0", "playbin", f"uri={uri}"], check=False)


def main():
    load_env_file()

    parser = argparse.ArgumentParser(description="Fetch an RTSP URL from an ONVIF camera.")
    parser.add_argument("--host", default=os.getenv("CAMERA_HOST", ""))
    parser.add_argument("--port", type=int, default=int(os.getenv("ONVIF_PORT", "8000")))
    parser.add_argument("--media-path", default="/onvif/Media")
    parser.add_argument("--user", default=os.getenv("ONVIF_USER", ""))
    parser.add_argument("--password", default=os.getenv("ONVIF_PASSWORD", ""))
    parser.add_argument("--wait", type=int, default=60)
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    if not args.host:
        parser.error("CAMERA_HOST must be set in .env or passed with --host")

    if not wait_for_port(args.host, args.port, args.wait):
        print(f"Timed out waiting for {args.host}:{args.port} to open.", file=sys.stderr)
        return 2

    media_url = f"http://{args.host}:{args.port}{args.media_path}"
    print(f"Using ONVIF media endpoint: {media_url}")
    profiles = get_profiles(media_url, args.user, args.password)
    if not profiles:
        print("No ONVIF media profiles returned.", file=sys.stderr)
        return 1

    for token, name in profiles:
        print(f"Profile: {name} ({token})")

    uri = get_stream_uri(media_url, args.user, args.password, profiles[0][0])
    if not uri:
        print("No RTSP URI returned.", file=sys.stderr)
        return 1

    print(f"RTSP URI: {uri}")
    if args.play:
        play(uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
