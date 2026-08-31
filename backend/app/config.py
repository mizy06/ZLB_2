from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QWEN_BASE_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
DEFAULT_QWEN_MODEL = "qwen3.7-max"
DEFAULT_QWEN_VISION_MODEL = "qwen3.7-plus"
DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS = 131_072
QWEN38_MAX_CONTEXT_WINDOW_TOKENS = 1_000_000
QWEN38_MAX_INPUT_TOKENS = 991_808
QWEN38_MAX_INPUT_TOKENS_WITH_THINKING = 983_616
DEFAULT_QWEN_IDENTITY_FILE = (
    PROJECT_ROOT / "runtime" / "secrets" / "qwen-age-identity.txt"
)
DEFAULT_QWEN_SECRETS_FILE = (
    PROJECT_ROOT / "runtime" / "secrets" / "qwen.enc.env.age"
)
TOKEN_PLAN_QWEN_HOSTS = frozenset(
    {
        "coding.dashscope.aliyuncs.com",
        "coding-intl.dashscope.aliyuncs.com",
        "token-plan.cn-beijing.maas.aliyuncs.com",
        "token-plan.ap-southeast-1.maas.aliyuncs.com",
    }
)
TRIAL_QWEN_HOSTS = frozenset(
    {
        "trial.cn-beijing.maas.aliyuncs.com",
        "trial.ap-southeast-1.maas.aliyuncs.com",
        "trial-us-east-1.dashscope.aliyuncs.com",
    }
)
STANDARD_QWEN_HOSTS = frozenset(
    {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
        "cn-hongkong.dashscope.aliyuncs.com",
        "ws-r1lp2twiz8lj5t79.cn-beijing.maas.aliyuncs.com",
    }
)
QWEN_WORKSPACE_HOST = re.compile(
    r"^llm-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"\.(?:cn-beijing|ap-southeast-1|ap-northeast-1|eu-central-1)"
    r"\.maas\.aliyuncs\.com$"
)
QWEN_OPENAI_COMPATIBLE_PATH = "/compatible-mode/v1"
QWEN_PRODUCTION_PROFILE_STANDARD = "standard"
QWEN_PRODUCTION_PROFILE_APPROVED_CN_TOKEN_PLAN_PREVIEW = (
    "approved_cn_token_plan_preview"
)
APPROVED_CN_TOKEN_PLAN_PREVIEW_BASE_URL = (
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
APPROVED_CN_TOKEN_PLAN_PREVIEW_MODEL = "qwen3.8-max-preview"
QWEN_VISION_MODEL_PATTERNS = (
    re.compile(r"^qwen3\.5-plus(?:-|$)"),
    re.compile(r"^qwen3\.6-plus(?:-|$)"),
    re.compile(r"^qwen3\.7-plus(?:-|$)"),
    re.compile(r"^qwen3\.8-max(?:-|$)"),
    re.compile(r"^qwen3\.8-flash(?:-|$)"),
    re.compile(r"^qwen-vl-"),
    re.compile(r"^qwen3-vl-"),
    re.compile(r"^qwen3\.6-35b(?:-|$)"),
)
QWEN38_LONG_CONTEXT_MODEL_PATTERN = re.compile(
    r"^qwen3\.8-(?:max|flash)(?:-|$)"
)
ENV_LINE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$"
)


def model_context_window_tokens(model: str) -> int:
    """Return the published context window for models used by this app."""
    if QWEN38_LONG_CONTEXT_MODEL_PATTERN.match(model.strip().casefold()):
        return QWEN38_MAX_CONTEXT_WINDOW_TOKENS
    return DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS


def model_max_input_tokens(
    model: str,
    *,
    thinking_enabled: bool,
) -> int:
    """Return the safe request-input limit for the selected model mode."""
    if QWEN38_LONG_CONTEXT_MODEL_PATTERN.match(model.strip().casefold()):
        return (
            QWEN38_MAX_INPUT_TOKENS_WITH_THINKING
            if thinking_enabled
            else QWEN38_MAX_INPUT_TOKENS
        )
    return model_context_window_tokens(model)


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


def _load_encrypted_secret(
    *,
    key_name: str,
    secrets_setting: str,
    identity_setting: str,
    default_secrets_file: Path,
    default_identity_file: Path,
    provider_label: str,
) -> tuple[str, str, str]:
    direct_key = os.getenv(key_name, "").strip()
    if direct_key:
        return direct_key, "environment", ""

    secrets_file = Path(
        os.getenv(secrets_setting, str(default_secrets_file))
    ).expanduser()
    identity_file = Path(
        os.getenv(identity_setting, str(default_identity_file))
    ).expanduser()
    if not secrets_file.is_file():
        return "", "none", f"未找到 {provider_label} 密文文件。"
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
        return "", "none", f"{provider_label} 密文解密结果不是 UTF-8 ENV 文件。"

    key = values.get(key_name, "").strip()
    if not key:
        return "", "none", f"{provider_label} 密文中未找到 {key_name}。"

    os.environ[key_name] = key
    return key, "age", ""


def _load_qwen_secret() -> tuple[str, str, str]:
    return _load_encrypted_secret(
        key_name="QWEN_API_KEY",
        secrets_setting="QWEN_SECRETS_FILE",
        identity_setting="QWEN_AGE_IDENTITY_FILE",
        default_secrets_file=DEFAULT_QWEN_SECRETS_FILE,
        default_identity_file=DEFAULT_QWEN_IDENTITY_FILE,
        provider_label="Qwen",
    )


def qwen_model_supports_vision(model: str) -> bool:
    normalized = model.strip().casefold()
    return any(
        pattern.match(normalized)
        for pattern in QWEN_VISION_MODEL_PATTERNS
    )


def _production_qwen_endpoint_issue(base_url: str) -> str | None:
    try:
        parsed = urlsplit(base_url.strip())
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return "invalid_endpoint"
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        return "invalid_endpoint"
    if hostname in TOKEN_PLAN_QWEN_HOSTS:
        return "token_plan_endpoint"
    if hostname in TRIAL_QWEN_HOSTS:
        return "trial_endpoint"
    if parsed.path.rstrip("/") != QWEN_OPENAI_COMPATIBLE_PATH:
        return "invalid_endpoint"
    if (
        hostname not in STANDARD_QWEN_HOSTS
        and QWEN_WORKSPACE_HOST.fullmatch(hostname) is None
    ):
        return "unapproved_endpoint"
    return None


def _endpoint_matches(base_url: str, expected_url: str) -> bool:
    try:
        parsed = urlsplit(base_url.strip())
        expected = urlsplit(expected_url)
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == expected.scheme.casefold()
        and hostname == (expected.hostname or "").casefold()
        and parsed.username is None
        and parsed.password is None
        and port is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path.rstrip("/") == expected.path.rstrip("/")
    )


@dataclass(frozen=True)
class Settings:
    qwen_api_key: str
    qwen_base_url: str
    qwen_model: str
    qwen_temperature: float
    qwen_secret_source: str
    qwen_secret_error: str
    workspace_name: str
    workspace_id: str
    vision_max_pages: int
    external_engine_token: str
    asset_public_base_url: str
    asset_access_token: str
    mindmap_data_dir: Path
    blackboard_path: Path
    qwen_vision_model: str = DEFAULT_QWEN_VISION_MODEL
    qwen_production_profile: str = QWEN_PRODUCTION_PROFILE_STANDARD
    pdf_transcription_mode: str = "vision_nodes_strict"
    pdf_page_extraction_mode: str = "direct"
    pdf_transcription_dpi: int = 192
    pdf_transcription_concurrency: int = 8
    pdf_transcription_max_attempts: int = 3
    pdf_transcription_min_confidence: float = 0.85
    solver_timeout_seconds: float = 5.0
    max_chunk_chars: int = 1800
    chunk_overlap_chars: int = 240
    extraction_concurrency: int = 4
    environment: str = "development"
    workbench_owner_id: str = "public-workbench"
    max_upload_bytes: int = 80 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    max_document_pages: int = 150
    max_zip_uncompressed_bytes: int = 300 * 1024 * 1024
    max_zip_compression_ratio: float = 120.0
    max_concurrent_jobs: int = 1
    provider_concurrency: int = 8
    export_concurrency: int = 1
    source_retention_hours: int = 72
    provider_timeout_seconds: float = 180.0
    provider_max_attempts: int = 3
    provider_retry_base_seconds: float = 0.5
    provider_retry_delay_cap_seconds: float = 30.0
    provider_circuit_cooldown_seconds: float = 120.0
    parser_version: str = "parser-v9-direct-visual-only"
    prompt_version: str = "editorial-ppt-vision-v1"
    theme_prompt_version: str = (
        "theme-synthesizer-v4-semantic-partition"
    )
    pdf_page_knowledge_prompt_version: str = (
        "editorial-ppt-vision-v1"
    )
    pdf_page_transcription_prompt_version: str = (
        "editorial-ppt-vision-v1"
    )
    schema_version: str = "mindmap-schema-v2"
    layout_version: str = "right-first-tree-v2"

    @property
    def key_configured(self) -> bool:
        return bool(self.qwen_api_key)

    @property
    def production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

def production_qwen_configuration_issues(
    configured: Settings,
) -> tuple[str, ...]:
    """Return fail-closed issues for a public automated Qwen deployment."""

    if not configured.production:
        return ()

    profile = configured.qwen_production_profile.strip().casefold()
    if (
        profile
        == QWEN_PRODUCTION_PROFILE_APPROVED_CN_TOKEN_PLAN_PREVIEW
    ):
        approved_issues: list[str] = []
        if not configured.qwen_api_key:
            approved_issues.append("missing_api_key")
        elif not configured.qwen_api_key.startswith("sk-sp-"):
            approved_issues.append("approved_profile_key_mismatch")
        if not _endpoint_matches(
            configured.qwen_base_url,
            APPROVED_CN_TOKEN_PLAN_PREVIEW_BASE_URL,
        ):
            approved_issues.append("approved_profile_endpoint_mismatch")
        if (
            configured.qwen_model.strip().casefold()
            != APPROVED_CN_TOKEN_PLAN_PREVIEW_MODEL
        ):
            approved_issues.append("approved_profile_text_model_mismatch")
        if (
            configured.qwen_vision_model.strip().casefold()
            != APPROVED_CN_TOKEN_PLAN_PREVIEW_MODEL
        ):
            approved_issues.append("approved_profile_vision_model_mismatch")
        return tuple(dict.fromkeys(approved_issues))

    if profile != QWEN_PRODUCTION_PROFILE_STANDARD:
        return ("unsupported_production_profile",)

    issues: list[str] = []
    if not configured.qwen_api_key:
        issues.append("missing_api_key")
    elif configured.qwen_api_key.startswith("sk-sp-"):
        issues.append("token_plan_key")

    endpoint_issue = _production_qwen_endpoint_issue(
        configured.qwen_base_url
    )
    if endpoint_issue is not None:
        issues.append(endpoint_issue)

    for role, model in (
        ("text", configured.qwen_model),
        ("vision", configured.qwen_vision_model),
    ):
        normalized = model.strip().casefold()
        if not normalized.startswith("qwen"):
            issues.append(f"{role}_model_not_qwen")
        elif role == "vision" and not qwen_model_supports_vision(model):
            issues.append("vision_model_not_multimodal")
        if "preview" in normalized:
            issues.append(f"{role}_preview_model")
    return tuple(dict.fromkeys(issues))


def validate_production_qwen_configuration(
    configured: Settings,
) -> None:
    issues = production_qwen_configuration_issues(configured)
    if issues:
        raise RuntimeError(
            "Qwen 生产配置不合规："
            + ",".join(issues)
            + "。请使用标准生产配置，或显式批准且精确匹配的"
            " Qwen production profile。"
        )


def _int_setting(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(value, minimum)


def _float_setting(
    name: str,
    default: float,
    minimum: float = 0,
) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(value, minimum)


def load_settings() -> Settings:
    qwen_api_key, qwen_secret_source, qwen_secret_error = _load_qwen_secret()
    qwen_model = (
        os.getenv("QWEN_MODEL", DEFAULT_QWEN_MODEL).strip()
        or DEFAULT_QWEN_MODEL
    )
    pdf_transcription_mode = os.getenv(
        "MINDMAP_PDF_TRANSCRIPTION_MODE",
        "vision_nodes_strict",
    ).strip().casefold()
    if pdf_transcription_mode != "vision_nodes_strict":
        pdf_transcription_mode = "vision_nodes_strict"
    pdf_page_extraction_mode = os.getenv(
        "MINDMAP_PDF_PAGE_EXTRACTION_MODE",
        "direct",
    ).strip().casefold()
    if pdf_page_extraction_mode != "direct":
        pdf_page_extraction_mode = "direct"
    try:
        qwen_temperature = float(os.getenv("QWEN_TEMPERATURE", "0.1"))
    except ValueError:
        qwen_temperature = 0.1
    qwen_temperature = min(max(qwen_temperature, 0.0), 2.0)

    external_engine_token = os.getenv("EXTERNAL_ENGINE_TOKEN", "")
    mindmap_data_dir = Path(
        os.getenv(
            "MINDMAP_DATA_DIR",
            str(PROJECT_ROOT / ".data" / "mindmap_engine"),
        )
    ).resolve()
    return Settings(
        qwen_api_key=qwen_api_key,
        qwen_base_url=os.getenv(
            "QWEN_BASE_URL",
            DEFAULT_QWEN_BASE_URL,
        ).rstrip("/"),
        qwen_model=qwen_model,
        qwen_temperature=qwen_temperature,
        qwen_secret_source=qwen_secret_source,
        qwen_secret_error=qwen_secret_error,
        workspace_name=os.getenv(
            "QWEN_WORKSPACE_NAME",
            "Qwen 本地工作区",
        ),
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
        qwen_vision_model=os.getenv(
            "QWEN_VISION_MODEL",
            DEFAULT_QWEN_VISION_MODEL,
        ).strip()
        or DEFAULT_QWEN_VISION_MODEL,
        qwen_production_profile=os.getenv(
            "MINDMAP_QWEN_PRODUCTION_PROFILE",
            QWEN_PRODUCTION_PROFILE_STANDARD,
        ).strip().casefold()
        or QWEN_PRODUCTION_PROFILE_STANDARD,
        pdf_transcription_mode=pdf_transcription_mode,
        pdf_page_extraction_mode=pdf_page_extraction_mode,
        pdf_transcription_dpi=_int_setting(
            "MINDMAP_PDF_TRANSCRIPTION_DPI",
            192,
            96,
        ),
        pdf_transcription_concurrency=_int_setting(
            "MINDMAP_PDF_TRANSCRIPTION_CONCURRENCY",
            8,
        ),
        pdf_transcription_max_attempts=_int_setting(
            "MINDMAP_PDF_TRANSCRIPTION_MAX_ATTEMPTS",
            3,
        ),
        pdf_transcription_min_confidence=min(
            _float_setting(
                "MINDMAP_PDF_TRANSCRIPTION_MIN_CONFIDENCE",
                0.85,
                0,
            ),
            1,
        ),
        solver_timeout_seconds=float(
            os.getenv("MINDMAP_SOLVER_TIMEOUT_SECONDS", "5")
        ),
        max_chunk_chars=_int_setting("MINDMAP_MAX_CHUNK_CHARS", 1800, 200),
        chunk_overlap_chars=_int_setting(
            "MINDMAP_CHUNK_OVERLAP_CHARS",
            240,
            0,
        ),
        extraction_concurrency=_int_setting(
            "MINDMAP_EXTRACTION_CONCURRENCY",
            4,
        ),
        environment=os.getenv("MINDMAP_ENV", "development").strip().lower(),
        workbench_owner_id=os.getenv(
            "MINDMAP_WORKBENCH_OWNER_ID",
            "public-workbench",
        ).strip()
        or "public-workbench",
        max_upload_bytes=_int_setting(
            "MINDMAP_MAX_UPLOAD_BYTES",
            80 * 1024 * 1024,
            1024,
        ),
        max_image_pixels=_int_setting(
            "MINDMAP_MAX_IMAGE_PIXELS",
            40_000_000,
        ),
        max_document_pages=_int_setting(
            "MINDMAP_MAX_DOCUMENT_PAGES",
            150,
        ),
        max_zip_uncompressed_bytes=_int_setting(
            "MINDMAP_MAX_ZIP_UNCOMPRESSED_BYTES",
            300 * 1024 * 1024,
            1024,
        ),
        max_zip_compression_ratio=_float_setting(
            "MINDMAP_MAX_ZIP_COMPRESSION_RATIO",
            120,
            1,
        ),
        max_concurrent_jobs=_int_setting(
            "MINDMAP_MAX_CONCURRENT_JOBS",
            1,
        ),
        provider_concurrency=_int_setting(
            "MINDMAP_PROVIDER_CONCURRENCY",
            8,
        ),
        export_concurrency=_int_setting(
            "MINDMAP_EXPORT_CONCURRENCY",
            1,
        ),
        source_retention_hours=_int_setting(
            "MINDMAP_SOURCE_RETENTION_HOURS",
            72,
            0,
        ),
        provider_timeout_seconds=_float_setting(
            "MINDMAP_PROVIDER_TIMEOUT_SECONDS",
            180,
            1,
        ),
        provider_max_attempts=_int_setting(
            "MINDMAP_PROVIDER_MAX_ATTEMPTS",
            3,
        ),
        provider_retry_base_seconds=_float_setting(
            "MINDMAP_PROVIDER_RETRY_BASE_SECONDS",
            0.5,
            0,
        ),
        provider_retry_delay_cap_seconds=_float_setting(
            "MINDMAP_PROVIDER_RETRY_DELAY_CAP_SECONDS",
            30,
            0,
        ),
        provider_circuit_cooldown_seconds=_float_setting(
            "MINDMAP_PROVIDER_CIRCUIT_COOLDOWN_SECONDS",
            120,
            1,
        ),
        parser_version=os.getenv(
            "MINDMAP_PARSER_VERSION",
            "parser-v9-direct-visual-only",
        ),
        prompt_version=os.getenv(
            "MINDMAP_PROMPT_VERSION",
            "editorial-ppt-vision-v1",
        ),
        theme_prompt_version=os.getenv(
            "MINDMAP_THEME_PROMPT_VERSION",
            "theme-synthesizer-v4-semantic-partition",
        ),
        pdf_page_knowledge_prompt_version=os.getenv(
            "MINDMAP_PDF_PAGE_KNOWLEDGE_PROMPT_VERSION",
            "editorial-ppt-vision-v1",
        ),
        pdf_page_transcription_prompt_version=os.getenv(
            "MINDMAP_PDF_PAGE_TRANSCRIPTION_PROMPT_VERSION",
            "editorial-ppt-vision-v1",
        ),
        schema_version=os.getenv(
            "MINDMAP_SCHEMA_VERSION",
            "mindmap-schema-v2",
        ),
        layout_version=os.getenv(
            "MINDMAP_LAYOUT_VERSION",
            "right-first-tree-v2",
        ),
    )


settings = load_settings()
