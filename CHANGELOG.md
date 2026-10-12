# Changelog

## 0.4.0 — first public beta candidate

- Local encrypted Bluetooth telemetry through Home Assistant and active ESPHome proxies.
- Button-confirmed key creation in the configuration wizard, with interrupted-pairing recovery.
- AC/DC, R-Drive, UPS and button-tone switches; charging power, fan and idle-timeout selects.
- Optional strict adapter/proxy selection without fallback to other scanners.
- Capability-aware controls, serialized read/modify/write operations and readback verification.
- Incremental detailed polling and unavailable values for unread dynamic registers.
- English/Russian UI, redacted diagnostics, 76 automated tests.
- Public packaging: HACS metadata, development dependencies, validation workflow,
  bilingual documentation and an original project icon.

This release has been exercised on one physical Cube with three battery modules
and Home Assistant 2026.10.1. See TEST_REPORT.md for the scope of hardware validation.
