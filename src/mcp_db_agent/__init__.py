"""MCP-enabled database query agent.

Layers, from the user inward:

    cli.py / api.py   interfaces (terminal, HTTP for the React UI)
    agent.py          ReAct loop over Gemini function calling
    mcp_client.py     MCP client — the boundary the agent may not cross
    server.py         FastMCP server exposing the database as tools
    database.py       the only module that opens a SQLite connection
    guard.py          static rejection of anything that is not a SELECT
"""

__version__ = "1.0.0"
