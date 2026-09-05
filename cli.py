"""
cli.py
Rex Code Terminal CLI (Claude Code Style).
Interactive terminal with Plan/Build mode, OpenCode model switcher, and rich formatting.
"""

import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.prompt import Prompt
from rich.text import Text

from rex.config import (
    load_config, save_config, get_active_mode, set_active_mode,
    get_active_provider_info, WORKSPACE_DIR, WORKFLOWS_DIR
)
from rex.core import RexAgent, StepEvent
from rex.anti_slop import detect_slop, clean_slop
from rex.automation.n8n_builder import create_webhook_ai_workflow
from rex.sessions import session_store
from rex.cli_spinner import spinner, BRAND_GREEN
from rex.voice import transcribe_audio, VoiceTranscriptionError
from rex.subagents import get_subagent

console = Console()


# ANSI Shadow block-letter "REX CODE" banner in brand green
_BANNER_LINES = (
    "██████╗ ███████╗██╗  ██╗     ██████╗ ██████╗ ██████╗ ███████╗",
    "██╔══██╗██╔════╝╚██╗██╔╝    ██╔════╝██╔═══██╗██╔══██╗██╔════╝",
    "██████╔╝█████╗   ╚███╔╝     ██║     ██║   ██║██║  ██║█████╗  ",
    "██╔══██╗██╔══╝   ██╔██╗     ██║     ██║   ██║██║  ██║██╔══╝  ",
    "██║  ██║███████╗██╔╝ ██╗    ╚██████╗╚██████╔╝██████╔╝███████╗",
    "╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝",
)


def print_banner():
    with tool_spinner("Loading..."):
        banner = "\n".join(f"[bold #22C55E]{line}[/bold #22C55E]" for line in _BANNER_LINES)
        banner += "\n[dim]                 Autonomous AI Coding & Workflow Agent  v1.0.0[/dim]"
        banner += "\n[dim]                      \"You think it, Rex builds it.\"[/dim]"
        console.print(banner)


def print_welcome_panel():
    """Display a rich welcome panel with mode, provider, model, workspace, and What's New."""
    pid, _, model = get_active_provider_info()
    mode = get_active_mode().upper()
    mode_color = "blue" if mode == "PLAN" else "green"

    info_table = Table.grid(padding=(0, 2))
    info_table.add_column(style="bold")
    info_table.add_column()
    info_table.add_row("Active Mode:", f"[bold {mode_color}]{mode}[/bold {mode_color}]")
    info_table.add_row("Provider:", f"[cyan]{pid}[/cyan]")
    info_table.add_row("Active Model:", f"[magenta]{model}[/magenta]")
    info_table.add_row("Workspace:", f"[dim]{WORKSPACE_DIR}[/dim]")

    whats_new = (
        "[bold green]What's New in v1.0.0:[/bold green]\n"
        "• [bold]Dinosaur Sub-agents[/bold]: Specialized read-only advisors\n"
        "  - [green]Brachio[/green] (Reviewer), [yellow]Raptor[/yellow] (Bug Hunter), [red]Trike[/red] (Security)\n"
        "  - [cyan]Ptero[/cyan] (Arch & Docs), [magenta]Dilo[/magenta] (Quality & Anti-Slop)\n"
        "• [bold]Strict Plan Mode Safeguards[/bold]: All delegate sub-agents are analysis-only\n"
        "• [bold]Visual Restyle[/bold]: Polished block-letter CLI banner and matching SVGs"
    )

    content = Table.grid(padding=(1, 0))
    content.add_row(info_table)
    content.add_row("")
    content.add_row(whats_new)

    panel = Panel(
        content,
        title="[bold #22C55E]Welcome to Rex Code CLI[/bold #22C55E]",
        border_style="#22C55E",
        expand=False,
    )
    console.print(panel)


def tool_spinner(text: str):
    """Context manager: shows a green dino spinner around a tool call."""
    return spinner(console=console, text=text, color=BRAND_GREEN)

def show_help():
    table = Table(title="Daftar Perintah Rex Code", show_header=True, header_style="bold magenta")
    table.add_column("Perintah", style="bold green", width=18)
    table.add_column("Deskripsi", style="white")
    table.add_row("/plan", "Beralih ke Mode PLAN (Perencanaan aman tanpa modifikasi file)")
    table.add_row("/build", "Beralih ke Mode BUILD (Eksekusi otonom, penulisan kode, auto-debug)")
    table.add_row("/models", "Ganti Model atau Provider (Gemini, 9router, OmniRoute, Local)")
    table.add_row("/n8n", "Generate template workflow otomasi n8n (JSON siap import)")
    table.add_row("/anti-slop", "Audit dan bersihkan teks dari buzzword & pola klise AI")
    table.add_row("/settings", "Ubah konfigurasi interaktif (mode, anti-slop, stream, voice, max-steps)")
    table.add_row("/scheduler", "Lihat daftar jobs dan trigger manual")
    table.add_row("/voice", "Voice input (Whisper): rekam suara, langsung jadi instruksi")
    table.add_row("/files", "Lihat daftar file di workspace/")
    table.add_row("/reset", "Reset riwayat percakapan")
    table.add_row("/sessions", "Lihat sesi lokal")
    table.add_row("/new", "Buat sesi baru")
    table.add_row("/use <id>", "Lanjutkan sesi")
    table.add_row("/delete <id>", "Hapus sesi")
    table.add_row("/help", "Tampilkan bantuan ini")
    table.add_row("/exit", "Keluar dari Rex Code")
    console.print(table)

def handle_models_switch():
    cfg = load_config()
    providers = cfg.get("providers", {})

    table = Table(title="Penyedia Model Tersedia", show_header=True)
    table.add_column("ID", style="bold yellow")
    table.add_column("Nama Provider", style="cyan")
    table.add_column("Model Aktif", style="green")

    for pid, pdata in providers.items():
        table.add_row(pid, pdata.get("name", pid), pdata.get("model", ""))
    console.print(table)

    choice = Prompt.ask("Pilih ID Provider", choices=list(providers.keys()), default=cfg.get("active_provider", "gemini"))
    cfg["active_provider"] = choice
    pdata = providers[choice]

    avail = pdata.get("available_models", [pdata.get("model")])
    if len(avail) > 1:
        console.print(f"[dim]Pilihan model: {', '.join(avail)}[/dim]")
        m_choice = Prompt.ask("Pilih Nama Model", default=avail[0])
        cfg["active_model"] = m_choice
        cfg["providers"][choice]["model"] = m_choice
    else:
        cfg["active_model"] = avail[0]

    save_config(cfg)
    console.print(f"[bold green]âœ“ Provider aktif diubah ke: {choice} ({cfg['active_model']})[/bold green]")

def handle_settings():
    cfg = load_config()
    while True:
        table = Table(title="Settings", show_header=True, header_style="bold magenta")
        table.add_column("Kunci", style="bold yellow")
        table.add_column("Nilai", style="white")
        table.add_row("mode", cfg.get("active_mode", "plan"))
        table.add_row("anti_slop_enabled", str(cfg.get("anti_slop_enabled", True)))
        table.add_row("stream_enabled", str(cfg.get("stream_enabled", True)))
        table.add_row("voice.engine", cfg.get("voice", {}).get("engine", "auto"))
        table.add_row("max_steps", str(cfg.get("max_steps", 25)))
        console.print(table)
        choice = Prompt.ask("Ubah setting (mode / anti-slop / stream / voice / max-steps / done)", choices=["mode", "anti-slop", "stream", "voice", "max-steps", "done"], default="done")
        if choice == "done":
            break
        elif choice == "mode":
            m = Prompt.ask("Mode", choices=["plan", "build"], default=cfg.get("active_mode", "plan"))
            cfg["active_mode"] = m
        elif choice == "anti-slop":
            v = Prompt.ask("Anti-slop enabled", choices=["true", "false"], default=str(cfg.get("anti_slop_enabled", True)).lower())
            cfg["anti_slop_enabled"] = v == "true"
        elif choice == "stream":
            v = Prompt.ask("Stream enabled", choices=["true", "false"], default=str(cfg.get("stream_enabled", True)).lower())
            cfg["stream_enabled"] = v == "true"
        elif choice == "voice":
            v = Prompt.ask("Voice engine", choices=["auto", "openai", "local"], default=cfg.get("voice", {}).get("engine", "auto"))
            cfg.setdefault("voice", {})["engine"] = v
        elif choice == "max-steps":
            v = Prompt.ask("Max steps", default=str(cfg.get("max_steps", 25)))
            try:
                cfg["max_steps"] = int(v)
            except ValueError:
                console.print("[red]Angka tidak valid.[/red]")
                continue
    save_config(cfg)
    console.print(f"[bold green]âœ“ Settings disimpan.[/bold green]")


def handle_anti_slop_audit():
    text = Prompt.ask("Masukkan teks atau kalimat yang ingin diaudit dari AI-Slop")
    findings = detect_slop(text)
    if not findings:
        console.print("[bold green]âœ“ Teks bersih! Tidak ditemukan kata klise atau AI slop.[/bold green]")
    else:
        console.print(f"[bold yellow]Ditemukan {len(findings)} indikasi AI Slop:[/bold yellow]")
        for f in findings:
            console.print(f"- [red]{f['type']}[/red] (Baris {f['line_number']}): {f['match']} -> [dim]{f['suggestion']}[/dim]")

        cleaned, changes = clean_slop(text)
        if changes:
            console.print("\n[bold cyan]Hasil Rekomendasi Bersih:[/bold cyan]")
            console.print(f"[white]{cleaned}[/white]")

def handle_voice_input() -> str:
    """Record microphone audio, transcribe with Whisper, return the text."""
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        console.print("[red]Voice input membutuhkan package tambahan.[/red] Jalankan: [cyan]pip install sounddevice numpy[/cyan]")
        return ""

    sample_rate = 16000
    chunks = []

    def callback(indata, frames, time_info, status):
        chunks.append(indata.copy())

    console.print("[cyan]🎤 Merekam... Tekan Enter untuk berhenti. [/cyan]")
    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", callback=callback):
            console.input()
    except Exception as exc:
        console.print(f"[red]Gagal mengakses mikrofon: {exc}[/red]")
        return ""

    if not chunks:
        console.print("[dim]Tidak ada audio terekam.[/dim]")
        return ""

    import io
    import wave

    audio = np.concatenate(chunks)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio.tobytes())

    try:
        with tool_spinner("Menyadap suara (Whisper)..."):
            text = transcribe_audio(buffer.getvalue(), "audio/wav")
    except VoiceTranscriptionError as exc:
        console.print(f"[red]{exc}[/red]")
        return ""

    text = text.strip()
    if not text:
        console.print("[dim]Tidak ada teks terdeteksi dari rekaman.[/dim]")
        return ""
    console.print(f"[dim]Transkripsi:[/dim] {text}")
    return text



def step_callback(event: StepEvent):
    if event.event_type == "stream_delta":
        console.print(str(event.data), end="", markup=False, highlight=False)
    elif event.event_type == "thought":
        console.print(Panel(Markdown(event.data), title="Rex Berpikir", border_style="dim blue"))
    elif event.event_type == "tool_call":
        name = event.data.get("name")
        args = event.data.get("args")
        console.print(f"Tool: [cyan]{name}[/cyan]({args})", style=f"bold {BRAND_GREEN}")
    elif event.event_type == "tool_result":
        name = event.data.get("name")
        res = str(event.data.get("result", ""))
        if name.startswith("delegate_to_"):
            sub_name = name[len("delegate_to_"):]
            sub = get_subagent(sub_name)
            if sub:
                ascii_face = sub.icon_ascii
                color = sub.color
                role = sub.role
                ascii_lines = ascii_face.split("\n")
                panel_text = "\n".join(f"[bold {color}]{line}[/bold {color}]" for line in ascii_lines)
                panel_text += f"\n\n[bold {color}]{sub.name.upper()} REPORT ({role})[/bold {color}]\n"
                panel_text += "─" * 40 + "\n\n"
                panel_text += res
                console.print(Panel(panel_text, title=f"Hasil Tool: {name}", border_style=color))
                return
        snippet = res if len(res) < 300 else res[:300] + "... (dipotong)"
        console.print(Panel(snippet, title=f"Hasil Tool: {name}", border_style=BRAND_GREEN))
    elif event.event_type == "error":
        err = str(event.data.get("error", ""))
        console.print(Panel(err, title="Error", border_style="red"))
    elif event.event_type == "mode_switch":
        mode = event.data.get("mode", "?")
        console.print(f"Beralih ke Mode {mode.upper()}", style="bold blue")
    elif event.event_type == "done":
        console.print("Selesai.", style=f"bold {BRAND_GREEN}")

def handle_scheduler():
    from rex.scheduler import get_scheduler
    scheduler = get_scheduler()
    jobs = scheduler.get_job_status()
    if not jobs:
        console.print("[dim]Tidak ada job yang terdaftar.[/dim]")
        return
    table = Table(title="Scheduler Jobs", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="bold yellow")
    table.add_column("Cron", style="cyan")
    table.add_column("Prompt", style="white")
    table.add_column("Mode", style="green")
    table.add_column("Enabled", style="green")
    table.add_column("Last Run", style="dim")
    table.add_column("Next Run", style="dim")
    for job in jobs:
        table.add_row(
            job.get("id", ""),
            job.get("cron", ""),
            job.get("prompt", "")[:60],
            job.get("mode", ""),
            "Y" if job.get("enabled") else "N",
            job.get("last_run") or "-",
            job.get("next_run") or "-",
        )
    console.print(table)
    choice = Prompt.ask("Masukkan job ID untuk trigger manual (kosongkan untuk batal)", default="")
    if choice.strip():
        try:
            res = scheduler.trigger_job(choice.strip())
            console.print(f"[bold green]âœ“ Job '{choice.strip()}' di-trigger.[/bold green]")
            if res.get("output"):
                console.print(Panel(str(res.get("output")), title="Output", border_style="dim green"))
        except Exception as exc:
            console.print(f"[red]Gagal trigger job: {exc}[/red]")


        console.print(str(event.data), end="", markup=False, highlight=False)
    elif event.event_type == "thought":
        console.print(Panel(Markdown(event.data), title="Rex Berpikir", border_style="dim blue"))
    elif event.event_type == "tool_call":
        name = event.data.get("name")
        args = event.data.get("args")
        console.print(f"Tool: [cyan]{name}[/cyan]({args})", style=f"bold {BRAND_GREEN}")
    elif event.event_type == "tool_result":
        name = event.data.get("name")
        res = str(event.data.get("result", ""))
        snippet = res if len(res) < 300 else res[:300] + "... (dipotong)"
        console.print(Panel(snippet, title=f"Hasil Tool: {name}", border_style=BRAND_GREEN))
    elif event.event_type == "error":
        err = str(event.data.get("error", ""))
        console.print(Panel(err, title="Error", border_style="red"))
    elif event.event_type == "mode_switch":
        mode = event.data.get("mode", "?")
        console.print(f"Beralih ke Mode {mode.upper()}", style="bold blue")
    elif event.event_type == "done":
        console.print("Selesai.", style=f"bold {BRAND_GREEN}")


def main():
    print_banner()
    print_welcome_panel()
    pid, _, model = get_active_provider_info()
    current_session_id = session_store.create(pid, model)["id"]
    agent = RexAgent(current_session_id)

    while True:
        mode = get_active_mode().upper()
        mode_style = "bold blue" if mode == "PLAN" else "bold green"
        pid, _, model = get_active_provider_info()

        prompt_text = Text.from_markup(f"\n[{mode_style}][Rex Code | {mode} | {model}][/{mode_style}] > ")

        try:
            user_input = console.input(prompt_text).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Sampai jumpa![/dim]")
            break

        if not user_input:
            continue

        if user_input == "/exit" or user_input == "/quit":
            console.print("[dim]Sampai jumpa![/dim]")
            break
        elif user_input == "/help":
            show_help()
            continue
        elif user_input == "/plan":
            set_active_mode("plan")
            console.print("[bold blue]ðŸ“‹ Beralih ke Mode PLAN (Perencanaan Aman).[/bold blue]")
            continue
        elif user_input == "/build":
            set_active_mode("build")
            console.print("[bold green]ðŸ”¨ Beralih ke Mode BUILD (Eksekusi Otonom & Auto-Debug).[/bold green]")
            continue
        elif user_input == "/models" or user_input == "/provider":
            handle_models_switch()
            continue
        elif user_input == "/anti-slop":
            handle_anti_slop_audit()
            continue
        elif user_input == "/settings":
            handle_settings()
            continue
        elif user_input == "/scheduler":
            handle_scheduler()
            continue
        elif user_input == "/n8n":
            wf_path = create_webhook_ai_workflow(name="Otomasi_Baru")
            console.print(f"[bold green]âœ“ Template workflow n8n berhasil dibuat:[/bold green] [cyan]{wf_path}[/cyan]")
            console.print("[dim]Anda bisa langsung mengimport file JSON tersebut ke dashboard n8n Anda.[/dim]")
            continue
        elif user_input == "/files":
            files = list(WORKSPACE_DIR.glob("**/*"))
            if not files:
                console.print("[dim]Folder workspace/ masih kosong.[/dim]")
            else:
                console.print("[bold]Daftar file di workspace/:[/bold]")
                for f in files:
                    if f.is_file():
                        console.print(f"ðŸ“„ {f.relative_to(WORKSPACE_DIR)}")
            continue
        elif user_input == "/sessions":
            sessions = session_store.list()
            for item in sessions:
                marker = "*" if item["id"] == current_session_id else " "
                console.print(f"{marker} {item['id']}  {item.get('title') or 'Percakapan baru'}")
            continue
        elif user_input == "/new" or user_input == "/reset":
            pid, _, model = get_active_provider_info()
            current_session_id = session_store.create(pid, model)["id"]
            agent = RexAgent(current_session_id)
            console.print(f"[green]Sesi baru: {current_session_id}[/green]")
            continue
        elif user_input == "/voice":
            voice_text = handle_voice_input()
            if voice_text:
                user_input = voice_text
            else:
                continue
        elif user_input.startswith("/use "):
            requested = user_input[5:].strip()
            try:
                session_store.load(requested)
                current_session_id = requested
                agent = RexAgent(current_session_id)
                console.print(f"[green]Sesi aktif: {current_session_id}[/green]")
            except (FileNotFoundError, ValueError):
                console.print("[red]Session ID tidak ditemukan.[/red]")
            continue
        elif user_input.startswith("/delete "):
            requested = user_input[8:].strip()
            try:
                session_store.delete(requested)
                if requested == current_session_id:
                    pid, _, model = get_active_provider_info()
                    current_session_id = session_store.create(pid, model)["id"]
                    agent = RexAgent(current_session_id)
                console.print("[green]Sesi dihapus.[/green]")
            except (FileNotFoundError, ValueError):
                console.print("[red]Session ID tidak ditemukan.[/red]")
            continue
        # Execute agent
        with tool_spinner("Thinking..."):
            response = agent.run(user_input, on_step=step_callback)
        console.print()

        console.print(Panel(Markdown(response), title="ðŸ¦– Rex Code", border_style="cyan"))

if __name__ == "__main__":
    main()


def tui_main():
    """Launch the native Textual TUI."""
    from rex.tui.app import main as tui_run
    tui_run()
