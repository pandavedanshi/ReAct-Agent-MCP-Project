"""The ReAct agent.

One iteration of the loop is:

    Reason      Gemini thinks about what it still needs to know
    Act         it emits a function call, which we forward over MCP
    Observe     the tool result is appended to the conversation

The loop repeats until the model answers in plain text instead of calling a
tool, or until MAX_AGENT_STEPS is reached.

Two properties are worth noting for the architecture:

  * Tool declarations are generated from the MCP server's advertised schemas at
    runtime. Adding an @mcp.tool to server.py makes it available to the model
    with no change here -- that is the decoupling the protocol buys.
  * The model is never given a database path, connection string, or credential.
    It can only name a tool and supply arguments.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from .config import settings
from .mcp_client import MCPToolbox, ToolSpec
from .ratelimit import default_rpm, limiter_for

# Status codes worth retrying. 429 is the common one: Gemini's free tier allows
# only a handful of requests per minute, and one ReAct loop spends several.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ModelUnusable(Exception):
    """This model cannot serve the request, and waiting will not change that.

    Raised for the two situations where switching model is the only useful
    response: the day's allowance is spent, or the model is not available to
    this key at all. Both are terminal for the current model but survivable for
    the session.

    `reason` is a short phrase for the switch message; str(exc) is the full
    explanation shown when no fallback remains.
    """

    reason = "is unusable"

    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        if reason:
            self.reason = reason


class DailyQuotaExhausted(ModelUnusable):
    """The model's per-day free-tier allowance is gone; retrying cannot help."""

    reason = "out of daily quota"


class ModelUnavailable(ModelUnusable):
    """Google returned 404 for the model - commonly one retired for new keys."""

    reason = "not available to this key"

SYSTEM_PROMPT = """\
You are a database analyst answering questions about a university's records.

You cannot see the database. You can only inspect and query it through the tools
provided. Follow this loop:

1. REASON about what you need. On your first tool call of a conversation, call
   get_database_schema -- never guess table or column names.
2. ACT by calling exactly one tool.
3. OBSERVE the result, then either call another tool or give the final answer.

Rules:
- Write standard SQLite SELECT statements. Any INSERT, UPDATE, DELETE, DROP,
  ALTER, ATTACH or PRAGMA will be rejected by the server's read-only guard, and
  you should refuse such requests yourself and explain that access is read-only.
- Derive JOIN conditions from the `relationships` edge list in the schema.
- If a query errors, read the error and fix the SQL; do not repeat it unchanged.
- If run_select_query reports used_index=false with a slow execution_ms, call
  explain_query_plan and rewrite the query to filter on an indexed column.
- Aggregate in SQL (COUNT, AVG, GROUP BY). Do not pull raw rows and count them
  yourself.
- Group and join on primary keys, not on human names. Two people can share a
  name, so `GROUP BY prof_id` is correct where `WHERE last_name = '...'` is not.
- Never invent numbers. Every figure in your answer must come from a tool result.

Final answer: two or three sentences in plain English, quoting the actual values
you retrieved. Do not restate the SQL -- the interface displays it separately.
"""


@dataclass
class Step:
    """One entry in the visible ReAct trace."""

    kind: str                  # "reason" | "act" | "observe" | "answer" | "error"
    content: str = ""
    tool: str | None = None
    arguments: dict | None = None
    result: Any = None
    duration_ms: float = 0.0


@dataclass
class AgentResult:
    question: str
    answer: str
    steps: list = field(default_factory=list)
    sql_executed: list = field(default_factory=list)
    total_ms: float = 0.0
    tool_calls: int = 0

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "sql_executed": self.sql_executed,
            "total_ms": round(self.total_ms, 1),
            "tool_calls": self.tool_calls,
            "steps": [
                {
                    "kind": s.kind,
                    "content": s.content,
                    "tool": s.tool,
                    "arguments": s.arguments,
                    "result": s.result,
                    "duration_ms": round(s.duration_ms, 2),
                }
                for s in self.steps
            ],
        }


def _to_function_declaration(spec: ToolSpec) -> types.FunctionDeclaration:
    """Translate an MCP tool schema into a Gemini function declaration.

    MCP publishes plain JSON Schema, which Gemini accepts verbatim through
    parameters_json_schema -- so no field-by-field mapping is needed and the two
    sides cannot drift apart.
    """
    schema = dict(spec.input_schema or {"type": "object", "properties": {}})
    schema.pop("title", None)             # Pydantic adds these; Gemini ignores them
    schema.pop("additionalProperties", None)
    return types.FunctionDeclaration(
        name=spec.name,
        description=spec.description[:1024],
        parameters_json_schema=schema,
    )


def _truncate(value: Any, limit: int = 6000) -> Any:
    """Keep a large tool result from blowing out the context window."""
    text = json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    return {"truncated": True, "preview": text[:limit] + " ...[truncated]"}


def _error_details(exc: genai_errors.APIError) -> list:
    details = exc.details if isinstance(exc.details, dict) else {}
    return (details.get("error") or {}).get("details") or []


def _retry_after_seconds(exc: genai_errors.APIError) -> float | None:
    """Read Google's suggested retry delay out of a RetryInfo detail block."""
    for entry in _error_details(exc):
        delay = entry.get("retryDelay") if isinstance(entry, dict) else None
        if isinstance(delay, str):
            match = re.match(r"([\d.]+)s", delay)
            if match:
                return float(match.group(1))
    return None


def daily_quota_exhausted(exc: genai_errors.APIError) -> dict | None:
    """Detect a per-day quota exhaustion, as opposed to a per-minute one.

    Both arrive as 429 with a retryDelay of about 30 seconds, but a daily cap
    does not reset for hours. Retrying it wastes the user's time and, because
    rejected requests still count, can consume the next day's allowance. The
    two are told apart by the quotaId, which ends in PerDay... or PerMinute...
    """
    for entry in _error_details(exc):
        if "QuotaFailure" not in (entry.get("@type") or ""):
            continue
        for violation in entry.get("violations") or []:
            quota_id = violation.get("quotaId") or ""
            if "PerDay" in quota_id:
                return {
                    "quota_id": quota_id,
                    "limit": violation.get("quotaValue"),
                    "model": (violation.get("quotaDimensions") or {}).get("model"),
                }
    return None


class DatabaseAgent:
    """Drives the Reason-Act-Observe loop against the MCP toolbox."""

    def __init__(
        self,
        toolbox: MCPToolbox,
        model: str | None = None,
        on_retry: Callable | None = None,
    ):
        if not settings.has_gemini_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Create a .env file with "
                "GEMINI_API_KEY=... (free key: https://aistudio.google.com/apikey), "
                "or use `dbagent query \"<SQL>\"` to exercise the MCP server without an LLM."
            )
        self.toolbox = toolbox
        self.model = model or settings.gemini_model
        # Each model has its own daily allowance, so an exhausted one can be
        # stepped over rather than ending the session. Only used on a per-day
        # 429 -- never to dodge a transient error.
        self._fallbacks = [m for m in settings.gemini_fallback_models if m != self.model]
        self._exhausted: set = set()
        self.client = genai.Client(api_key=settings.gemini_api_key)
        # Notified as (attempt, wait_seconds, reason) so an interface can tell the
        # user why nothing is happening instead of appearing to hang.
        self.on_retry = on_retry
        # Shared per model across the process: every agent in the API server
        # draws from the same quota, so each must not assume it owns all of it.
        self._limiter = limiter_for(self.model, self._rpm())
        self._declarations = [_to_function_declaration(t) for t in toolbox.tools]
        # History persists across ask() calls: this is the contextual memory that
        # lets follow-up questions ("now break that down by year") work.
        self._history: list = []

    def reset(self) -> None:
        self._history = []

    def _rpm(self) -> int:
        """Explicit override, else the free-tier rate for this model family."""
        return settings.gemini_rpm or default_rpm(self.model)

    def _on_pace_wait(self, delay: float) -> None:
        if self.on_retry:
            self.on_retry(0, delay, f"pacing {self.model} to {self._rpm()} req/min")

    @property
    def _config(self) -> types.GenerateContentConfig:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.0,  # deterministic SQL generation
            tools=[types.Tool(function_declarations=self._declarations)],
            # We run the loop ourselves so every step can be shown to the user;
            # the SDK's built-in auto-calling would hide it.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        # Thinking models can expose their reasoning, which becomes the "Reason"
        # line of the trace. Older Flash models reject the field outright.
        if self._supports_thinking():
            config.thinking_config = types.ThinkingConfig(include_thoughts=True)
        return config

    def _supports_thinking(self) -> bool:
        # Allowlisting version numbers would silently drop the reasoning trace
        # every time Google ships a new model, so only the known-legacy families
        # that reject the field are excluded.
        return not any(tag in self.model for tag in ("1.0", "1.5", "2.0"))

    def _switch_to_fallback(self, reason: str) -> bool:
        """Move to the next usable model. False if none remain."""
        self._exhausted.add(self.model)
        for candidate in self._fallbacks:
            if candidate in self._exhausted:
                continue
            previous, self.model = self.model, candidate
            self._limiter = limiter_for(self.model, self._rpm())
            if self.on_retry:
                self.on_retry(0, 0.0, f"{previous} {reason}, switching to {candidate}")
            return True
        return False

    async def _generate(self):
        """One Gemini call, falling back to another model if this one is spent
        for the day. Delegates the per-call work to _generate_once."""
        while True:
            try:
                return await self._generate_once()
            except ModelUnusable as exc:
                if not self._switch_to_fallback(exc.reason):
                    raise

    async def _generate_once(self):
        """One Gemini call: paced, then retried if it still fails.

        Two mechanisms, in order. The limiter keeps us under the quota so a 429
        is rare; the retry recovers when one happens anyway (another process
        sharing the key, or a server-side hiccup).

        Uses the async client so waiting does not block the event loop — which
        matters for the FastAPI server, where other requests continue while one
        session is queued.
        """
        last: Exception | None = None
        for attempt in range(settings.max_retries):
            try:
                await self._limiter.acquire(on_wait=self._on_pace_wait)
                return await self.client.aio.models.generate_content(
                    model=self.model, contents=self._history, config=self._config
                )
            except genai_errors.APIError as exc:
                last = exc
                # Google retires models for new keys; the old name then 404s
                # forever, so this must switch model rather than retry.
                if exc.code == 404:
                    raise ModelUnavailable(
                        f"{self.model} is not available to this API key. {exc.message}"
                    ) from exc
                # A daily cap will not clear within any sane retry window.
                daily = daily_quota_exhausted(exc)
                if daily:
                    raise DailyQuotaExhausted(
                        f"Daily free-tier quota exhausted for {daily['model'] or self.model}: "
                        f"{daily['limit']} requests per day. This resets tomorrow "
                        "(midnight Pacific). Switch models with GEMINI_MODEL in .env — "
                        "each model has its own daily allowance — or use "
                        '`dbagent query "<SQL>"`, which needs no LLM.'
                    ) from exc
                if exc.code not in RETRYABLE_STATUS or attempt == settings.max_retries - 1:
                    raise
                # Honour Google's own RetryInfo when present; otherwise back off
                # exponentially, capped so a stuck loop still finishes.
                wait = _retry_after_seconds(exc) or min(2 ** attempt, 30)
                wait = min(wait + 1, 65)  # +1s of slack against clock skew
                if self.on_retry:
                    reason = "rate limited" if exc.code == 429 else f"HTTP {exc.code}"
                    self.on_retry(attempt + 1, wait, reason)
                await asyncio.sleep(wait)
        raise last  # unreachable: the final attempt re-raises above

    async def ask(self, question: str) -> AgentResult:
        started = time.perf_counter()
        result = AgentResult(question=question, answer="")
        self._history.append(
            types.Content(role="user", parts=[types.Part.from_text(text=question)])
        )

        for _ in range(settings.max_agent_steps):
            response = await self._generate()

            candidate = (response.candidates or [None])[0]
            if candidate is None or candidate.content is None:
                result.answer = "The model returned no content. Try rephrasing the question."
                break

            parts = candidate.content.parts or []
            calls = [p.function_call for p in parts if p.function_call]

            # Reasoning arrives either as thought parts or as text preceding a call.
            for part in parts:
                if part.text and part.thought:
                    result.steps.append(Step(kind="reason", content=part.text.strip()))
                elif part.text and calls:
                    result.steps.append(Step(kind="reason", content=part.text.strip()))

            self._history.append(candidate.content)

            if not calls:
                # No tool call means the model is answering.
                answer = "".join(p.text for p in parts if p.text and not p.thought).strip()
                result.answer = answer or "No answer produced."
                result.steps.append(Step(kind="answer", content=result.answer))
                break

            # Gemini may request several tools in one turn; each response part
            # must be returned in the same order.
            response_parts = []
            for call in calls:
                args = dict(call.args or {})
                result.steps.append(Step(kind="act", tool=call.name, arguments=args))
                result.tool_calls += 1
                if call.name == "run_select_query" and "sql" in args:
                    result.sql_executed.append(args["sql"])

                call_started = time.perf_counter()
                try:
                    observation = await self.toolbox.call(call.name, args)
                except Exception as exc:
                    observation = {"error": f"Tool call failed: {exc}"}
                elapsed = (time.perf_counter() - call_started) * 1000

                result.steps.append(Step(
                    kind="observe", tool=call.name, result=observation, duration_ms=elapsed
                ))
                response_parts.append(types.Part.from_function_response(
                    name=call.name, response={"result": _truncate(observation)}
                ))

            self._history.append(types.Content(role="user", parts=response_parts))
        else:
            result.answer = (
                f"Stopped after {settings.max_agent_steps} steps without reaching an "
                "answer. Try a narrower question."
            )
            result.steps.append(Step(kind="error", content=result.answer))

        result.total_ms = (time.perf_counter() - started) * 1000
        return result
