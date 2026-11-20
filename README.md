# 수협 적조 안내 갱신 에이전트

IBM watsonx 실무교육 팀 프로젝트입니다. 수협 당직자가 해역과 기준시각을 입력하면 에이전트가 직전 승인 안내와 공식 발표를 대조합니다. 변경이 확인되면 근거와 함께 승인 대기 초안을 모의 승인함에 남깁니다.

## 첫 시연

여수 가막만의 2025년 8월 26일 가상 승인본과 8월 29일 공식 발표를 비교합니다. 화면에서 해역 적조특보와 정부 위기경보의 변경을 각각 확인하고, 같은 요청을 다시 실행해 승인함에 초안이 한 건만 남는지 확인합니다.

[시연 범위와 검증 기준](docs/demo-plan.md)

## 팀 작업 시작

1. 저장소를 복제합니다.

   ```sh
   git clone https://github.com/Ki-Wizard/IBM-watsonx-.git
   ```

2. 아래 작업 브랜치에서 작업하고, 변경은 `main`을 대상으로 Pull Request를 엽니다.
3. IBM 연동을 개발할 때는 `.env.example`을 복사해 로컬 `.env`를 만들고, 발급받은 값을 그 파일에 넣습니다.

### 브랜치와 병합

| 브랜치 | 담당 작업 |
| --- | --- |
| `main` | 팀 통합과 시연 기준 |
| `feat/backend-ledger` | 공통 입출력, 공식 자료 조회, 검증, 승인함 저장 |
| `feat/demo-ui` | Streamlit 화면 및 백엔드 연결 |
| `feat/agent-prompt` | 에이전트 프롬프트와 시연 사례별 기대 결과 |
| `feat/watsonx-integration` | watsonx Orchestrate 도구, 에이전트 배포, 호출 연동 |

처음 복제한 뒤에는 `git switch feat/backend-ledger`와 같이 담당 브랜치로 이동합니다. 이후 작업은 최신 `main`에서 `feat/<작업명>`, `fix/<작업명>`, `docs/<작업명>` 브랜치를 만들어 진행합니다.

PR에 변경 내용과 확인 결과를 기록하고, 입출력이나 환경변수를 바꿨다면 연동 담당자에게 리뷰를 요청합니다. 병합할 때는 **Squash and merge**를 사용합니다.

## 개발 상태

가막만 대표 사례는 보관한 공식 발표와 가상 승인본으로 로컬에서 실행할 수 있습니다. 두 발표의 원문과 시연 중 조회 가능한 자료는 `data/gamak-archive.json`에 있습니다. 웹 페이지에 게시 분 단위 정보가 없어 즉시 보도자료의 정부 발령시각을 시연 자료의 조회 가능시각으로 사용합니다.

### 화면 없이 대표 사례 실행

```sh
uv sync
uv run python -m gamak_demo examples/gamak-update.request.json --db data/local/cli-rehearsal.sqlite3
uv run python -m gamak_demo examples/gamak-update.request.json --db data/local/cli-rehearsal.sqlite3
uv run pytest -q
```

빈 DB에서 동일 요청을 실행하면 승인함은 `0 → 1 → 1`이 되고 두 응답의 초안 ID가 같습니다. 새 리허설을 시작할 때는 아직 사용하지 않은 DB 파일명을 지정하세요.

### Streamlit 리허설

```powershell
$env:GAMAK_DB_PATH = "data/local/ui-rehearsal.sqlite3"
uv run streamlit run app.py --server.address 127.0.0.1
```

IBM 경로를 실행하려면 `.env`에서 `WXO_ENDPOINT_URL`, `WXO_API_KEY`를 설정하고 `GAMAK_MODE=watsonx`로 선택합니다. 기존 교육용 설정 파일을 사용할 때는 `GAMAK_ENV_FILE`로 그 파일을 가리킬 수 있습니다. 에이전트가 반환한 판정과 대화 이력의 공식 근거 도구 결과를 모두 검증한 경우 화면에 **IBM 실호출**이 표시됩니다. 호출이나 검증에 실패하면 안내와 함께 **로컬 재현**으로 전환됩니다.

### 프로젝트 에이전트 배포

IBM Orchestrate ADK CLI에서 교육 환경을 활성화한 뒤 PowerShell 7에서 `./watsonx/deploy.ps1`을 실행합니다. 교육 계정의 `kiw_gamak_red_tide`에 공용 시연 자료를 조회하는 `kiw_gamak_official_evidence` 도구가 연결됩니다.

[시연 검증표와 발표 순서](docs/rehearsal.md)
