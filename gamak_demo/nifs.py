"""Read the NIFS red-tide bulletin list and detail for the release demonstration."""
from __future__ import annotations

import logging
import re
import socket
from datetime import date, datetime, timedelta
from html import unescape
from typing import Annotated, Final, Literal

import httpx2
from pydantic import BaseModel, Field, JsonValue, SecretStr, StringConstraints, ValidationError

from .contract import KST, Contract, Request

CONNECTION_ID: Final = "kiw_nifs_red_tide"
KEY_ENV: Final = "NIFS_RED_TIDE_API_KEY"
_API: Final = "https://www.nifs.go.kr/api/OpenAPI_json"
# Verified against the official bulletin board entry and its linked detail.
_REGISTERED: Final = {"20250925-001": date(2025, 9, 25)}
_GAMAK_RELEASE: Final = re.compile(
    r"(?m)(?:^|(?<=\s)[-•]\s+)\s*(?:[-•]\s*)?"
    r"(?:적조\s*)?(?:예비특보|특보|주의보)\s*해제\s*[:：]\s*([^\n]+)",
)
Code = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,24}$")]


class _PrivateQuery(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "/api/OpenAPI_json?" not in message or "key=" not in message


_PRIVATE_QUERY: Final = _PrivateQuery()
for _logger in ("httpx2", "httpcore2.http11", "httpcore2.http2", "hpack.hpack"):
    logging.getLogger(_logger).addFilter(_PRIVATE_QUERY)


class Bulletin(Contract):
    code: Code
    survey_day: date
    breaking: Annotated[str, StringConstraints(max_length=4000)]

    @property
    def url(self) -> str:
        return f"https://www.nifs.go.kr/rtm/TRS/450/view.do?codNews={self.code}"

    @property
    def known_by(self) -> datetime | None:
        # The public board verifies the registration date, with no publication clock time.
        registered = _REGISTERED.get(self.code)
        if registered is not None:
            return datetime.combine(registered + timedelta(days=1), datetime.min.time(), KST)
        return None


class NifsChecked(Contract):
    status: Literal["checked"] = "checked"
    bulletin: Bulletin | None = None


class NifsUnavailable(Contract):
    status: Literal["unavailable"] = "unavailable"
    reason: Literal["missing_key", "license", "service", "response"]


NifsReport = Annotated[NifsChecked | NifsUnavailable, Field(discriminator="status")]


class _Header(BaseModel):
    resultCode: str


class _Response(BaseModel):
    header: _Header
    body: JsonValue = None


class _ListEntry(BaseModel):
    cod_news: Code
    day_report: str

    @property
    def survey_day(self) -> date:
        return date.fromisoformat(self.day_report[:10].replace(".", "-").replace("/", "-"))


class _Detail(_ListEntry):
    txt_breaking: str | None = None


class _ApiFailure(RuntimeError):
    def __init__(self, *, license_error: bool) -> None:
        self.license_error = license_error
        super().__init__("NIFS API did not return results.")


def is_release_question(question: str) -> bool:
    return ("해제" in question and ("특보" in question or "일부" in question)) or (
        "안내" in question and "종료" in question
    )


def release_excerpt(bulletin: Bulletin, request: Request) -> str | None:
    """Require known publication availability and explicit inclusion in the release list."""
    known_by = bulletin.known_by
    if known_by is None or known_by > request.as_of or bulletin.survey_day >= known_by.date():
        return None
    text = re.sub(r"(?i)<(?:br\b[^>]*|/(?:p|div|li))>", "\n", unescape(bulletin.breaking))
    text = re.sub(r"<[^>]*>", "", text)
    for match in _GAMAK_RELEASE.finditer(text):
        targets = re.split(r"\s+-\s+|-\s+(?=예비특보로\s+하향)", match[1], maxsplit=1)[0].strip().rstrip(".。")
        if any(
            re.fullmatch(r"(?:전남\s+)?(?:여수\s+)?가막만", part.strip())
            for part in re.split(r"[,，、]", targets)
        ):
            return f"특보 해제 대상 · {targets}"
    return None


def release_confirmed(report: NifsReport | None, request: Request) -> bool | None:
    """Return the scope finding from a successful lookup, or defer to the archive."""
    if not isinstance(report, NifsChecked):
        return None
    return report.bulletin is not None and release_excerpt(report.bulletin, request) is not None


def _records(node: JsonValue, *, detail: bool = False) -> tuple[_ListEntry, ...]:
    if isinstance(node, list):
        return tuple(record for child in node for record in _records(child, detail=detail))
    if isinstance(node, dict):
        if "cod_news" in node and "day_report" in node:
            record_type = _Detail if detail else _ListEntry
            return (record_type.model_validate(node),)
        return tuple(record for child in node.values() for record in _records(child, detail=detail))
    return ()


def _get(client: httpx2.Client, key: SecretStr, *, detail: bool = False, **params: str) -> tuple[_ListEntry, ...]:
    operation = "redtideDetail" if detail else "redtideList"
    response = client.get(
        _API, params={"id": operation, "key": key.get_secret_value(), **params},
    ).raise_for_status()
    envelope = _Response.model_validate_json(response.content)
    if envelope.header.resultCode != "00":
        raise _ApiFailure(license_error=envelope.header.resultCode == "02")
    return _records(envelope.body, detail=detail)


def fetch_release(client: httpx2.Client, key: SecretStr, request: Request) -> NifsReport:
    """Check the published demo bulletin and retain detail from one matching list entry."""
    end = request.as_of.date()
    start = date.fromordinal(max(1, end.toordinal() - 7))
    try:
        rows = _get(client, key, sdate=f"{start:%Y%m%d}", edate=f"{end:%Y%m%d}")
        candidates = [row for row in rows if start <= row.survey_day <= end]
        chosen = max(candidates, key=lambda row: (row.cod_news in _REGISTERED, row.survey_day), default=None)
        if chosen is None:
            return NifsChecked()
        for item in _get(client, key, detail=True, cod_news=chosen.cod_news):
            if item.cod_news == chosen.cod_news and item.survey_day == chosen.survey_day and isinstance(item, _Detail):
                return NifsChecked(bulletin=Bulletin(
                    code=item.cod_news, survey_day=item.survey_day, breaking=item.txt_breaking or "",
                ))
        return NifsUnavailable(reason="response")
    except _ApiFailure as error:
        return NifsUnavailable(reason="license" if error.license_error else "service")
    except httpx2.HTTPError:
        return NifsUnavailable(reason="service")
    except (ValidationError, ValueError, RecursionError):
        return NifsUnavailable(reason="response")


def lookup_release(key: SecretStr | None, request: Request) -> NifsReport:
    if key is None or not key.get_secret_value().strip():
        return NifsUnavailable(reason="missing_key")
    transport = httpx2.HTTPTransport(
        http2=True, retries=3,
        limits=httpx2.Limits(max_connections=200, max_keepalive_connections=40, keepalive_expiry=30),
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    # Use the observed HTTPS endpoint directly. Never forward the license in a redirect.
    with httpx2.Client(
        transport=transport, follow_redirects=False,
        timeout=httpx2.Timeout(connect=5, read=8, write=10, pool=10),
    ) as client:
        return fetch_release(client, key, request)
