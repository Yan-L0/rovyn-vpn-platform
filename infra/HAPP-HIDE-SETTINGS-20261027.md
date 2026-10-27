# Happ server settings visibility — 2026-10-27

Applied `hide-settings: 1` to Remnawave subscription settings via PATCH
`/api/subscription-settings`, preserving every existing custom response header.
The API readback matched the intended header map. A real subscription GET with
Happ user-agent returned HTTP 200, application/json and `hide-settings: 1`.

Private rollback snapshot on the panel server:
`/opt/remnawave/backups/happ-hide-settings-20261027T061311Z.json` (0600).
To roll back, merge only the previous hide-settings value (or remove that key)
into the current header map; do not overwrite newer settings with the snapshot.

Client follow-up: enabled the native `Hide server settings` switch for the
active Remnawave subscription in Happ 6.1.0. Verified visually that configuration
arrows disappeared from REALITY, XHTTP and Hysteria rows; other providers retained
their arrows. The hide state remained visible after invoking subscription update.
Happ stayed CONNECTED throughout (session counter advanced, no reset).

The server header alone had not enabled the local switch on this existing
installation. Therefore this verifies the local subscription UI, not automatic
application on every other device. Other clients still need verification.
No VPN disconnect, core restart or transport change was performed.

Reference: https://www.happ.su/main/dev-docs/app-management
This is an application UI restriction, not cryptographic protection of credentials.
