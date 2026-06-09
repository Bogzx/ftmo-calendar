"""Provider-agnostic LLM extraction with validation, repair retry, and model fallback."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)


class RawEvent(BaseModel):
    """One event as extracted by the model, before validation/normalization."""

    event_type: Literal["maintenance", "crypto_closure", "holiday_hours", "other"]
    start_time: str
    end_time: str
    stated_utc_offset: str | None = None
    confidence: Literal["high", "low"] = "high"


_EVENTS = TypeAdapter(list[RawEvent])


class BackendError(Exception):
    """The LLM API call itself failed (quota, network, refusal)."""


class ExtractionError(Exception):
    """No model produced a valid extraction."""


class LLMBackend(Protocol):
    def complete(self, prompt: str, model: str) -> str: ...


PROMPT_TEMPLATE = """You extract scheduled trading interruptions from a prop-firm announcement.

Identify every scheduled platform maintenance window, crypto market closure, and \
modified/closed trading-hours period in the text below.

Rules:
- Output ONLY a JSON array, no prose and no markdown fences.
- Each element: {{"event_type": "maintenance"|"crypto_closure"|"holiday_hours"|"other", \
"start_time": "YYYY-MM-DDTHH:MM:SS", "end_time": "YYYY-MM-DDTHH:MM:SS", \
"stated_utc_offset": "+03:00" or null, "confidence": "high"|"low"}}
- If the text states a timezone (e.g. "GMT+3"), set stated_utc_offset to it ("+03:00"); else null.
- If an end time is implied rather than stated (e.g. "closed whole day"), infer it \
(00:00:00 to 23:59:00 of that day) and set confidence to "low".
- Ignore anything without a concrete scheduled date (general reminders, swap notices).
- If there are no scheduled events, output [].

Announcement text:
---
{text}
---
"""

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class EventExtractor:
    def __init__(self, backend: LLMBackend, models: Sequence[str]) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self.backend = backend
        self.models = list(models)

    def extract(self, text: str) -> list[RawEvent]:
        prompt = PROMPT_TEMPLATE.format(text=text)
        last_error: Exception | None = None
        for model in self.models:
            try:
                return self._extract_once(prompt, model)
            except (BackendError, ExtractionError) as e:
                logger.warning("Model %s failed: %s", model, e)
                last_error = e
        raise ExtractionError(f"all models failed; last error: {last_error}")

    def _extract_once(self, prompt: str, model: str) -> list[RawEvent]:
        raw = self.backend.complete(prompt, model)
        try:
            return self._parse(raw)
        except ValidationError as first:
            logger.info("Invalid extraction from %s; attempting repair retry", model)
            repair_prompt = (
                f"{prompt}\n\nYour previous reply was invalid: {str(first)[:500]}\n"
                "Reply again with ONLY the corrected JSON array."
            )
            raw = self.backend.complete(repair_prompt, model)
            try:
                return self._parse(raw)
            except ValidationError as second:
                raise ExtractionError(f"invalid JSON after repair retry: {second}") from second

    @staticmethod
    def _parse(raw: str) -> list[RawEvent]:
        cleaned = _FENCE.sub("", raw.strip()).strip()
        return _EVENTS.validate_json(cleaned)
