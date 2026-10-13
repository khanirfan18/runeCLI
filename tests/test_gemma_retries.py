"""Tests for Gemma retry behavior, status code paths, timeout cap, and spinner updates."""

import time
from unittest.mock import MagicMock, call, patch
import pytest

from rune.gemma import SYSTEM_CONTRACT, GemmaError, default_generate


@pytest.fixture(autouse=True)
def set_dummy_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_api_key_test")


@pytest.mark.parametrize(
    "error_exc",
    [
        Exception("500 INTERNAL: internal server error"),
        Exception("502 Bad Gateway"),
        Exception("503 Service Unavailable"),
        Exception("504 Gateway Timeout"),
        Exception("429 RESOURCE_EXHAUSTED"),
        Exception("The model is overloaded. Please try again later."),
    ],
)
def test_retryable_errors_exhaust_retries_and_fallback(monkeypatch, error_exc):
    """500, 502, 503, 504, 429, and overloaded errors retry 2x on primary, fall back to second model 2x, then raise GemmaError."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = error_exc

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    spinner_updates: list[str] = []
    monkeypatch.setattr("rune.gemma.update_working", lambda msg: spinner_updates.append(msg))

    with pytest.raises(GemmaError) as exc_info:
        default_generate(
            model="gemma-4-31b-it",
            contract=SYSTEM_CONTRACT,
            content="test prompt",
            client=mock_client,
        )

    # 3 attempts on gemma-4-31b-it + 3 attempts on gemma-4-26b-a4b-it = 6 calls
    assert mock_client.models.generate_content.call_count == 6

    calls = mock_client.models.generate_content.call_args_list
    assert calls[0].kwargs["model"] == "gemma-4-31b-it"
    assert calls[1].kwargs["model"] == "gemma-4-31b-it"
    assert calls[2].kwargs["model"] == "gemma-4-31b-it"
    assert calls[3].kwargs["model"] == "gemma-4-26b-a4b-it"
    assert calls[4].kwargs["model"] == "gemma-4-26b-a4b-it"
    assert calls[5].kwargs["model"] == "gemma-4-26b-a4b-it"

    # Retries wait 1s, then 2s on each model
    assert slept == [1.0, 2.0, 1.0, 2.0]

    # Spinner text updated on each retry
    assert spinner_updates == ["Google's servers are busy, retrying..."] * 4

    # Friendly error message
    assert "The oracle is unreachable." in str(exc_info.value)


def test_retry_success_on_second_attempt(monkeypatch):
    """If primary model succeeds on retry 1, returns text without calling fallback model."""
    mock_client = MagicMock()
    ok_resp = MagicMock()
    ok_resp.text = '{"status": "OK"}'
    mock_client.models.generate_content.side_effect = [
        Exception("500 INTERNAL"),
        ok_resp,
    ]

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    spinner_updates: list[str] = []
    monkeypatch.setattr("rune.gemma.update_working", lambda msg: spinner_updates.append(msg))

    res = default_generate(
        model="gemma-4-31b-it",
        contract=SYSTEM_CONTRACT,
        content="test prompt",
        client=mock_client,
    )

    assert res == '{"status": "OK"}'
    assert mock_client.models.generate_content.call_count == 2
    assert slept == [1.0]
    assert spinner_updates == ["Google's servers are busy, retrying..."]


def test_fallback_model_success(monkeypatch):
    """If primary model exhausts retries, falls back to second model and succeeds."""
    mock_client = MagicMock()
    ok_resp = MagicMock()
    ok_resp.text = '{"status": "OK"}'
    mock_client.models.generate_content.side_effect = [
        Exception("503 Unavailable"),
        Exception("503 Unavailable"),
        Exception("503 Unavailable"),
        ok_resp,
    ]

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    res = default_generate(
        model="gemma-4-31b-it",
        contract=SYSTEM_CONTRACT,
        content="test prompt",
        client=mock_client,
    )

    assert res == '{"status": "OK"}'
    assert mock_client.models.generate_content.call_count == 4
    # Waited 1s, 2s on primary, then immediately attempted fallback model
    assert slept == [1.0, 2.0]


def test_timeout_cap_at_60_seconds(monkeypatch):
    """Total time spent on retries is capped at ~60s."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("500 INTERNAL")

    current_time = 1000.0

    def mock_monotonic():
        return current_time

    def mock_sleep(s):
        nonlocal current_time
        # Advance clock by 35s on each sleep
        current_time += 35.0

    monkeypatch.setattr(time, "monotonic", mock_monotonic)
    monkeypatch.setattr(time, "sleep", mock_sleep)

    with pytest.raises(GemmaError) as exc_info:
        default_generate(
            model="gemma-4-31b-it",
            contract=SYSTEM_CONTRACT,
            content="test prompt",
            client=mock_client,
        )

    # After attempt 0 (sleep 35s) and attempt 1 (sleep 35s), elapsed is 70s > 60s, so it breaks
    assert mock_client.models.generate_content.call_count < 6
    assert "The oracle is unreachable." in str(exc_info.value)


def test_bad_request_400_not_retried(monkeypatch):
    """400 is not retried and does not attempt fallback model."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("400 Bad Request: invalid argument")

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    with pytest.raises(GemmaError) as exc_info:
        default_generate(
            model="gemma-4-31b-it",
            contract=SYSTEM_CONTRACT,
            content="test prompt",
            client=mock_client,
        )

    # Exactly 1 call: no retry, no fallback
    assert mock_client.models.generate_content.call_count == 1
    assert slept == []
    assert "The oracle is unreachable." in str(exc_info.value)


@pytest.mark.parametrize(
    "error_exc",
    [
        Exception("401 Unauthorized: invalid API key"),
        Exception("403 Forbidden: API key expired"),
    ],
)
def test_auth_errors_401_403_print_friendly_message_and_exit_1(monkeypatch, error_exc, capsys):
    """401 and 403 print friendly key rejection message and exit code 1 immediately without retry."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = error_exc

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    with pytest.raises(SystemExit) as exc_info:
        default_generate(
            model="gemma-4-31b-it",
            contract=SYSTEM_CONTRACT,
            content="test prompt",
            client=mock_client,
        )

    assert exc_info.value.code == 1
    # Exactly 1 attempt
    assert mock_client.models.generate_content.call_count == 1
    assert slept == []

    captured = capsys.readouterr()
    assert "Gemini rejected your API key. Check it and run rune again." in captured.out
