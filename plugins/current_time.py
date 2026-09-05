"""
Plugin contoh: current_time
Menunjukkan kontrak plugin Rex Code — cukup definisikan PLUGIN_TOOLS.

Tool ini berjalan tanpa dependency tambahan dan cross-platform
(Windows / Linux / macOS).
"""

import datetime
import zoneinfo
from typing import Optional


def _current_time(timezone: Optional[str] = None) -> str:
    try:
        tz = zoneinfo.ZoneInfo(timezone) if timezone else datetime.datetime.now().astimezone().tzinfo
        now = datetime.datetime.now(tz)
    except Exception:
        return f"Error: zona waktu '{timezone}' tidak dikenal. Gunakan nama IANA (misal: Asia/Jakarta)."
    return f"{now.strftime('%Y-%m-%d %H:%M:%S %Z')} (zona: {tz})"


PLUGIN_TOOLS = [
    {
        "name": "current_time",
        "description": "Mengembalikan waktu dan tanggal lokal saat ini. Parameter timezone opsional (nama IANA, misal 'Asia/Jakarta', 'UTC').",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "Zona waktu IANA (opsional). Kosong = zona lokal mesin.",
                }
            },
            "required": [],
        },
        "handler": _current_time,
    }
]