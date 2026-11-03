# TASK-006: R01 현재 AI 채점(자동 association 기반 잠정 평가)

- 상태: ready
- 작성: Aside / 승인: 사용자 / 작성일: 2026-11-03
- 브랜치: task/006-r01-baseline-scoring

## 목적

동결된 R01 GT v1(태그 `gt-r01-v1`, 커밋 `ed72492`)로 현재 기준선
(COCO YOLO11m, 슬라이스 검출, 클래스별 ByteTrack, 필터, 분절 병합)의 검출·추적 품질을
`raw_tracker`, `filtered`, `merged` 단계별로 채점한다.
association은 자동 생성값이므로 모든 수치는 잠정값(`provisional_automatic`)이다. 사람 검토(adjudication)는 후속 TASK에서 한다.

## 사용자 결정 (2026-11-03)

1. 매칭: IoU 0.5 이상을 공식 기준으로, IoU 0.3을 민감도 기준으로 함께 보고한다. 클래스와 무관하게 프레임별 일대일(헝가리안) 매칭을 하고,
   클래스 일치는 별도로 집계한다.
2. 궤적 완전성: Mostly Tracked(MT)는 분모 앵커의 80% 이상 매칭, Mostly Lost(ML)는 20% 미만, 나머지는 Partially Tracked(PT)다.
   MOT16 정의대로 ID 유지 여부와 무관하다.
3. 종합: HOTA, DetA, AssA, LocA를 α 0.05~0.95(19개) 평균과 α=0.5 값으로 함께 보고한다. IDF1, IDSW, MOTA를 병기한다.

## 운영 규칙 (사용자 확인 완료)

- A. 시간 허용오차는 0이다. GT 앵커와 같은 `frame_index`의 자동 박스만 비교한다. GT 960행은 모두 짝수 프레임이다.
  자동 실행이 처리한 프레임에 GT 프레임이 빠져 있으면(예: 시작 프레임이 홀수) 멈추고 보고한다.
- B. 분모는 정본 `gt_observations.csv` 960행이다(분모 대상 구간의 manual 관측). skip 10건은 분모에서 빼고 목록으로 보고한다.
- C. 프레임 수준 지표(Precision, MOTA, IDF1, IDSW, HOTA 계열)는 **완전 프레임**에서만 계산한다. 완전 프레임은 그 시점의 분모 대상 객체
  전원에게 GT 박스가 있는 프레임이다. 4196부터 30프레임 간격인 공통 격자 60개 가운데 skip이 있는 프레임을 뺀 것으로 예상되며(54개 예상),
  Codex가 다시 계산해 보고한다.
  격자 밖 객체별 앵커(시작·끝 등)는 객체 수준 지표에만 쓴다. 그 프레임에서는 다른 객체의 GT 박스가 없어서 오탐 판정이 틀어지기 때문이다.
- D. 클래스 호환표: GT `person`은 `person`, GT `car`는 `car`·`bus`·`truck`, GT `motorcycle`은 `motorcycle`과 일치로 본다.
  나머지는 `class_match=mismatch`로 처리한다. 클래스 혼동행렬을 함께 보고한다.
- E. 프로젝트 판정(`coverage_status`, 프로토콜 9절): 한 auto ID가 분모 앵커의 80% 이상을 덮으면 `complete`,
  매칭이 1건 이상이면 `partial`, 0건이면 `missed`다. 최대 연속 누락은 앵커 해상도(약 1초)로 계산해 보고만 하고 판정에는 쓰지 않는다.
  사용자가 2026-11-03 확인했다. 최대 연속 누락은 수치 판정 기준이 아니라 보고값이다.
- F. GT manifest는 이번 TASK에서 수정하지 않는다. 실행계보는 평가 출력 폴더의 `run_lineage.json`에 기록한다.
- 사용자 확인(2026-11-03): 운영 규칙 C, D, E 확인 완료.

## 읽을 문서

- `docs/PROJECT_RULES.md`, `README.md`, `docs/validation/DECISION_LOG.md`
- `docs/validation/OBJECT_TRACK_GT_PROTOCOL.md` 7~11절, 14절
- `docs/validation/OBJECT_TRACK_RECALL_METHOD_REVIEW.md` 6절
- `data/ground_truth/object_track_v1/DATA_DICTIONARY.md` 2.7절, 2.9절, 6절, 8절, 10절
- `data/ground_truth/object_track_v1/ground_truth_manifest.json`
- `configs/baseline.json`, `src/roundabout/detect_track.py`, `filter_tracks.py`, `merge_track_fragments.py`

## 범위

### 1단계: 채점할 자동 실행 선택

1. `outputs/`에서 DJI_0482의 `tracks.csv`(raw_tracker), `filtered_tracks.csv`(filtered), `filtered_tracks_merged.csv`(merged)를
   **같은 실행계보**로 모두 갖춘 실행을 찾는다.
2. 후보마다 프로토콜 7.4절 항목을 표로 보고한다. 항목은 영상 SHA-256, Git commit, 설정 경로와 SHA-256, 가중치 SHA-256, 단계별 CSV SHA-256,
   처리 프레임 범위와 frame step, 4196~5994 포함 여부다.
3. 조건을 갖춘 실행이 없으면 현재 `configs/baseline.json` 그대로 DJI_0482를 다시 실행하는 안을 보고한다. 설정값은 바꾸지 않는다.
   전체 영상 실행 후 4196~5994를 잘라 쓰는 것을 권장한다(구간만 실행하면 추적기가 빈 상태에서 시작한다). 예상 GPU 시간을 함께 적는다.

### 2단계: 평가 설정, 코드, 테스트

1. 새 설정 `configs/evaluation_object_track_v1.yaml`에 결정 1~3과 운영 규칙 A~E의 값을 넣는다. 값마다 근거등급과 출처를 단다
   (MOT16 arXiv:1603.00831, HOTA arXiv:2009.07736, 2026-11-03 사용자 결정). 코드에 임계값을 하드코딩하지 않는다.
2. `src/roundabout/evaluate_object_track.py`
   - GT 3개 파일의 SHA-256을 manifest `frozen_files`와 대조한다. 불일치하면 오류로 멈춘다.
   - 단계별 CSV를 4196~5994로 자르고, 앵커 프레임마다 IoU 헝가리안 일대일 매칭을 한다(클래스 무관).
   - 아래 "산출 지표"를 계산하고 출력한다.
3. HOTA 계열은 공식 구현 TrackEval(MIT)을 우선 쓴다. 현재 venv(Python 3.14, numpy)에서 동작하지 않으면 멈추고 보고한다.
   대안은 `hota.py` 로직을 이식하고 TrackEval 결과와의 일치를 테스트로 확인하는 것이다.
   의존성은 `pyproject.toml`에 새 optional 그룹 `evaluation`으로 추가하고 README 설치 명령도 함께 고친다.
4. `tests/test_evaluate_object_track.py`(unittest)
   - IoU 계산, 일대일 매칭(한 박스가 두 GT에 매칭되지 않음), IoU 경계값(0.5 정확히)
   - MT/PT/ML 경계(80%, 20% 정확히), complete/partial/missed
   - fragment 수와 IDSW 계산, 클래스 호환표, 완전 프레임 선택
   - GT 해시 불일치 시 오류, 완벽한 예측이면 HOTA=1과 IDF1=1

### 3단계: 채점 실행

- 3개 단계 × IoU 0.5/0.3을 실행한다.
- 출력 위치는 `outputs/evaluation/<evaluation_run_id>/`이고, 모든 파일에 `.meta.json`을 붙인다.
  - `metrics_summary.json`: 단계 × IoU별 전체 지표
  - `per_object.csv`: GT 객체별 앵커 수, 매칭 수, 커버리지, MT/PT/ML, coverage_status, fragment 수, 최대 연속 누락, 클래스 일치
  - `gt_track_associations.csv`: 템플릿 스키마를 따르고 `matching_method=automatic`, `review_status=draft`
  - `auto_track_audit_candidates.csv`: 구간 안에서 GT와 연결되지 않은 자동 트랙. `audit_status=uncertain`, 사람 검토 대상
  - `stage_survival.csv`: raw_tracker → filtered → merged 생존율(프로토콜 10.1절)
  - `run_lineage.json`: 1단계 표의 항목 전체

### 산출 지표

| 수준 | 지표 | 계산 범위 |
|---|---|---|
| 객체 | 앵커 recall(매칭 앵커 / 960), 객체 포착률(1회 이상 매칭 객체 / 분모 객체) | 960행 전체 |
| 객체 | MT/PT/ML, complete/partial/missed, 커버리지(평균, 중앙값, 하위 10%) | 960행 전체 |
| 객체 | 객체당 auto ID 수, fragmentation, 최대 연속 누락(앵커 해상도) | 960행 전체 |
| 객체 | 클래스 일치율과 혼동행렬 | 매칭된 앵커 |
| 프레임 | Precision(감사 전 잠정), MOTA, IDF1, IDSW | 완전 프레임 |
| 프레임 | HOTA, DetA, AssA, LocA(α 평균, α=0.5) | 완전 프레임 |
| 단계 | 필터 생존율, 병합 정확성 후보(오병합 의심 목록) | 3단계 비교 |

객체 수준 지표는 전체와 GT 클래스별(person, car, motorcycle)로 나눠 보고한다.

### 하지 않을 일

- GT 파일(정본 CSV 3개, manifest) 수정. 해시 검증만 한다.
- 모델, confidence, 추적·필터·병합 임계값, frame step 변경. 재실행이 필요해도 현재 기준선 설정 그대로만 한다.
- 학습·미세조정. 140~200 s 구간은 학습에 쓰지 않는다.
- association과 audit의 사람 판정(adjudication). 자동 후보만 만든다.
- 상호작용쌍 GT, PET/TTC 등 안전지표.
- 결과가 좋아지는 방향의 규칙 조정. 이상한 결과는 고치지 말고 보고한다.

## 체크포인트

1. 1단계 표와 채점할 실행 제안을 보고하고 대기한다. 재실행이 필요하면 예상 GPU 시간을 함께 보고한다.
2. 2단계를 마친 뒤 채점 실행 전에 다음을 보고하고 대기한다: 완전 프레임 수와 목록, GT 프레임이 실행에 모두 있는지,
   TrackEval 동작 여부, 설정 파일 내용, pytest 결과.
3. 3단계 결과(단계 × IoU 결과 표, 변경 파일 목록, diff 요약)를 보고하고, 사용자 확인 전에는 커밋·push하지 않는다.

## 완료 조건

- `.venv/bin/pytest` 통과
- 3단계 출력 전체와 `.meta.json` 생성
- `docs/validation/R01_BASELINE_SCORING_RESULT.md` 작성: 결과 표, 실행계보 요약, 한계
  - 한계에 반드시 넣을 것: 자동 association 잠정값(adjudication 전), Precision은 audit 전 값, 1초 앵커 간격으로 앵커 사이 ID 전환 미검출,
    필터 임계값 튜닝 구간(150~210 s)과 겹쳐 filtered·merged 결과가 좋게 나올 수 있음, 단일 검토자 draft GT,
    복사 박스 후보 3건(C004 4826, C005 5186, P006 4706) 육안 미확인
- `DECISION_LOG.md`에 2026-11-03 사용자 결정 1~3과 운영 규칙 A~F 기록
- `OBJECT_TRACK_GT_PROTOCOL.md` 14절과 `DATA_DICTIONARY.md` 10절에서 이번에 정한 항목(association IoU·시간 허용오차, 클래스 호환규칙,
  complete 커버리지 기준)을 "평가 설정 v1으로 잠정 승인"으로 표시. 최대 누락 기준은 계속 `pending`
- README 현재 상태 갱신, 이 지시문의 완료 보고 작성

## 완료 보고(Codex 작성)

- 변경 파일:
- 실행한 명령과 결과:
- 채점한 실행(evaluation_run_id)과 실행계보:
- 결과 요약(단계 × IoU):
- 바뀐 설정과 영향 단계:
- 한계와 미해결:
