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
- Client Area, website, IT, billing, or account-services maintenance is NOT a trading \
interruption — never emit an event for it. Only windows where trading itself is unavailable \
or restricted count (platform maintenance, market/symbol closures, modified trading hours).
- If there are no scheduled events, output [].

Announcement text:
---
{text}
---
"""

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class EventExtractor:
    def __init__(self, backend: LLMBackend, models: Sequence[str], consensus_runs: int = 1) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self.backend = backend
        self.models = list(models)
        self.consensus_runs = max(1, consensus_runs)

    def extract(self, text: str) -> list[RawEvent]:
        """Extract events; with consensus_runs > 1, majority-vote across runs.

        Hosted APIs (notably OpenRouter, which routes one model id across
        several providers) are not perfectly deterministic even at
        temperature 0. Majority voting across runs makes the reported event
        set stable run-to-run.
        """
        prompt = PROMPT_TEMPLATE.format(text=text)
        if self.consensus_runs == 1:
            return self._extract_with_fallback(prompt)
        runs = [self._extract_with_fallback(prompt) for _ in range(self.consensus_runs)]
        return self._consensus(runs)

    def _extract_with_fallback(self, prompt: str) -> list[RawEvent]:
        last_error: Exception | None = None
        for model in self.models:
            try:
                return self._extract_once(prompt, model)
            except (BackendError, ExtractionError) as e:
                logger.warning("Model %s failed: %s", model, e)
                last_error = e
        raise ExtractionError(f"all models failed; last error: {last_error}")

    def _consensus(self, runs: list[list[RawEvent]]) -> list[RawEvent]:
        # Identity excludes stated_utc_offset: one announcement has one timezone
        # context, and offset-None resolves to the same instant downstream — an
        # offset-attribution flicker must not split the vote. The most explicit
        # variant wins the merge.
        majority = self.consensus_runs // 2 + 1
        counts: dict[tuple, int] = {}
        merged: dict[tuple, RawEvent] = {}
        order: list[tuple] = []
        for run in runs:
            seen_this_run: set[tuple] = set()
            for event in run:
                key = (event.event_type, event.start_time, event.end_time)
                if key in seen_this_run:
                    continue
                seen_this_run.add(key)
                counts[key] = counts.get(key, 0) + 1
                if key not in merged:
                    merged[key] = event
                    order.append(key)
                elif merged[key].stated_utc_offset is None and event.stated_utc_offset:
                    merged[key] = event
        kept = [merged[key] for key in order if counts[key] >= majority]
        dropped = [key for key in order if counts[key] < majority]
        if dropped:
            logger.info(
                "Consensus (%d runs) dropped %d minority event(s): %s",
                self.consensus_runs,
                len(dropped),
                dropped,
            )
        return kept

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
        cleaned = _THINK.sub("", raw)  # reasoning models (DeepSeek R1, …) inline <think> blocks
        cleaned = _FENCE.sub("", cleaned.strip()).strip()
        try:
            return _EVENTS.validate_json(cleaned)
        except ValidationError:
            # Some models wrap the array in prose despite instructions —
            # fall back to the outermost JSON array in the reply.
            start, end = cleaned.find("["), cleaned.rfind("]")
            if 0 <= start < end:
                return _EVENTS.validate_json(cleaned[start : end + 1])
            raise
