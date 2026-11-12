# questline-completability

논문 「LLM 기반 게임 퀘스트 생성에서 상태 변화로 인한 진행 불가 오류 분석 및 개선」(한국정보통신학회논문지)의 실험 자료와 코드다.
논문이 쓴 설정집, 퀘스트 라인, 규칙 기반 검사기, 생성 요청(프롬프트), 분석 스크립트, 생성 결과를 담았다.
다른 모델로 같은 퀘스트 라인을 생성해 같은 검사기로 평가할 수 있다.

## 들어 있는 것

| 경로 | 내용 |
|---|---|
| `worldbible/worldbible_v1.json` | 설정집. 인물 23, 장소 14, 세력 6, 사물 22, 사건 10 과 속성(생몰년, 거처, 소유자, 보관처, 출입 제한). 모든 고유명사와 설정은 창작이다 |
| `worldbible/schema.json`, `worldbible/validate.py` | 설정집 형식과 정합성 검사 |
| `worldbible/worldbible_v0.json`, `worldbible/mini_worldbible.json` | 테스트가 쓰는 설정집. v0 은 v1 의 앞 판이고 mini 는 시험용 작은 설정집이다. 본 실험에는 쓰지 않았다 |
| `scenarios/questlines_v1.yaml` | 본 실험 퀘스트 라인 40개(M01~M40). 라인마다 퀘스트 5개의 개요, 미리 정한 결과, 상태 변화, 함정 지점, 모범 풀이 |
| `scenarios/questlines_pre.yaml` | 예비 측정 퀘스트 라인 6개(P01~P06) |
| `questline/lines.py` | 라인 정의를 읽고 형식을 검사하는 코드 |
| `questline/checker.py` | 규칙 기반 검사기. 규칙 R0~R7 과 함정 지점 판정(`probe_status`) |
| `questline/prompting.py`, `pipeline/prompting.py` | 생성 요청과 재생성 요청(검사기 피드백 C2, 자기 수정 C4)을 만드는 코드, 출력 파서 |
| `examples/` | 실제로 보낸 글의 예 - 라인 M40 의 생성 요청 전문, 조건 C2 의 피드백 두 건, 조건 C4 의 메시지 |
| `questline/run.py`, `questline/score.py` | 교정 조건 C1~C4 의 실행과 셀 채점 |
| `questline/analysis.py`, `scripts/analyze_questline.py` | 본 실험 분석(H1~H4, 비용 지표) |
| `analysis/` | 분석 결과(`main_analysis.json`, `.txt`, `main_results.md`), C4 탐색 분석(`selfcorrect_c4.*`), 사후 분석 스크립트 |
| `runs/questline/main/` | 본 실험 생성 결과 1,080셀(`cells.jsonl`)과 채점 결과(`scores.jsonl`) |
| `runs/questline/selfcorrect_c4/` | 추가 탐색 조건 C4 의 생성 결과 360셀과 채점 결과 |
| `configs/models.yaml` | 모델 3종과 호출 설정(temperature 0.7, top_p 0.9, 최대 출력 4,000토큰, 추론 기능 비활성화, 최대 재생성 2회) |
| `scripts/run_questline_batch.py`, `pipeline/generators.py` | 배치 실행기와 모델 호출 코드(OpenRouter 경유) |
| `scripts/check_lines.py`, `scripts/rejudge_batch.py` | 라인 점검, 저장된 출력을 지금 검사기로 다시 판정 |
| `tests/` | 오프라인 테스트 169건. 규칙마다 오류를 심은 시험용 라인이 그 규칙으로 잡히는지, 모범 풀이가 위반 0 인지 등을 본다 |
| `CHECKSUMS.sha256` | 이 파일을 뺀 모든 파일의 sha256 |
| `.env.example` | 모델을 새로 호출할 때 쓰는 API 키 자리(값 없음). 저장된 결과를 다시 분석하는 데는 필요 없다 |
| `LICENSE`, `LICENSE-DATA.md` | 코드와 자료의 라이선스 |

## 설치와 확인

Python 3.11 이상.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

.venv/bin/python -m pytest -q                                   # 테스트 169건
.venv/bin/python scripts/check_lines.py scenarios/questlines_v1.yaml scenarios/questlines_pre.yaml   # 라인 점검
```

논문의 수치는 아래 명령으로 다시 낸다. 출력은 `analysis/` 의 저장된 결과와 글자까지 같아야 한다.

```bash
.venv/bin/python scripts/analyze_questline.py runs/questline/main --json /tmp/main.json > /tmp/main.txt
cmp /tmp/main.json analysis/main_analysis.json && cmp /tmp/main.txt analysis/main_analysis.txt

.venv/bin/python analysis/selfcorrect_c4.py --json /tmp/c4.json > /tmp/c4.txt
cmp /tmp/c4.json analysis/selfcorrect_c4.json && cmp /tmp/c4.txt analysis/selfcorrect_c4.txt

.venv/bin/python analysis/posthoc_descriptives.py      # 사후 기술 수치(실패 유형 구성, 회차별 누적 비율 등)
.venv/bin/python analysis/sensitivity_h4_death_q3.py   # H4 민감도(죽음 함정에서 물은 인물 분류)
.venv/bin/python analysis/posthoc_undetermined.py      # 판정 불가 지점 수와 그 처리에 따른 H4
.venv/bin/python analysis/posthoc_state_only.py        # 규칙 R2, R4, R6, R7 만으로 계산한 진행 가능 비율
.venv/bin/python analysis/posthoc_c4_first_fail.py     # 첫 출력이 진행 불가였던 셀의 교정률 (C2, C3, C4)
.venv/bin/python analysis/posthoc_trap_correction.py   # 함정 종류별 교정 비율과 조건 × 함정 종류 상호작용
.venv/bin/python analysis/posthoc_known_answer.py      # 모범 풀이와 오류를 넣은 풀이로 검사기 확인
.venv/bin/python analysis/posthoc_misjudgment.py       # 검사기 판정이 틀렸다고 가정한 H1, H2 재검정
.venv/bin/python analysis/posthoc_discussion.py        # 논문 고찰에 실은 수치
```

## 실험 구성

- 본 실험: 라인 40개 × 모델 3종 × 조건 3개(C1, C2, C3) × 반복 3회 = 1,080셀
- 추가 탐색: 같은 라인 40개 × 모델 3종 × 조건 C4 × 반복 3회 = 360셀
- 모델(날짜 판): gpt-6-luna(2026-09-22), claude-haiku-5.5(2026-10-07), gemini-3.1-flash-lite(2026-05-07)
- 교정 조건: C1 한 번만 생성, C2 이전 출력과 검사기의 오류 목록을 주고 재생성, C3 같은 요청을 새 seed 로 재생성, C4 이전 출력과 진행 불가 사실만 주고 재생성
- seed: 반복과 시도마다 정해 요청에 넣었다. Claude 는 seed 를 받지 않고 GPT 는 같은 seed 에서도 출력이 달라, 조건 사이에 첫 출력이 모두 같은 것은 Gemini 뿐이다
- 모델 등급: 본 실험 전날(2026-10-12) 비용 때문에 중간 등급에서 저비용 등급으로 바꿔 고정했다. 바꾸면서 예비 측정 라인 6개로 확인 시험(모델 3종, C1)을 해 출력 형식을 지키는지와 함정 오류가 0% 나 100% 로 쏠리지 않는지를 보았다. 본 실험 라인 40개는 이 확인에 쓰지 않았다(`configs/models.yaml` 머리말)

## 자료 형식

`cells.jsonl` 은 한 줄이 셀 하나다. `line_id`, `model`, `condition`, `rep` 와 시도 목록 `attempts` 를 담는다.
시도마다 seed, 모델이 낸 글 원문(`text`), 읽어 낸 퀘스트(`quests`), 검사기가 찾은 오류(`violations` - 퀘스트, 단계, 규칙, 종류, 설명),
호출 기록(`meta` - 모델 날짜 판, 요청과 응답 시각, 토큰 수, 비용)이 있다.

`text` 는 모델이 낸 글 그대로다. 아래 세 가지를 알고 읽는다.

- **JSON 뒤에 붙은 글**: GPT 응답 49건(C1 10, C2 8, C3 22, C4 9)은 JSON 객체 뒤에 다른 글이 붙어 있고, 그중 46건은 두 번째 퀘스트 JSON 이다. 파서(`questline/prompting.py` 의 `split_json`)는 첫 JSON 객체만 읽고 검사기도 그것만 판정한다. 다만 49건 가운데 출력이 잘린 8건(본 실험 7, C4 1)은 `questline/run.py` 가 읽지 못한 출력으로 처리해 R0 으로 판정했고, 첫 JSON 객체로 판정한 것은 41건이다. 뒤에 붙은 글은 판정에 쓰지 않았고 따로 집계하지도 않았다(`split_json` 의 설명에는 따로 센다고 적혀 있으나 그 집계는 만들지 않았다). 마지막 출력 기준으로는 22건이고 그중 8건(C1 2, C3 4, C4 2)이 진행 가능으로 세어졌다
- **깨진 문자열**: GPT 응답 일부는 JSON 뒤에 뜻 없는 여러 문자(한자, 키릴 문자 등)가 붙어 있고, 그 가운데 광고성 낱말이 섞인 것이 있다. 모델이 낸 그대로 두었다
- **잘리거나 오류로 끝난 응답**: 출력이 잘린 응답(본 실험 7, C4 1)과 오류 상태로 끝난 GPT 응답(본 실험 4, C4 1)은 읽을 수 없는 출력(R0)으로 판정했다

`scores.jsonl` 은 한 줄이 셀 하나의 채점 결과다. 첫 출력과 마지막 출력 각각의 진행 가능 여부, 오류 수와 규칙,
함정 지점별 판정(`error`, `kept`, `undetermined`)을 담는다.

## 고정 시점

실험 자산과 분석 스크립트를 생성 전에 고정한 기록이다. 시각은 한국 시간이다.
커밋 시각은 작업 저장소의 커밋 기록, 올린 시각은 저장소 서버(GitHub)가 기록한 푸시 시각, 첫 생성 요청은 `cells.jsonl` 의 `request_utc` 최솟값이다.

| 고정한 것 | 태그 | 커밋 | 커밋 시각 | 서버에 올린 시각 | 그 뒤 첫 생성 요청 |
|---|---|---|---|---|---|
| 설정집, 라인, 검사 규칙 | `assets-v2` | `ab828b6bc4e02a455c6664e49c433c59a3a524f5` | 2026-10-12 15:55:58 | 2026-10-12 15:56:01 | 본 실험 2026-10-13 14:40:02 |
| 분석 스크립트 | `analysis-v4` | `325893e9359d20571b008a092fbc0a0c89decca3` | 2026-10-13 14:26:35 | 2026-10-13 14:26:38 | 본 실험 2026-10-13 14:40:02 |
| C4 의 분석 스크립트 | (태그 없음) | `cbf2652e2d54bf80f9e2effe2e632a50c4ec5e67` | 2026-10-13 18:53:51 | 2026-10-13 18:53:53 | C4 2026-10-13 18:54:08 |

- `assets-v2` 부터 본 실험까지 `worldbible/worldbible_v1.json`, `scenarios/questlines_v1.yaml`, `questline/checker.py` 는 바뀌지 않았다.
- `assets-v2` 뒤 본 실험 전에 모델 응답에서 JSON 을 읽는 부분(`questline/prompting.py` 의 `split_json`)을 한 번 고쳤다(2026-10-12 18:33, 커밋 `ff80eeafb05aed13c479894a1032db10233e826b`). 올바른 JSON 객체 뒤에 다른 문자열이 붙은 응답도 읽게 한 것이고(예비 측정의 GPT 응답 2건), 그 뒤 본 실험이 끝날 때까지 이 부분은 바뀌지 않았다.
  출력 파서와 판정 경로(`questline/prompting.py`, `questline/run.py`, `questline/score.py`)는 예비 측정 뒤 `analysis-v4` 전에 고쳤다.
- 분석 스크립트는 `analysis-v1`(2026-10-12 19:33) 뒤 본 실험 전에 세 번 더해 다시 고정했다 - `analysis-v2`(10-13 13:47, 정가 기준 비용과 함정 종류 × 모델 탐색), `analysis-v3`(14:21, 가격과 무관한 호출 수와 토큰 수 지표), `analysis-v4`(14:26, 상태 변화와 함정 사이 거리 탐색). 네 번 모두 본 실험 첫 생성 요청보다 앞이다(`questline/analysis.py` 머리말).
- 외부 기관에 사전 등록하지는 않았다.
- 이 폴더에는 작업 저장소의 커밋 이력이 들어 있지 않다.

## 고정 뒤에 바뀐 것

1. **본 실험 도중 호출 재시도 추가** (2026-10-13, 커밋 `0afcd0d`) - 실행 중 한 공급 경로가 연결을 끊어 멈췄고,
   `pipeline/generators.py` 가 응답을 읽다 연결이 끊긴 경우를 재시도하게 고친 뒤 이어 돌렸다. 요청 내용, seed, 검사 규칙은 그대로다(`runs/questline/main/README.md`).
2. **조건 C4 추가** (2026-10-13, 커밋 `cbf2652`) - 본 실험 뒤에 `questline/prompting.py`, `questline/run.py` 에 C4 를 더했다. C1~C3 의 동작은 바꾸지 않았다.
3. **분석 스크립트 정정** (2026-10-15, 커밋 `a721922`) - `questline/analysis.py` 의 죽음 함정 민감도 분류가 인물 이름을 부분 문자열로 대조해,
   다른 인물의 더 긴 이름 안에 든 경우까지 셌다. 이를 고친 뒤 고정 분석을 다시 돌렸다. 바뀐 값은 죽음 함정 민감도 수치 넷이고 H1~H4 의 결과는 글자까지 같다(`analysis/main_results.md` "고정 분석 정정").
4. **사후 분석** - `analysis/posthoc_descriptives.py`, `analysis/sensitivity_h4_death_q3.py` 와 논문 수정 과정에서 2026-11-12 에 더한 일곱 파일(`analysis/posthoc_undetermined.py`, `posthoc_state_only.py`, `posthoc_c4_first_fail.py`, `posthoc_trap_correction.py`, `posthoc_known_answer.py`, `posthoc_misjudgment.py`, `posthoc_discussion.py`)은 미리 정한 분석이 아니다. 각 파일 머리말에 더한 날짜와 이유가 있다. H4 는 판정 기준에 민감하다 - 죽음 함정에서 개요에 나온 다른 생존 인물을 고른 경우를 판정 불가로 돌리면 유의하지 않고(p 0.277), 판정 불가 지점을 모두 통과로 처리해도 유의하지 않으며(p 0.069), 판정 불가를 H4 에 가장 불리하게 처리하면 p 0.350 이다(`posthoc_undetermined.py` 의 출력).
5. **공개하며 바꾼 것** - 아래 아홉 가지이고, 그 밖의 파일은 작업 저장소의 파일과 글자까지 같다. `README.md`, `LICENSE`, `LICENSE-DATA.md`, `CHECKSUMS.sha256`, `examples/` 는 공개하며 새로 넣은 파일이다. 바꾼 뒤에도 본 실험 분석과 C4 분석의 출력은 `analysis/` 의 저장된 결과와 글자까지 같다.
   - `runs/questline/*/cells.jsonl`: 호출 식별자 두 항목(`generation_id`, `generation.upstream_id`)을 지웠다. 그 밖의 값은 같다
   - `runs/questline/*/README.md`: 위 사실과 공개본의 지문을 한 줄 더했다
   - `tests/test_questline.py`: 라인 확정 화면의 테스트 1건을 뺐다(화면 도구를 넣지 않았다)
   - `analysis/main_results.md`: 이 폴더에 없는 내부 문서와 파일을 가리키는 구절을 고쳤다. 수치는 그대로다
   - `configs/models.yaml`: 내부 문서를 가리키는 주석 세 줄을 고쳤다. 설정값은 그대로다
   - `pipeline/generators.py` 의 호출 머리글 두 줄(저장소 주소와 이름), `pyproject.toml` 의 패키지 이름
   - `analysis/selfcorrect_c4.py`: 머리말 주석 두 곳을 고쳤다(조건을 더한 이유의 표현, 선행연구를 번호 대신 저자와 학술대회로). 계산 코드는 그대로다
   - `tests/test_shared.py`: 테스트용 가짜 키 값을 바꿨다
   - `.gitignore`: 이 폴더에 맞게 줄였다

## 들어 있지 않은 것

- 예비 측정(54셀)과 시험 배치의 생성 결과, 검정력 모의 스크립트
- 연구자가 라인을 읽고 확정할 때 쓴 화면 도구와 그 기록
- 실행별 로그와 manifest
- 논문 그림과 원고를 만드는 도구
- 작업 저장소의 커밋 이력
- 주석이 가리키는 것 가운데 작업 저장소에만 있는 것 - "설계 불변식"(작업 저장소 안내 문서의 절), 탐침 기록과 스크립트(`probe_questline`), 실행별 폴더(`main_parts`, `selfcorrect_c4_parts`, `errors.jsonl`), 이전 주제의 태그(`lore-consistency-final`)

## 주석에 나오는 문서 이름

코드와 자료의 주석에 나오는 "연구계획서", "실험 상세 설계"는 연구자가 쓰는 내부 설계 문서이며 이 폴더에 들어 있지 않다.
주석의 "단계 0~5", "부록 A, B"는 실험 상세 설계의 절 이름이다.
설정집의 `meta.notes` 칸에는 설정집을 처음 만들 때의 메모가 남아 있다 - 거기 나오는 "규모 설계 기준서"도 내부 문서이고, 규모 수치(엔티티 60, 관계 약 120)는 v0 의 목표치다(v1 은 엔티티 75, 관계 155). 이 칸은 모델에게 보내지 않는다.
`pipeline/` 은 이전 연구 주제와 함께 쓰던 공유 코드(생성 요청의 공통 부분, 모델 호출)이고, 주석의 "이전 주제"는 그 연구를 가리킨다.

## 생성형 AI 사용

퀘스트 라인 초안 작성, 예비 측정 오류 대조, 코드 작성에 생성형 AI 도구를 사용하였으며, 모든 내용은 연구자가 검토하고 확정하였다.

## 생성 결과의 권리

`runs/` 의 글은 OpenAI, Anthropic, Google 의 모델이 생성한 출력이다. 세 공급사의 약관은 출력에 대한 권리를 이용자에게 두거나 공급사가 소유를 주장하지 않는다고 정한다(2026-11-12 확인).

## 라이선스

코드는 MIT(`LICENSE`), 설정집과 퀘스트 라인과 생성 결과와 분석 결과는 CC BY 4.0(`LICENSE-DATA.md`)이다.
