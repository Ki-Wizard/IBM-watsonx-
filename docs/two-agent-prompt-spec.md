# 2-에이전트 협업 프롬프트 및 핵심 검증 사례 명세

IBM watsonx Orchestrate 실제 배포 설정(`gamak_research.yaml`, `gamak_supervisor.yaml`)과 백엔드 인계 규격에 맞춰 동기화된 2-에이전트 협업 명세서입니다.

---

## 1. 2-에이전트 협업 및 백엔드 확정 구조

```
[수협 당직자 요청] (해역, 기준시각, 직전 승인본 ID, 질문)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1단계: 근거 조사 에이전트 (gamak_research.yaml)              │
│ - 프롬프트: prompts/evidence-researcher-prompt.md           │
│ - 기준시각(as_of) 이전 공식 원문만 조회                      │
│ - 인계 필드: scope_status, approved, regional, government   │
│ - 인용 ID: mof-62990-regional 등 경보별 발췌 인용 ID 사용     │
└───────────────────────────┬─────────────────────────────────┘
                            │ 구조화된 인계 JSON
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 2단계: 당직 지원 에이전트 (gamak_supervisor.yaml)            │
│ - 프롬프트: prompts/duty-support-prompt.md                  │
│ - 반환 필드: decision, regional_citation, government_citation│
└───────────────────────────┬─────────────────────────────────┘
                            │ 판정 및 경보별 인용 ID
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 3단계: 백엔드 검증 및 승인함 확정 (Ledger)                   │
│ - 인용 ID 및 판정 교차 검증                                   │
│ - 초안(draft) 또는 확인 질문(follow_up_question) 최종 생성   │
│ - 중복 방지(created / reused / none) 및 당직자 승인 대기 유지 │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 보강된 핵심 검증 사례 요약

### A. 같은 질문의 기준시각 비교 (Temporal Cutoff)
완전히 동일한 질문(`"이 안내를 계속 써도 되나?"`)을 던졌을 때, `as_of`(기준시각)에 따라 1단계 근거 조사 에이전트의 검색 범위가 달라져 판정과 인용 ID가 달라집니다.

| 비교 항목 | 시점 A (8월 26일 16:30 KST) | 시점 B (8월 29일 16:30 KST) |
| :--- | :--- | :--- |
| **당직자 질문** | `"이 안내를 계속 써도 되나?"` | `"이 안내를 계속 써도 되나?"` |
| **1단계 인계 (`scope_status`)** | `confirmed` (`mof-62891-*`만 조회) | `confirmed` (`mof-62990-*` 조회) |
| **2단계 반환 (`decision`)** | **`유지`** | **`갱신 필요`** |
| **경보별 인용 ID** | `mof-62891-regional`, `mof-62891-government` | `mof-62990-regional`, `mof-62990-government` |
| **백엔드 확정 & 승인함** | 초안 없음 (`0 → 0`, `none`) | 초안 생성 (`0 → 1`, `created`) |

### B. 해제 범위 불명 사례 (Ambiguity Handling)
- **질문**: `"남해안 일부 해역 특보가 해제되었다는데 가막만 안내를 종료해도 되나요?"`
- **1단계 인계**: 공식 원문에 가막만 해제 근거가 없으므로 `scope_status: "ambiguous"` 전달
- **2단계 반환**: `decision: "확인 필요"`, `regional_citation: "mof-62990-regional"`, `government_citation: "mof-62990-government"`
- **백엔드 확정**: 초안 발급 보류(`null`), 확인 질문(`"국립수산과학원 적조속보에서 해제 대상에 가막만이 포함되는지 확인하시겠습니까?"`) 생성, 승인함 `1 → 1` (`none`)

---

## 3. 산출물 파일 목록

- **1단계 프롬프트**: [prompts/evidence-researcher-prompt.md](../prompts/evidence-researcher-prompt.md)
- **2단계 프롬프트**: [prompts/duty-support-prompt.md](../prompts/duty-support-prompt.md)
- **통합 프롬프트 JSON**: [prompts/two-agent-prompts.json](../prompts/two-agent-prompts.json)
- **2-에이전트 시나리오 JSON**: [examples/two-agent-scenarios.json](../examples/two-agent-scenarios.json)
