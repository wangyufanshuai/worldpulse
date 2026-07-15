from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiplomaticSignalParameters(_Parameters):
    signal: Literal["deescalatory", "neutral", "firm"]
    channel: Literal["public", "backchannel", "multilateral"]
    public: bool = False


class AllianceRequestParameters(_Parameters):
    objective: str = Field(min_length=3, max_length=240)
    requested_support: list[Literal["diplomatic", "logistics", "intelligence", "humanitarian"]] = Field(min_length=1, max_length=3)
    duration_days: int = Field(ge=1, le=90)


class AllianceResponseParameters(_Parameters):
    request_id: str = Field(min_length=3, max_length=80)
    response: Literal["accept", "decline", "conditional"]
    conditions: list[str] = Field(default_factory=list, max_length=5)


class SanctionProposalParameters(_Parameters):
    sector: Literal["energy", "food", "chips", "shipping", "settlement"]
    scope: Literal["targeted", "sectoral", "multilateral"]
    review_days: int = Field(ge=1, le=90)


class TradeRerouteRequestParameters(_Parameters):
    chain_key: Literal["energy", "food", "chips", "shipping", "settlement"]
    alternative_route: str = Field(min_length=3, max_length=120)
    duration_days: int = Field(ge=1, le=90)


class PublicNarrativeParameters(_Parameters):
    theme: str = Field(min_length=3, max_length=240)
    audience: Literal["domestic", "regional", "global"]
    tone: Literal["stabilizing", "informational", "firm"]


class HumanitarianOfferParameters(_Parameters):
    assistance_type: Literal["food", "medical", "evacuation", "infrastructure"]
    delivery_channel: Literal["bilateral", "multilateral", "ngo"]
    duration_days: int = Field(ge=1, le=90)


class DeescalationOfferParameters(_Parameters):
    measure: Literal["hotline", "temporary_pause", "observer_mission", "negotiation"]
    verification: Literal["bilateral", "third_party", "public_commitment"]
    duration_days: int = Field(ge=1, le=90)


class IntelligenceRequestParameters(_Parameters):
    topic: str = Field(min_length=3, max_length=160)
    classification: Literal["open_source", "restricted_simulation"]
    horizon_days: int = Field(ge=1, le=90)


PARAMETER_MODELS = {
    "diplomatic_signal": DiplomaticSignalParameters,
    "alliance_request": AllianceRequestParameters,
    "alliance_response": AllianceResponseParameters,
    "sanction_proposal": SanctionProposalParameters,
    "trade_reroute_request": TradeRerouteRequestParameters,
    "public_narrative": PublicNarrativeParameters,
    "humanitarian_offer": HumanitarianOfferParameters,
    "deescalation_offer": DeescalationOfferParameters,
    "intelligence_request": IntelligenceRequestParameters,
}


def validate_parameters(action_type: str, parameters: dict) -> dict:
    model = PARAMETER_MODELS[action_type]
    return model(**parameters).model_dump(mode="json")
