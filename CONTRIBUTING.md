# Contributing

Use Python 3.14. Create a virtual environment, install `requirements-dev.txt`,
then run `python -m pytest tests -q` and `python -m ruff check .`.
The tests use synthetic credentials and mock BLE sessions; they do not contact a station.

Describe the Cube model, firmware and Home Assistant version when reporting compatibility.
Check supported-feature flags before adding controls, preserve unrelated register bits,
and confirm writes by reading the resulting value. Include a source for new register mappings.
Keep hardware-tested behavior separate from assumptions and mock-based test coverage.

Submit changes as a pull request. Do not commit device keys, identifiers, Home Assistant
configuration, research APKs or vendor application binaries. Review diagnostics before posting.
Contributions are distributed under the project's Apache-2.0 license.
