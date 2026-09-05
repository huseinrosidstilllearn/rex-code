"""
app.py
Rex Code Web Dashboard Backend (FastAPI + WebSockets).
Provides a visual interface like Devin / OpenCode for chat, Plan/Build toggle, and file management.
"""

import os
import sys
import json
import asyncio
import queue
from pathlib import Path
from typing import Dict, Any

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from rex.voice import transcribe_audio, engine_status, get_voice_config, VoiceTranscriptionError
from rex.webhooks import handle_github_event, webhook_settings, WebhookError

from rex.config import (
    load_config, save_config, get_active_mode, set_active_mode,
    normalize_config, VALID_MODES,
    WORKSPACE_DIR, WORKFLOWS_DIR
)
from rex.core import RexAgent, StepEvent
from rex.anti_slop import detect_slop, clean_slop
from rex.automation.n8n_builder import create_webhook_ai_workflow
from rex.sessions import session_store

app = FastAPI(title="Rex Code Web Dashboard")

# Mount web assets
web_dir = Path(__file__).resolve().parent / "web"
web_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

class ConfigUpdate(BaseModel):
    active_provider: str = None
    active_model: str = None
    active_mode: str = None
    anti_slop_enabled: bool = None

class SlopAuditRequest(BaseModel):
    text: str

class SessionCreate(BaseModel):
    provider: str = None
    model: str = None

@app.get("/")
async def root():
    return FileResponse(web_dir / "index.html")

@app.get("/api/config")
async def get_config():
    return normalize_config(load_config())

@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    cfg = load_config()
    if update.active_provider:
        cfg["active_provider"] = update.active_provider
    if update.active_model:
        cfg["active_model"] = update.active_model
    if update.active_mode:
        mode = update.active_mode.lower()
        if mode not in VALID_MODES:
            raise HTTPException(status_code=400, detail="Mode harus 'plan' atau 'build'")
        cfg["active_mode"] = mode
    if update.anti_slop_enabled is not None:
        cfg["anti_slop_enabled"] = update.anti_slop_enabled
    cfg = normalize_config(cfg)
    save_config(cfg)
    return cfg

@app.get("/api/files")
async def list_files():
    workspace_files = []
    for p in WORKSPACE_DIR.glob("**/*"):
        if p.is_file():
            workspace_files.append(str(p.relative_to(WORKSPACE_DIR)))

    workflow_files = []
    for p in WORKFLOWS_DIR.glob("**/*"):
        if p.is_file():
            workflow_files.append(str(p.relative_to(WORKFLOWS_DIR)))

    return {
        "workspace": workspace_files,
        "workflows": workflow_files
    }

@app.get("/api/file")
async def get_file_content(path: str, source: str = "workspace"):
    base = WORKFLOWS_DIR if source == "workflows" else WORKSPACE_DIR
    target = (base / path).resolve()
    if not target.is_relative_to(base) or not target.exists():
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    with open(target, "r", encoding="utf-8", errors="ignore") as f:
        return {"content": f.read(), "filename": target.name}

@app.post("/api/webhook/github")
async def github_webhook(request: Request):
    """GitHub webhook receiver: run Rex Code on PR events (see rex/webhooks.py)."""
    if not webhook_settings().get("enabled", True):
        return JSONResponse({"status": "disabled"}, status_code=404)
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event = request.headers.get("X-GitHub-Event", "")
    try:
        result = await asyncio.to_thread(handle_github_event, event, payload_bytes, signature)
    except WebhookError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=403)
    return JSONResponse(result)

@app.get("/api/voice/config")
async def voice_config():
    cfg = get_voice_config()
    return {"engine": cfg["engine"], "engines": engine_status()}

@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Transcribe an uploaded voice note (webm/ogg/wav/mp3) to text."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File audio kosong")
    mime_type = file.content_type or "audio/webm"
    try:
        text = await asyncio.to_thread(transcribe_audio, data, mime_type)
    except VoiceTranscriptionError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception:
        raise HTTPException(status_code=500, detail="Transkripsi gagal. Periksa logs/rex.log dan konfigurasi voice di config.json.")
    return {"text": text, "engine": get_voice_config()["engine"]}

@app.post("/api/anti-slop/audit")
async def audit_anti_slop(req: SlopAuditRequest):
    findings = detect_slop(req.text)
    cleaned, changes = clean_slop(req.text)
    return {
        "findings": findings,
        "cleaned": cleaned,
        "changes": changes
    }

@app.post("/api/n8n/create-template")
async def create_n8n_template(name: str = "Otomasi_Baru"):
    path = create_webhook_ai_workflow(name=name)
    return {"status": "success", "file": path.name, "path": str(path)}

@app.get("/api/sessions")
async def list_sessions():
    return session_store.list()

@app.post("/api/sessions")
async def create_session(request: SessionCreate = SessionCreate()):
    cfg = normalize_config(load_config())
    provider = request.provider or cfg["active_provider"]
    model = request.model or cfg["active_model"]
    return session_store.create(provider, model)

@app.get("/api/sessions/{session_id}")
async def load_session(session_id: str):
    try:
        data = session_store.load(session_id)
        data["stats"] = {
            "messages": len(data.get("messages", [])),
            "characters": sum(len(str(item.get("content", ""))) for item in data.get("messages", [])),
        }
        return data
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    try:
        session_store.delete(session_id)
        return {"status": "deleted"}
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

# WebSocket endpoint for streaming chat
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    agent = None
    active_session_id = None
    incoming: asyncio.Queue = asyncio.Queue()

    async def receive_messages():
        try:
            while True:
                await incoming.put(json.loads(await websocket.receive_text()))
        except WebSocketDisconnect:
            await incoming.put(None)

    receiver = asyncio.create_task(receive_messages())

    try:
        while True:
            payload = await incoming.get()
            if payload is None:
                break
            if payload.get("type") == "abort":
                if agent:
                    agent.abort()
                continue
            user_msg = payload.get("message", "")
            requested_session_id = payload.get("session_id")
            requested_mode = payload.get("mode")

            if not user_msg.strip():
                continue

            if not requested_session_id:
                cfg = normalize_config(load_config())
                requested_session_id = session_store.create(
                    cfg["active_provider"], cfg["active_model"]
                )["id"]
            try:
                session_store.load(requested_session_id)
            except (FileNotFoundError, ValueError):
                await websocket.send_text(json.dumps({
                    "type": "error", "data": "Percakapan tidak ditemukan"
                }))
                continue

            if agent is None or active_session_id != requested_session_id:
                agent = RexAgent(session_id=requested_session_id)
                active_session_id = requested_session_id

            if requested_mode:
                try:
                    set_active_mode(requested_mode)
                except ValueError:
                    pass

            loop = asyncio.get_running_loop()
            events: queue.Queue = queue.Queue()

            def send_step_event(event: StepEvent):
                # Called from the worker thread; hand events to the event loop via queue
                events.put(event)

            def run_agent():
                return agent.run(user_msg, on_step=send_step_event)

            # Run the agent off the event loop so the server stays responsive
            task = loop.run_in_executor(None, run_agent)

            while True:
                try:
                    event = await asyncio.wait_for(
                        loop.run_in_executor(None, events.get), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    while not incoming.empty():
                        control = incoming.get_nowait()
                        if control is None:
                            agent.abort()
                        elif control.get("type") == "abort":
                            agent.abort()
                    if task.done():
                        break
                    continue
                await websocket.send_text(json.dumps({
                    "type": event.event_type,
                    "data": event.data
                }))

            try:
                response = await task
            except Exception:
                response = "Terjadi kesalahan saat menjalankan agen. Periksa logs/rex.log."

            await websocket.send_text(json.dumps({
                "type": "final_response",
                "data": response,
                "session_id": active_session_id,
            }))

    except WebSocketDisconnect:
        pass
    finally:
        receiver.cancel()
