# 본실험 (단계 4, 2026-10-13)

라인 40(`scenarios/questlines_v1.yaml`) × 모델 3 × 조건 3 × 반복 3 = 1,080셀. 호출 1,964회, 청구액 $4.549.

모델 × 반복 9개 실행으로 나눠 동시에 돌리고(`../main_parts/<모델>_r<반복>/` - 실행마다 manifest 와 run.log), 끝난 뒤 이 폴더로 합쳤다.
합친 뒤 1,080셀이 모두 있고 중복이 없으며 cells 와 scores 의 키가 같음을 확인했고, 실행별 사본은 지웠다.
처음 한 줄로 돌린 10셀은 `../main_parts/_sequential_start/` 기록을 남기고 해당 실행 폴더로 옮겨 이어 갔다.

- 실행 중 Claude 공급 경로가 세 실행의 연결을 같은 순간 끊어 멈췄고, 어댑터가 응답 본문 읽기 중 연결 끊김을 재시도하게 고친 뒤
  이어 갔다(`pipeline/generators.py`). 끊긴 호출은 기록되지 않았다.
- 호출 하나(M23 gemini C3 반복 1, 첫 시도)는 생성 뒤 날짜 판 조회(/generation)가 실패해 경고가 남았다. 호출 자체와 토큰, 청구액은
  기록되었고, 실행 전 endpoints 대조는 통과했다.

sha256 앞 16자리: cells.jsonl 0bd09bacca7cb099, scores.jsonl c93e5412d59022b0

공개본의 `cells.jsonl` 은 호출 식별자 두 항목(`generation_id`, `generation.upstream_id`)을 지워 위 값과 지문이 다르다(sha256 앞 16자리 4d58daf757848fc3). `scores.jsonl` 은 그대로다.
