# TASK-002: 블라인드 GT 작업표를 정본 GT로 전환(객체·가시성)

- 상태: done
- 작성: Aside / 승인: 사용자 / 작성일: 2026-10-29
- 브랜치: task/002-gt-canonical-objects-visibility

## 목적

R01 작업표(`review/gate3a2_object_inventory_R01.csv`, `review/gate3a2_visibility_R01.csv`)를 규약에 맞는
정본 파일 `gt_objects.csv`, `gt_visibility_intervals.csv`로 변환한다. 사람이 판단한 값은 바꾸지 않고, 규약상
`auto_generated` 필드만 프로그램으로 생성한다. 위치 관측(`gt_observations.csv`)과 상호작용쌍은 이 작업에 포함하지 않는다.

## 읽을 문서

- `docs/PROJECT_RULES.md`
- `docs/validation/OBJECT_TRACK_GT_PROTOCOL.md` (3, 4, 5, 6.1, 6.2, 13절)
- `data/ground_truth/object_track_v1/DATA_DICTIONARY.md` (`gt_objects`, `gt_visibility_intervals`, 공통 검토상태)
- `data/ground_truth/object_track_v1/ground_truth_manifest.json`
- `data/ground_truth/object_track_v1/review/README.md`

## 범위

### 1. 변환 스크립트

- `scripts/ground_truth/build_canonical_gt.py`를 새로 만든다. 입력은 두 작업표와 manifest, 출력은
  `gt_objects.csv`, `gt_visibility_intervals.csv`다. 헤더와 열 순서는 `.template.csv`를 그대로 따른다.
- 사람이 판단한 값(`gt_object_id`, `object_class`, 프레임 경계, `visibility_status`, `occlusion_reason`,
  `in_scope`, `exclusion_reason`, `notes`)은 그대로 옮긴다. 공백 제거 외에는 바꾸지 않는다.
- 생성하는 값: `schema_version`, `gt_dataset_id`, `video_id`(manifest), timestamp(`frame_index / source_fps`,
  manifest 값), `visibility_interval_id`(객체별 순번, 형식은 데이터사전을 따름), `denominator_eligible`(규약 6.2절),
  `annotation_method=manual`, `reviewer=R01`, `review_status=draft`, `occlusion_summary`(구간에서 집계).
- 데이터사전에 생성 규칙이 없는 필드(`origin_zone`, `destination_zone` 등)는 비워 두고 완료 보고에 목록을 적는다.
  `notes`의 "from SW" 같은 메모를 zone 값으로 옮기지 않는다.
- 같은 입력이면 같은 출력이 나오게 한다(정렬 고정, 실행 시각을 값에 넣지 않음). `review_timestamp_utc`는
  작업표 저장 시각을 알 수 없으면 비워 두고 사유를 적는다.

### 2. 검증

변환 전에 작업표를 검사하고, 오류가 하나라도 있으면 **파일을 쓰지 말고 멈춰서 보고**한다. 작업표를 고치지 않는다.

- 기존 `scripts/blind_gt_review_viewer.py --validate-only` 통과
- 모든 경계가 평가 grid(4196~5994, 짝수)에 있음
- 객체별 가시성 구간이 겹치지 않고 빈틈 없이 이어짐(앞 구간 끝 + 2 = 다음 구간 시작)
- 객체별 첫 구간 시작과 마지막 구간 끝이 객체 목록의 first/last와 같음
- `visible`이 아닌 구간에 `occlusion_reason`이 있음
- 객체 목록에 없는 ID가 가시성 표에 없음

### 3. 테스트

- `tests/test_build_canonical_gt.py`: 정상 변환, 각 검증 오류(겹침, 빈틈, grid 이탈, 사유 누락, 미등록 ID),
  `fully_occluded`의 `denominator_eligible=false`, 같은 입력의 출력 동일성.

### 4. manifest

- `files` 경로 확인, `updated_at_utc` 갱신. `dataset_status`는 `draft` 그대로 둔다.
- 실행계보(`automatic_run_lineage`)와 14절의 미결정 항목은 건드리지 않는다.

### 5. 저장소 정리

- `review/` 폴더의 `객체확인.pptx`(약 44.8MB), `gate3a2_object_inventory_R01-작업중V1.0.xlsx`,
  `gate3a2_visibility_R01-작업중v1.0.xlsx`를 Git 추적에서 빼고(`git rm --cached`) 로컬
  `work/ground_truth/review/`로 옮긴다. 파일 자체는 지우지 않는다.
- 이미 커밋된 이력은 다시 쓰지 않는다.

### 하지 않을 일

- 작업표 값 수정, 객체 추가·삭제·병합
- `gt_observations.csv`, `gt_interaction_pairs.csv`, association 작성
- 자동 추적 결과 열람이나 대조, GPU 실행
- 규약 14절 미결정 항목(매칭 허용오차, 보간 간격 등)의 값 결정

## 체크포인트

1. 2번 검증 결과를 보고한다. 오류가 있으면 여기서 멈춘다.
2. 커밋 전에 출력 요약(객체 수, 클래스별 수, 구간 수, 상태별 grid 프레임 수, 분모 포함 grid 프레임 수)과
   변경 파일 목록을 보고하고 사용자 확인을 받는다.

## 완료 조건

- `.venv/bin/pytest` 전체 통과
- `gt_objects.csv` 50행, 구간 수가 작업표와 일치
- README "현재 상태"의 블라인드 GT 행 갱신, `DECISION_LOG.md`에 "R01 객체·가시성 GT draft 동결" 기록
- 아래 완료 보고 작성 후 함께 커밋

## 완료 보고(Codex 작성)

- 변경 파일: `scripts/ground_truth/build_canonical_gt.py`,
  `tests/test_build_canonical_gt.py`, `data/ground_truth/object_track_v1/gt_objects.csv`,
  `data/ground_truth/object_track_v1/gt_visibility_intervals.csv`,
  `data/ground_truth/object_track_v1/review/occlusion_reason_map_R01.csv`,
  `data/ground_truth/object_track_v1/ground_truth_manifest.json`, `README.md`,
  `docs/validation/DECISION_LOG.md`, 이 지시문. 검토용 XLSX/PPTX 3개는
  `work/ground_truth/review/`에 보존하고 `data/.../review/` 경로에서는 Git 추적 제외.
- 검증 결과: 변환 전 `scripts/blind_gt_review_viewer.py --validate-only` 통과. 그리드·객체 참조·
  구간 연속성·시작/종료 일치·비가시 구간 사유 추가 점검 오류 없음. 가림 원인 매핑 누락 테스트를
  포함해 전체 테스트 47 passed. 매핑표를 읽고 재생성했으며 작업표는 수정하지 않음.
- 출력 요약: 객체 50개(person 38, car 9, motorcycle 3), 가시성 구간 142개.
  Grid object-frames: visible 9,798, partially_occluded 1,322, fully_occluded 414,
  not_observable 0. 분모 포함 11,120 object-frames. `vegetation` 37구간(partial 29,
  full 8), `structure` 25구간(partial 24, full 1), 허용 목록 밖 사유 0건.
- 비워 둔 필드와 사유: `origin_zone`, `destination_zone`은 승인된 구역 매핑이 없고
  `notes`의 방향 메모를 zone으로 해석하지 않아 비움. `review_timestamp_utc`는 작업표에 실제
  판독 시각이 없어 비움. manifest `automatic_run_lineage`와 미결정 항목은 유지.
- 한계와 미해결: uppercase `TRUE`는 CSV boolean 규격에 맞춰 `true`로 표기 정규화. 사용자 결정
  (2026-10-29)에 따라 `tree→vegetation`, `canopy→structure`, `reflector→structure`로 매핑하고,
  원래 사유는 각 정본 구간 `notes`의 `original_occlusion_reason`에 보존. 매핑 결정은
  `docs/validation/DECISION_LOG.md`에 기록.
