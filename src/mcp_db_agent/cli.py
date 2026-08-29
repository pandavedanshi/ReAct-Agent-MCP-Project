"""Terminal interface.

    dbagent chat                 interactive REPL, shows the full ReAct trace
    dbagent ask "question"       single question, then exit
    dbagent query "SELECT ..."   run SQL through MCP with no LLM involved
    dbagent tools                list what the MCP server advertises
    dbagent schema               print the schema the agent sees

`query` and `tools` need no API key, so the MCP and database layers can be
demonstrated on a machine that has no Gemini credentials.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

import typer
from google.genai import errors as genai_errors
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .agent import AgentResult, DatabaseAgent, ModelUnusable
from .config import settings
from .mcp_client import MCPToolbox

app = typer.Typer(add_completion=False, help="MCP-enabled database query agent.")

# Windows terminals default to a legacy codepage (cp1252 here). A single
# character the model emits outside that set would otherwise raise
# UnicodeEncodeError part-way through printing an answer.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

console = Console()

STEP_STYLE = {
    "reason": ("REASON", "yellow"),
    "act": ("ACT", "cyan"),
    "observe": ("OBSERVE", "green"),
    "answer": ("ANSWER", "bold white"),
    "error": ("ERROR", "red"),
}


def _render_rows(columns: list, rows: list) -> Optional[Table]:
    if not rows:
        return None
    table = Table(show_header=True, header_style="bold magenta", box=None, pad_edge=False)
    for col in columns:
        table.add_column(str(col), overflow="fold")
    for row in rows[:15]:
        table.add_row(*["" if row.get(c) is None else str(row.get(c)) for c in columns])
    return table


def _condense(text: str, limit: int = 260) -> str:
    """Shorten a thought for terminal display.

    Gemini's thought summaries run to several paragraphs, which buries the ACT
    and OBSERVE lines the trace exists to show. The full text is still carried
    in the step, so the web UI can render all of it.
    """
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    stop = max(cut.rfind(". "), cut.rfind("? "))
    return (cut[:stop + 1] if stop > limit // 2 else cut.rstrip()) + " […]"


def _render_step(step) -> None:
    label, colour = STEP_STYLE.get(step.kind, (step.kind.upper(), "white"))

    if step.kind == "reason":
        console.print(f"[{colour}]{label}[/] {_condense(step.content)}")

    elif step.kind == "act":
        console.print(f"[{colour}]{label}[/]    [bold]{step.tool}[/]")
        sql = (step.arguments or {}).get("sql")
        if sql:
            console.print(Syntax(sql, "sql", theme="ansi_dark", word_wrap=True))
        elif step.arguments:
            console.print(f"        {json.dumps(step.arguments)}")

    elif step.kind == "observe":
        result = step.result if isinstance(step.result, dict) else {}
        timing = f"[dim]({step.duration_ms:.0f} ms)[/]"
        if "error" in result:
            console.print(f"[red]{label}[/] {result['error']} {timing}")
        elif "rows" in result:
            index = "index" if result.get("used_index") else "[red]full scan[/]"
            console.print(
                f"[{colour}]{label}[/] {result.get('row_count', 0)} rows in "
                f"{result.get('execution_ms', 0)} ms ({index}) {timing}"
            )
            rendered = _render_rows(result.get("columns", []), result.get("rows", []))
            if rendered:
                console.print(rendered)
        else:
            summary = ", ".join(sorted(result.keys())) if result else str(step.result)[:120]
            console.print(f"[{colour}]{label}[/] received {summary} {timing}")

    elif step.kind == "answer":
        console.print()
        console.print(Panel(step.content, title="Answer", border_style="green"))

    else:
        console.print(f"[{colour}]{label}[/] {step.content}")


def _render_result(result: AgentResult) -> None:
    for step in result.steps:
        _render_step(step)
    console.print(
        f"[dim]{result.tool_calls} tool calls · {result.total_ms:.0f} ms total[/]\n"
    )


def _on_retry(attempt: int, wait: float, reason: str) -> None:
    """Render the three kinds of delay the agent reports.

    attempt 0 means the agent paced itself or switched model; a positive
    attempt means a request actually failed and is being retried.
    """
    if attempt == 0 and wait <= 0:
        console.print(f"[yellow]SWITCH[/] {reason}")
    elif attempt == 0:
        console.print(f"[yellow]QUEUE[/]  {reason} — next slot in {wait:.0f}s")
    else:
        console.print(f"[yellow]RETRY[/]  {reason} (attempt {attempt}) in {wait:.0f}s")


async def _ask(agent: DatabaseAgent, question: str) -> bool:
    """Ask one question, rendering API failures as a message rather than a
    traceback. Returns False if the session should stop."""
    try:
        _render_result(await agent.ask(question))
    except ModelUnusable as exc:
        console.print(Panel(str(exc), title="No usable model", border_style="red"))
        return False
    except genai_errors.APIError as exc:
        detail = {
            429: "Gemini quota exhausted. The free tier allows only a few requests "
                 "per minute and each question spends several. Wait a minute, or add "
                 "more models to GEMINI_FALLBACK_MODELS in .env.",
            400: "Gemini rejected the request. Check that GEMINI_API_KEY in .env is a "
                 "valid AI Studio key (https://aistudio.google.com/apikey).",
            403: "Gemini denied access. The key may be restricted or the API not "
                 "enabled for this project.",
        }.get(exc.code, f"Gemini returned HTTP {exc.code}: {exc.message}")
        console.print(Panel(detail, title="Gemini API error", border_style="red"))
        return False
    return True


async def _run_agent(questions: list, interactive: bool) -> None:
    async with MCPToolbox() as toolbox:
        console.print(
            f"[dim]MCP session up ({toolbox.transport_kind} transport) · "
            f"{len(toolbox.tools)} tools · model {settings.gemini_model}[/]\n"
        )
        try:
            agent = DatabaseAgent(toolbox, on_retry=_on_retry)
        except RuntimeError as exc:
            console.print(Panel(str(exc), title="Configuration", border_style="red"))
            raise typer.Exit(1)

        for question in questions:
            console.rule(f"[bold]{question}")
            if not await _ask(agent, question):
                raise typer.Exit(1)

        if not interactive:
            return

        console.print("[dim]Ask a question, or 'exit' to quit, 'reset' to clear memory.[/]")
        while True:
            try:
                question = console.input("[bold cyan]you >[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]bye[/]")
                return
            if not question:
                continue
            if question.lower() in {"exit", "quit"}:
                console.print("[dim]bye[/]")
                return
            if question.lower() == "reset":
                agent.reset()
                console.print("[dim]Conversation memory cleared.[/]")
                continue
            console.print()
            await _ask(agent, question)


@app.command()
def chat(question: Optional[str] = typer.Argument(None, help="Optional opening question")):
    """Start an interactive session with the agent."""
    asyncio.run(_run_agent([question] if question else [], interactive=True))


@app.command()
def ask(question: str = typer.Argument(..., help="Question to answer, in quotes")):
    """Answer one question and exit."""
    asyncio.run(_run_agent([question], interactive=False))


@app.command()
def query(sql: str = typer.Argument(..., help="A SELECT statement, in quotes")):
    """Run SQL directly through the MCP server. No LLM, no API key needed."""

    async def _run():
        async with MCPToolbox() as toolbox:
            result = await toolbox.call("run_select_query", {"sql": sql})
            if "error" in result:
                console.print(Panel(result["error"], title="Rejected", border_style="red"))
                raise typer.Exit(1)
            console.print(
                f"[dim]{result['row_count']} rows · {result['execution_ms']} ms · "
                f"{'index used' if result['used_index'] else 'full scan'}[/]"
            )
            table = _render_rows(result["columns"], result["rows"])
            if table:
                console.print(table)

    asyncio.run(_run())


@app.command()
def tools():
    """List the tools the MCP server advertises."""

    async def _run():
        async with MCPToolbox() as toolbox:
            table = Table(title=f"MCP tools ({toolbox.transport_kind} transport)")
            table.add_column("Tool", style="cyan", no_wrap=True)
            table.add_column("Arguments", style="magenta")
            table.add_column("Description", overflow="fold")
            for spec in toolbox.tools:
                params = ", ".join((spec.input_schema.get("properties") or {}).keys()) or "-"
                first_line = spec.description.split("\n")[0]
                table.add_row(spec.name, params, first_line)
            console.print(table)

    asyncio.run(_run())


@app.command()
def schema():
    """Print the schema exactly as the agent receives it."""

    async def _run():
        async with MCPToolbox() as toolbox:
            data = await toolbox.call("get_database_schema", {})
            for table_info in data["tables"]:
                cols = ", ".join(
                    f"{c['name']}{'*' if c['primary_key'] else ''}" for c in table_info["columns"]
                )
                console.print(
                    f"[bold cyan]{table_info['table']}[/] "
                    f"[dim]({table_info['row_count']} rows)[/]\n  {cols}"
                )
            console.print("\n[bold]Foreign keys[/]")
            for edge in data["relationships"]:
                console.print(f"  {edge['from']}.{edge['column']} -> {edge['to']}")

    asyncio.run(_run())


@app.command()
def resource():
    """Read the schema://university MCP resource (protocol demonstration)."""

    async def _run():
        async with MCPToolbox() as toolbox:
            console.print(JSON(await toolbox.read_schema_resource()))

    asyncio.run(_run())


if __name__ == "__main__":
    app()
