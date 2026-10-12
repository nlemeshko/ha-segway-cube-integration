# Validation scope — Segway Cube 0.4.0

## Hardware validation

One physical Cube with three battery modules, Home Assistant 2026.10.1,
and an active ESPHome Bluetooth proxy:

- Gen2 authorization, first refresh and subsequent automatic polling succeeded.
- Charge, main temperature and module count matched the station display/application.
- Strict proxy selection matched the actual connection source; seven successive
  automatic polls completed without register failures after applying it.
- Eleven supported controls were available. AC charging limit was changed from
  700 W to 600 W and restored; button tone was enabled and restored to disabled.
  Readback confirmed both changes and preservation of unrelated flag bits.
- Button-confirmed pairing and telemetry were exercised directly from a Mac.

## Automated validation

76 tests cover protocol/crypto vectors, packet integrity and fragmentation,
authorization, explicit pairing consent, persisted-key recovery, startup timeout,
incremental polling, battery-module counts, controls and capability gating,
readback confirmation, concurrent changes, and strict proxy selection.
The public candidate passes these tests and Ruff using the existing Python 3.14 /
Home Assistant 2026.10.1 development environment. These are not hardware tests.

## Not yet validated

- A complete new physical pairing performed through the Home Assistant wizard.
  The wizard's logic is tested; direct Mac pairing is the hardware proof.
- AC/DC and UPS switching on a connected load, or an actual mains-loss UPS transition.
- Every timer/fan/R-Drive setting changed on hardware.
- Other Cube units, regional variants, firmware versions, or different HA versions.
- Long-duration stability and operation with five battery modules.
- A fresh Linux dependency installation or the GitHub-hosted validation workflow.
  HACS and hassfest checks require their first remote run after upload.

Controls are based on the official Cube application's configuration, not guessed
generic Ninebot commands. Some compound battery/port fields remain raw registers.
Strict source selection uses an internal habluetooth backend hook; Home Assistant
updates may require compatibility fixes. Future releases should expand the matrix.
