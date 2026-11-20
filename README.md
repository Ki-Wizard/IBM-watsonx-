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

기획과 저장소 초기 설정 단계입니다. 화면은 Streamlit, 승인함은 Python과 SQLite, 에이전트는 IBM watsonx Orchestrate를 사용하도록 설계했습니다. 교육 계정 연결에 문제가 있을 때는 같은 시연 데이터를 사용하는 로컬 재현 경로를 준비합니다.
