from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KIMI_SECRETS_FILE = PROJECT_ROOT.parent / "kimi.enc.env.age"
DEFAULT_KIMI_IDENTITY_FILE = (
    PROJECT_ROOT.parent / ".secrets" / "kimi-age-identity.txt"
)
ENV_LINE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$"
)


def _parse_env_text(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE.match(line)
        if not match:
            continue
        name, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def _find_age_executable() -> Path | None:
    explicit = os.getenv("AGE_EXECUTABLE", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate.resolve() if candidate.is_file() else None

    discovered = shutil.which("age")
    if discovered:
        return Path(discovered).resolve()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return None
    packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    candidates = sorted(
        packages.glob("FiloSottile.age_*/age/age.exe"),
        reverse=True,
    )
    return candidates[0].resolve() if candidates else None


def _sanitized_error(message: str) -> str:
    compact = " ".join(message.replace("\x00", "").split())
    return compact[:240]


def _load_kimi_secret() -> tuple[str, str, str]:
    direct_key = os.getenv("KIMI_API_KEY", "").strip()
    if direct_key:
        return direct_key, "environment", ""

    alias_key = os.getenv("MOONSHOT_API_KEY", "").strip()
    if alias_key:
        os.environ["KIMI_API_KEY"] = alias_key
        return alias_key, "environment", ""

    secrets_file = Path(
        os.getenv("KIMI_SECRETS_FILE", str(DEFAULT_KIMI_SECRETS_FILE))
    ).expanduser()
    identity_file = Path(
        os.getenv("KIMI_AGE_IDENTITY_FILE", str(DEFAULT_KIMI_IDENTITY_FILE))
    ).expanduser()
    if not secrets_file.is_file():
        return "", "none", "未找到 Kimi 密文文件。"
    if not identity_file.is_file():
        return "", "none", "未找到本机 age 私钥文件。"

    age_executable = _find_age_executable()
    if not age_executable:
        return "", "none", "未找到 age 解密程序。"

    try:
        completed = subprocess.run(
            [
                str(age_executable),
                "--decrypt",
                "-i",
                str(identity_file.resolve()),
                str(secrets_file.resolve()),
            ],
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", "none", _sanitized_error(f"age 解密启动失败：{exc}")

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace")
        return "", "none", _sanitized_error(f"age 解密失败：{detail}")

    try:
        values = _parse_env_text(completed.stdout.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return "", "none", "Kimi 密文解密结果不是 UTF-8 ENV 文件。"

    key = (
        values.get("KIMI_API_KEY", "").strip()
        or values.get("MOONSHOT_API_KEY", "").strip()
    )
    if not key:
        return "", "none", "Kimi 密文中未找到 KIMI_API_KEY。"

    os.environ["KIMI_API_KEY"] = key
    return key, "age", ""


@dataclass(frozen=True)
class Settings:
    kimi_api_key: str
    kimi_base_url: str
    kimi_model: str
    kimi_reasoning_effort: str
    kimi_secret_source: str
    kimi_secret_error: str
    workspace_name: str
    workspace_id: str
    vision_max_pages: int
    external_engine_token: str
    asset_public_base_url: str
    asset_access_token: str
    mindmap_data_dir: Path
    blackboard_path: Path
    solver_timeout_seconds: float = 5.0
    max_chunk_chars: int = 1800
    chunk_overlap_chars: int = 240
    extraction_concurrency: int = 4

    @property
    def key_configured(self) -> bool:
        return bool(self.kimi_api_key)


def load_settings() -> Settings:
    kimi_api_key, secret_source, secret_error = _load_kimi_secret()
    reasoning_effort = os.getenv("KIMI_REASONING_EFFORT", "low").strip().lower()
    if reasoning_effort not in {"low", "high", "max"}:
        reasoning_effort = "low"

    external_engine_token = os.getenv("EXTERNAL_ENGINE_TOKEN", "")
    mindmap_data_dir = Path(
        os.getenv(
            "MINDMAP_DATA_DIR",
            str(PROJECT_ROOT / ".data" / "mindmap_engine"),
        )
    ).resolve()
    return Settings(
        kimi_api_key=kimi_api_key,
        kimi_base_url=os.getenv(
            "KIMI_BASE_URL",
            "https://api.moonshot.cn/v1",
        ).rstrip("/"),
        kimi_model=os.getenv("KIMI_MODEL", "kimi-k3"),
        kimi_reasoning_effort=reasoning_effort,
        kimi_secret_source=secret_source,
        kimi_secret_error=secret_error,
        workspace_name=os.getenv("KIMI_WORKSPACE_NAME", "Kimi K3 本地工作区"),
        workspace_id="",
        vision_max_pages=int(os.getenv("MINDMAP_VISION_MAX_PAGES", "24")),
        external_engine_token=external_engine_token,
        asset_public_base_url=os.getenv("ASSET_PUBLIC_BASE_URL", "").rstrip("/"),
        asset_access_token=os.getenv(
            "ASSET_ACCESS_TOKEN",
            external_engine_token,
        ),
        mindmap_data_dir=mindmap_data_dir,
        blackboard_path=Path(
            os.getenv(
                "MINDMAP_BLACKBOARD_PATH",
                str(mindmap_data_dir / "blackboard.sqlite3"),
            )
        ).resolve(),
        solver_timeout_seconds=float(
            os.getenv("MINDMAP_SOLVER_TIMEOUT_SECONDS", "5")
        ),
    )


settings = load_settings()
