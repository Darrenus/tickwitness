"""Native-free bounded values shared by replay qualification contracts."""

import hashlib
import json
import re
from typing import Never, cast

INT64_MAX = (1 << 63) - 1
MAX_DATA_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 10_000
MAX_RESULT_BYTES = 16 * 1024 * 1024
_DECIMAL = re.compile(r"([+-]?)([0-9]+)(?:\.([0-9]+))?\Z")


class ReplayValidationError(ValueError):
    """A qualification request or result violates its explicit supported scope."""


def integer(value: object, label: str, low: int = 0, high: int = INT64_MAX) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ReplayValidationError(f"{label} must be an integer in [{low}, {high}]")
    return value


def text(value: object, label: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ReplayValidationError(f"{label} must be nonempty text within {maximum} characters")
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ReplayValidationError(f"{label} cannot contain padding or control characters")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ReplayValidationError(f"{label} must contain valid Unicode") from error
    return value


def identity(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ReplayValidationError(f"{label} must be a lowercase SHA-256 identity")
    return value


def exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or value.keys() != keys:
        raise ReplayValidationError(f"{label} has missing or unknown fields")
    return cast("dict[str, object]", value)


def _reject_number(_value: str) -> Never:
    raise ReplayValidationError("Float syntax and non-finite JSON numbers are unsupported")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayValidationError("Duplicate JSON object key")
        result[key] = value
    return result


def parse(raw: bytes, maximum: int) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > maximum:
        raise ReplayValidationError(f"Input must be nonempty bytes within {maximum} bytes")
    try:
        value: object = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, ReplayValidationError):
            raise
        raise ReplayValidationError("Invalid bounded UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ReplayValidationError("Expected a JSON object")
    return cast("dict[str, object]", value)


def canonical(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ReplayValidationError("Value cannot be encoded as finite canonical JSON") from error


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def decimal(value: object, label: str, *, precision: int = 8) -> str:
    if not isinstance(value, str):
        raise ReplayValidationError(f"{label} must be a decimal string")
    match = _DECIMAL.fullmatch(value)
    if match is None:
        raise ReplayValidationError(f"{label} must be plain decimal without exponent")
    sign, whole, fraction = match.groups()
    fraction = fraction or ""
    if len(whole) + len(fraction) > 28 or len(fraction) > 18:
        raise ReplayValidationError(f"{label} exceeds decimal input precision")
    whole, fraction = whole.lstrip("0") or "0", fraction.rstrip("0")
    if len(fraction) > precision:
        raise ReplayValidationError(f"{label} exceeds {precision} canonical fractional places")
    magnitude = whole + ("." + fraction if fraction else "")
    return "-" + magnitude if sign == "-" and magnitude != "0" else magnitude


def ratio(value: str) -> tuple[int, int]:
    whole, _, fraction = value.partition(".")
    sign = -1 if whole.startswith("-") else 1
    digits = whole.lstrip("-") + fraction
    return sign * int(digits), 10 ** len(fraction)


def decimal_range(value: str, label: str, low: int, high: int, *, positive: bool = False) -> None:
    numerator, denominator = ratio(value)
    if (
        numerator < low * denominator
        or numerator > high * denominator
        or (positive and numerator <= 0)
    ):
        raise ReplayValidationError(f"{label} falls outside the supported physical range")
