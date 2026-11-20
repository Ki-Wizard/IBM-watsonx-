# 수협 적조 안내 갱신 에이전트 프롬프트 및 검증 사례 명세

`feat/agent-prompt` 브랜치에서 작성된 에이전트 시스템 프롬프트 규격과 5대 검증 질문(시나리오)별 기대 판정 및 근거 정리 문서입니다.

---

## 1. 개요 및 목적

- **목적**: 당직자가 해역, 기준시각(KST), 직전 승인본 ID, 질문을 입력하면 에이전트가 공식 발표문헌과 직전 승인본을 대조하여 갱신 여부를 판정하고, 승인 대기 초안 또는 확인 질문을 공통 JSON 스키마로 출력합니다.
- **연동 대상**: 
  - `feat/backend-ledger`: SQLite 모의 승인함(Ledger) 중복 방지 및 공식 자료 조회 백엔드
  - `feat/demo-ui`: Streamlit 화면 표출
  - `feat/watsonx-integration`: IBM watsonx Orchestrate 및 LLM 연동

---

## 2. 5대 검증 질문 및 기대 결과 요약

| 번호 | 사례 | 질문 (Question) | 기대 판정 (`decision`) | 핵심 근거 (`evidence_id`) | 초안 (`draft`) / 후속 조치 | 승인함 변화 (`ledger`) |
| :---: | :--- | :--- | :---: | :---: | :--- | :---: |
| **1** | **갱신** | "이 안내를 계속 써도 되나?" (8/29 16:30 KST) | `갱신 필요` | `mof-62990` | 주의보·경계 발령 반영 초안 생성 | `0 → 1` (`created`) |
| **2** | **유지** | "8월 26일 발령된 안내를 현재 시점(17:00)에도 유지해도 됩니까?" | `유지` | `mof-62891` | 초안 없음 (`null`), 기존 안내 유지 | `0 → 0` (`none`) |
| **3** | **반복 요청** | "이 안내를 계속 써도 되나?" (동일 조건 재실행) | `갱신 필요` | `mof-62990` | 기존 초안 ID 재반환 | `1 → 1` (`reused`) |
| **4** | **해역 불명** | "남해안 일부 해역 특보가 해제되었다는데 가막만 안내를 종료해도 되나요?" | `확인 필요` | `mof-62990` | 초안 없음 (`null`), 세부 경계 확인 질문(`follow_up_question`) | `1 → 1` (`none`) |
| **5** | **수온 누락** | "가막만 적조 특보 현황과 현장 수온을 확인해 안내문을 작성해줘." | `갱신 필요` | `mof-62990` | 수온 "확인 필요" 표기 포함 초안 생성 | `0 → 1` (`created`) |

---

## 3. 검증 질문별 상세 분석

### Case 1. 갱신 (Update)
- **상황**: 2025-08-26 가상 승인본(예비특보/주의) 이후, 2025-08-29 14:00 가막만 적조주의보 및 16:00 정부 위기경보 '경계' 발령.
- **판정**: `갱신 필요`
- **근거**: 해양수산부 8월 29일 발표(`mof-62990`).
- **초안 텍스트**:
  > "가막만 적조 특보는 8월 29일 14시부터 적조주의보로 변경됐습니다. 정부 위기경보는 같은 날 16시부터 ‘경계’입니다. 당시 가막만 수온은 확인이 필요합니다."
- **참조 파일**: [examples/test-cases/case1-update.request.json](../examples/test-cases/case1-update.request.json), [examples/test-cases/case1-update.expected.json](../examples/test-cases/case1-update.expected.json)

### Case 2. 유지 (Maintain)
- **상황**: 2025-08-26 16:00 승인 직후인 17:00 시점에 동일 안내 사용 가능 여부 질의.
- **판정**: `유지`
- **근거**: 해양수산부 8월 26일 발표(`mof-62891`). 기준시각(17:00)까지 추가 발표가 없으므로 상태 변경 없음.
- **초안 및 후속 조치**: 초안 생성 없음 (`draft: null`), 확인 질문 없음 (`follow_up_question: null`).
- **참조 파일**: [examples/test-cases/case2-maintain.request.json](../examples/test-cases/case2-maintain.request.json), [examples/test-cases/case2-maintain.expected.json](../examples/test-cases/case2-maintain.expected.json)

### Case 3. 반복 요청 (Idempotency / Deduplication)
- **상황**: Case 1과 동일한 해역, 기준시각, 직전 승인본으로 동일 질문을 재실행.
- **판정**: `갱신 필요`
- **백엔드/승인함 동작**: 기존에 발급된 동일 초안 식별자(`draft-5b09a129...`)를 반환하며, 승인함 등록 건수는 1건 유지(`action: "reused"`).
- **참조 파일**: [examples/test-cases/case3-repeat.request.json](../examples/test-cases/case3-repeat.request.json), [examples/test-cases/case3-repeat.expected.json](../examples/test-cases/case3-repeat.expected.json)

### Case 4. 해역 불명 (Ambiguous Region Scope)
- **상황**: 남해안 일부 해역 특보 해제 발표가 있으나, 발표문 상에 가막만의 포함 여부가 불명확한 상태.
- **판정**: `확인 필요`
- **근거 및 후속 질문**: 공식 문헌(`mof-62990`)에서 가막만 해제 여부 확정 불가. 당직자에게 국립수산과학원 적조속보 상세 경계 구역 확인을 유도하는 후속 질문(`follow_up_question`) 제시.
- **초안**: 자동 초안 발송 보류 (`draft: null`).
- **참조 파일**: [examples/test-cases/case4-unknown-region.request.json](../examples/test-cases/case4-unknown-region.request.json), [examples/test-cases/case4-unknown-region.expected.json](../examples/test-cases/case4-unknown-region.expected.json)

### Case 5. 수온 누락 (Missing Water Temperature)
- **상황**: 특보 및 위기경보 격상은 확인되었으나 공식 보도자료에 당시 가막만의 실측 수온 데이터가 누락됨.
- **판정**: `갱신 필요`
- **수온 필드 처리**: 임의 추정 금지, `water_temperature: { "status": "확인 필요", "celsius": null }`로 기록.
- **초안 반영**: 특보 갱신 초안을 정상 발행하되, "당시 가막만 수온은 확인이 필요합니다."를 본문에 반드시 포함.
- **참조 파일**: [examples/test-cases/case5-missing-temp.request.json](../examples/test-cases/case5-missing-temp.request.json), [examples/test-cases/case5-missing-temp.expected.json](../examples/test-cases/case5-missing-temp.expected.json)

---

## 4. 시스템 프롬프트 규격

전체 시스템 프롬프트 전문은 [prompts/agent-system-prompt.md](../prompts/agent-system-prompt.md)에 위치합니다.
에이전트는 엄격하게 Grounding(공식 근거 일치), Temporal Cutoff(기준시각 준수), Schema Validation(공통 JSON 포맷)을 준수하도록 설계되었습니다.
