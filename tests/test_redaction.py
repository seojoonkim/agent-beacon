import pytest

from agent_beacon import WorkerObservation
from agent_beacon.redact import redact_text, worker_observation_from_dict


def test_unknown_worker_observation_fields_are_rejected():
    with pytest.raises(ValueError, match="unknown"):
        worker_observation_from_dict({"worker_id": "w", "live": True, "prompt": "steal me"})


def test_typed_worker_observation_accepts_only_allowlisted_shape():
    assert worker_observation_from_dict({"worker_id": "w", "live": True}) == WorkerObservation("w", True)
    assert WorkerObservation.from_dict({"worker_id": "w", "live": True}) == WorkerObservation("w", True)


def test_secret_like_tokens_are_removed_from_safe_text():
    example_provider_token = "sk" + "-example00000000"
    text = redact_text(f"status token=EXAMPLE_TOKEN password: EXAMPLE_PASSWORD {example_provider_token}")
    lowered = text.lower()
    assert "EXAMPLE_TOKEN" not in text
    assert "EXAMPLE_PASSWORD" not in text
    assert example_provider_token not in text
    assert "[redacted]" in lowered


def test_worker_type_cannot_hold_prompt_goal_args_or_results():
    with pytest.raises(TypeError):
        WorkerObservation("w", True, prompt="hidden")
