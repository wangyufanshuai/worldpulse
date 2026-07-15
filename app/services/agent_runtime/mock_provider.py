from __future__ import annotations

import json

from .models import AgentProviderRequest, AgentProviderResponse


ALLOWED_OUTPUT_FIELDS = {
    "action_type",
    "target_ids",
    "parameters",
    "justification",
    "evidence_refs",
    "expected_direction",
    "confidence",
}


class DeterministicMockProvider:
    name = "mock"
    model = "mock-deterministic-v1"
    enabled = True

    def generate(self, request: AgentProviderRequest) -> AgentProviderResponse:
        if not request.mock_payload:
            raise ValueError("Mock provider request is missing deterministic payload")
        payload = {key: value for key, value in request.mock_payload.items() if key in ALLOWED_OUTPUT_FIELDS}
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return AgentProviderResponse(provider=self.name, model=self.model, mode="mock", payload=payload, output_text=text)
