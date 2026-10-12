# First public release

Prepared for `nlemeshko/ha-segway-cube-integration`, version 0.4.0.
This directory is the publication source. Do not upload the surrounding development
workspace, old deliverable archives, device screenshots, phone backups or HA configuration.

## Repository settings

Create an empty public GitHub repository with Issues enabled. Suggested description:

> Local Bluetooth integration for Segway Cube power stations in Home Assistant.

Suggested topics: `home-assistant`, `hacs`, `segway`, `bluetooth`, `esphome`, `power-station`.
The source already includes a README, license and .gitignore, so do not generate competing
files when creating an empty repository. For an existing repository, inspect its contents
before combining histories; do not force-push.

## Upload from this directory

For a new empty repository, these commands create and upload the initial source history.
Run them only when you are ready to publish the files:

```sh
git init -b main
git add .
git diff --cached --stat
git commit -m "Prepare Segway Cube 0.4.0 public beta"
git remote add origin https://github.com/nlemeshko/ha-segway-cube-integration.git
git push -u origin main
```

## Validate before announcing the release

1. Wait for all three jobs in the **Validate** GitHub Actions workflow: tests, hassfest,
   HACS. These hosted checks have not run during local preparation. Fix any failures.
2. Install through HACS as a custom repository on a test HA installation and check
   discovery, loading, existing-key authorization and the bundled icon.
3. Test a complete new button-confirmed pairing through the HA wizard with a willing
   station owner. Direct Mac pairing succeeded, but this HA hardware flow remains untested.
   The confirmation explains that the station's current application key can be replaced.
4. Publish a GitHub **prerelease** tagged `v0.4.0`, titled `0.4.0 — public beta`, after
   validation. Use CHANGELOG.md and TEST_REPORT.md to state the actual test coverage.
   A GitHub source archive is enough; HACS downloads the component from the repository.
5. Ask testers for model, firmware, HA version and reviewed diagnostics; do not ask
   them to post credentials, .storage files or phone backups.

Default HACS catalog inclusion is a separate application, not a consequence of creating
this repository. Custom-repository installation can be used first.

References: [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/),
[HACS general requirements](https://www.hacs.xyz/docs/publish/start/),
[HACS validation action](https://www.hacs.xyz/docs/publish/action/).
