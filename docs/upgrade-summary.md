# 프로젝트 업그레이드 결과 정리 (`feat/watsonx-ai-cloud-upgrade`)

## 1. 업그레이드 배경 및 목표
- **대상 프로젝트**: 수협 적조 안내 갱신 에이전트 (`IBM-watsonx-`)
- **목표**: 평가 기준표(IBM AI 실무교육 활용도·기술적 완성도·창의성/혁신성·실현 가능성/확장성·UI/UX)에 맞추어 **watsonx.ai**, **거버넌스 검증**, **IBM Cloud 서비스(Code Engine, Cloudant, COS)** 연동을 강화.

## 2. 주요 구현 내역

### A. watsonx.ai 다중 채널 안내문 생성 및 거버넌스 검증 (`gamak_demo/watsonx_ai.py`)
- **다중 채널 생성 (`generate_channel_notices`)**: `WATSONX_AI_API_KEY`, `WATSONX_AI_PROJECT_ID` 설정 시 `ibm/granite-3-8b-instruct` 모델로 아래 3종 안내문을 동시 생성(미설정 시 결정론적 템플릿 폴백).
  1. 어업인 발송용 SMS/알림톡
  2. 지자체·유관기관 보고용 공문 초안
  3. 수협 홈페이지·SNS 공지문
- **거버넌스 검증 (`evaluate_groundedness`)**:
  - 요청 해역명 일치, 해역 특보 단계 일치, 정부 위기경보 단계 일치, **미확인 수온 환각 차단**, 공식 출처 연결성을 자동 검증해 `Groundedness 점수(%)`와 `환각 위험도` 산출.

### B. 대응 매뉴얼 Hybrid RAG (`gamak_demo/hybrid_rag.py`, `data/gamak-manual.json`)
- `search_manual()`: 경보 단계별 수협 대응 지침을 `intfloat/multilingual-e5-large` 임베딩(watsonx.ai 연결 시)과 한국어 바이그램/토큰 유사도 하이브리드 검색으로 조회.

### C. IBM Cloud 연동 및 컨테이너 배포 (`gamak_demo/cloud_store.py`, `Dockerfile`, `ibmcloud/deploy-code-engine.ps1`)
- **IBM Cloudant**: `CLOUDANT_URL`, `CLOUDANT_APIKEY` 설정 시 로컬 SQLite와 함께 공용 클라우드 승인함으로 동기화(`sync_result_to_cloudant`).
- **IBM Cloud Object Storage**: `archive_report_to_cos()` 아카이빙 헬퍼 추가.
- **IBM Cloud Code Engine**: 포트 `8080` 기준 `Dockerfile` 및 원클릭 배포 스크립트(`ibmcloud/deploy-code-engine.ps1`) 구축.

### D. UI/UX 개선 (`app.py`, `gamak_demo/report_ui.py`)
- **사이드바 연동 현황**: `watsonx Orchestrate`, `watsonx.ai`, `IBM Cloudant`, `IBM COS`, `국립수산과학원 API` 연결 상태 표시.
- **판정 결과 비주얼 배너**: `갱신 필요` / `유지` / `확인 필요` 상태별 컬러 강조 배너 추가.
- **여수 가막만 해역 지도 시각화**: 특보 단계별 색상 마커가 표시되는 지도 패널(`show_region_map`) 추가.
- **다중 채널 안내문 & 리포트 다운로드**: 채널별 탭 UI 및 `.md` 리포트 원클릭 다운로드(`st.download_button`) 지원.

## 3. 검증 및 배포 상태
- **단위·통합 테스트**: `uv run pytest -q` (기존 37개 + 신규 7개 = **총 44개 통과**, `tests/test_watsonx_ai_cloud.py` 포함)
- **IBM Cloud Code Engine**: `gamak-red-tide` 프로젝트 / `gamak-red-tide-app` 배포 완료 (`https://gamak-red-tide-app.2hfa64w2nd9n.us-south.codeengine.appdomain.cloud`)
  - *참고: 최신 지도 크기/마커 조정분은 로컬 확인 후 재배포 예정*
