"""Prompt building, the Ollama call, and the repair retry.

This module takes state the caller already gathered and returns one parsed
decision. It doesn't touch MCP or asyncio, which keeps it testable without
a live simulation or a live model; that loop lives in agent_runner.

Every call is a fresh conversation. Recent history is passed in as data,
never as accumulated chat turns.
"""

import json
from pathlib import Path

import httpx
import ollama

from abms.decision_parsing import Decision, DecisionParseError, parse_decision

REPO_ROOT = Path(__file__).resolve().parents[3]
SYSTEM_PROMPT_PATH = REPO_ROOT / "prompts" / "controller_system.md"


class OllamaUnavailableError(RuntimeError):
    """Ollama could not be reached. Fall back rather than retry; a downed
    server won't recover mid-retry."""


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text()


def render_feedback_block(previous_feedback: dict | None) -> str:
    """Tell the model what the guardrails did to its last decision, so it
    can adapt. Empty on the first decision of a session."""
    if previous_feedback is None:
        return ""
    requested = previous_feedback.get("requested")
    applied = previous_feedback.get("applied") or {}
    notes = previous_feedback.get("guardrail_notes") or []
    if requested and (
        requested.get("heating_c") != applied.get("heating_c")
        or requested.get("cooling_c") != applied.get("cooling_c")
        or notes
    ):
        return (
            "Your previous decision was adjusted by the safety layer; account for this.\n"
            f"You requested: heating={requested.get('heating_c')} cooling={requested.get('cooling_c')}\n"
            f"What was applied: heating={applied.get('heating_c')} cooling={applied.get('cooling_c')}\n"
            f"Why: {'; '.join(notes) if notes else 'guardrail adjustment'}\n"
        )
    return (
        f"Your previous decision (heating={applied.get('heating_c')} "
        f"cooling={applied.get('cooling_c')}) was applied unmodified; no adjustment was needed.\n"
    )


def build_user_prompt(state: dict, goals: dict, history: dict, previous_feedback: dict | None = None) -> str:
    """Pack the three read-tool responses into one JSON blob for the
    model, after the guardrail feedback block."""
    payload = {
        "current_state": state,
        "goals_and_constraints": goals,
        "recent_history": history,
    }
    feedback_block = render_feedback_block(previous_feedback)
    return (
        f"{feedback_block}"
        "Decide the next heating and cooling setpoints (deg C) for this "
        "building, given the following data.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        'Respond with ONLY a JSON object: {"reasoning": "<1-2 sentence '
        'explanation>", "heating_c": <number>, "cooling_c": <number>}.'
    )


REPAIR_PROMPT_TEMPLATE = (
    "Your previous reply could not be parsed: {error}\n"
    'Reply again with ONLY a single JSON object of the exact form '
    '{{"reasoning": "<1-2 sentence explanation>", "heating_c": <number>, '
    '"cooling_c": <number>}}. No other text, no markdown fences.'
)


class LLMAgent:
    """Everything model-specific is the model string and the host, both
    settable from config or env."""

    def __init__(
        self,
        model: str,
        host: str,
        temperature: float = 0.2,
        keep_alive: str = "10m",
        request_timeout_s: float = 30.0,
        max_repair_retries: int = 1,
    ):
        self.model = model
        self.temperature = temperature
        self.keep_alive = keep_alive
        self.max_repair_retries = max_repair_retries
        self._client = ollama.Client(host=host, timeout=request_timeout_s)
        self._system_prompt = load_system_prompt()

    @property
    def client(self) -> ollama.Client:
        """Exposed so native tool-calling mode can reuse this client
        instead of building a second one."""
        return self._client

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def propose(
        self, state: dict, goals: dict, history: dict, previous_feedback: dict | None = None
    ) -> Decision:
        """Return a validated Decision.

        Raises OllamaUnavailableError if the model can't be reached, or
        DecisionParseError if every reply was malformed. Callers fall back
        on either, though they may want to log them differently.

        previous_feedback is the last cycle's write result, or None on the
        first decision.
        """
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": build_user_prompt(state, goals, history, previous_feedback)},
        ]
        last_error = None
        for _ in range(self.max_repair_retries + 1):
            raw = self._complete(messages)
            try:
                return parse_decision(raw)
            except DecisionParseError as e:
                last_error = e
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": REPAIR_PROMPT_TEMPLATE.format(error=e)})
        raise last_error

    def _complete(self, messages: list) -> str:
        try:
            response = self._client.chat(
                model=self.model,
                messages=messages,
                format="json",
                keep_alive=self.keep_alive,
                options={"temperature": self.temperature},
            )
        except ConnectionError as e:
            # ollama-py raises the builtin ConnectionError when the host is
            # unreachable. A bad model name raises something else and is
            # deliberately not caught here; that's a config bug.
            raise OllamaUnavailableError(f"could not reach Ollama: {e}") from e
        except httpx.TransportError as e:
            # Timeouts aren't rewrapped into ConnectionError, so catch them
            # separately. A slow Ollama should fail like a refused one
            # rather than kill the run.
            raise OllamaUnavailableError(f"Ollama request failed: {e}") from e
        return response["message"]["content"]
