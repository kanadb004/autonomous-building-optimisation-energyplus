"""LLM agent core (§4.1-§4.2, §4.4): prompt construction, the Ollama call,
and malformed-JSON repair-retry. v1.1 scope, fixed by docs/PROJECT_PLAN.md
§4.1 (not revisited): structured-output mode only -- this module builds one
prompt from state already gathered by the caller and returns one parsed
JSON decision. It does not call MCP tools itself and knows nothing about
asyncio; the MCP client loop that gathers state and submits the decision
lives in `agent_runner.py`, so this module stays unit-testable without a
live sim or a live model.

Each call is a fresh, stateless conversation (§6 trap #6) -- callers must
not accumulate messages across decisions; a short rolling history is passed
in as data (`get_recent_history`'s output), not as prior chat turns.
"""

import json
from pathlib import Path

import httpx
import ollama

from abms.decision_parsing import Decision, DecisionParseError, parse_decision

REPO_ROOT = Path(__file__).resolve().parents[3]
SYSTEM_PROMPT_PATH = REPO_ROOT / "prompts" / "controller_system.md"


class OllamaUnavailableError(RuntimeError):
    """Raised when Ollama cannot be reached at all (connection refused) --
    distinct from a malformed reply, per §4.4's two separate fallback
    paths. Callers should fall back immediately rather than retrying, since
    a downed Ollama server won't recover mid-retry."""


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text()


def build_user_prompt(state: dict, goals: dict, history: dict) -> str:
    """Packs the three MCP read-tool responses into one compact JSON blob
    for the model (§4.1: "the runner...packs the state into the prompt")."""
    payload = {
        "current_state": state,
        "goals_and_constraints": goals,
        "recent_history": history,
    }
    return (
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
    """Model-agnostic (§1.2): everything model-specific is the `model`
    string and `host`, both overridable via config/env with no code
    change (see `abms.config.llm_agent_config`)."""

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

    def propose(self, state: dict, goals: dict, history: dict) -> Decision:
        """Returns a validated `Decision`. Raises `OllamaUnavailableError`
        if the model can't be reached at all, or `DecisionParseError` if
        every reply (original call + repair retries) was malformed --
        callers treat both as "use the fallback for this decision" but may
        want to log them differently (§4.4)."""
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": build_user_prompt(state, goals, history)},
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
            # ollama-py raises the builtin ConnectionError (verified against
            # the installed 0.6.2 client) when it can't reach the host at
            # all -- a bad model name or other server-side error surfaces as
            # a different exception type and is deliberately NOT caught
            # here, since that's a config bug, not the runtime-robustness
            # case §4.4 asks for.
            raise OllamaUnavailableError(f"could not reach Ollama: {e}") from e
        except httpx.TransportError as e:
            # Unlike a refused connection, ollama-py does NOT rewrap timeouts
            # (read/connect/pool) into ConnectionError -- verified against
            # the installed client's source, which only catches
            # httpx.ConnectError. A slow/overloaded Ollama (e.g. a cold
            # model load, or CPU contention from something else on the
            # machine) must fail the same way a refused connection does,
            # not crash the whole run.
            raise OllamaUnavailableError(f"Ollama request failed: {e}") from e
        return response["message"]["content"]
