from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, model_validator
from pushary.adapters import decision_fingerprint


class ReviewRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    question: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    node: str = "hitl"
    idempotency_key: Optional[str] = Field(default=None, min_length=1)
    type: Literal["confirm", "select", "input"] = "confirm"
    options: Optional[List[str]] = None
    callback_url: Optional[str] = None
    context: Optional[str] = None
    agent_name: Optional[str] = None
    tool_target: Optional[str] = None
    actor: Optional[str] = None
    environment: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    presentation: Optional[Dict[str, Any]] = None
    placeholder: Optional[str] = None
    expires_in_seconds: Optional[int] = Field(default=None, ge=1)
    require_reachable: Optional[bool] = None

    @model_validator(mode="after")
    def validate_review(self) -> "ReviewRequest":
        if not self.external_id.strip() or not self.question.strip():
            raise ValueError("Pushary: question and recipient must not be blank.")
        if len(self.external_id.encode("utf-16-le", errors="surrogatepass")) // 2 > 256:
            raise ValueError("Pushary: recipient must not exceed 256 UTF-16 code units.")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("Pushary: operation idempotency_key must not be blank.")
        if self.type == "select" and (not self.options or any(not option for option in self.options)):
            raise ValueError("Pushary: select requires options.")
        if self.callback_url and (not self.idempotency_key or not self.idempotency_key.strip()):
            raise ValueError("Pushary: durable review requires an operation idempotency_key.")
        return self

    def bound_input(self) -> Dict[str, Any]:
        values = self.model_dump(exclude_none=True)
        if self.idempotency_key:
            values["idempotency_key"] = decision_fingerprint(values)
        return values


class CreatedDecision(BaseModel):
    model_config = ConfigDict(strict=True)
    decision_id: str = Field(alias="decisionId", min_length=1)
    correlation_id: str = Field(alias="correlationId", min_length=1)
    status: Literal["pending", "answered", "expired", "cancelled"]


class ReviewResume(BaseModel):
    model_config = ConfigDict(strict=True)
    correlation_id: str = Field(alias="correlationId", min_length=1)
    answer: Optional[str] = Field(max_length=5000)
    status: Literal["answered", "expired", "cancelled"] = "answered"


_answer = TypeAdapter(StrictStr)


def parse_answer(value: Any, review: ReviewRequest) -> str:
    answer = _answer.validate_python(value)
    if not answer or len(answer) > 5000:
        raise ValueError("Pushary: answer must contain 1 to 5000 characters.")
    if review.type == "confirm" and answer not in ("yes", "no"):
        raise ValueError("Pushary: confirm answer must be yes or no.")
    if review.type == "select" and answer not in (review.options or []):
        raise ValueError("Pushary: answer must match an offered option.")
    return answer


def parse_resume(value: Any, correlation_id: str, review: ReviewRequest) -> Optional[str]:
    resumed = ReviewResume.model_validate(value)
    if resumed.correlation_id != correlation_id:
        raise ValueError("Pushary: resumed answer belongs to another decision.")
    if resumed.status != "answered":
        if resumed.answer is not None:
            raise ValueError("Pushary: an expired or cancelled review cannot carry an answer.")
        return None
    return parse_answer(resumed.answer, review)
