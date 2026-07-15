from __future__ import annotations


WORLDPULSE_VERSION = "1.2.0-dev"
API_CONTRACT_VERSION = "v1"
RELEASE_CHANNEL = "development"


def version_info() -> dict[str, str]:
    return {
        "service": "worldpulse",
        "version": WORLDPULSE_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "release_channel": RELEASE_CHANNEL,
    }
