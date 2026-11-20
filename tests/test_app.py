"""Run the Streamlit form twice against a clean SQLite inbox."""
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from pydantic import SecretStr
from pytest import MonkeyPatch
from streamlit.testing.v1 import AppTest

from gamak_demo import nifs
from gamak_demo.contract import Request


def test_local_form_uses_real_ledger(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GAMAK_DB_PATH", str(tmp_path / "ui.sqlite3"))
    monkeypatch.setenv("GAMAK_MODE", "local")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception
    assert app.metric[0].value == "0건"

    app.button(key="judge").click().run()
    assert not app.exception
    assert any(item.value == "갱신 필요" for item in app.subheader)
    assert any("승인함 0 → 1건" in item.value for item in app.markdown)
    assert any("근거 1 원문" in item.value for item in app.markdown)
    assert any("근거 2 원문" in item.value for item in app.markdown)
    draft_id = app.code[0].value

    app.button(key="judge").click().run()
    assert not app.exception
    assert any("승인함 1 → 1건" in item.value for item in app.markdown)
    assert app.code[0].value == draft_id


def test_ibm_without_credentials_uses_local_inbox(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GAMAK_DB_PATH", str(tmp_path / "fallback.sqlite3"))
    monkeypatch.setenv("GAMAK_MODE", "watsonx")
    monkeypatch.setenv("WXO_ENDPOINT_URL", "")
    monkeypatch.setenv("WXO_API_KEY", "")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()

    app.button(key="judge").click().run()
    assert not app.exception
    assert "로컬 자료로 재현했습니다" in app.warning[0].value
    assert any("승인함 0 → 1건" in item.value for item in app.markdown)


def test_load_and_compare_uses_no_ledger_when_no_judgment(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    db = tmp_path / "rehearsal.sqlite3"
    monkeypatch.setenv("GAMAK_DB_PATH", str(db))
    monkeypatch.setenv("GAMAK_MODE", "local")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    app.selectbox(key="scenario").select("cutoff-compare-maintain").run()
    app.button(key="load_scenario").click().run()
    assert app.date_input(key="as_of_day").value.isoformat() == "2025-08-26"
    assert app.selectbox(key="notice").value == "gamak-2025-08-26-demo"

    app.button(key="compare").click().run()

    assert not app.exception
    assert {"유지", "갱신 필요"} <= {item.value for item in app.subheader}
    assert any("적조 위기경보 ‘경계’ 단계 발령" in item.value for item in app.markdown)
    assert not db.exists()


def test_fresh_demo_preserves_rehearsal_when_switched_back(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    db = tmp_path / "rehearsal.sqlite3"
    monkeypatch.setenv("GAMAK_DB_PATH", str(db))
    monkeypatch.setenv("GAMAK_MODE", "local")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    app.button(key="judge").click().run()

    app.button(key="new_demo").click().run()
    assert not app.exception
    assert app.metric[0].value == "0건"
    assert "demo" in app.query_params
    app.selectbox(key="demo_session").select("").run()

    assert app.metric[0].value == "1건"
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM checks").fetchone() == (1,)


def test_follow_up_and_approval_are_present_in_reopened_inbox(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    db = tmp_path / "rehearsal.sqlite3"
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    monkeypatch.setenv("GAMAK_DB_PATH", str(db))
    monkeypatch.setenv("GAMAK_MODE", "local")
    app = AppTest.from_file(app_path).run()
    app.button(key="judge").click().run()
    next(item for item in app.text_input if item.label == "처리 담당자").set_value("테스트 담당자")
    next(item for item in app.text_area if item.label == "처리 메모").set_value("경보 발령시각 대조")
    app.button(key="approve").click().run()
    app.selectbox(key="scenario").select("ambiguous-release-scope").run()
    app.button(key="load_scenario").click().run()
    app.button(key="judge").click().run()
    next(item for item in app.text_input if item.label == "확인 담당자").set_value("테스트 담당자")
    next(item for item in app.text_area if item.label == "확인 메모").set_value("해제 범위 추가 확인")
    app.button(key="retry").click().run()

    reopened = AppTest.from_file(app_path).run()

    assert not reopened.exception
    assert any(item.value == "**승인** · 테스트 담당자" for item in reopened.markdown)
    assert {"경보 발령시각 대조", "해제 범위 추가 확인"} <= {item.value for item in reopened.text}
    assert reopened.metric[0].value == "0건"


def test_release_demo_links_nifs_and_mof_separately(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GAMAK_DB_PATH", str(tmp_path / "release.sqlite3"))
    monkeypatch.setenv("GAMAK_MODE", "local")
    monkeypatch.setenv("NIFS_RED_TIDE_API_KEY", "fixture")

    def supplied_bulletin(key: SecretStr | None, request: Request) -> nifs.NifsChecked:
        assert key is not None and request.as_of.date() == date(2025, 9, 26)
        return nifs.NifsChecked(bulletin=nifs.Bulletin(
            code="20250925-001", survey_day=date(2025, 9, 25),
            breaking="- 특보 해제 : 사천·강진만, 가막만",
        ))

    monkeypatch.setattr(nifs, "lookup_release", supplied_bulletin)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    app.selectbox(key="scenario").select("gamak-release").run()
    app.button(key="load_scenario").click().run()
    assert app.text_area(key="question").value == "가막만도 특보 해제 대상인가요?"

    app.button(key="judge").click().run()

    assert not app.exception
    links = [element.value for element in app.markdown]
    assert any("근거 1 원문" in value and "codNews=20250925-001" in value for value in links)
    assert any("근거 2 원문" in value and "docSeq=63302" in value for value in links)
    assert any("승인함 0 → 1건" in value for value in links)
