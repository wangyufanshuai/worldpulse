from __future__ import annotations


WORLDPULSE_VERSION = "1.3.0-rc1"
API_CONTRACT_VERSION = "v3"
RELEASE_CHANNEL = "release-candidate"


def version_info() -> dict[str, str]:
    return {
        "service": "worldpulse",
        "version": WORLDPULSE_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "release_channel": RELEASE_CHANNEL,
    }
