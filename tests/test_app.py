"""Run the Streamlit form twice against a clean SQLite inbox."""
from pathlib import Path

from pytest import MonkeyPatch
from streamlit.testing.v1 import AppTest


def test_local_form_uses_real_ledger(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GAMAK_DB_PATH", str(tmp_path / "ui.sqlite3"))
    monkeypatch.setenv("GAMAK_MODE", "local")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception
    assert app.metric[0].value == "0건"

    app.button[0].click().run()
    assert not app.exception
    assert app.subheader[1].value == "갱신 필요"
    assert any("승인함 0 → 1건" in item.value for item in app.markdown)
    draft_id = app.code[0].value

    app.button[0].click().run()
    assert not app.exception
    assert any("승인함 1 → 1건" in item.value for item in app.markdown)
    assert app.code[0].value == draft_id


def test_ibm_without_credentials_uses_local_inbox(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GAMAK_DB_PATH", str(tmp_path / "fallback.sqlite3"))
    monkeypatch.setenv("GAMAK_MODE", "watsonx")
    monkeypatch.setenv("WXO_ENDPOINT_URL", "")
    monkeypatch.setenv("WXO_API_KEY", "")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()

    app.button[0].click().run()
    assert not app.exception
    assert "로컬 자료로 재현했습니다" in app.warning[0].value
    assert any("승인함 0 → 1건" in item.value for item in app.markdown)
