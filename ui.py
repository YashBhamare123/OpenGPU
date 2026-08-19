from __future__ import annotations

import os
import sys

CYAN = "\033[38;2;37;181;255m"
WHITE = "\033[38;2;235;245;250m"
MUTED = "\033[38;2;139;162;175m"
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
) -> None:
    stream = sys.stdout if stream is None else stream
    if color_enabled(stream=stream):
        stream.write("\033[2J\033[H")
    stream.write(wordmark(stream=stream) + "\n\n")
    stream.write(heading(title, stream=stream) + "\n")
    if description:
        for line in description.splitlines() or [description]:
            stream.write(muted(line, stream=stream) + "\n")
        stream.write("\n")
    if options:
        for index, (_value, label, detail) in enumerate(options):
            marker = "*" if index == default_index else " "
            row = f" {marker} {index + 1}) {label}"
            if detail:
                row = f"{row}  —  {detail}"
            stream.write(row + "\n")
        stream.write("\n")
        stream.write(muted("Enter a number. Press Enter for the starred option.", stream=stream) + "\n")
    if hint:
        stream.write(muted(hint, stream=stream) + "\n")
    stream.write("\n")
    stream.flush()


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
    default = min(max(default, 0), len(options) - 1)
    aliases = {}
    for value, label, _detail in options:
        aliases[value.lower()] = value
        aliases[label.lower()] = value
    while True:
        print_page(title, description, options=options, default_index=default)
        raw = input_fn("Select: ")
        answer = "" if raw is None else str(raw).strip().lower()
        if not answer:
            return options[default][0]
        if answer.isdigit():
            index = int(answer) - 1
            if 0 <= index < len(options):
                return options[index][0]
        if answer in aliases:
            return aliases[answer]
        print("Choose a number from the list.", file=sys.stderr)


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
