from pathlib import Path

ROOT = Path(__file__).resolve().parent


def frontend_path(*parts: str) -> Path:
    return ROOT.joinpath("frontend", *parts)


def postgres_path(*parts: str) -> Path:
    return ROOT.joinpath("postgres", *parts)


def script_path(*parts: str) -> Path:
    return ROOT.joinpath("scripts", *parts)
