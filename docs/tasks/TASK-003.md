# TASK-003: 블라인드 GT 위치 판독 도구(박스 입력 모드)

- 상태: 완료 (입력 도구 구현; R01 위치 GT 입력은 사용자 진행 중)
- 작성: Aside / 승인: 사용자 / 작성일: 2026-10-29
- 브랜치: task/003-gt-box-annotation-tool

## 목적

사용자가 원본 영상만 보고 객체별 위치 박스를 직접 찍어 `gt_observations.csv`(manual 관측)를 만들 수 있도록, 기존
브라우저 판독 도구(`apps/demo/blind_gt_review.py`, `http://127.0.0.1:8502`)에 **박스 입력 모드**를 추가한다.
박스 값은 사용자가 입력한다. Codex는 도구만 만들고 박스 값을 만들지 않는다.

## 결정 사항(2026-10-29, 사용자 승인)

- 위치 GT 작성 방식: 드문드문 박스 입력(규약 14절 "위치 GT 작성 간격" 결정)
- 앵커 프레임: 객체의 분모 포함 구간(`visible`, `partially_occluded`)마다
  - 구간의 첫 프레임과 마지막 프레임
  - 그 사이에서 `(frame_index - 4196)`이 30의 배수인 프레임(원본 기준 1초 간격)
- 예상 앵커 수: 약 970개(R01 기준). 구현 계산 결과는 971개다. `fully_occluded` 구간에는 앵커를 만들지 않는다.
- 보간(`interpolated`)은 이 작업에 포함하지 않는다. 최대 보간 간격은 평가 지시문에서 따로 정한다.

- 화면 설계와 단축키는 2026-10-29 사용자 승인을 받았다. 전체 프레임·확대 입력창, 객체·앵커 진행률,
  visibility 상태, 기존 GT 박스와 건너뛰기 입력을 한 화면에 제공한다.
- 확대 중심은 동일 객체의 직전 두 GT 박스로 선형 예측한다. 과거 박스가 없으면 전체 프레임을 클릭해 중심을
  지정한다. 같은 프레임의 다른 객체 박스는 흐리게 표시하고 토글할 수 있다.
- person·bicycle 기본 확대는 3배, 차량류는 1배다. `P`는 anchor 전후 ±1초를 확대창에서 재생하고,
  `C`는 직전 박스를 복사해 확정행에 `copied_from_previous`를 남긴다. `N`/`Shift+N`은 다음/이전 객체다.

`DECISION_LOG.md`에 위 내용을 기록한다.

## 읽을 문서

- `docs/PROJECT_RULES.md`
- `docs/validation/OBJECT_TRACK_GT_PROTOCOL.md` (4, 5.3, 6.3절)
- `data/ground_truth/object_track_v1/DATA_DICTIONARY.md` (`gt_observations`)
- `apps/demo/blind_gt_review.py`, `scripts/blind_gt_review_viewer.py`, 관련 테스트

## 범위

### 1. 블라인드 유지

- 화면에는 원본 프레임, 프레임 번호, 현재 객체의 GT 정보(ID, class, notes, 현재 가시성 상태), 그리고 **사용자가 이미
  입력한 GT 박스**만 보인다.
- 자동 검출·추적 결과, 모델, `outputs/` 폴더를 읽거나 표시하는 코드를 넣지 않는다. 이를 확인하는 테스트를 둔다.

### 2. 작업 흐름

- 입력 데이터: TASK-002가 만든 `gt_objects.csv`, `gt_visibility_intervals.csv`(정본). 없거나 검증에 실패하면 시작하지 않는다.
- 객체 단위로 진행한다. 객체를 고르면 그 객체의 앵커 프레임을 순서대로 보여 준다.
- 4K 화면에서 보행자가 작으므로, 직전 박스 주변(첫 앵커는 사용자가 클릭한 지점 주변)을 **원본 해상도로 확대**한
  화면에서 박스를 그린다. 확대 배율은 바꿀 수 있게 한다.
- 박스: 마우스 드래그로 그리고, 다시 그리기와 한 단계 되돌리기를 지원한다.
- 발 위치: 기본은 박스 하단 중앙. 사용자가 클릭으로 바꿀 수 있고, 바꾼 경우 `notes`에 `foot_adjusted`를 남긴다.
- 건너뛰기: 객체를 찾을 수 없으면 박스 없이 넘어가되, 사유를 골라 `review/gt_observation_skips_R01.csv`에 기록한다
  (`gt_object_id, frame_index, reason, notes`). 관측행은 만들지 않는다. 사유: `not_found`, `ambiguous_identity`,
  `occluded_more_than_marked`, `other`.
- 직전 앵커의 박스를 반투명하게 겹쳐 보여 같은 객체를 따라가기 쉽게 한다.
- 진행률(객체별, 전체)을 보여 주고, 저장은 앵커마다 즉시 한다. 도구를 껐다 켜도 이어서 할 수 있어야 한다.
- 단축키를 화면에 표시한다(다음/이전 앵커, 건너뛰기, 되돌리기, 확대·축소).

### 3. 출력

- 작업 파일: `review/gt_observations_R01.csv`. 헤더는 `gt_observations.template.csv`와 같고, `observation_method=manual`,
  `coordinate_system=source_pixel`, `position_unit=px`, `review_status=draft`, `reviewer=R01`, timestamp는 자동 생성.
- 좌표는 원본 3840×2160 화소 기준이다. 확대 화면 좌표를 원본 좌표로 되돌리는 변환을 테스트로 검증한다.
- 정본 `gt_observations.csv`로의 변환은 이 작업에 포함하지 않는다(사용자 입력 완료 후 별도 작업).

### 4. 검증 기능

- `--validate-only`에 관측 작업 파일 검사를 추가한다: 박스가 프레임 안, `x2>x1`, `y2>y1`, 같은 객체·프레임 중복 없음,
  관측 프레임이 분모 포함 구간 안, class가 객체 목록과 같음, 앵커 대비 입력·건너뛰기 누락 수.

### 5. 실행 방법 문서

- `data/ground_truth/object_track_v1/review/BOX_INPUT_GUIDE.md`: 실행 명령, 화면 설명, 단축키, 건너뛰기 기준,
  저장 위치, 검증 명령을 비전문가도 따라 할 수 있게 한국어로 쓴다.

### 6. 테스트

- 앵커 계산(구간 끝 포함, 30 간격, fully_occluded 제외), 좌표 변환, 저장·이어하기, 검증 오류, 자동 결과 비참조.

### 하지 않을 일

- 박스 값 입력이나 자동 생성(자동 검출로 초벌 박스 만들기 포함)
- 보간, association, 평가 지표 계산
- 기존 작업표·정본 GT 값 수정
- GPU 실행

## 체크포인트

1. 화면 구성안(스크린샷 또는 설명)과 단축키 목록을 먼저 보고하고 사용자 확인을 받은 뒤 구현한다.
2. 구현 후 사용자가 객체 1개(예: P001)로 직접 시험 입력해 보고, 불편한 점을 반영한 뒤 커밋한다.

체크포인트 1은 2026-10-29 승인됐다. P001/P002 시험 입력 작업파일은 validator를 통과한다. 작은 화면이라는
사용자 피드백에 따라 브라우저 전체 영역과 확대창 휠 확대를 추가했고, 박스 안 드래그 이동 시 발점도 함께
이동하도록 했다. 입력 완료 뒤 skip 요약으로 visibility 경계를 재검토하는 절차와 `--skip-summary`를 추가했다.

## 완료 조건

- `.venv/bin/pytest` 전체 통과
- WSL에서 도구 실행, Windows 브라우저에서 `127.0.0.1:8502` 접속 확인
- `BOX_INPUT_GUIDE.md` 작성, README "현재 상태" 갱신, `DECISION_LOG.md` 기록
- 아래 완료 보고 작성 후 함께 커밋

## 완료 보고(Codex 작성)

- 변경 파일: `.gitignore`, `README.md`, `apps/demo/blind_gt_review.py`, `apps/demo/gt_box_annotation.py`,
  `data/ground_truth/object_track_v1/review/BOX_INPUT_GUIDE.md`, `docs/tasks/TASK-003.md`,
  `docs/validation/DECISION_LOG.md`, `tests/test_gt_box_annotation.py`.
- 실행 방법: WSL 저장소 루트에서 `PYTHONPATH=src .venv/bin/python apps/demo/blind_gt_review.py --box-input`;
  작업 파일 검증은 같은 명령에 `--validate-only`를, 건너뛰기 정리는 `--skip-summary`를 붙인다.
- 시험 입력 결과: P001/P002 작업파일 54개 관측, 3개 skip. 971개 anchor 중 914개는 아직 미입력이다.
  `--validate-only` 통과, skip 요약은 P002 `other` 3건(4736, 4766, 4792)을 표시했다.
  시험 입력 중 확인된 작은 화면 피드백에 따라 전체 화면 배치와 확대창 휠 확대, 박스 이동 시 발점 이동을 반영했다.
- 검증: 위치 입력 전용 테스트 11개 통과, 전체 pytest 58개 통과, `git diff --check` 통과.
  승인된 환경에서 로컬 서버가 기동되고 `GET /`이 HTTP 200과 입력 페이지를 반환했다. 이 세션에서는
  Windows 브라우저 자체 접속을 새로 확인하지 않았다.
- 한계와 미해결: 박스 값 작성, visibility 경계 재검토, 정본 변환은 범위 밖이며 사용자 입력 완료 후 별도 수행한다.
  자동 검출·추적 결과, GPU 및 전체 영상 처리는 사용하지 않았다.
