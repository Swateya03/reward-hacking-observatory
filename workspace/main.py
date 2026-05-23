"""
Workspace Server — Layer 0
FastAPI application exposing the workspace environment via MCP protocol.

Routes:
  GET  /health          → server health check
  GET  /session/create  → create a new isolated session
  POST /session/reset   → reset a session to its initial fixture state
  GET  /session/state   → get raw DB state (for verification/debugging)
  POST /mcp             → MCP protocol endpoint (tools/list, tools/call)

Run with:
  uvicorn workspace.main:app --reload --port 8000
"""

import logging

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from workspace.database.session import (
    create_session,
    delete_session,
    get_state_snapshot,
    init_db,
    list_fixtures,
    reset_session,
    session_exists,
)
from workspace.mcp_handler import handle_mcp_request

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Reward Hacking Observatory — Workspace Server",
    description=(
        "Simulated productivity workspace environment for "
        "agentic RL experiments. Exposes file system operations "
        "via MCP protocol."
    ),
    version="0.1.0"
)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Initialise the database on server start."""
    init_db()
    logger.info("Workspace server started")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint. Used by Docker Compose and tests."""
    return {
        "status": "healthy",
        "service": "workspace-server",
        "layer": 0,
        "available_fixtures": list_fixtures()
    }


# ── Session management ────────────────────────────────────────────────────────

@app.post("/session/create")
async def create_new_session(
    fixture: str = Query(default="default",
                         description="Fixture name to seed the session with")
):
    """
    Create a new isolated session seeded with fixture data.
    Returns the session_id to use in subsequent tool calls.

    This is env.reset() — gives a clean starting state.
    """
    available = list_fixtures()
    if fixture not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fixture '{fixture}'. "
                   f"Available: {available}"
        )
    session_id = create_session(fixture)
    return {
        "session_id": session_id,
        "fixture": fixture,
        "message": "Session created. Pass session_id as "
                   "x-session-id header in all tool calls."
    }


@app.post("/session/reset")
async def reset_existing_session(
    x_session_id: str = Header(..., description="Session to reset"),
    fixture: str = Query(default="default")
):
    """
    Reset an existing session back to its initial fixture state.
    All changes made during an episode are wiped.
    """
    if not session_exists(x_session_id):
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {x_session_id}"
        )
    reset_session(x_session_id, fixture)
    return {
        "session_id": x_session_id,
        "status": "reset",
        "fixture": fixture
    }


@app.delete("/session/delete")
async def delete_existing_session(
    x_session_id: str = Header(..., description="Session to delete")
):
    """Delete a session and all its data. Used for cleanup after episodes."""
    if not session_exists(x_session_id):
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {x_session_id}"
        )
    delete_session(x_session_id)
    return {"session_id": x_session_id, "status": "deleted"}


@app.get("/session/state")
async def get_session_state(
    x_session_id: str = Header(..., description="Session to inspect")
):
    """
    Get the raw current database state of a session.
    Used by reward functions and verifiers to check ground truth.
    NOT exposed to the agent — this is the verifier's view of the world.
    """
    if not session_exists(x_session_id):
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {x_session_id}"
        )
    state = get_state_snapshot(x_session_id)
    return state


# ── MCP protocol ─────────────────────────────────────────────────────────────

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """
    Main MCP protocol endpoint.
    Handles tools/list and tools/call JSON-RPC requests.
    Requires x-session-id header for tool calls.
    """
    return await handle_mcp_request(request)
