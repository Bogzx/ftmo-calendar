import pytest

from ftmo_calendar.parsing.llm import (
    BackendError,
    EventExtractor,
    ExtractionError,
    RawEvent,
)

VALID_JSON = (
    '[{"event_type": "maintenance", "start_time": "2026-06-06T08:00:00",'
    ' "end_time": "2026-06-06T14:00:00", "stated_utc_offset": "+03:00",'
    ' "confidence": "high"}]'
)


class ScriptedBackend:
    """Returns queued responses; raises queued exceptions."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: str, model: str) -> str:
        self.calls.append((prompt, model))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_extracts_valid_events() -> None:
    backend = ScriptedBackend([VALID_JSON])
    events = EventExtractor(backend, ["m1"]).extract("some announcement")
    assert events == [
        RawEvent(
            event_type="maintenance",
            start_time="2026-06-06T08:00:00",
            end_time="2026-06-06T14:00:00",
            stated_utc_offset="+03:00",
            confidence="high",
        )
    ]


def test_strips_markdown_fences() -> None:
    backend = ScriptedBackend(["```json\n" + VALID_JSON + "\n```"])
    events = EventExtractor(backend, ["m1"]).extract("text")
    assert len(events) == 1


def test_repair_retry_on_invalid_json() -> None:
    backend = ScriptedBackend(["not json at all", VALID_JSON])
    events = EventExtractor(backend, ["m1"]).extract("text")
    assert len(events) == 1
    assert len(backend.calls) == 2
    assert "invalid" in backend.calls[1][0].lower()  # repair prompt mentions the failure


def test_falls_back_to_next_model() -> None:
    backend = ScriptedBackend([BackendError("quota"), VALID_JSON])
    events = EventExtractor(backend, ["m1", "m2"]).extract("text")
    assert len(events) == 1
    assert backend.calls[1][1] == "m2"


def test_raises_when_all_models_fail() -> None:
    backend = ScriptedBackend([BackendError("a"), BackendError("b")])
    with pytest.raises(ExtractionError):
        EventExtractor(backend, ["m1", "m2"]).extract("text")


def test_empty_array_is_valid() -> None:
    backend = ScriptedBackend(["[]"])
    assert EventExtractor(backend, ["m1"]).extract("text") == []


def test_strips_reasoning_think_blocks() -> None:
    """DeepSeek R1-style models may inline <think>…</think> before the answer."""
    thinking = "<think>\nThe text mentions maintenance on Saturday...\n[not json]\n</think>\n"
    response = thinking + VALID_JSON
    backend = ScriptedBackend([response])
    events = EventExtractor(backend, ["deepseek/deepseek-r1"]).extract("text")
    assert len(events) == 1


def test_extracts_array_wrapped_in_prose() -> None:
    """Chat models sometimes wrap the JSON in pleasantries despite instructions."""
    response = f"Sure! Here is the extracted data:\n{VALID_JSON}\nLet me know if you need more."
    backend = ScriptedBackend([response])
    events = EventExtractor(backend, ["deepseek/deepseek-chat"]).extract("text")
    assert len(events) == 1


def test_think_block_and_prose_combined() -> None:
    response = f"<think>reasoning [1,2,3] here</think>The answer:\n```json\n{VALID_JSON}\n```"
    backend = ScriptedBackend([response])
    events = EventExtractor(backend, ["m1"]).extract("text")
    assert len(events) == 1
