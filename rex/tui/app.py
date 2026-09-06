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
from textual.widgets import Header, Footer, RichLog, Input, Label, ListView, ListItem
from textual.reactive import reactive
from textual.message import Message

from rex.config import load_config, get_active_mode, set_active_mode, get_active_provider_info
from rex.approval import set_provider, reset_session_allows
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
            yield Label("", id="accent-indicator")

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


class PromptBar(Container):
    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type a message... (/, up/down for history)", id="prompt-input")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    @on(Input.Submitted, "#prompt-input")
    def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.post_message(PromptSubmitted(text))
        event.input.value = ""


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
            ("/help", "Show help"),
            ("/exit", "Exit Rex Code"),
        ]
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
    PromptBar { height: 3; background: $rex-subtle; border-top: solid $rex-dim; }
    #prompt-input { background: $rex-bg; border: solid $rex-dim; color: $zinc-200; padding: 0 1; }
    #prompt-input:focus { border: solid $rex-primary; }
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
        pid, _, model = get_active_provider_info()
        self.session_id = session_store.create(pid, model)["id"]
        status = self.query_one("#status", StatusBar)
        chat = self.query_one("#chat", ChatArea)
        theme = get_active_theme()
        chat.write(f"[b {theme.primary}]Rex Code v{rex.__version__}[/b {theme.primary}]")
        chat.write("[dim]Native TUI -- Autonomous AI Coding & Workflow Agent[/dim]")
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
            elif cmd == "/cost":
                usage = getattr(self.agent, "total_usage", None) or {} if self.agent else {}
                chat.write(
                    f"[dim]Session tokens — prompt: {usage.get('prompt_tokens', 0):,} · "
                    f"completion: {usage.get('completion_tokens', 0):,} · "
                    f"total: {usage.get('total_tokens', 0):,}[/dim]"
                )
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
        chat.write(f"  [b]/init[/b]      Create REX.md project instructions")
        chat.write(f"  [b]/checkpoints[/b] List automatic snapshots")
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
        elif event.event_type == "error":
            chat.add_error(str(event.data.get("error", "")))
        elif event.event_type == "mode_switch":
            mode = event.data.get("mode", "?")
            self.query_one("#status", StatusBar).mode = mode.upper()

    def _on_done(self, result):
        chat = self.query_one("#chat", ChatArea)
        chat.add_done(result)
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
