"""
rex.automation.activepieces
Generates valid Activepieces flow JSON exports.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from rex.config import WORKFLOWS_DIR

def build_activepieces_flow(name: str, trigger_type: str = "WEBHOOK") -> Dict[str, Any]:
    """
    Constructs an Activepieces flow export format.
    """
    flow = {
        "version": "1.0",
        "displayName": name,
        "trigger": {
            "name": "trigger",
            "type": "WEBHOOK",
            "displayName": "Catch Webhook",
            "settings": {
                "response": {
                    "status": 200,
                    "body": "{\"status\":\"received\"}"
                }
            },
            "nextAction": {
                "name": "step_1",
                "type": "CODE",
                "displayName": "Run Custom JavaScript/Python",
                "settings": {
                    "sourceCode": {
                        "packageJson": "{}",
                        "code": "export const code = async (inputs) => {\n  return { processed: true, data: inputs };\n};"
                    }
                }
            }
        }
    }
    return flow

def save_activepieces_flow(name: str, flow_data: Dict[str, Any]) -> Path:
    filename = f"activepieces_{name.lower().replace(' ', '_')}.json"
    target = WORKFLOWS_DIR / filename
    with open(target, "w", encoding="utf-8") as f:
        json.dump(flow_data, f, indent=2)
    return target
