"""
rex.anti_slop
Integration of the global 'no-ai-slop' skill principles.
Protects output from AI clichÃ©s, robotic fluff, and empty corporate buzzwords.
"""

import re
from typing import List, Dict, Tuple

# Outright banned words and buzzwords
BANNED_WORDS = [
    "delve", "foster", "leverage", "utilize", "facilitate", "empower", "streamline",
    "robust", "cutting-edge", "paradigm shift", "game changer", "this is huge",
    "this changes everything", "tapestry", "realm", "beacon", "multifaceted",
    "meticulous", "intricate", "paramount", "transformative", "elevate", "embark",
    "supercharge", "harness", "ever-evolving", "game-changing", "seamless", "seamlessly"
]

# Throat-clearing openers
THROAT_CLEARING = [
    r"^(Here'?s the thing[:,]?)",
    r"^(Here'?s what I mean[:,]?)",
    r"^(Let me be clear[:,]?)",
    r"^(I'?ll be honest[:,]?)",
    r"^(The uncomfortable truth is[:,]?)",
    r"^(At the end of the day[:,]?)",
    r"^(It'?s worth noting that)",
    r"^(It'?s important to note that)",
    r"^(In today'?s world[:,]?)",
    r"^(In the fast-paced world of)"
]

# Summary-recap endings
SUMMARY_RECAPS = [
    r"(In conclusion[,:].*)$",
    r"(Ultimately[,:].*)$",
    r"(Overall[,:].*)$",
    r"(To sum up[,:].*)$"
]

SYSTEM_PROMPT_ANTI_SLOP = """
[ANTI-SLOP PRINCIPLES - STRICT MANDATE]
1. ZERO AI CLICHÃ‰S: Never use banned words: delve, foster, leverage, utilize, facilitate, empower, streamline, robust, cutting-edge, paradigm shift, game changer, tapestry, realm, beacon, multifaceted, meticulous, intricate, transformative, elevate, supercharge, harness, ever-evolving, seamless.
2. NO THROAT-CLEARING: Never start with "Here's the thing", "Let me be clear", "The truth is", "In today's digital era". State the point directly.
3. NO SUMMARY RECAPS: Do not end with "In conclusion", "Ultimately", "Overall". End on the next concrete action or takeaway.
4. ACTIVE & DIRECT: Use active verbs. State facts, numbers, and concrete code mechanisms rather than abstract fluff.
5. PRESERVE HUMAN VOICE: Speak sharp, natural, and helpful in friendly Indonesian.
"""

def detect_slop(text: str) -> List[Dict[str, str]]:
    """
    Detect AI slop patterns in a given text string.
    Returns a list of detected issues with line content and recommendations.
    """
    findings = []
    lines = text.split("\n")

    for idx, line in enumerate(lines, 1):
        # Check banned words
        for bw in BANNED_WORDS:
            pattern = rf"\b{re.escape(bw)}\b"
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "line_number": idx,
                    "type": "Banned Buzzword",
                    "match": bw,
                    "snippet": line.strip(),
                    "suggestion": f"Hapus atau ganti kata '{bw}' dengan padanan yang lebih konkret dan langsung."
                })

        # Check throat-clearing openers
        for tc in THROAT_CLEARING:
            if re.search(tc, line.strip(), re.IGNORECASE):
                findings.append({
                    "line_number": idx,
                    "type": "Throat-Clearing Opener",
                    "match": tc,
                    "snippet": line.strip(),
                    "suggestion": "Hapus pembuka bertele-tele dan langsung sampaikan inti kalimat."
                })

    return findings

def clean_slop(text: str) -> Tuple[str, List[str]]:
    """
    Basic automated cleaner to strip throat-clearing and common buzzwords.
    Returns cleaned text and a changelog list.
    """
    changes = []
    cleaned = text

    for bw in ["delve into", "leverage", "utilize", "streamline", "supercharge", "foster"]:
        pattern = rf"\b{re.escape(bw)}\b"
        if re.search(pattern, cleaned, re.IGNORECASE):
            # Replace with simpler direct words
            replacements = {
                "delve into": "pelajari",
                "leverage": "gunakan",
                "utilize": "pakai",
                "streamline": "sederhanakan",
                "supercharge": "percepat",
                "foster": "bangun"
            }
            rep = replacements.get(bw.lower(), "gunakan")
            cleaned = re.sub(pattern, rep, cleaned, flags=re.IGNORECASE)
            changes.append(f"Mengganti '{bw}' dengan '{rep}'.")

    return cleaned, changes
