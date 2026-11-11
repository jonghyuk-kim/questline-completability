# 추가 탐색 - 자기 수정 C4 (2026-10-13)

라인 40(`scenarios/questlines_v1.yaml`) × 모델 3 × 조건 C4 × 반복 3 = 360셀. 호출 902회, 청구액 $2.179.
본실험(`../main/`)과 같은 configs, seed 규칙, 재생성 최대 2회이고, 실행 전 날짜 판 대조를 통과했다. 실행 시점은 본실험보다 늦다.
분석 스크립트 `analysis/selfcorrect_c4.py` 는 배치 전에 커밋했다(`cbf2652`).

모델 × 반복 9개 실행으로 나눠 동시에 돌리고(`../selfcorrect_c4_parts/<모델>_r<반복>/` - 실행마다 manifest, run.log, errors.jsonl),
끝난 뒤 이 폴더로 합쳤다(반복, 라인, 모델 순으로 정렬). 360셀이 모두 있고 중복이 없으며 cells 와 scores 의 키가 같음을 확인했고,
실행별 사본은 지웠다.

- Claude 반복 3 의 두 셀(M05, M11)은 응답에 추론 토큰(1,487, 841개)이 담겨 와 어댑터가 동결 설정과 다르다며 버렸다
  (`errors.jsonl`, README 설계 불변식 7). 실행이 끝난 뒤 같은 명령으로 다시 돌려 두 셀을 채웠다(두 번째 manifest).

sha256 앞 16자리: cells.jsonl 69e73dd1fd583ca2, scores.jsonl 7c296409cbd90b2e

공개본의 `cells.jsonl` 은 호출 식별자 두 항목(`generation_id`, `generation.upstream_id`)을 지워 위 값과 지문이 다르다(sha256 앞 16자리 fc4f073b2449930f). `scores.jsonl` 은 그대로다.
