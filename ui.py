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
