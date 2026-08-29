"""ReAct loop mechanics, driven by a scripted model.

Gemini is replaced with a stub that returns a fixed sequence of responses, so
these tests verify the loop itself -- tool dispatch, trace construction, memory,
step limit -- without a network call or an API key. The MCP server and database
underneath are real.
"""

import asyncio
import dataclasses

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from mcp_db_agent import agent as agent_module
from mcp_db_agent import ratelimit
from mcp_db_agent.agent import DatabaseAgent
from mcp_db_agent.mcp_client import MCPToolbox


def _call(name, **args):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name=name, args=args))
        ])
    )])


def _thought_then_call(thought, name, **args):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[
            types.Part(text=thought, thought=True),
            types.Part(function_call=types.FunctionCall(name=name, args=args)),
        ])
    )])


def _answer(text):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[types.Part(text=text)])
    )])


class _FakeModels:
    """Stands in for client.aio.models: returns scripted responses, and raises
    any Exception placed in the script instead of returning it."""

    def __init__(self, script):
        self.script = list(script)
        self.turns = []

    async def generate_content(self, *, model, contents, config):
        self.turns.append(list(contents))
        # Repeat the last scripted response if the loop asks for more turns.
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


class _Aio:
    def __init__(self, models):
        self.models = models


class _FakeClient:
    def __init__(self, script):
        self.aio = _Aio(_FakeModels(script))


@pytest.fixture
def scripted(monkeypatch):
    """Install a fake Gemini client, pretend a key is configured, and lift the
    request pacing so loop tests are not throttled by the real limiter."""
    ratelimit.reset()
    monkeypatch.setattr(
        agent_module, "settings",
        dataclasses.replace(
            agent_module.settings, gemini_api_key="test-key", gemini_rpm=10_000
        ),
    )

    def _install(script):
        monkeypatch.setattr(agent_module.genai, "Client", lambda **kw: _FakeClient(script))

    return _install


@pytest.fixture
async def toolbox():
    async with MCPToolbox(transport="memory") as tb:
        yield tb


async def test_tool_declarations_mirror_the_mcp_schemas(toolbox, scripted):
    scripted([_answer("done")])
    agent = DatabaseAgent(toolbox)
    declared = {d.name for d in agent._declarations}
    assert declared == {t.name for t in toolbox.tools}

    run_select = next(d for d in agent._declarations if d.name == "run_select_query")
    assert "sql" in run_select.parameters_json_schema["properties"]


async def test_full_reason_act_observe_cycle(toolbox, scripted):
    scripted([
        _thought_then_call("I need the schema first.", "get_database_schema"),
        _thought_then_call(
            "Now I can count.", "run_select_query",
            sql="SELECT COUNT(*) AS n FROM students",
        ),
        _answer("There are 420 students on record."),
    ])
    result = await DatabaseAgent(toolbox).ask("How many students are there?")

    assert result.answer == "There are 420 students on record."
    assert result.tool_calls == 2
    assert result.sql_executed == ["SELECT COUNT(*) AS n FROM students"]

    kinds = [s.kind for s in result.steps]
    assert kinds == [
        "reason", "act", "observe",
        "reason", "act", "observe",
        "answer",
    ]

    observation = result.steps[5].result
    assert observation["rows"][0]["n"] == 420


async def test_blocked_write_is_observed_not_raised(toolbox, scripted):
    """A destructive tool call must come back as an observation the model can
    read, so it can apologise and move on rather than crashing the session."""
    scripted([
        _call("run_select_query", sql="DROP TABLE students"),
        _answer("That is not permitted; the database is read-only."),
    ])
    result = await DatabaseAgent(toolbox).ask("Delete all the students")

    observation = next(s for s in result.steps if s.kind == "observe").result
    assert observation["blocked"] is True
    assert "read-only guard" in observation["error"]
    assert "read-only" in result.answer


async def test_conversation_memory_persists_across_questions(toolbox, scripted):
    scripted([_answer("ok")])
    agent = DatabaseAgent(toolbox)
    await agent.ask("first question")
    await agent.ask("second question")

    texts = [
        part.text
        for content in agent._history
        for part in (content.parts or [])
        if part.text
    ]
    assert "first question" in texts and "second question" in texts

    agent.reset()
    assert agent._history == []


async def test_step_limit_stops_a_runaway_loop(toolbox, scripted):
    scripted([_call("list_tables")])  # never answers, always calls a tool
    result = await DatabaseAgent(toolbox).ask("loop forever")

    assert "Stopped after" in result.answer
    assert result.steps[-1].kind == "error"
    assert result.tool_calls == agent_module.settings.max_agent_steps


async def test_missing_api_key_raises_a_helpful_error(toolbox, monkeypatch):
    monkeypatch.setattr(
        agent_module, "settings",
        dataclasses.replace(agent_module.settings, gemini_api_key=""),
    )
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        DatabaseAgent(toolbox)


@pytest.fixture
def fast_sleep(monkeypatch):
    """Record retry waits and return immediately instead of really sleeping."""
    real_sleep = asyncio.sleep
    waits = []

    def _sleep(seconds):
        waits.append(seconds)
        return real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return waits


def _quota_error(retry_delay="2s"):
    return genai_errors.ClientError(429, {"error": {
        "code": 429, "message": "quota exceeded", "status": "RESOURCE_EXHAUSTED",
        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                     "retryDelay": retry_delay}],
    }})


def test_retry_delay_is_read_from_the_error_payload():
    assert agent_module._retry_after_seconds(_quota_error("30.2s")) == 30.2
    assert agent_module._retry_after_seconds(_quota_error("7s")) == 7.0


def test_retry_delay_absent_returns_none():
    err = genai_errors.ClientError(429, {"error": {"code": 429, "message": "quota"}})
    assert agent_module._retry_after_seconds(err) is None


async def test_rate_limit_is_retried_and_the_answer_still_arrives(
    toolbox, scripted, fast_sleep
):
    """A 429 on the first call must not surface to the user: the free tier
    returns them routinely, so the loop waits and tries again."""
    notices = []
    scripted([_quota_error("2s"), _answer("There are 420 students.")])
    agent = DatabaseAgent(toolbox, on_retry=lambda *a: notices.append(a))
    result = await agent.ask("How many students?")

    assert result.answer == "There are 420 students."
    assert fast_sleep == [3.0]  # 2s from RetryInfo + 1s of slack
    assert notices and notices[0][2] == "rate limited"


async def test_backoff_is_exponential_when_no_delay_is_supplied(
    toolbox, scripted, fast_sleep
):
    err = genai_errors.ClientError(503, {"error": {"code": 503, "message": "overloaded"}})
    scripted([err, err, _answer("ok")])
    assert (await DatabaseAgent(toolbox).ask("q")).answer == "ok"
    assert fast_sleep == [2.0, 3.0]  # 2**0+1, 2**1+1


async def test_non_retryable_error_is_raised_immediately(toolbox, scripted, fast_sleep):
    """A bad key is 400: retrying would only waste the user's time."""
    bad_key = genai_errors.ClientError(400, {"error": {"code": 400, "message": "bad key"}})
    scripted([bad_key])
    with pytest.raises(genai_errors.ClientError):
        await DatabaseAgent(toolbox).ask("anything")
    assert fast_sleep == []


async def test_retries_give_up_after_max_retries(toolbox, scripted, fast_sleep, monkeypatch):
    monkeypatch.setattr(
        agent_module, "settings",
        dataclasses.replace(agent_module.settings, gemini_api_key="test-key", max_retries=3),
    )
    scripted([_quota_error("1s")])  # always throttled
    with pytest.raises(genai_errors.ClientError):
        await DatabaseAgent(toolbox).ask("anything")
    assert len(fast_sleep) == 2  # 3 attempts means 2 waits


def _daily_quota_error(limit="20", model="gemini-2.5-flash"):
    """A per-day exhaustion. Note it carries the same ~30s retryDelay as a
    per-minute one, which is exactly why the quotaId has to be inspected."""
    return genai_errors.ClientError(429, {"error": {
        "code": 429, "message": "quota exceeded", "status": "RESOURCE_EXHAUSTED",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                "quotaValue": limit, "quotaDimensions": {"model": model}}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "30s"},
        ],
    }})


def _minute_quota_error():
    return genai_errors.ClientError(429, {"error": {
        "code": 429, "message": "quota exceeded", "status": "RESOURCE_EXHAUSTED",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                "quotaValue": "5", "quotaDimensions": {"model": "gemini-2.5-flash"}}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "30s"},
        ],
    }})


def test_per_day_and_per_minute_quota_errors_are_distinguished():
    daily = agent_module.daily_quota_exhausted(_daily_quota_error())
    assert daily["limit"] == "20" and daily["model"] == "gemini-2.5-flash"
    # A per-minute 429 looks almost identical but must not be treated as fatal.
    assert agent_module.daily_quota_exhausted(_minute_quota_error()) is None
    assert agent_module.daily_quota_exhausted(_quota_error()) is None


async def test_daily_quota_falls_back_to_the_next_model(toolbox, scripted, fast_sleep):
    """The whole point of the fallback: a spent model must not end the session
    when another model still has allowance."""
    switches = []
    scripted([_daily_quota_error(), _answer("There are 420 students.")])
    agent = DatabaseAgent(toolbox, on_retry=lambda *a: switches.append(a))
    result = await agent.ask("How many students?")

    assert result.answer == "There are 420 students."
    expected = agent_module.settings.gemini_fallback_models[0]
    assert agent.model == expected                # first configured fallback
    assert f"switching to {expected}" in switches[0][2]
    assert "out of daily quota" in switches[0][2]
    assert fast_sleep == [], "a daily cap must not be waited out"


async def test_daily_quota_is_not_retried_on_the_same_model(toolbox, scripted, fast_sleep):
    """With no fallbacks configured, it fails fast rather than burning attempts
    on a quota that will not reset for hours."""
    monkey = dataclasses.replace(
        agent_module.settings, gemini_api_key="test-key", gemini_rpm=10_000,
        gemini_fallback_models=(),
    )
    scripted([_daily_quota_error()])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(agent_module, "settings", monkey)
        with pytest.raises(agent_module.DailyQuotaExhausted, match="20 requests per day"):
            await DatabaseAgent(toolbox).ask("anything")
    assert fast_sleep == []


async def test_fallback_stops_when_every_model_is_exhausted(toolbox, scripted, fast_sleep):
    scripted([_daily_quota_error()])  # every model reports exhausted
    with pytest.raises(agent_module.DailyQuotaExhausted):
        await DatabaseAgent(toolbox).ask("anything")


async def test_retired_model_404_falls_back_instead_of_failing(
    toolbox, scripted, fast_sleep
):
    """Google retires models for new API keys; the old name then 404s forever.
    That must switch model, not retry and not abort."""
    gone = genai_errors.ClientError(404, {"error": {
        "code": 404, "status": "NOT_FOUND",
        "message": "This model models/gemini-2.5-flash is no longer available to "
                   "new users. Please update your code to use models/gemini-3.6-flash",
    }})
    switches = []
    scripted([gone, _answer("There are 420 students.")])
    agent = DatabaseAgent(toolbox, model="gemini-2.5-flash",
                          on_retry=lambda *a: switches.append(a))
    result = await agent.ask("How many students?")

    assert result.answer == "There are 420 students."
    assert agent.model == agent_module.settings.gemini_fallback_models[0]
    assert fast_sleep == [], "a retired model must not be waited on"
    assert "not available to this key" in switches[0][2]


async def test_404_with_no_fallbacks_left_raises_model_unavailable(toolbox, scripted):
    gone = genai_errors.ClientError(404, {"error": {"code": 404, "message": "gone"}})
    scripted([gone])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(agent_module, "settings", dataclasses.replace(
            agent_module.settings, gemini_api_key="test-key",
            gemini_rpm=10_000, gemini_fallback_models=()))
        with pytest.raises(agent_module.ModelUnavailable, match="not available"):
            await DatabaseAgent(toolbox).ask("anything")


async def test_large_observations_are_truncated_before_going_back_to_the_model():
    payload = {"rows": [{"value": "x" * 200} for _ in range(200)]}
    truncated = agent_module._truncate(payload, limit=500)
    assert truncated["truncated"] is True
    assert len(truncated["preview"]) < 600
