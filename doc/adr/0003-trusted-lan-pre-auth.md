# ADR 0003: Trusted-LAN posture before authentication

## Status

Accepted — 2026-07-11.

## Decision

Before Phase 4 authentication, published services bind to loopback by default.
LAN exposure is an explicit environment choice and is documented as trusted
network only. Camera URLs, credentials, webhook URLs, and the `go2rtc`
administrative API never reach browser payloads, logs, health responses, or CI
artifacts.

## Consequences

This is not a substitute for authentication. Operators who expose the service
on a LAN accept that any party on that trusted network can use it until Phase 4.
