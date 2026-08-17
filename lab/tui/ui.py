from __future__ import annotations

import os
import select
import sys
import termios
import time
import tty

CYAN = "\033[38;2;37;181;255m"
WHITE = "\033[38;2;235;245;250m"
MUTED = "\033[38;2;139;162;175m"
SELECT = "\033[38;2;140;188;220m"
WARNING = "\033[38;2;255;193;92m"
BOLD = "\033[1m"
RESET = "\033[0m"

CYNAPTICS = (
    " ██████╗██╗   ██╗███╗   ██╗ █████╗ ██████╗ ████████╗██╗ ██████╗███████╗",
    "██╔════╝╚██╗ ██╔╝████╗  ██║██╔══██╗██╔══██╗╚══██╔══╝██║██╔════╝██╔════╝",
    "██║      ╚████╔╝ ██╔██╗ ██║███████║██████╔╝   ██║   ██║██║     ███████╗",
    "██║       ╚██╔╝  ██║╚██╗██║██╔══██║██╔═══╝    ██║   ██║██║     ╚════██║",
    "╚██████╗   ██║   ██║ ╚████║██║  ██║██║        ██║   ██║╚██████╗███████║",
    " ╚═════╝   ╚═╝   ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝        ╚═╝   ╚═╝ ╚═════╝╚══════╝",
)
OPENGPU = (
    " ██████╗ ██████╗ ███████╗███╗   ██╗ ██████╗ ██████╗ ██╗   ██╗",
    "██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔════╝ ██╔══██╗██║   ██║",
    "██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║  ███╗██████╔╝██║   ██║",
    "██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║   ██║██╔═══╝ ██║   ██║",
    "╚██████╔╝██║     ███████╗██║ ╚████║╚██████╔╝██║     ╚██████╔╝",
    " ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝      ╚═════╝ ",
)


def color_enabled(*, stream=None) -> bool:
    stream = sys.stdout if stream is None else stream
    if os.environ.get("NO_COLOR", "").strip() or os.environ.get("TEST_MODE", "").strip():
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _paint(text: str, color: str, *, enabled: bool) -> str:
    return f"{color}{text}{RESET}" if enabled else text


def banner(*, stream=None) -> str:
    enabled = color_enabled(stream=stream)
    lines = [_paint(line, CYAN, enabled=enabled) for line in CYNAPTICS]
    lines.append("")
    lines.extend(_paint(line, WHITE, enabled=enabled) for line in OPENGPU)
    return "\n".join(lines)


def print_banner(*, stream=None) -> None:
    stream = sys.stdout if stream is None else stream
    if color_enabled(stream=stream):
        stream.write("\033[2J\033[H")
    stream.write(banner(stream=stream) + "\n\n")
    stream.flush()


def wordmark(*, stream=None) -> str:
    enabled = color_enabled(stream=stream)
    return "\n".join(_paint(line, CYAN, enabled=enabled) for line in OPENGPU)


def print_page(
    title: str,
    description: str = "",
    *,
    options: list[tuple[str, str, str]] | None = None,
    default_index: int = 0,
    hint: str = "",
    stream=None,
    arrow_select: bool = False,
    link: str = "",
) -> None:
    stream = sys.stdout if stream is None else stream
    enabled = color_enabled(stream=stream)
    if enabled:
        stream.write("\033[2J\033[H")
        if arrow_select:
            stream.write("\033[?25l")
    stream.write(wordmark(stream=stream) + "\n\n")
    stream.write(heading(title, stream=stream) + "\n")
    if description:
        for line in description.splitlines() or [description]:
            stream.write(muted(line, stream=stream) + "\n")
        stream.write("\n")
    if link:
        stream.write(_paint(link, CYAN, enabled=enabled) + "\n\n")
    if options:
        for index, (_value, label, detail) in enumerate(options):
            selected = index == default_index
            marker = ">" if selected else " "
            if arrow_select:
                row = f" {marker} {label}"
            else:
                row = f" {marker} {index + 1}) {label}"
            if detail:
                row = f"{row}  —  {detail}"
            if selected:
                stream.write(_paint(row, SELECT, enabled=enabled) + "\n")
            else:
                stream.write(muted(row, stream=stream) + "\n")
        stream.write("\n")
        if not hint:
            if arrow_select:
                hint = "Arrow keys to move · Enter to continue"
            else:
                hint = "Press Enter to continue"
    if hint:
        stream.write(muted(hint, stream=stream) + "\n")
    stream.write("\n")
    stream.flush()


def _arrow_select_enabled(input_fn) -> bool:
    if input_fn is not input:
        return False
    if os.environ.get("TEST_MODE", "").strip():
        return False
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _show_cursor(*, stream=None) -> None:
    stream = sys.stdout if stream is None else stream
    stream.write("\033[?25h")
    stream.flush()


def _read_key(fd: int) -> str:
    ch = os.read(fd, 1)
    if not ch:
        return ""
    if ch == b"\x03":
        raise KeyboardInterrupt
    if ch != b"\x1b":
        return ch.decode("utf-8", "replace")
    seq = bytearray(ch)
    if not select.select([fd], [], [], 0.2)[0]:
        return "\x1b"
    seq.extend(os.read(fd, 1))
    if seq[-1] in (ord("["), ord("O")):
        while select.select([fd], [], [], 0.2)[0]:
            seq.extend(os.read(fd, 1))
            if 0x40 <= seq[-1] <= 0x7E:
                break
    return bytes(seq).decode("latin-1")


def _key_action(key: str) -> str:
    if key in {"\r", "\n"}:
        return "enter"
    if key in {"k", "K"}:
        return "up"
    if key in {"j", "J"}:
        return "down"
    if key.startswith("\x1b") and key.endswith("A"):
        return "up"
    if key.startswith("\x1b") and key.endswith("B"):
        return "down"
    return "other"


def ask_choice(
    title: str,
    description: str,
    options: list[tuple[str, str, str]],
    *,
    default: int = 0,
    input_fn=input,
) -> str:
    if not options:
        raise ValueError("ask_choice requires at least one option")
    index = min(max(default, 0), len(options) - 1)
    if _arrow_select_enabled(input_fn):
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                print_page(title, description, options=options, default_index=index, arrow_select=True)
                action = _key_action(_read_key(fd))
                if action == "enter":
                    return options[index][0]
                if action == "up":
                    index = (index - 1) % len(options)
                elif action == "down":
                    index = (index + 1) % len(options)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            _show_cursor()
    aliases = {}
    for value, label, _detail in options:
        aliases[value.lower()] = value
        aliases[label.lower()] = value
    while True:
        print_page(title, description, options=options, default_index=index, arrow_select=True)
        raw = input_fn("Select: ")
        answer = "" if raw is None else str(raw).strip().lower()
        if not answer:
            return options[index][0]
        if answer.isdigit():
            picked = int(answer) - 1
            if 0 <= picked < len(options):
                return options[picked][0]
        if answer in aliases:
            return aliases[answer]
        print("Use arrow keys, or a number from the list.", file=sys.stderr)


def hold_page(
    title: str,
    description: str,
    *,
    ready=None,
    link: str = "",
    hint: str = "",
    input_fn=input,
    fallback_after: float | None = None,
    fallback: tuple[str, str, str] | None = None,
) -> str:
    if not _arrow_select_enabled(input_fn):
        if callable(ready) and ready():
            return "ok"
        return fallback[0] if fallback else "ok"
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    index = 0
    started = time.monotonic()
    try:
        tty.setcbreak(fd)
        while True:
            if callable(ready) and ready():
                return "ok"
            elapsed = time.monotonic() - started
            options = None
            page_hint = hint
            if fallback is not None and fallback_after is not None and elapsed >= fallback_after:
                options = [
                    ("wait", "Keep waiting", ""),
                    fallback,
                ]
                page_hint = "Arrow keys to move · Enter to continue"
            shown = link() if callable(link) else link
            print_page(
                title,
                description,
                hint=page_hint,
                link=shown,
                options=options,
                default_index=index,
                arrow_select=bool(options),
            )
            waiting, _, _ = select.select([fd], [], [], 1.0)
            if not waiting:
                continue
            action = _key_action(_read_key(fd))
            if options:
                if action == "up":
                    index = (index - 1) % len(options)
                elif action == "down":
                    index = (index + 1) % len(options)
                elif action == "enter" and options[index][0] != "wait":
                    return options[index][0]
            elif action == "enter" and fallback is None:
                return "ok"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        _show_cursor()


def ask_text(
    title: str,
    description: str,
    *,
    default: str = "",
    required: bool = False,
    secret: bool = False,
    input_fn=input,
    getpass_fn=None,
) -> str | None:
    hint = f"Default: {default}" if default else ("Required." if required else "Leave blank to skip.")
    while True:
        print_page(title, description, hint=hint)
        prompt = "> "
        if secret:
            getter = getpass_fn or (lambda _prompt: "")
            raw = getter(prompt)
        else:
            raw = input_fn(prompt)
        answer = "" if raw is None else str(raw).strip()
        if answer:
            return answer
        if default:
            return default
        if not required:
            return None
        print("This value is required.", file=sys.stderr)


def heading(text: str, *, stream=None) -> str:
    enabled = color_enabled(stream=stream)
    return _paint(f"{BOLD}{text}", WHITE, enabled=enabled) if enabled else text


def muted(text: str, *, stream=None) -> str:
    return _paint(text, MUTED, enabled=color_enabled(stream=stream))


def panel(title: str, lines: list[str], *, stream=None) -> str:
    enabled = color_enabled(stream=stream)
    width = max([len(title) + 2, *(len(line) for line in lines), 40])
    top = "┌" + "─" * (width + 2) + "┐"
    mid = "│ " + title.ljust(width) + " │"
    body = ["│ " + line.ljust(width) + " │" for line in lines]
    bottom = "└" + "─" * (width + 2) + "┘"
    if not enabled:
        return "\n".join([f"[{title}]", *lines])
    return "\n".join(
        [
            _paint(top, CYAN, enabled=True),
            _paint(mid, WHITE, enabled=True),
            *(_paint(row, MUTED, enabled=True) for row in body),
            _paint(bottom, CYAN, enabled=True),
        ]
    )


def format_checks(checks) -> str:
    lines = []
    for check in checks:
        if check.ok:
            status = "ok  "
        elif check.fatal:
            status = "fail"
        else:
            status = "warn"
        line = f"{status}  {check.name}: {check.detail}"
        if color_enabled():
            color = CYAN if check.ok else WARNING if not check.fatal else "\033[38;2;255;118;110m"
            lines.append(_paint(line, color, enabled=True))
        else:
            lines.append(line)
    return "\n".join(lines)


def step(index: int, total: int, text: str) -> str:
    return muted(f"[{index}/{total}]") + " " + text
