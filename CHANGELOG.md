# Changelog

## 0.4.1 — authentication recovery

- Treat missing or corrupt Bluetooth authentication replies as temporary connection
  failures, so Home Assistant keeps polling with the saved key and can recover.
- Request reauthentication only when a key is missing or the station explicitly
  rejects it; do not replace the saved key on a transport failure.
- Add regression coverage for recovery on the next poll, control failures without
  spurious reauthentication, and explicit key rejection (87 automated tests total).

## 0.4.0 — first public beta

- Local encrypted Bluetooth telemetry through Home Assistant and active ESPHome proxies.
- Button-confirmed key creation in the configuration wizard, with interrupted-pairing recovery.
- AC/DC, R-Drive, UPS and button-tone switches; charging power, fan and idle-timeout selects.
- Optional strict adapter/proxy selection without fallback to other scanners.
- Capability-aware controls, serialized read/modify/write operations and readback verification.
- Incremental detailed polling and unavailable values for unread dynamic registers.
- Immediate first detailed cycle on newly booted hosts, independent of system uptime.
- English/Russian UI, redacted diagnostics, 78 automated tests.
- Public packaging: HACS metadata, development dependencies, validation workflow,
  bilingual documentation and an original project icon.

This release has been exercised on one physical Cube with three battery modules
and Home Assistant 2026.10.1. See TEST_REPORT.md for the scope of hardware validation.
