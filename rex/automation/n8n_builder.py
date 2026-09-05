"""
rex.automation.n8n_builder
Generates valid, importable n8n workflow JSON files.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from rex.config import WORKFLOWS_DIR

def build_n8n_workflow(name: str, description: str = "", nodes: List[Dict[str, Any]] = None, connections: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Constructs a standard n8n workflow schema.
    """
    workflow = {
        "name": name,
        "nodes": nodes or [],
        "connections": connections or {},
        "active": False,
        "settings": {
            "executionOrder": "v1"
        },
        "versionId": "1",
        "meta": {
            "templateCredsSetupCompleted": True,
            "description": description or "Dihasilkan secara otomatis oleh Rex Code"
        }
    }
    return workflow

def save_n8n_workflow(name: str, workflow_data: Dict[str, Any]) -> Path:
    """
    Saves the n8n workflow to workflows/ folder.
    """
    filename = f"n8n_{name.lower().replace(' ', '_')}.json"
    target = WORKFLOWS_DIR / filename
    with open(target, "w", encoding="utf-8") as f:
        json.dump(workflow_data, f, indent=2)
    return target

def create_webhook_ai_workflow(name: str, webhook_path: str = "webhook-input", ai_prompt: str = "") -> Path:
    """
    Creates a pre-configured, common n8n workflow: Webhook -> Gemini AI Analysis -> Response / Storage.
    """
    nodes = [
        {
            "parameters": {
                "httpMethod": "POST",
                "path": webhook_path,
                "responseMode": "onReceived",
                "responseData": "allEntries"
            },
            "name": "Webhook Trigger",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 1.1,
            "position": [240, 300],
            "webhookId": f"rex-{webhook_path}"
        },
        {
            "parameters": {
                "jsCode": "// Ekstraksi data masuk dari Webhook\nconst inputData = $input.first().json.body || $input.first().json;\nreturn {\n  timestamp: new Date().toISOString(),\n  payload: inputData,\n  summaryNeeded: true\n};"
            },
            "name": "Preprocess Data",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [460, 300]
        },
        {
            "parameters": {
                "model": "gemini-1.5-flash",
                "options": {}
            },
            "name": "Google Gemini Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatGoogleGemini",
            "typeVersion": 1,
            "position": [680, 480]
        },
        {
            "parameters": {
                "promptType": "define",
                "text": ai_prompt or "Analisis data berikut dan berikan intisari serta rekomendasi tindakan:\n{{ $json.payload }}"
            },
            "name": "AI Agent / LLM Chain",
            "type": "@n8n/n8n-nodes-langchain.chainLlm",
            "typeVersion": 1.4,
            "position": [680, 300]
        },
        {
            "parameters": {
                "respondWith": "json",
                "responseBody": "{\n  \"status\": \"success\",\n  \"result\": \"{{ $json.text }}\",\n  \"processedBy\": \"Rex Code n8n Automation\"\n}"
            },
            "name": "Respond to Webhook",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1.1,
            "position": [920, 300]
        }
    ]

    connections = {
        "Webhook Trigger": {
            "main": [[{"node": "Preprocess Data", "type": "main", "index": 0}]]
        },
        "Preprocess Data": {
            "main": [[{"node": "AI Agent / LLM Chain", "type": "main", "index": 0}]]
        },
        "Google Gemini Model": {
            "ai_languageModel": [[{"node": "AI Agent / LLM Chain", "type": "ai_languageModel", "index": 0}]]
        },
        "AI Agent / LLM Chain": {
            "main": [[{"node": "Respond to Webhook", "type": "main", "index": 0}]]
        }
    }

    wf = build_n8n_workflow(name=name, description="Alur kerja AI Otomatisasi (Webhook ke Gemini)", nodes=nodes, connections=connections)
    return save_n8n_workflow(name, wf)
