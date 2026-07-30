"""Source observation contracts and clean-room parsers."""

from backend.vnext.contracts.source import SourceObservationIR
from .parser import (
    PARSER_MAJOR,
    PARSER_NAME,
    PARSER_VERSION,
    SUPPORTED_SUFFIXES,
    parse_source,
)

__all__ = [
    "PARSER_MAJOR",
    "PARSER_NAME",
    "PARSER_VERSION",
    "SUPPORTED_SUFFIXES",
    "SourceObservationIR",
    "parse_source",
]
