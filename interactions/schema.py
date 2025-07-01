from pydantic import BaseModel, Field, model_validator, AwareDatetime
from datetime import datetime, timezone

# Pydantic models using V2 validators
class Interaction(BaseModel):
    timestamp: AwareDatetime
    sessionId: str
    actionKind: str
    payload: dict = Field(default_factory=dict)
    clientId: str
    metadata: dict = Field(default_factory=dict)
    userAgent: str
    url: str
    source: str

    @model_validator(mode='after')
    def check_required_fields(cls, model):
        missing = [f for f in ('sessionId', 'actionKind', 'clientId', 'userAgent', 'url', 'source')
                   if not getattr(model, f)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        return model


class BatchRequest(BaseModel):
    interactions: list[Interaction]
    batchId: str
    timestamp: AwareDatetime
    sessionId: str

    @model_validator(mode='after')
    def check_non_empty(cls, model):
        if not model.interactions:
            raise ValueError("interactions list cannot be empty")
        return model


class HealthResponse(BaseModel):
    status: str = "healthy"
    timestamp: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000))