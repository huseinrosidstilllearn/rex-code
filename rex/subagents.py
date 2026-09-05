"""
rex.subagents
Sub-agent framework for Rex Code.
Provides specialized dinosaur sub-agents operating in read-only (Plan) mode.
"""

from typing import Optional, Dict, Any
from rex.config import get_active_mode, set_active_mode
from rex.core import RexAgent


class SubAgent:
    """Base class for specialized Rex Code sub-agents."""
    name: str = "generic"
    role: str = "Generic Sub-Agent"
    color: str = "green"
    icon_ascii: str = "  (o.o)\n  /(_)\\"
    web_icon: str = "/static/icons/brachio.svg"
    system_prompt: str = "You are a sub-agent of Rex Code."

    def __init__(self, max_depth: int = 1):
        self._max_depth = max_depth
        self._depth = 0

    def run(self, task: str, context: str = "") -> str:
        if self._depth >= self._max_depth:
            return f"[{self.name}] DIBLOKIR: delegasi rekursif tidak diizinkan."
        self._depth += 1
        prev_mode = get_active_mode()
        # Sub-agents operate strictly in read-only plan mode
        set_active_mode("plan")
        try:
            agent = RexAgent()
            prompt = (
                f"You are {self.name}, {self.role} in Rex Code.\n"
                f"System Directive:\n{self.system_prompt}\n\n"
                f"Context:\n{context}\n\n"
                f"Task:\n{task}"
            )
            return agent.run(prompt)
        finally:
            set_active_mode(prev_mode or "plan")
            self._depth -= 1


class BrachioAgent(SubAgent):
    name = "brachio"
    role = "Code Reviewer & General Analyzer"
    color = "green"
    icon_ascii = r"  _\_/\\n ( o o )\\n  (_/\_"
    web_icon = "/static/icons/brachio.svg"
    system_prompt = (
        "You are Brachio, the long-necked analysis sub-agent. "
        "Review code, evaluate quality, find logical gaps, and propose robust solutions. "
        "You operate in read-only plan mode; do not attempt to write or modify files directly."
    )


class RaptorAgent(SubAgent):
    name = "raptor"
    role = "Bug Hunter & Traceback Specialist"
    color = "yellow"
    icon_ascii = "  /\\_/\\\n ( o.o )\n  > ^ <"
    web_icon = "/static/icons/raptor.svg"
    system_prompt = (
        "You are Raptor, the agile bug-hunting sub-agent. "
        "Analyze tracebacks, locate root causes of runtime errors, and diagnose faulty logic. "
        "Operate strictly in read-only plan mode."
    )


class TrikeAgent(SubAgent):
    name = "trike"
    role = "Security Auditor & Vulnerability Scanner"
    color = "red"
    icon_ascii = "  /▲▲▲\\\n ( ⊙.⊙ )\n  ---v---"
    web_icon = "/static/icons/trike.svg"
    system_prompt = (
        "You are Trike, the armored security audit sub-agent. "
        "Scan code for hardcoded secrets, injection vectors, unsafe practices, and vulnerabilities. "
        "Operate strictly in read-only plan mode."
    )


class PteroAgent(SubAgent):
    name = "ptero"
    role = "Architecture & Documentation Specialist"
    color = "cyan"
    icon_ascii = "  /\\~/\\\\/\n ( o-o )\n  v---v"
    web_icon = "/static/icons/ptero.svg"
    system_prompt = (
        "You are Ptero, the flying architecture and documentation sub-agent. "
        "Review project structure, module dependencies, and draft comprehensive technical documentation. "
        "Operate strictly in read-only plan mode."
    )


class DiloAgent(SubAgent):
    name = "dilo"
    role = "Quality & Anti-Slop Auditor"
    color = "magenta"
    icon_ascii = "  /|~~|\\\n ( o_o )\n  (:::)"
    web_icon = "/static/icons/dilo.svg"
    system_prompt = (
        "You are Dilo, the quality and AI-slop auditing sub-agent. "
        "Detect verbose boilerplate, redundant comments, AI buzzword fluff, and poor maintainability. "
        "Operate strictly in read-only plan mode."
    )


SUBAGENTS: Dict[str, SubAgent] = {
    "brachio": BrachioAgent(),
    "raptor": RaptorAgent(),
    "trike": TrikeAgent(),
    "ptero": PteroAgent(),
    "dilo": DiloAgent(),
}


def get_subagent(name: str) -> Optional[SubAgent]:
    return SUBAGENTS.get(name.lower())
