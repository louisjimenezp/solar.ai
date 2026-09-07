#!/usr/bin/env python3
"""HTTP client for Solar Host — no imports from host_server (platform layer)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def host_url() -> str:
    host = os.environ.get("SOLAR_APP_HOST", "127.0.0.1")
    port = os.environ.get("SOLAR_APP_PORT", "9000")
    return f"http://{host}:{port}"


def request_json(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    *,
    timeout: float = 8,
) -> Tuple[int, Optional[Dict[str, Any]]]:
    url = f"{host_url()}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            parsed = json.loads(raw) if raw else {}
            payload = parsed if isinstance(parsed, dict) else None
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode()
            parsed = json.loads(raw) if raw else {}
            payload = parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, OSError):
            payload = None
        return int(exc.code), payload
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return 0, None


def get_json(path: str, *, timeout: float = 4) -> Optional[Dict[str, Any]]:
    status, data = request_json("GET", path, timeout=timeout)
    return data if status == 200 else None


def post_json(path: str, body: Optional[Dict[str, Any]] = None, *, timeout: float = 8) -> bool:
    status, _ = request_json("POST", path, body, timeout=timeout)
    return 200 <= status < 300


def last_assistant_text(detail: Optional[Dict[str, Any]]) -> str:
    if not detail:
        return ""
    messages = detail.get("messages") or []
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            text = str(message.get("text") or "").strip()
            if text:
                return text
    return ""


def transcript_ok(text: str) -> bool:
    cleaned = (text or "").strip()
    return bool(cleaned) and not cleaned.startswith("[voice]")


def app_bootstrap() -> Optional[Dict[str, Any]]:
    return get_json("/api/app/bootstrap")


def app_ensure_conversation(workspace: str, conversation_id: Optional[str] = None) -> Optional[str]:
    if conversation_id:
        quoted = urllib.parse.quote(workspace, safe="")
        status, _ = request_json(
            "GET",
            f"/api/app/conversations/{conversation_id}?workspace={quoted}",
            timeout=4,
        )
        if status == 200:
            return conversation_id
    status, data = request_json("POST", "/api/app/conversations", {"workspace": workspace}, timeout=8)
    if status == 200 and data and data.get("id"):
        return str(data["id"])
    return None


def app_send_turn(workspace: str, conversation_id: str, text: str, request_id: str) -> Optional[Dict[str, Any]]:
    status, data = request_json(
        "POST",
        f"/api/app/conversations/{conversation_id}/messages",
        {"workspace": workspace, "text": text, "request_id": request_id},
        timeout=95,
    )
    return data if status == 200 else None


def pending_approval_count() -> int:
    data = get_json("/api/approvals")
    if not data:
        return 0
    approvals = data.get("approvals", [])
    if not isinstance(approvals, list):
        return 0
    return sum(1 for a in approvals if isinstance(a, dict) and a.get("status") == "pending")


def list_workspaces() -> List[Dict[str, Any]]:
    data = get_json("/api/workspaces")
    if not data:
        return []
    workspaces = data.get("workspaces", [])
    return [w for w in workspaces if isinstance(w, dict)]


def switch_workspace(path: str) -> bool:
    return post_json("/api/workspaces/active", {"path": path})


def fetch_events(*, limit: int = 30, types: str) -> List[Dict[str, Any]]:
    data = get_json(f"/api/events?limit={limit}&types={types}")
    if not data:
        return []
    events = data.get("events", [])
    return [e for e in events if isinstance(e, dict)]
