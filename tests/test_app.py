"""Run the Streamlit form twice against a clean SQLite inbox."""
from pathlib import Path

from pytest import MonkeyPatch
from streamlit.testing.v1 import AppTest


def test_local_form_uses_real_ledger(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GAMAK_DB_PATH", str(tmp_path / "ui.sqlite3"))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception
    assert app.metric[0].value == "0건"

    app.button[0].click().run()
    assert not app.exception
    assert app.subheader[1].value == "갱신 필요"
    assert "승인함 0 → 1건" in app.caption[1].value
    draft_id = app.code[0].value

    app.button[0].click().run()
    assert not app.exception
    assert "승인함 1 → 1건" in app.caption[1].value
    assert app.code[0].value == draft_id
