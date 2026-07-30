from __future__ import annotations

import importlib.metadata
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit


def sanitize_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "invalid"
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        netloc = host
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit(
            (
                parsed.scheme,
                netloc,
                parsed.path.rstrip("/"),
                "",
                "",
            )
        )
    except ValueError:
        return "invalid"


def distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def poppler_version() -> str:
    executable = shutil.which("pdftoppm")
    if not executable:
        return "unavailable"
    try:
        completed = subprocess.run(
            [executable, "-v"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )
    match = re.search(r"\bversion\s+([0-9][^\s]*)", output)
    return match.group(1) if match else "unknown"


@lru_cache(maxsize=1)
def runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "pypdf": distribution_version("pypdf"),
        "pdfplumber": distribution_version("pdfplumber"),
        "pdfminer.six": distribution_version("pdfminer.six"),
        "pylatexenc": distribution_version("pylatexenc"),
        "poppler": poppler_version(),
    }
