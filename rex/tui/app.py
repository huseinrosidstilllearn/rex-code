"""
rex.tui.app
===========
Native TUI application - Claude-Code-style terminal interface.
"""

from __future__ import annotations
import sys
import threading
from typing import Optional
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, RichLog, Input, Label, ListView, ListItem, Static
from textual.reactive import reactive
from textual.message import Message

from rex.config import load_config, get_active_mode, set_active_mode, get_active_provider_info
from rex.approval import set_provider, reset_session_allows
from rex.commands import load_commands, expand_prompt, parse_input, format_help
from rex.core import RexAgent, StepEvent
from rex.sessions import session_store
from rex.subagents import get_subagent
from rex.tui.theme import get_theme_css, get_active_theme, list_presets, set_theme, set_custom_accent


class PromptSubmitted(Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class ApprovalDecided(Message):
    """Raised by ApprovalScreen when the user answers a confirmation."""

    def __init__(self, approved: bool, remember: bool) -> None:
        self.approved = approved
        self.remember = remember
        super().__init__()


class ApprovalScreen(ModalScreen):
    """Modal y/n confirmation for a destructive BUILD action."""

    BINDINGS = [
        Binding("y", "approve", "Setujui", show=True),
        Binding("n", "deny", "Tolak", show=True, key_display="n/Esc"),
        Binding("a", "approve_always", "Selalu (sesi ini)", show=True),
        Binding("escape", "deny", "", show=False),
    ]

    def __init__(self, action: str, summary: str) -> None:
        super().__init__()
        self.action = action
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Container(id="approval-box"):
            yield Label(f"[b yellow]Approval: {self.action}[/b yellow]")
            yield Label(self.summary)
            yield Label("[dim]y = setujui · n = tolak · a = selalu (sesi ini)[/dim]")

    def action_approve(self) -> None:
        self.dismiss((True, False))

    def action_deny(self) -> None:
        self.dismiss((False, False))

    def action_approve_always(self) -> None:
        pattern = self.summary.lower()
        if self.action == "run_command":
            body = pattern.split(":", 1)[-1].strip()
            head = body.split(" ")[0] if body else "*"
            pattern = f"jalankan perintah: {head} *"
        self.dismiss((True, pattern))


class CommandPaletteCustom(Message):
    pass


class StatusBar(Container):
    mode = reactive("PLAN")
    provider = reactive("gemini")
    model = reactive("gemini-2.5-flash")

    def compose(self) -> ComposeResult:
        with Horizontal(id="status-inner"):
            yield Label("", id="mode-badge")
            yield Label(" | ", classes="sep")
            yield Label("", id="provider-label")
            yield Label(" | ", classes="sep")
            yield Label("", id="model-label")
            yield Label(" | ", classes="sep")
            yield Label("", id="usage-indicator")
            yield Label(" | ", classes="sep")
            yield Label("", id="todo-indicator")
            yield Label(" | ", classes="sep")
            yield Label("", id="accent-indicator")

    def update_todo(self, summary: str, todos: list) -> None:
        """Show agent progress in the status bar (e.g. ``todo 2/5 selesai``)."""
        try:
            indicator = self.query_one("#todo-indicator", Label)
            if todos:
                indicator.update(f"[b cyan]todo {summary}[/b cyan] [dim]— /todos[/dim]")
            else:
                indicator.update("")
        except Exception:
            pass  # status bar is cosmetic — never break a run on it

    def update_usage(self, text: str) -> None:
        """Show the session token/cost meter in the status bar."""
        try:
            indicator = self.query_one("#usage-indicator", Label)
            indicator.update(f"[dim]{text}[/dim]" if text else "")
        except Exception:
            pass  # status bar is cosmetic — never break a run on it

    def watch_mode(self, value: str) -> None:
        badge = self.query_one("#mode-badge", Label)
        color = "blue" if value == "PLAN" else "green"
        badge.update(f"[{color}]{value}[/{color}]")

    def watch_provider(self, value: str) -> None:
        self.query_one("#provider-label", Label).update(f"[dim]{value}[/dim]")

    def watch_model(self, value: str) -> None:
        self.query_one("#model-label", Label).update(f"[dim]{value}[/dim]")

    def on_mount(self) -> None:
        self.refresh_accent()

    def refresh_accent(self) -> None:
        theme = get_active_theme()
        indicator = self.query_one("#accent-indicator", Label)
        indicator.update(f"[on {theme.primary}]  [/on {theme.primary}] [dim]accent[/dim]")


class ChatArea(RichLog):
    """Scrollable chat area with streaming and markdown rendering."""

    def __init__(self, *args, id: str | None = None, **kwargs) -> None:
        super().__init__(*args, id=id, **kwargs, wrap=True, highlight=True, markup=True, auto_scroll=True)
        self._buffer = ""
        self._assistant_line_idx = -1

    def add_user_message(self, text: str) -> None:
        theme = get_active_theme()
        self.write(f"[b {theme.primary}]You[/b {theme.primary}] {text}")
        self.write("")

    def add_assistant_start(self) -> None:
        self._buffer = ""
        theme = get_active_theme()
        self.write(f"[{theme.primary}][/{theme.primary}]")
        self._assistant_line_idx = len(self.lines) - 1

    def stream_delta(self, text: str) -> None:
        self._buffer += text
        if self._assistant_line_idx >= 0 and self._assistant_line_idx < len(self.lines):
            self.remove_line(self._assistant_line_idx)
        theme = get_active_theme()
        self.write(f"[{theme.primary}]{self._buffer}[/{theme.primary}]")
        self._assistant_line_idx = len(self.lines) - 1

    def flush_assistant(self) -> None:
        if self._buffer:
            if self._assistant_line_idx >= 0 and self._assistant_line_idx < len(self.lines):
                self.remove_line(self._assistant_line_idx)
            theme = get_active_theme()
            self.write(f"[{theme.primary}]{self._buffer}[/{theme.primary}]")
            self._buffer = ""
            self._assistant_line_idx = -1

    def add_thought(self, text: str) -> None:
        self.write(f"[dim italic]... {text}[/dim italic]")

    def add_tool_call(self, name: str, args: dict) -> None:
        self.write(f"[b dark_orange]tool: {name}[/b dark_orange] [dim]{args}[/dim]")

    def add_tool_result(self, name: str, result: str) -> None:
        if name.startswith("delegate_to_"):
            sub_name = name[len("delegate_to_"):]
            sub = get_subagent(sub_name)
            if sub:
                self._render_subagent_report(sub, result)
                return
        snippet = result if len(result) < 500 else result[:500] + " ... (truncated)"
        self.write(f"[dim]-> {snippet}[/dim]")

    def _render_subagent_report(self, sub, result: str) -> None:
        color = sub.color
        ascii_face = sub.icon_ascii
        self.write("")
        self.write(ascii_face)
        self.write(f"[b {color}]{'-' * 30}[/b {color}]")
        self.write(f"[b {color}]{sub.name.upper()} REPORT ({sub.role})[/b {color}]")
        self.write("")
        self.write(result)
        self.write("\n")

    def add_error(self, error: str) -> None:
        self.write(f"[bold red]Error: {error}[/bold red]")

    def add_done(self, result: str) -> None:
        self.flush_assistant()
        if result.strip():
            self.write(result)
        self.write("")


class PromptInput(Input):
    """Input with Tab-completion for ``@file`` / ``@file:symbol`` tokens."""

    BINDINGS = [Binding("tab", "complete_at", "Complete @", show=False)]

    def action_complete_at(self) -> None:
        try:
            bar = self.app.query_one("#prompt-bar", PromptBar)
        except Exception:
            return
        token = bar.current_at_token(self.value)
        if not token:
            return
        if bar._at_token != token or not bar._at_candidates:
            bar._at_token = token
            bar._at_candidates = bar.at_candidates(token)
            bar._at_index = 0
        if not bar._at_candidates:
            return
        choice = bar._at_candidates[bar._at_index % len(bar._at_candidates)]
        bar._at_index += 1
        prefix_end = self.cursor_position
        prefix = self.value[:prefix_end]
        start = prefix.rfind("@" + token)
        if start < 0:
            return
        self.value = self.value[:start] + "@" + choice + self.value[prefix_end:]
        self.cursor_position = start + len(choice) + 1


class PromptBar(Container):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._index = None
        self._index_at = 0.0
        self._at_token = ""
        self._at_candidates: list = []
        self._at_index = 0

    def compose(self) -> ComposeResult:
        yield PromptInput(placeholder="Type a message... (/, @ for files, up/down for history)", id="prompt-input")
        yield Static("", id="at-suggestions")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    def _get_index(self) -> dict:
        import time as _time
        now = _time.monotonic()
        if self._index is None or now - self._index_at > 30:
            try:
                from rex.codeindex import build_index
                self._index = build_index()
            except Exception:
                self._index = {}
            self._index_at = now
        return self._index or {}

    def current_at_token(self, text: str) -> str:
        """The trailing ``@token`` (without '@') at the cursor, or ''."""
        before = text[: self.query_one("#prompt-input", Input).cursor_position]
        piece = before.split()[-1] if before.split() else ""
        if piece.startswith("@") and len(piece) > 1:
            return piece[1:]
        return ""

    def at_candidates(self, token: str) -> list:
        try:
            from rex.codeindex import complete_reference
            return complete_reference(self._get_index(), token)
        except Exception:
            return []

    @on(Input.Changed, "#prompt-input")
    def _on_changed(self, event: Input.Changed) -> None:
        try:
            suggestions = self.query_one("#at-suggestions", Static)
            token = self.current_at_token(event.value)
            candidates = self.at_candidates(token) if token else []
            if not candidates:
                suggestions.remove_class("has-suggestions")
                suggestions.update("")
                return
            suggestions.add_class("has-suggestions")
            shown = "  ".join(candidates[:3])
            extra = f"  (+{len(candidates) - 3})" if len(candidates) > 3 else ""
            suggestions.update(f"[dim green]@{token} → {shown}{extra}[/dim green] [dim](Tab)[/dim]")
        except Exception:
            pass  # suggestions are cosmetic

    @on(Input.Submitted, "#prompt-input")
    def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.post_message(PromptSubmitted(text))
        event.input.value = ""
        try:
            self.query_one("#at-suggestions", Static).update("")
        except Exception:
            pass


class CommandPalette(Container):
    DEFAULT_CSS = """
    /* Rex accent variables — needed in this widget's own stylesheet scope */
    $rex-bg:      #022C22;
    $rex-subtle:  #0A3D2E;
    $rex-dim:     #166534;
    $rex-mid:     #16A34A;
    $rex-primary: #22C55E;
    $rex-bright:  #4ADE80;
    $rex-pale:    #86EFAC;
    $zinc-950: #09090B;
    $zinc-900: #18181B;
    $zinc-800: #27272A;
    $zinc-700: #3F3F46;
    $zinc-600: #52525B;
    $zinc-500: #71717A;
    $zinc-400: #A1A1AA;
    $zinc-300: #D4D4D8;
    $zinc-200: #E4E4E7;
    $zinc-100: #F4F4F5;
    $zinc-50:  #FAFAFA;

    CommandPalette {
        layer: overlay;
        align: center middle;
        display: none;
    }
    CommandPalette.visible {
        display: block;
    }
    CommandPalette > Container {
        width: 65;
        max-height: 40;
        background: $rex-subtle;
        border: solid $rex-mid;
        padding: 1 2;
        overflow-y: scroll;
    }
    CommandPalette ListView {
        background: transparent;
        height: auto;
    }
    CommandPalette Label {
        margin-left: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="palette-box"):
            yield Label("[b]Command Palette[/b] [dim](Ctrl+P to close)[/dim]")
            yield ListView(id="palette-list")

    def on_mount(self) -> None:
        self.populate()

    def populate(self) -> None:
        lv = self.query_one("#palette-list", ListView)
        lv.clear()
        actions = [
            ("/plan", "Switch to PLAN mode"),
            ("/build", "Switch to BUILD mode"),
            ("/theme rex", "Default emerald theme"),
            ("/theme mono", "Monochrome theme"),
            ("/theme amber", "Amber theme"),
            ("/theme cyan", "Cyan theme"),
            ("/theme violet", "Violet theme"),
            ("/theme rose", "Rose theme"),
            ("/resume", "Continue a past session"),
            ("/new", "Start a fresh session"),
            ("/rewind", "Restore an older checkpoint"),
            ("/compare", "Ask several providers the same question"),
            ("/status", "Full subsystem health report"),
            ("/help", "Show help"),
            ("/exit", "Exit Rex Code"),
        ]
        try:
            for slash, info in sorted(load_commands().items()):
                actions.append((slash, info.get("description") or "Custom command"))
        except Exception:
            pass  # palette must never fail on a broken commands dir
        for cmd, desc in actions:
            lv.append(ListItem(Label(f"[b]{cmd}[/b] [dim]-- {desc}[/dim]")))

    def action_close(self) -> None:
        self.remove_class("visible")
        self.app.set_focus(self.app.query_one("#prompt-input", Input))

    @on(ListView.Selected)
    def on_select(self, event: ListView.Selected) -> None:
        item = event.item
        if item.children:
            label = item.children[0]
            text = label.plain if hasattr(label, 'plain') else str(label)
            if "/theme custom" in text:
                self.action_close()
                self.app.post_message(CommandPaletteCustom())
            elif "/" in text:
                parts = text.split()
                cmd = parts[0] if parts else text.strip()
                self.action_close()
                self.app.post_message(PromptSubmitted(cmd))


class RexTUIApp(App):
    CSS = """
    ApprovalScreen {
        align: center middle;
        background: #022C22cc;
    }
    #approval-box {
        width: 70;
        height: auto;
        background: $rex-subtle;
        border: solid yellow;
        padding: 1 2;
    }
    $rex-bg:      #022C22;
    $rex-subtle:  #0A3D2E;
    $rex-dim:     #166534;
    $rex-mid:     #16A34A;
    $rex-primary: #22C55E;
    $rex-bright:  #4ADE80;
    $rex-pale:    #86EFAC;

    $zinc-950: #09090B;
    $zinc-900: #18181B;
    $zinc-800: #27272A;
    $zinc-700: #3F3F46;
    $zinc-600: #52525B;
    $zinc-500: #71717A;
    $zinc-400: #A1A1AA;
    $zinc-300: #D4D4D8;
    $zinc-200: #E4E4E7;
    $zinc-100: #F4F4F5;
    $zinc-50:  #FAFAFA;

    Screen {
        background: $rex-bg;
        color: $zinc-300;
    }
    #main-layout { layout: vertical; height: 1fr; }
    StatusBar {
        height: 1; background: $rex-subtle; border-bottom: solid $rex-dim;
    }
    #status-inner { width: 1fr; height: 1; padding: 0 2; layout: horizontal; align: center middle; }
    .sep { color: $rex-dim; }
    ChatArea { height: 1fr; padding: 1 2; background: $rex-bg; border: none; }
    PromptBar { height: auto; background: $rex-subtle; border-top: solid $rex-dim; }
    #prompt-input { background: $rex-bg; border: solid $rex-dim; color: $zinc-200; padding: 0 1; }
    #prompt-input:focus { border: solid $rex-primary; }
    #at-suggestions { height: 1; color: $zinc-400; padding: 0 1; display: none; }
    #at-suggestions.has-suggestions { display: block; }
    Header { background: $rex-subtle; color: $rex-primary; border: none; }
    Footer { background: $rex-subtle; color: $zinc-500; border: none; }
    CommandPalette > Container { width: 65; max-height: 40; background: $rex-subtle; border: solid $rex-mid; padding: 1 2; }
    CommandPalette ListView { background: transparent; }
    CommandPalette Label { margin-left: 1; }
    """

    BINDINGS = [
        Binding("ctrl+p", "command_palette", "Commands", show=True),
        Binding("ctrl+c", "abort", "Abort", show=True),
        Binding("ctrl+d", "quit", "Quit", show=False),
    ]

    TITLE = "Rex Code"
    SUB_TITLE = "Autonomous AI Agent"

    def __init__(self):
        super().__init__()
        self.agent = None
        self.session_id = None
        self._running = False
        self._custom_commands = {}  # loaded lazily per message (cheap dir scan)
        set_provider(self._approval_provider)

    def _approval_provider(self, action: str, summary: str):
        """Runs on the agent thread: push the modal, block on the answer."""
        result = {}
        done = threading.Event()

        def ask():
            def callback(decision):
                result["value"] = decision
                done.set()
            self.push_screen(ApprovalScreen(action, summary), callback)

        self.call_from_thread(ask)
        done.wait(timeout=300)  # don't hang forever if the UI is closed
        decision = result.get("value") or (False, False)
        return decision

    def compose(self):
        yield Header()
        yield Container(ChatArea(id="chat"), id="main-layout")
        yield StatusBar(id="status")
        yield PromptBar(id="prompt-bar")
        yield CommandPalette(id="palette")
        yield Footer()

    def on_mount(self):
        status = self.query_one("#status", StatusBar)
        chat = self.query_one("#chat", ChatArea)
        theme = get_active_theme()
        chat.write(f"[b {theme.primary}]Rex Code v{rex.__version__}[/b {theme.primary}]")
        chat.write("[dim]Native TUI -- Autonomous AI Coding & Workflow Agent[/dim]")
        resumed = None
        try:
            resumed = session_store.last_open_session()  # crash recovery candidate
        except Exception:
            resumed = None
        if resumed:
            self.session_id = resumed["id"]
            chat.write(
                f"[yellow]Sesi sebelumnya dilanjutkan:[/yellow] [dim]{(resumed.get('title') or '')[:50]} "
                f"({resumed.get('message_count', 0)} pesan) — /resume untuk memilih sesi lain, /new untuk mulai baru.[/dim]"
            )
        else:
            pid, _, model = get_active_provider_info()
            self.session_id = session_store.create(pid, model)["id"]
        pid, _, model = get_active_provider_info()
        chat.write(f"[dim]Mode: {status.mode} | {pid} | {model}[/dim]")
        chat.write("")
        try:
            self.agent = RexAgent(self.session_id)
        except Exception as exc:
            self.agent = None
            chat.write("[bold red]Provider gagal diinisialisasi.[/bold red]")
            chat.write(f"[dim]{exc}[/dim]")
            env_path = "[dim]%LOCALAPPDATA%\\RexCode\\.env[/dim]" if getattr(sys, "frozen", False) else "[dim].env[/dim]"
            chat.write(f"[dim]Isi API key di {env_path} (lihat .env.example), lalu jalankan ulang.[/dim]")
            chat.write("")
            chat.write("[dim]Press Ctrl+P for commands. Type /help for reference.[/dim]")
            chat.write("")
            return
        status.mode = get_active_mode().upper()
        status.provider = pid
        status.model = model
        chat.write("[dim]Press Ctrl+P for commands. Type /help for reference.[/dim]")
        chat.write("")
        self._start_update_check()

    def on_unmount(self):
        """Clean exit marker: closed sessions are never auto-resumed.
        A crash skips this, so the session stays 'open' for recovery."""
        if not self.session_id:
            return
        try:
            session_store.close(self.session_id)
        except Exception:
            pass

    def _start_update_check(self):
        """Background update check - never blocks or crashes startup."""
        from rex.config import normalize_config
        from rex.updates import maybe_update

        settings = normalize_config(load_config()).get("updates", {})
        if not settings.get("enabled", True):
            return

        def notice(text: str) -> None:
            def writer():
                try:
                    self.query_one("#chat", ChatArea).write(f"[dim]{text}[/dim]")
                except Exception:
                    pass
            self.call_from_thread(writer)

        def ready_to_install(installer_path) -> None:
            import time
            notice(f"Menjalankan installer v{installer_path.name}... aplikasi akan ditutup.")
            from rex.updates import install_update
            time.sleep(1.0)  # let the notice render
            install_update(installer_path)
            time.sleep(0.5)
            self.call_from_thread(self.exit)

        threading.Thread(target=lambda: maybe_update(settings, notice, ready_to_install), daemon=True).start()

        # Post-update changelog: shown once after restarting into a new version.
        def show_changelog():
            from rex.updates import take_pending_changelog
            text = take_pending_changelog()
            if text:
                first_lines = "\n".join(text.splitlines()[:8])
                def write_it():
                    try:
                        self.query_one("#chat", ChatArea).write(
                            f"[b]Yang baru setelah pembaruan:[/b]\n[dim]{first_lines}[/dim]"
                        )
                    except Exception:
                        pass
                self.call_from_thread(write_it)
        threading.Thread(target=show_changelog, daemon=True).start()

    def refresh_theme(self):
        self.query_one("#status", StatusBar).refresh_accent()

    def action_command_palette(self):
        palette = self.query_one("#palette", CommandPalette)
        palette.add_class("visible")
        self.set_focus(palette.query_one("ListView"))

    def action_abort(self):
        if self.agent and self._running:
            self.agent.abort()


    @on(PromptSubmitted)
    def on_prompt_submitted(self, event: PromptSubmitted):
        text = event.text
        chat = self.query_one("#chat", ChatArea)

        if text.startswith("/"):
            cmd = text.split()[0].lower()
            arguments = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
            if cmd == "/plan":
                set_active_mode("plan")
                self.query_one("#status", StatusBar).mode = "PLAN"
                chat.write("[dim]Switched to PLAN mode (read-only)[/dim]")
            elif cmd == "/build":
                set_active_mode("build")
                self.query_one("#status", StatusBar).mode = "BUILD"
                chat.write("[dim]Switched to BUILD mode (autonomous execution)[/dim]")
            elif cmd == "/settings":
                from rex.config import save_config, normalize_config
                cfg = normalize_config(load_config())
                appr = cfg.setdefault("approval", {})
                appr["enabled"] = not bool(appr.get("enabled", False))
                save_config(cfg)
                state = "AKTIF" if appr["enabled"] else "MATI"
                chat.write(f"[dim]Approval mode {state} — aksi BUILD sekarang {'perlu konfirmasi' if appr['enabled'] else 'langsung dieksekusi'}[/dim]")
            elif cmd == "/theme":
                parts = text.split()
                if len(parts) > 1:
                    name = parts[1].lower()
                    if name == "custom":
                        if len(parts) > 2:
                            hex_color = parts[2]
                            try:
                                set_custom_accent(hex_color)
                                self.refresh_theme()
                                theme = get_active_theme()
                                chat.write(f"[b {theme.primary}]Custom theme set to {hex_color}[/b]")
                            except ValueError as e:
                                chat.write(f"[red]{e}[/red]")
                        else:
                            chat.write("[dim]Custom theme: use /theme custom #RRGGBB[/dim]")
                    else:
                        try:
                            set_theme(name)
                            self.refresh_theme()
                            theme = get_active_theme()
                            chat.write(f"[b {theme.primary}]Theme switched to {name}[/b]")
                        except ValueError as e:
                            chat.write(f"[red]{e}[/red]")
                else:
                    chat.write(f"[dim]Available: {', '}.join(list_presets())]/dim")
            elif cmd == "/models":
                rest_of_command = text[7:].strip()
                try:
                    cfg = normalize_config(load_config())
                    providers = cfg.get("providers", {})
                    if not providers:
                        chat.write("[red]No providers configured.[/red]")
                    else:
                        for pid, pdata in providers.items():
                            marker = " *" if pid == cfg.get("active_provider") else ""
                            chat.write(f"[b]{pid}[/b]{marker} — {pdata.get('name', pid)} · model: {pdata.get('model', '?')}")
                        chat.write("[dim]Switch: /models <provider_id> [model_name][/dim]")
                except Exception as e:
                    chat.write(f"[red]Failed to list providers: {e}[/red]")
                rest = rest_of_command.strip()
                if rest:
                    parts = rest.split(None, 1)
                    pid = parts[0]
                    try:
                        cfg = normalize_config(load_config())
                        if pid not in cfg.get("providers", {}):
                            chat.write(f"[red]Unknown provider: {pid}[/red]")
                        else:
                            pdata = cfg["providers"][pid]
                            model = parts[1].strip() if len(parts) > 1 else pdata.get("model")
                            if model not in pdata.get("available_models", [model]):
                                chat.write(f"[red]Model '{model}' not in {pdata.get('available_models', [])}[/red]")
                            else:
                                cfg["active_provider"] = pid
                                cfg["active_model"] = model
                                cfg["providers"][pid]["model"] = model
                                save_config(cfg)
                                chat.write(f"[green]Switched to {pid} ({model}) — applies on next message.[/green]")
                    except Exception as e:
                        chat.write(f"[red]Switch failed: {e}[/red]")
            elif cmd == "/resume":
                arg = arguments.strip()
                sessions = session_store.list()[:8]
                if not sessions:
                    chat.write("[yellow]Belum ada sesi tersimpan.[/yellow]")
                elif not arg.isdigit():
                    chat.write("[b]Sesi terakhir[/b] [dim]— lanjutkan dengan /resume <n>[/dim]")
                    for i, meta in enumerate(sessions, 1):
                        try:
                            count = len(session_store.load(meta["id"]).get("messages", []))
                        except Exception:
                            count = 0
                        marker = " [green](aktif)[/green]" if meta["id"] == self.session_id else ""
                        title = (meta.get("title") or "")[:40]
                        chat.write(f"  [b]{i}[/b]. {title} [dim]· {meta.get('model') or '?'} · {count} pesan · {(meta.get('updated_at') or '')[:16]}{marker}[/dim]")
                else:
                    idx = int(arg)
                    if not (1 <= idx <= len(sessions)):
                        chat.write(f"[red]Nomor di luar rentang 1-{len(sessions)}.[/red]")
                    elif sessions[idx - 1]["id"] == self.session_id:
                        chat.write("[dim]Anda sudah berada di sesi itu.[/dim]")
                    else:
                        chosen = sessions[idx - 1]
                        try:
                            self.agent = RexAgent(chosen["id"])
                        except Exception as exc:
                            chat.write(f"[red]Gagal memuat sesi: {exc}[/red]")
                        else:
                            self.session_id = chosen["id"]
                            try:
                                count = len(session_store.load(chosen["id"]).get("messages", []))
                            except Exception:
                                count = 0
                            chat.write(f"[green]Lanjut sesi:[/green] {(chosen.get('title') or '')[:50]} [dim]({count} pesan dimuat)[/dim]")
            elif cmd == "/new":
                if self.session_id:
                    try:
                        session_store.close(self.session_id)
                    except Exception:
                        pass
                pid, _, model = get_active_provider_info()
                self.session_id = session_store.create(pid, model)["id"]
                try:
                    self.agent = RexAgent(self.session_id)
                    chat.write(f"[green]Sesi baru dimulai[/green] [dim]({model})[/dim]")
                except Exception as exc:
                    chat.write(f"[red]Provider gagal: {exc}[/red]")
                try:
                    self.query_one("#status", StatusBar).update_usage("")
                except Exception:
                    pass
            elif cmd == "/cost":
                if self.agent:
                    self.agent.usage.refresh_config()
                    chat.write(f"[b]Session usage[/b] [dim]{self.agent.usage.format_summary()}[/dim]")
                else:
                    chat.write("[dim]No active agent — usage unavailable.[/dim]")
            elif cmd == "/init":
                from rex.context_inject import create_rex_md
                created, path = create_rex_md()
                if created:
                    chat.write(f"[green]REX.md created at {path}[/green]")
                else:
                    chat.write(f"[yellow]REX.md already exists at {path} — untouched.[/yellow]")
            elif cmd == "/commit":
                rest = text[7:].strip().lower()
                pending = getattr(self, "_pending_commit", None)
                if rest == "yes" and pending:
                    from rex.autogit import commit_with_message
                    chat.write(commit_with_message(pending, confirm=lambda m: True))
                    self._pending_commit = None
                elif rest == "no":
                    self._pending_commit = None
                    chat.write("[dim]Commit proposal cancelled.[/dim]")
                elif pending and not rest:
                    chat.write(f"[b]Pending:[/b] {pending}\n[dim]Confirm: /commit yes — cancel: /commit no[/dim]")
                else:
                    from rex.autogit import generate_commit_message
                    chat.write("[dim]Menganalisis diff…[/dim]")
                    message = generate_commit_message()
                    if not message:
                        chat.write("[yellow]Nothing to commit (or provider failed).[/yellow]")
                    else:
                        chat.write(f"[b]Proposed:[/b] {message}")
                        self._pending_commit = message
                        chat.write("[dim]Confirm: /commit yes — cancel: /commit no[/dim]")
            elif cmd.startswith("/ask"):
                from rex.codeindex import build_index, format_ask
                question = text[4:].strip()
                chat.write(format_ask(build_index(), question) if question else "[dim]Usage: /ask <query>[/dim]")
            elif cmd == "/imports":
                from rex.codeindex import build_index, format_import_graph
                chat.write(format_import_graph(build_index()))
            elif cmd == "/pr":
                from rex.autogit import generate_pr_description
                chat.write("[dim]Menganalisis diff…[/dim]")
                description = generate_pr_description()
                chat.write(description or "[yellow]Nothing to describe (or provider failed).[/yellow]")
            elif cmd == "/stats":
                from rex.stats import format_stats
                chat.write(format_stats())
            elif cmd == "/diff":
                from rex.review import format_session_diff
                chat.write(format_session_diff())
            elif cmd == "/doctor":
                from rex.review import format_doctor
                chat.write(format_doctor())
            elif cmd == "/skills":
                from rex.skills import load_skills
                skills = load_skills()
                if not skills:
                    chat.write("[yellow]Belum ada skill (.rex/skills/<name>/SKILL.md).[/yellow]")
                else:
                    chat.write(f"[b]Skills[/b] [dim]{len(skills)} tersedia — jalankan dengan /skill <name>[/dim]")
                    for skill in skills.values():
                        chat.write(f"  [b]{skill['name']}[/b] [dim]{skill['description']}[/dim]")
            elif cmd.startswith("/skill"):
                rest = text[len("/skill"):].strip()
                parts = rest.split(None, 1)
                name = parts[0] if parts else ""
                extra = parts[1].strip() if len(parts) > 1 else ""
                from rex.skills import get_skill, load_skills
                skill = get_skill(name) if name else None
                if skill is None:
                    chat.write("[dim]Usage: /skill <name> [argumen] — /skills untuk daftar[/dim]")
                    for skill_item in load_skills():
                        chat.write(f"  [b]{skill_item['name']}[/b] [dim]{skill_item['description']}[/dim]")
                else:
                    chat.write(f"[dim]Skill {skill['name']} dimuat — menjalankan…[/dim]")
                    prompt = skill["body"] + (f"\n\nArgumen: {extra}" if extra else "")
                    chat.add_user_message(prompt)
                    self.run_agent(prompt)
            elif cmd == "/export":
                arg = (arguments or "md").strip().lower().lstrip(".") or "md"
                if not self.session_id:
                    chat.write("[yellow]Belum ada sesi aktif untuk diekspor.[/yellow]")
                else:
                    from rex.export import export_session
                    chat.write(export_session(self.session_id, fmt=arg))
            elif cmd == "/compare":
                question = text[len("/compare"):].strip()
                if not question:
                    chat.write("[dim]Usage: /compare <pertanyaan> — bandingkan jawaban antar provider[/dim]")
                else:
                    from rex.core import compare_models, format_compare
                    chat.write("[dim]Menjalankan prompt di beberapa provider…[/dim]")
                    results = compare_models(question)
                    chat.write(format_compare(results))
            elif cmd == "/status":
                from rex.status import format_status
                chat.write(format_status())
            elif cmd == "/test":
                from rex.review import run_tests_hook
                result = run_tests_hook()
                if not result.get("ran"):
                    chat.write("[yellow]test_hook not set — fill config test_hook.command + enabled: true[/yellow]")
                elif result.get("passed"):
                    chat.write("[green]Tests passed ✔[/green]")
                else:
                    chat.write(f"[red]Tests failed ✘[/red]\n{result.get('output', '')[-2000:]}")
            elif cmd == "/checkpoints":
                from rex.checkpoints import format_checkpoints_table
                chat.write(format_checkpoints_table())
            elif cmd == "/todos":
                from rex.todos import get as get_todos, format_board, summary
                board = get_todos(self.session_id)
                chat.write(f"[b]Agent todos[/b] [dim]{summary(board)}[/dim]")
                chat.write(format_board(board))
            elif cmd == "/rewind":
                arg = arguments.strip()
                if not arg.isdigit():
                    from rex.checkpoints import format_timeline
                    chat.write(format_timeline())
                else:
                    from rex.checkpoints import rewind
                    result = rewind(int(arg))
                    if result:
                        chat.write(
                            f"[green]Workspace dikembalikan {result['steps']} checkpoint "
                            f"ke {result['restored'][:9]}[/green] [dim]— /redo untuk membatalkan[/dim]"
                        )
                    else:
                        chat.write("[yellow]Tidak bisa rewind (riwayat kurang / tidak ada checkpoint).[/yellow]")
            elif cmd == "/undo":
                from rex.checkpoints import undo
                result = undo()
                if result:
                    chat.write(f"[green]Workspace restored to {result['previous'][:9]}[/green] (previous state saved — /redo to revert)")
                else:
                    chat.write("[yellow]Nothing to undo.[/yellow]")
            elif cmd == "/redo":
                from rex.checkpoints import redo
                result = redo()
                if result:
                    chat.write(f"[green]Pre-undo state restored ({result['restored'][:9]})[/green]")
                else:
                    chat.write("[yellow]Nothing to redo.[/yellow]")
            elif cmd == "/help":
                self._show_help(chat)
            elif cmd in ("/exit", "/quit"):
                self.exit()
            else:
                custom = self._custom_commands.get(cmd)
                if custom is None:
                    # Not cached: rescan (covers newly added command files).
                    self._custom_commands = load_commands()
                    custom = self._custom_commands.get(cmd)
                if custom is not None:
                    prompt = expand_prompt(custom, arguments)
                    chat.write(f"[dim]Custom command {cmd} — running…[/dim]")
                    chat.add_user_message(prompt)
                    self.run_agent(prompt)
                else:
                    chat.write(f"[red]Unknown command: {cmd}[/red]")
                    chat.write("[dim]Type /help for available commands[/dim]")
            return

        chat.add_user_message(text)
        self.run_agent(text)

    def _show_help(self, chat):
        theme = get_active_theme()
        chat.write(f"[b {theme.primary}]Rex Code -- Commands[/b {theme.primary}]")
        chat.write(f"  [b]/plan[/b]      Plan mode (read-only analysis)")
        chat.write(f"  [b]/build[/b]     Build mode (autonomous execution)")
        chat.write(f"  [b]/settings[/b]  Toggle approval mode (confirm every BUILD action)")
        chat.write(f"  [b]/cost[/b]      Token usage for this session")
        chat.write(f"  [b]/resume[/b]    Continue a past session (/resume <n> to pick)")
        chat.write(f"  [b]/export[/b]    Save this session as md or html")
        chat.write(f"  [b]/new[/b]       Start a fresh session (old one is kept)")
        chat.write(f"  [b]/init[/b]      Create REX.md project instructions")
        chat.write(f"  [b]/checkpoints[/b] List automatic snapshots")
        chat.write(f"  [b]/rewind[/b]     Restore an older checkpoint (/rewind <n>)")
        chat.write(f"  [b]/todos[/b]     Show the agent todo board for this session")
        chat.write(f"  [b]/skills[/b]    List on-demand skills (.rex/skills/)")
        chat.write(f"  [b]/skill[/b]     Run a skill: /skill <name> [args]")
        chat.write(f"  [b]/undo[/b]      Roll workspace back one checkpoint")
        chat.write(f"  [b]/redo[/b]      Re-apply the last undo")
        chat.write(f"  [b]/theme <n>[/b] Change theme: rex mono amber cyan violet rose custom")
        chat.write(f"  [b]/help[/b]      Show this help")
        chat.write(f"  [b]/exit[/b]      Exit")
        chat.write("")
        chat.write("[b]Sub-agents (Plan mode only):[/b]")
        chat.write("  delegate_to_brachio -- Code review")
        chat.write("  delegate_to_raptor  -- Bug hunting")
        chat.write("  delegate_to_trike   -- Security audit")
        chat.write("  delegate_to_ptero   -- Architecture")
        chat.write("  delegate_to_dilo    -- Quality check")
        for line in format_help(load_commands()):
            chat.write(line)
        chat.write("[dim]Press Ctrl+P for quick command palette[/dim]")


    def run_agent(self, user_input):
        if self._running:
            return
        if self.agent is None:
            chat = self.query_one("#chat", ChatArea)
            chat.add_error("Provider belum siap. Isi API key di .env lalu jalankan ulang.")
            return
        self._running = True
        chat = self.query_one("#chat", ChatArea)
        chat.add_assistant_start()

        def step_callback(event):
            self.call_from_thread(self._on_step, event)

        def thread_func():
            try:
                result = self.agent.run(user_input, on_step=step_callback)
                self.call_from_thread(self._on_done, result)
            except Exception as e:
                self.call_from_thread(self._on_error, str(e))
            finally:
                self._running = False

        threading.Thread(target=thread_func, daemon=True).start()

    def _on_step(self, event):
        chat = self.query_one("#chat", ChatArea)
        if event.event_type == "stream_delta":
            chat.stream_delta(str(event.data))
        elif event.event_type == "thought":
            chat.add_thought(str(event.data))
        elif event.event_type == "tool_call":
            chat.add_tool_call(event.data.get("name", ""), event.data.get("args", {}))
        elif event.event_type == "tool_result":
            chat.add_tool_result(event.data.get("name", ""), str(event.data.get("result", "")))
        elif event.event_type == "todo_update":
            todos = event.data.get("todos", [])
            summary = event.data.get("summary", "")
            status = self.query_one("#status", StatusBar)
            status.update_todo(summary, todos)
        elif event.event_type == "usage_alert":
            level = event.data.get("status", "warning")
            message = event.data.get("message", "")
            color = "red" if level == "exceeded" else "yellow"
            chat.write(f"[b {color}]Budget: {message}[/b {color}]")
            try:
                self.query_one("#status", StatusBar).update_usage(self.agent.usage.format_footer())
            except Exception:
                pass
        elif event.event_type == "error":
            chat.add_error(str(event.data.get("error", "")))
        elif event.event_type == "mode_switch":
            mode = event.data.get("mode", "?")
            self.query_one("#status", StatusBar).mode = mode.upper()

    def _on_done(self, result):
        chat = self.query_one("#chat", ChatArea)
        chat.add_done(result)
        if self.agent:
            try:
                self.agent.usage.refresh_config()
                self.query_one("#status", StatusBar).update_usage(self.agent.usage.format_footer())
            except Exception:
                pass  # footer meter is cosmetic
        self.query_one("#prompt-input", Input).focus()

    def _on_error(self, error):
        chat = self.query_one("#chat", ChatArea)
        chat.add_error(error)
        self.query_one("#prompt-input", Input).focus()


def main():
    app = RexTUIApp()
    app.run()


if __name__ == "__main__":
    main()
