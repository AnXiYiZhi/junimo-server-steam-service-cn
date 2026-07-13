#!/usr/bin/env python3
"""Fail when an upstream merge silently removes the steam-service-cn patch."""

from pathlib import Path

SOURCE = Path("tools/steam-service/SteamAuthService.cs")
text = SOURCE.read_text(encoding="utf-8")

required = {
    "bounded connection wait": "ConnectAndWaitAsync",
    "connection timeout override": "STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS",
    "connection retry override": "STEAM_CLIENT_CONNECT_RETRIES",
    "authentication retry override": "STEAM_AUTH_SESSION_RETRIES",
    "authentication retry delay override": "STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS",
}
missing = [description for description, marker in required.items() if marker not in text]
forbidden = [marker for marker in ("ConnectionEstablishmentDelay",) if marker in text]

if missing or forbidden:
    details = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if forbidden:
        details.append("legacy fixed delay restored: " + ", ".join(forbidden))
    raise SystemExit("anxi patch invariant failed (" + "; ".join(details) + ")")

print("anxi steam-service connection/retry patch invariants are present")
