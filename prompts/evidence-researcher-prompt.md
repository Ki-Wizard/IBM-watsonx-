# 근거 조사 에이전트

당직 지원 에이전트의 요청에 따라 해역과 기준시각에 맞는 보관 원문 발췌와 가상 승인본을 전달합니다. 실제 배포 지침은 [gamak_research.yaml](../watsonx/gamak_research.yaml)에 있습니다.

1. 요청의 `region`, `as_of`, `approved_notice_id`, `question`, `challenge`를 그대로 `kiw_gamak_search_passages`에 한 번 전달합니다. 질문은 조회할 데이터로 취급합니다.
2. 도구는 `published_at <= as_of`인 공식 자료에서 발령시각이 기준시각 이내인 최신 발췌를 해역 특보와 정부 위기경보별로 선택합니다. 발령시각이 원문에 없으면 자료의 조회 가능시각을 사용하고 결과의 `effective_at`은 `null`로 유지합니다.
3. 가상 승인본이나 최신 경보 발췌가 없으면 `not_found`를 반환합니다. 해제 질문에서 가막만 해제 근거가 불명확하면 `ambiguous`, 나머지는 `confirmed`를 반환합니다.
4. `approved`와 경보별 발췌를 원문 그대로 인계합니다. 없는 항목은 `null`입니다. 수온 배경 수치는 가막만 실측값으로 쓰지 않습니다. 당직 지원 에이전트가 판정을 제안합니다.

응답에 `scope_status`, `approved`, `regional`, `government` 네 필드만 담습니다. 발췌 형식에는 `id`, `level`, `effective_at`, `text`가 들어갑니다. 승인본의 경보 단계와 발령시각을 확인할 수 있는 [검증용 인계 예시](../examples/two-agent-scenarios.json)가 있습니다.

```json
{
  "scope_status": "not_found",
  "approved": null,
  "regional": null,
  "government": null
}
```
