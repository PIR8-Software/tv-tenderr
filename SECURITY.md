# Security and upgrade notes (1.3.4)

## Authentication and transport

All `/api/` requests except `/api/health` require `Authorization: Bearer <token>`.
Set `TV_TENDERR_API_TOKEN` to a strong secret in the protected local `.env` using a secure editor. Never commit it or paste it into logs/chat. Set `BACKEND_HOST` explicitly to loopback or the intended private interface. Without an explicit host, a configured token selects **all interfaces**; a token is not a firewall. Use HTTPS or a trusted encrypted private-network transport, not bearer HTTP on an untrusted network.

An existing configured installation cannot use unauthenticated bootstrap. Before upgrading its backend, install the signing-compatible Android client, retain private backups, configure the shared token on server and clients, and schedule your own backend restart. Do not uninstall the app or replace its signing identity. Old clients without the token field cannot authenticate after this upgrade.

For a genuinely empty server, local loopback first-run web setup accepts an explicitly chosen new token. It is unavailable once service credentials or an API token exist. Blank secret fields preserve stored values. API config responses expose presence flags, not raw service secrets.

## Client login

Web Settings → **Connect** authenticates the current tab; it does not rotate the server token or save server settings. Authentication is in `sessionStorage`: same-tab reload survives, independently opened tabs and browser restarts are not guaranteed. Any script executing in that origin can access sessionStorage. Use a trusted browser and do not treat it as a password manager.

Android Settings → **API token** stores the client credential. Existing service secrets migrate to encrypted preferences; backup/device-transfer exclusions apply. Retain configuration securely yourself. Downgrades may not understand encrypted preferences. Ordinary Android Save does not rotate the backend token; avoid saving unchanged server settings just to test connectivity.

## Data and action safety

Run exactly **one backend process/worker**. The process-local transaction lock is not cross-process locking. Atomic JSON/config replacement does not provide rollback of external Radarr/Sonarr actions or full power-loss durability.

Decision files live beside `backend.py` in `data/`. Preserve all current JSON and private `.env` before upgrades. The legacy-path guard refuses an empty current store when the old store exists; it does not migrate or merge data for you. Retain the `tv-tenderr.service` name and customize the template for your installation. Do not blindly restore old decision files over newer ones.

Undo cancels destructive actions still in the ten-second pending window; it cannot undelete files after the upstream operation has executed. Competing web Keep/Add cancels the matching pending action. Leaving Android cancels pending deletion. Partial external failures can require manual recovery. Test mutations only against disposable synthetic fixtures, never a production library.

## Verification boundaries

Regression coverage is not full accessibility certification, exhaustive live Arr/Plex failure coverage, or a reproducible-build attestation. Direct Python dependencies are pinned; transitive dependencies are not fully locked. Release APKs must be production-signed and checked against their published checksum. Private audit bundles, decision history, credentials, signing keys and device records are not release assets.
