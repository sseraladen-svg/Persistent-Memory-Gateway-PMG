"""Where PMG keeps its data. Resolved on every call so tests and users can override with env vars.

PMG_DATA   directory for the database and rules (default: ~/.pmg)
PMG_RULES  path to a rules file (default: <PMG_DATA>/rules.json, created from the packaged default)
"""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

DEFAULT_RULES = Path(__file__).with_name("rules.default.json")


def data_dir() -> Path:
    path = Path(os.environ.get("PMG_DATA") or Path.home() / ".pmg")
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "pmg.db"


def rules_path() -> Path:
    explicit = os.environ.get("PMG_RULES")
    path = Path(explicit) if explicit else data_dir() / "rules.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # Copy to a temporary name, then link it into place: a reader never sees a half-written file,
        # and a file created by another process in the meantime is never overwritten.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        shutil.copyfile(DEFAULT_RULES, tmp)
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass
        finally:
            tmp.unlink(missing_ok=True)
    return path


def write_atomic(path: Path, text: str) -> None:
    """Replace a file's contents in one step so concurrent readers never see a partial file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
