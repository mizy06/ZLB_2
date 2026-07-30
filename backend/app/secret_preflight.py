from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Sequence


DEFAULT_EXPECTED_UID = 0
DEFAULT_EXPECTED_GID = 10001
DEFAULT_EXPECTED_MODE = 0o440


class SecretPreflightError(RuntimeError):
    """Raised when a mounted secret cannot be consumed safely."""


def validate_secret_file(
    path: Path,
    *,
    expected_uid: int = DEFAULT_EXPECTED_UID,
    expected_gid: int = DEFAULT_EXPECTED_GID,
    expected_mode: int = DEFAULT_EXPECTED_MODE,
) -> None:
    """Validate metadata without opening or reading the secret."""

    secret_path = Path(path)
    try:
        metadata = os.lstat(secret_path)
    except FileNotFoundError as exc:
        raise SecretPreflightError(
            f"{secret_path}: secret 文件不存在。"
        ) from exc
    except OSError as exc:
        raise SecretPreflightError(
            f"{secret_path}: 无法检查 secret 文件元数据（errno={exc.errno}）。"
        ) from exc

    if stat.S_ISLNK(metadata.st_mode):
        raise SecretPreflightError(
            f"{secret_path}: secret 文件不能是符号链接。"
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise SecretPreflightError(
            f"{secret_path}: secret 路径必须是普通文件。"
        )
    if metadata.st_uid != expected_uid:
        raise SecretPreflightError(
            f"{secret_path}: owner UID 必须是 {expected_uid}，"
            f"当前为 {metadata.st_uid}。"
        )
    if metadata.st_gid != expected_gid:
        raise SecretPreflightError(
            f"{secret_path}: group GID {expected_gid} 是必需值，"
            f"当前为 {metadata.st_gid}。"
        )

    actual_mode = stat.S_IMODE(metadata.st_mode)
    if actual_mode != expected_mode:
        raise SecretPreflightError(
            f"{secret_path}: 权限必须是 {expected_mode:04o}，"
            f"当前为 {actual_mode:04o}。"
        )


def validate_secret_files(
    paths: Sequence[Path],
    *,
    expected_uid: int = DEFAULT_EXPECTED_UID,
    expected_gid: int = DEFAULT_EXPECTED_GID,
    expected_mode: int = DEFAULT_EXPECTED_MODE,
) -> None:
    for path in paths:
        validate_secret_file(
            path,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            expected_mode=expected_mode,
        )


def _octal_mode(value: str) -> int:
    try:
        parsed = int(value, 8)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("权限必须是八进制数，例如 0440。") from exc
    if parsed < 0 or parsed > 0o7777:
        raise argparse.ArgumentTypeError("权限必须位于 0000 到 7777。")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "在不读取内容的前提下，验证 age secret 的文件类型、"
            "属主、属组和权限。"
        )
    )
    parser.add_argument(
        "--expected-uid",
        type=int,
        default=DEFAULT_EXPECTED_UID,
        help=f"要求的 owner UID（默认 {DEFAULT_EXPECTED_UID}）",
    )
    parser.add_argument(
        "--expected-gid",
        type=int,
        default=DEFAULT_EXPECTED_GID,
        help=f"要求的 group GID（默认 {DEFAULT_EXPECTED_GID}）",
    )
    parser.add_argument(
        "--expected-mode",
        type=_octal_mode,
        default=DEFAULT_EXPECTED_MODE,
        help="要求的八进制权限（默认 0440）",
    )
    parser.add_argument(
        "secret_files",
        type=Path,
        nargs="+",
        help="需要验证的 secret 文件",
    )
    parser.add_argument(
        "--exec",
        dest="exec_command",
        nargs=argparse.REMAINDER,
        help="验证通过后替换为该进程",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_secret_files(
            args.secret_files,
            expected_uid=args.expected_uid,
            expected_gid=args.expected_gid,
            expected_mode=args.expected_mode,
        )
    except SecretPreflightError as exc:
        print(f"secret preflight failed: {exc}", file=sys.stderr)
        return 2

    command = list(args.exec_command or ())
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        return 0

    try:
        os.execvp(command[0], command)
    except OSError as exc:
        print(
            "secret preflight passed, but target process could not start "
            f"(errno={exc.errno}).",
            file=sys.stderr,
        )
        return 126
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
