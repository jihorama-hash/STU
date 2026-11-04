# TASK-007: R01 검출기 단독 평가(ByteTrack 분리)

- 상태: done
- 작성: Aside / 승인: 사용자 / 작성일: 2026-11-04
- 브랜치: task/007-r01-detection-only

## 목적

TASK-006의 `raw_tracker` 점수는 검출기(YOLO11m 슬라이스 검출)와 ByteTrack을 거친 결과다.
같은 동결 GT v1(태그 `gt-r01-v1`)로 **검출기만의 성능**을 따로 측정하고, GT 앵커별로 누락이
검출기에서 생겼는지 ByteTrack에서 생겼는지 분해한다. 결과는 다음 TASK인 ByteTrack 파라미터
검토의 기준선으로 쓴다.

## 배경 (Aside 코드 확인, 2026-11-04, main `b6625b6`)

- `detect_track.py`는 검출 결과를 저장하지 않는다. `tracks.csv`에는 ByteTrack을 통과한 박스만 있다.
- `sv.ByteTrack(track_activation_threshold=0.15)`. 설치된 supervision 0.29.1 소스를 직접 확인했다
  (0.26.1 예시 설명과 버전은 다르지만, 아래 주요 동작은 동일했다).
  - 저점수 2차 연결 구간은 `0.1 < conf < 0.15`인데, 검출 conf가 0.15라서 이 구간이 사실상 비어 있다.
  - 새 트랙 시작 기준은 `det_thresh = track_activation_threshold + 0.1 = 0.25`다.
  - 출력 박스는 트랙과 IoU 0.5 초과로 매칭된 **원본 검출 박스**다. 트래커는 박스를 추가하지 않는다.
- 따라서 conf 0.15 검출 재현율은 `raw_tracker` 재현율의 상한이어야 한다.
- A 실행 `_01`은 `detections.csv.meta.json`과 `tile_diagnostics.csv.meta.json`이 없어
  device·설정·입력 계보를 검증할 수 없다. 파일은 보존하되 `meta 없음, 사용 안 함`으로 표시한다.

## 사용자 결정 (2026-11-04)

1. 매칭은 TASK-006과 같다. IoU 0.5 공식, 0.3 민감도, 프레임별 클래스 무관 일대일 Hungarian 매칭.
   클래스 호환표는 GT `person`↔`person`, `car`↔`car`·`bus`·`truck`, `motorcycle`↔`motorcycle`이다.
   GT 규칙상 탑승자는 별도 `person` 객체이므로 운전자·탑승자 검출은 정탐이다.
2. skip, `fully_occluded`, `in_scope=false` GT와 겹치는 검출은 오탐으로 세지 않는다. 그 밖의 미매칭
   검출은 감사 전 잠정 오탐으로 두고 목록과 오버레이를 남긴다(사용자 육안 판정용).
3. PR 곡선과 conf 비교는 진단용이다. 이 GT(140~200 s)로 운영 conf나 검출 설정을 고르지 않는다.
4. 이 작업을 TASK-007로 한다. 차량 제외 구역 점검은 후속 TASK로 미룬다.
5. 차량 전체 프레임 검출(B 실험)은 비교용으로 넣는다. 2단계 결과를 보고 본 평가와 무관하면 생략한다.

## 운영 규칙

- A. 검출 프레임은 공통 격자 60개와 정본 `gt_observations.csv`의 모든 `frame_index`의 합집합이다
  (약 236개, 모두 짝수). 프레임 목록은 GT CSV에서 만들고 실행 메타데이터에 저장한다. 재현율과
  재현성 대조는 이 전체 프레임에서 한다. 정밀도·AP는 TASK-006과 같은 **완전 프레임 54개**로만
  계산한다. Codex가 다시 계산해 TASK-006 목록과 일치하는지 보고한다.
- B. 검출 코드는 `detect_track.py`의 `make_slices()`·`detect_sliced()`를 import해 그대로 쓴다.
  복사하거나 수정하지 않는다. `detect_track.py`의 동작은 바꾸지 않는다.
- C. 설정값은 `configs/baseline.json`과 같다(YOLO11m, 1024 타일, 겹침 0.2, imgsz 1024, NMS 0.5, COCO 프로필).
  conf만 하한 **0.01**로 낮춰 저장한다. 운영점은 **0.15**(현재 검출 기준)와 **0.25**(ByteTrack 새 트랙 시작 기준)
  두 곳에 표시한다. 새 평가 설정은 `configs/`에 새 파일로 두고 근거등급과 출처를 붙인다.
- D. 프레임 읽기는 `outputs/diagnostics/r01_frame_alignment_20261103_01/`에서 검증한 방식을 따른다.
- E. GT 파일은 읽기만 한다. SHA-256이 동결 manifest와 다르면 멈춘다.
- 메타/YAML 일치: 평가 시 detection 메타의 모델·가중치·클래스·타일·imgsz·NMS·pass·conf 값이
  evaluation YAML과 다르면 점수 산출을 중단한다.
- F. 오탐 제외(사용자 결정 2)용 위치는 해당 객체의 앞뒤 manual 박스를 선형 보간해 만든다. 판정은
  `ignore_candidate`로 표시하고 보고만 한다. 확정 오탐 여부는 사용자 감사로 정한다.

## 읽을 문서

- `docs/PROJECT_RULES.md`, `README.md`, `docs/validation/DECISION_LOG.md`
- `docs/tasks/TASK-006.md`, `docs/validation/R01_BASELINE_SCORING_RESULT.md`
- `configs/baseline.json`, `configs/evaluation_object_track_v1.yaml`
- `src/roundabout/detect_track.py`, `src/roundabout/evaluate_object_track.py`
- `data/ground_truth/object_track_v1/DATA_DICTIONARY.md`, `ground_truth_manifest.json`

## 범위

### 1단계: 환경 확인, 코드, 테스트

1. 설치된 supervision 버전과 ByteTrack의 `det_thresh`, 저점수 구간, 출력 박스 처리 코드 줄을 확인해 보고한다.
   위 배경과 다르면 멈추고 보고한다.
2. 검출 단독 실행 모듈을 만든다(예: `src/roundabout/detect_frames.py`). 지정 프레임만 읽어
   `detections.csv`를 저장한다. 열은 `frame_index`, 클래스, conf, 박스, `pass_id`(A/B 구분),
   `tile_center_candidate_ids`(박스 중심 기준 후보 타일)다. 타일별 박스 수와 `max_det` 도달 여부는
   별도 `tile_diagnostics.csv`에 기록한다.
3. 평가 모듈을 만든다(예: `src/roundabout/evaluate_detection.py`). 매칭·클래스 호환·완전 프레임 선택은
   `evaluate_object_track.py`의 함수를 재사용한다.
4. AP는 검증된 구현을 쓴다. 권장은 `pycocotools`이며 `evaluation` extra에 추가한다. 의존성을 추가하면
   README의 설치 명령을 pyproject와 하나씩 대조해 맞춘다.
5. 테스트(`unittest.TestCase`, pytest 실행)
   - 매칭, conf 운영점별 P/R
   - 작은 예제에서 AP 수기 계산값과 일치
   - 앵커 분해 범주(아래 2단계 6번)
   - 타일 포함 판정
6. **체크포인트 1**: 변경 파일, 테스트 결과, GPU 실행 명령, 예상 시간을 보고하고 대기한다.

### 2단계: A 실행(현재 설정, 본 평가)

1. 공통 격자와 전체 GT anchor frame_index의 합집합에서 A(전 클래스 타일 검출)를 실행한다.
2. 재현성 검증: 같은 실행계보 `r01_baseline_yolo11m_full_20261103_02`의 `raw_tracker/tracks.csv` 박스 중
   해당 프레임 박스가 모두 conf 0.15 이상 검출과 IoU 0.99 이상으로 대응하는지 확인한다. 불일치가 있으면
   멈추고 보고한다.
3. 타일별 박스 수가 Ultralytics `max_det`(기본 300)에 닿은 경우가 있는지 보고한다.
4. 지표(클래스별 및 클래스 무관, IoU 0.5/0.3)
   - conf 0.15·0.25에서 Precision, Recall, F1(Precision은 감사 전)
   - AP50, AP50:95. `areaRng=all`, COCO `maxDets`는 설정된 단일 상한 사용. ignore 대상은
     `iscrowd=1` GT로 넣으며 P/R과 동일한 IoA 기준을 사용한다. ignore 건수를 보고한다.
   - 클래스별 P/R은 클래스별로 분리 매칭한다. ByteTrack 손실 분해와 TASK-006 비교는 클래스 무관
     Hungarian 매칭 후 호환표를 적용한다. 이 계산 차이를 결과 문서에 명시한다.
   - 클래스는 person, car(car+bus+truck), motorcycle
   - PR 곡선 그림
   - 클래스 혼동행렬
5. 누락 원인
   - GT 앵커별 최고 IoU 분포: 겹침 없음 / 0~0.3 / 0.3~0.5 / 0.5 이상
   - 면적비, 중심거리
   - GT 박스 크기 구간(클래스별 3분위)별 재현율
   - 어느 타일에도 다 들어가지 않는 GT 앵커(Aside 계산으로는 car 16/185, 6대)의 재현율과 분할·중복 검출 수
6. ByteTrack 손실 분해(IoU 0.5, 클래스 호환). 먼저 클래스 무관 Hungarian 매칭 후 TASK-006
   클래스 호환표로 유효 매칭을 판정한다. GT 앵커마다 다음 중 하나로 분류하고, 클래스별 개수를 보고한다.
   - ① conf 0.15 이상 검출 없음(검출기 누락)
   - ② 0.15~0.25 검출만 있고 `tracks.csv`에 없음
   - ③ 0.25 이상 검출이 있는데 `tracks.csv`에 없음
   - ④ `tracks.csv`에 있음
   - 별도 재현성 이상: 트랙은 GT와 매칭되지만 conf 0.15 이상 원시 검출이 같은 GT와 매칭되지 않음. ④로 합치지 않고 프레임·객체를 별도 보고한다.
   - ②·③ 사례는 프레임·객체 목록을 남긴다.
7. 미매칭 검출 목록, `ignore_candidate` 표시, 대표 프레임 오버레이(GT 초록, 검출 빨강, conf 표기)
   4장 이상을 저장한다.
8. **체크포인트 2**: 결과 요약표를 보고하고 대기한다. 이 보고를 보고 B 실행 여부를 정한다.
   판단 근거는 차량 누락 중 타일 경계 앵커의 비중, 차량 누락이 ①인지 ②·③인지다.

### 3단계: B 실행(조건부, 비교용)

체크포인트 2에서 진행으로 정해졌을 때만 한다. 생략으로 정해지면 결과 문서에 생략 사유를 쓴다.

1. car·bus·truck은 전체 프레임 1회 검출(imgsz 1280, 1920)로, person·bicycle은 A의 타일 검출로 한다.
   motorcycle은 타일과 전체 프레임을 각각 따로 평가한다.
   검출은 클래스별로 겹치지 않게 이어 붙이고, 두 실행 사이 NMS는 하지 않는다.
2. A와 같은 지표로 비교한다. 타일 경계 앵커는 따로 집계한다.
3. 파이프라인 변경은 하지 않는다. 채택 여부는 별도 구간 검증과 사용자 승인 후에 정한다.

### 하지 않을 일

- `detect_track.py`, `configs/baseline.json`, 마스크, GT 파일 수정
- ByteTrack 재실행이나 파라미터 변경(다음 TASK)
- 이 GT 결과로 운영 conf·imgsz·타일 설정 결정
- 전체 영상 GPU 실행, 학습, 미세조정
- 체크포인트 보고 없이 커밋·병합

## 체크포인트

1. 1단계 끝: 코드·테스트·실행 명령 보고 후 대기
2. 2단계 끝: A 결과와 B 진행 여부 판단 자료 보고 후 대기
3. 커밋 전: 변경 파일 목록과 diff 요약 보고 후 대기(코드와 산출물은 커밋을 나눈다)

## 완료 조건

- 전체 `.venv/bin/pytest` 통과
- 산출물은 `outputs/evaluation/r01_detection_only_20261104_02/`에 저장하고, 모든 파일에 `.meta.json`을 붙인다.
  B를 실행했으면 같은 폴더의 하위 폴더에 둔다.
- 결과 문서 `docs/validation/R01_DETECTION_ONLY_RESULT.md`
  - 맨 위에 3줄 요약
  - 지표표, 손실 분해표
  - 한계(GT 1구간 60 s, motorcycle 3대, 감사 전 Precision, 이 GT로 설정을 고르지 않음)
- `DECISION_LOG.md`에 사용자 결정 1~5를 기록하고, README "현재 상태"를 갱신한다.

## 완료 보고(Codex 작성)

- 변경 파일: `src/roundabout/detect_frames.py`, `src/roundabout/evaluate_detection.py`, `tests/test_detect_frames.py`, `tests/test_evaluate_detection.py`, `configs/evaluation_detection_v1.yaml`, `pyproject.toml`, `requirements.txt`, `README.md`, `scripts/diagnostics/40_check_r01_detection_reproducibility.py`, `scripts/diagnostics/41_score_r01_detection_only.py`, `scripts/diagnostics/42_supplement_r01_checkpoint3.py`, 본 문서, `docs/validation/R01_DETECTION_ONLY_RESULT.md`, `docs/validation/DECISION_LOG.md`. 실행 산출물은 `outputs/evaluation/r01_detection_only_20261104_02/A/`에 있으며 Git에 포함하지 않는다.
- 실행한 명령과 결과: `.venv/bin/pytest` — 전체 테스트 통과(100 passed). A 실행은 사용자 GPU 터미널에서 수행했으며 CUDA 장치·입력 계보·설정 해시를 확인했다. 재현성 대조 236프레임, 1,488/1,488 박스가 IoU≥.99로 일치했다. 결과 문서에 기록한 별도 진단과 오버레이를 생성했다.
- 바뀐 설정과 영향 단계: 검출 전용 평가 설정 `configs/evaluation_detection_v1.yaml`을 추가했다. `detect_frames.py`에서 raw detections를 기록하고 평가기에서 P/R·AP 및 추적 손실을 분리 집계한다. 기준 추적 파이프라인 설정과 `detect_track.py`는 변경하지 않았다.
- 한계와 미해결: GT는 단일 60초 구간이고 motorcycle은 3개 객체다. 미매칭 검출 301개는 사용자 감사 전이므로 Precision은 잠정값이다. B는 차량 누락 중 타일 경계 비중이 6.1%이고 ① 검출기 누락이 대부분이라 생략했다. 도로 영역 층화 평가는 사용자 결정에 따라 미세조정 후 성능이 부족할 때 재검토한다. 미세조정 라벨 작성 전 GT/AI 박스 작성 규칙을 정해야 하며, ByteTrack 파라미터 검토는 미세조정 후 검출 점수 분포 확인 뒤 수행한다.
