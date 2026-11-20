"""Run a review from a JSON request with Python's module entry point."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from .contract import Request
from .evidence import ARCHIVE
from .service import review


def main(
    request: Annotated[Path, typer.Argument(help="UTF-8 request JSON")],
    db: Annotated[Path, typer.Option(help="SQLite approval inbox")] = Path("data/local/gamak.sqlite3"),
    archive: Annotated[Path, typer.Option(help="Official announcement archive")] = ARCHIVE,
) -> None:
    """Compare the approved notice against official evidence and print the result."""
    try:
        payload = Request.model_validate_json(request.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        typer.echo("요청 JSON을 읽을 수 없습니다. 입력 형식과 기준시각을 확인해 주세요.", err=True)
        raise typer.Exit(2) from None
    typer.echo(review(payload, db, archive=archive).model_dump_json(indent=2))


if __name__ == "__main__":
    typer.run(main)
