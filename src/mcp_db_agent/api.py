"""HTTP bridge between the React frontend and the agent.

The MCP session is opened once at startup and shared by every request, so the
server subprocess is not re-launched per question.

Endpoints that do not need an LLM (/api/query, /api/schema, /api/tools) work
without a Gemini key; only /api/ask requires one.

Run:
    uvicorn mcp_db_agent.api:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

from .agent import DatabaseAgent, ModelUnusable
from .config import settings
from .mcp_client import MCPToolbox

# One MCP session for the process, plus one agent per browser session so that
# follow-up questions keep their conversation history.
_toolbox: MCPToolbox | None = None
_agents: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _toolbox
    _toolbox = MCPToolbox()
    await _toolbox.__aenter__()
    try:
        yield
    finally:
        await _toolbox.__aexit__(None, None, None)
        _toolbox = None
        _agents.clear()


app = FastAPI(title="MCP Database Query Agent", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _toolbox_or_503() -> MCPToolbox:
    if _toolbox is None:
        raise HTTPException(503, "MCP session is not available.")
    return _toolbox


def _agent_for(session_id: str) -> DatabaseAgent:
    if session_id not in _agents:
        try:
            _agents[session_id] = DatabaseAgent(_toolbox_or_503())
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
    return _agents[session_id]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=64)


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=8000)
    max_rows: int = Field(default=200, ge=1, le=500)


@app.get("/api/health")
async def health() -> dict:
    toolbox = _toolbox_or_503()
    return {
        "status": "ok",
        "transport": toolbox.transport_kind,
        "tools": len(toolbox.tools),
        "model": settings.gemini_model,
        "llm_configured": settings.has_gemini_key,
    }


@app.get("/api/tools")
async def tools() -> dict:
    toolbox = _toolbox_or_503()
    return {
        "tools": [
            {"name": t.name, "description": t.description, "schema": t.input_schema}
            for t in toolbox.tools
        ]
    }


@app.get("/api/schema")
async def schema() -> dict:
    return await _toolbox_or_503().call("get_database_schema", {})


@app.get("/api/query-log")
async def query_log(limit: int = 20) -> dict:
    return await _toolbox_or_503().call("get_query_log", {"limit": limit})


@app.post("/api/query")
async def run_query(request: QueryRequest) -> dict:
    """Execute SQL directly through MCP, bypassing the LLM."""
    result = await _toolbox_or_503().call(
        "run_select_query", {"sql": request.sql, "max_rows": request.max_rows}
    )
    if "error" in result:
        # 400, not 500: a rejected or malformed query is a client-side mistake.
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/ask")
async def ask(request: AskRequest) -> dict:
    """Run the full ReAct loop and return the answer plus its trace."""
    agent = _agent_for(request.session_id)
    try:
        result = await agent.ask(request.question)
    except ModelUnusable as exc:
        raise HTTPException(429, str(exc)) from exc
    except genai_errors.APIError as exc:
        # Pass Gemini's status through so the UI can distinguish "slow down"
        # from "your key is wrong" instead of showing a generic 500.
        raise HTTPException(
            429 if exc.code == 429 else 502,
            "Gemini quota exhausted — the free tier allows only a few requests per "
            "minute. Wait a moment and try again."
            if exc.code == 429 else f"Gemini API error {exc.code}: {exc.message}",
        ) from exc
    return result.to_dict()


@app.post("/api/reset")
async def reset(session_id: str = "default") -> dict:
    """Clear one session's conversation memory."""
    if session_id in _agents:
        _agents[session_id].reset()
    return {"status": "reset", "session_id": session_id}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
