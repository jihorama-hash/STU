# Object Track GT v1 데이터사전

스키마 버전: `object_track_gt_v1`

관련 규약: `docs/validation/OBJECT_TRACK_GT_PROTOCOL.md`

## 1. 공통 표기와 필수값 규칙

### 1.1 파일과 인코딩

- JSON은 UTF-8, 유효한 JSON 문법, 들여쓰기 2칸을 사용한다.
- CSV는 UTF-8, 쉼표 구분, 첫 행 헤더를 사용한다.
- 실제 데이터 파일의 헤더 순서는 해당 `.template.csv`와 같아야 한다.
- CSV의 빈 값은 `null`을 뜻한다. 문자열 `null`, `None`, `N/A`, `-`를 대체값으로
  쓰지 않는다.
- 자유서술에 쉼표·줄바꿈·따옴표가 있으면 RFC 4180 방식으로 인용한다.
- 하나의 셀에 여러 ID나 허용값을 넣을 때만 세미콜론(`;`)으로 구분한다.

### 1.2 자료형

| 표기 | 형식 |
|---|---|
| `string` | 앞뒤 공백이 없는 UTF-8 문자열 |
| `id` | 영문자·숫자·밑줄·하이픈으로 구성한 비어 있지 않은 문자열 |
| `integer` | 소수점 없는 10진 정수 |
| `number` | 유한한 10진 실수; `NaN`, `inf` 금지 |
| `boolean` | CSV에서는 소문자 `true` 또는 `false`; JSON에서는 boolean |
| `sha256` | 소문자 16진수 64자 |
| `timestamp_utc` | RFC 3339 UTC, 예: `YYYY-MM-DDTHH:MM:SSZ` |
| `path` | 프로젝트 루트 기준 POSIX 상대경로; 절대경로 금지 |

### 1.3 필수 여부

| 표기 | 의미 |
|---|---|
| 필수 | 실제 데이터 행 또는 확정 manifest에서 빈 값 불가 |
| 조건부 | 명시한 조건을 만족할 때 필수, 그 밖에는 빈 값 허용 |
| 선택 | 없어도 스키마상 유효하나 가능한 경우 기록 |
| 템플릿 고정 | 템플릿에 있는 값을 임의 변경하지 않음 |

이 표의 필수 여부는 canonical 파일이 완성됐을 때의 유효성 조건이다. `필수`가 사람이
직접 입력해야 한다는 뜻은 아니다. 수작업 여부는 아래 `manual_required`,
`auto_generated`, `optional_future` 분류를 우선 적용한다.

manifest 템플릿의 `null`은 미정값을 뜻한다. 실제 annotation을 시작하기 전에는 영상,
파일럿 구간, 좌표 및 sampling 메타데이터를 채워야 한다. 자동 association 또는 audit을
작성하기 전에는 `automatic_run_lineage`의 모든 필수값을 채워야 한다.

### 1.4 공통 ID와 시간 규칙

- `schema_version`은 모든 파일에서 `object_track_gt_v1`이다.
- `gt_dataset_id`는 한 GT 묶음 안에서 동일하다.
- `video_id`는 manifest의 `video.video_id`와 동일하다.
- `frame_index`는 원본 영상 기준 0 이상 정수다.
- 시작·종료 프레임은 포함하는 폐구간이며 `start <= end`다.
- 초 단위 시각은 0 이상이고 단위는 `s`다.
- 기본 시각식은 `frame_index / source_fps`다. 부동소수점 비교 허용오차는 향후
  validator에서 실제 FPS에 맞게 정의하며 현재 임의로 고정하지 않는다.

### 1.5 공통 검토상태

모든 `review_status`의 허용값은 다음과 같다.

| 값 | 의미 | 확정 평가 사용 |
|---|---|---|
| `draft` | 1차 작성 | 불가 |
| `reviewed` | 재검토 완료, adjudication 전 | 불가 |
| `adjudicated` | 불일치 해결 및 확정 | 가능 |
| `uncertain` | 현 자료로 확정 불가 | 제외 |

`review_status`가 `reviewed` 또는 `adjudicated`이면 `reviewer`와
`review_timestamp_utc`가 필수다. `uncertain`이면 불확실한 이유를 `notes`에 기록한다.

### 1.6 필드 생성 역할

canonical 저장 구조는 유지하되 최초 파일럿에서 사람이 모든 필드를 입력하지 않는다.

| 범주 | 정의 |
|---|---|
| `manual_required` | 객체·가시성·위치·상호작용처럼 사람이 의미를 반드시 판단하는 원자료 |
| `auto_generated` | 고정 메타데이터, 반복 ID, 원자료 파생값, 실행계보 또는 평가 프로그램이 생성하는 값 |
| `optional_future` | 최초 파일럿에는 요구하지 않고 향후 확장 시 선택적으로 사용하는 값 |

`auto_generated` 값은 프로그램 생성 후 사람이 검토할 수 있지만 반복 수기 입력하지 않는다.
timestamp, duration, FPS 파생값, checksum, denominator eligibility, coverage, gap,
fragmentation, ID switch, class match와 요약 판정은 모두 이 범주다.

#### 1.6.1 Manifest 필드 분류

| 범주 | JSON 경로 |
|---|---|
| `manual_required` | `pilot.selection_rationale`, `pilot.evaluation_start_frame_index`, `pilot.evaluation_end_frame_index`, `video.video_id`, `video.relative_path`, `sampling.frame_step`, `scope.in_scope_regions`, `scope.region_definition_path`, `annotation.reviewers` |
| `auto_generated` | `template`, `schema_version`, `gt_dataset_id`, `dataset_status`, `pilot.minimum_duration_seconds`, `pilot.maximum_duration_seconds`, `pilot.selection_status`, `pilot.selection_criteria`, `pilot.evaluation_start_timestamp_seconds`, `pilot.evaluation_end_timestamp_seconds`, `pilot.actual_duration_seconds`, `video.sha256`, `video.width_pixels`, `video.height_pixels`, `video.source_fps`, `video.source_frame_count`, `video.coordinate_system`, `video.position_unit`, `sampling.frame_index_origin`, `sampling.evaluation_fps`, `sampling.timestamp_rule`, `scope.object_classes`, `scope.region_definition_sha256`, `scope.interaction_pair_gt_purpose`, `annotation.protocol_path`, `annotation.blind_original_video_first`, `annotation.observation_methods`, `annotation.visibility_statuses`, `annotation.denominator_excluded_visibility_statuses`, `annotation.created_at_utc`, `annotation.updated_at_utc`, `automatic_run_lineage.evaluation_run_id`, `automatic_run_lineage.git_commit`, `automatic_run_lineage.config_path`, `automatic_run_lineage.config_sha256`, `automatic_run_lineage.model_weights_path`, `automatic_run_lineage.model_weights_sha256`, `automatic_run_lineage.raw_tracker.artifact_path`, `automatic_run_lineage.raw_tracker.artifact_sha256`, `automatic_run_lineage.raw_tracker.summary_path`, `automatic_run_lineage.raw_tracker.summary_sha256`, `automatic_run_lineage.filtered.artifact_path`, `automatic_run_lineage.filtered.artifact_sha256`, `automatic_run_lineage.filtered.summary_path`, `automatic_run_lineage.filtered.summary_sha256`, `automatic_run_lineage.merged.artifact_path`, `automatic_run_lineage.merged.artifact_sha256`, `automatic_run_lineage.merged.report_path`, `automatic_run_lineage.merged.report_sha256`, `files.objects`, `files.visibility_intervals`, `files.observations`, `files.track_associations`, `files.interaction_pairs`, `files.auto_track_audit` |
| `optional_future` | `annotation.adjudicator` |

`sampling.frame_step`, `scope.in_scope_regions`와 `scope.region_definition_path`는 사람의 승인이
필요한 `manual_required` 필드지만 현재 기준은 `pending`이다. 승인 전에는 null로 둔다.

#### 1.6.2 CSV 필드 분류

| 파일 | 범주 | 필드 |
|---|---|---|
| `gt_objects.csv` | `manual_required` | `object_class`, `first_visible_frame_index`, `last_visible_frame_index`, `in_scope`, `exclusion_reason` |
| `gt_objects.csv` | `auto_generated` | `schema_version`, `gt_dataset_id`, `video_id`, `gt_object_id`, `first_visible_timestamp_seconds`, `last_visible_timestamp_seconds`, `occlusion_summary`, `reviewer`, `review_status`, `review_timestamp_utc` |
| `gt_objects.csv` | `optional_future` | `origin_zone`, `destination_zone`, `notes` |
| `gt_visibility_intervals.csv` | `manual_required` | `start_frame_index`, `end_frame_index`, `visibility_status`, `in_scope`, `occlusion_reason` |
| `gt_visibility_intervals.csv` | `auto_generated` | `schema_version`, `gt_dataset_id`, `video_id`, `gt_object_id`, `visibility_interval_id`, `start_timestamp_seconds`, `end_timestamp_seconds`, `denominator_eligible`, `annotation_method`, `reviewer`, `review_status`, `review_timestamp_utc` |
| `gt_visibility_intervals.csv` | `optional_future` | `notes` |
| `gt_observations.csv` | `manual_required` | `frame_index`, `x1`, `y1`, `x2`, `y2` |
| `gt_observations.csv` | `auto_generated` | `schema_version`, `gt_dataset_id`, `video_id`, `gt_object_id`, `timestamp_seconds`, `object_class`, `foot_x`, `foot_y`, `coordinate_system`, `position_unit`, `visibility_status`, `observation_method`, `interpolation_span_frames`, `in_scope`, `reviewer`, `review_status`, `review_timestamp_utc` |
| `gt_observations.csv` | `optional_future` | `notes` |
| `gt_track_associations.csv` | `manual_required` | 없음; 평가 단계의 자동 후보를 사람이 검토·adjudicate함 |
| `gt_track_associations.csv` | `auto_generated` | `schema_version`, `gt_dataset_id`, `evaluation_run_id`, `video_id`, `stage`, `source_artifact_sha256`, `gt_object_id`, `auto_track_id`, `match_start_frame_index`, `match_end_frame_index`, `match_start_timestamp_seconds`, `match_end_timestamp_seconds`, `association_status`, `coverage_status`, `fragmentation_status`, `identity_status`, `class_match`, `matching_method`, `match_score`, `reviewer`, `review_status`, `review_timestamp_utc` |
| `gt_track_associations.csv` | `optional_future` | `notes` |
| `gt_interaction_pairs.csv` | `manual_required` | `pedestrian_gt_object_id`, `vehicle_gt_object_id`, `start_frame_index`, `end_frame_index`, `interaction_zone`, `interaction_basis`, `observable`, `exclusion_reason` |
| `gt_interaction_pairs.csv` | `auto_generated` | `schema_version`, `gt_dataset_id`, `video_id`, `interaction_gt_id`, `start_timestamp_seconds`, `end_timestamp_seconds`, `denominator_eligible`, `reviewer`, `review_status`, `review_timestamp_utc` |
| `gt_interaction_pairs.csv` | `optional_future` | `notes` |
| `auto_track_audit.csv` | `manual_required` | `audit_status`, `false_positive_reason` |
| `auto_track_audit.csv` | `auto_generated` | `schema_version`, `gt_dataset_id`, `evaluation_run_id`, `video_id`, `stage`, `source_artifact_sha256`, `auto_track_id`, `first_frame_index`, `last_frame_index`, `first_timestamp_seconds`, `last_timestamp_seconds`, `object_class_auto`, `related_gt_object_ids`, `reviewer`, `review_status`, `review_timestamp_utc` |
| `auto_track_audit.csv` | `optional_future` | `notes` |

사람이 화면에서 객체를 새로 구분하거나 association·audit 결과를 adjudicate하는 행위는
필수 human review다. 다만 `gt_object_id`, 반복 참조 ID, 판정 결과 셀과 검토시각은 작성
도구나 평가 workflow가 canonical 값으로 생성한다. 발점은 기본적으로 박스 하단 중앙에서
생성하고 사람이 수정한 경우에만 수정 위치를 보존한다.

### 1.7 작성 단계와 `pending`

최초 blind GT 작성파일은 다음 네 개로 한정한다.

1. `ground_truth_manifest.json`
2. `gt_objects.csv`
3. `gt_visibility_intervals.csv`
4. `gt_observations.csv`

`gt_interaction_pairs.csv`는 객체 ID를 검토·확정한 뒤 작성한다.
`gt_track_associations.csv`와 `auto_track_audit.csv`는 blind GT 동결 후 평가 단계에서
자동 생성하고 사람이 검토한다. 최초 blind 작성 중에는 두 파일을 헤더만 유지한다.

아직 기준이 정해지지 않은 값은 `pending` workflow 상태로 유지한다. JSON에서는 null을
유지하고, CSV에서는 그 값을 필요로 하는 후속 데이터 행을 만들지 않는다. 현재 허용값에
문자열 `pending`을 추가하거나 임시 숫자·임계값을 입력하지 않는다. 특히 다음은 pending이다.

- 파일럿 평가구간
- frame step과 evaluation FPS
- in-scope region
- observation 작성 간격과 최대 interpolation span
- 자동 association의 IoU·거리·시간 허용오차와 match score
- complete·partial coverage 및 maximum-gap 기준
- 미병합 확정조건
- 상호작용 성립 운영규칙

## 2. `ground_truth_manifest.json`

### 2.1 최상위

| JSON 경로 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `template` | boolean | 템플릿 고정 | 템플릿은 `true`; 실제 파일은 `false` | 실제 파일에서 `true`면 확정 평가 불가 |
| `schema_version` | string | 필수 | `object_track_gt_v1` | 다른 값은 별도 변환 없이 사용 금지 |
| `gt_dataset_id` | id 또는 null | 실제 파일 필수 | 프로젝트 내 고유 | 템플릿만 null 허용 |
| `dataset_status` | string | 필수 | `template`, `draft`, `reviewed`, `adjudicated`, `frozen` | `template`은 평가 불가; `frozen` 변경 시 새 ID 필요 |

### 2.2 `pilot`

| JSON 경로 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `pilot.minimum_duration_seconds` | number | 템플릿 고정 | `30.0 s` | 규약 개정 없이 변경 금지 |
| `pilot.maximum_duration_seconds` | number | 템플릿 고정 | `60.0 s` | 규약 개정 없이 변경 금지 |
| `pilot.selection_status` | string | 필수 | `pending_video_review`, `selected`, `rejected` | `selected` 전 annotation 시작 금지 |
| `pilot.selection_criteria` | string 배열 | 필수 | 템플릿의 세 기준 포함 | 추가 기준 허용; 기존 기준 삭제는 규약 개정 필요 |
| `pilot.selection_rationale` | string 또는 null | `selected`일 때 필수 | 원본 영상 확인 근거 | 자동 후보 건수만을 근거로 사용 금지 |
| `pilot.evaluation_start_frame_index` | integer 또는 null | `selected`일 때 필수 | 0 이상, frame | 종료보다 커서는 안 됨 |
| `pilot.evaluation_end_frame_index` | integer 또는 null | `selected`일 때 필수 | 시작 이상, frame | 원본 프레임 수 이상 금지 |
| `pilot.evaluation_start_timestamp_seconds` | number 또는 null | `selected`일 때 필수 | 0 이상, s | 프레임과 FPS에 불일치하면 오류 |
| `pilot.evaluation_end_timestamp_seconds` | number 또는 null | `selected`일 때 필수 | 시작 이상, s | 프레임과 FPS에 불일치하면 오류 |
| `pilot.actual_duration_seconds` | number 또는 null | `selected`일 때 필수 | 30~60 s | 범위 밖이면 파일럿으로 승인 불가 |

### 2.3 `video`

| JSON 경로 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `video.video_id` | id 또는 null | 실제 파일 필수 | 영상 식별자 | CSV 값과 불일치하면 오류 |
| `video.relative_path` | path 또는 null | 실제 파일 필수 | 원본 영상 상대경로 | 파일이 없으면 annotation·평가 중단 |
| `video.sha256` | sha256 또는 null | 실제 파일 필수 | 원본 영상 checksum | 불일치하면 다른 영상으로 처리 |
| `video.width_pixels` | integer 또는 null | 실제 파일 필수 | 1 이상, px | 관측 x 범위 검증에 사용 |
| `video.height_pixels` | integer 또는 null | 실제 파일 필수 | 1 이상, px | 관측 y 범위 검증에 사용 |
| `video.source_fps` | number 또는 null | 실제 파일 필수 | 0보다 큼, frame/s | 반올림 정수 대신 컨테이너 실제값 기록 |
| `video.source_frame_count` | integer 또는 null | 실제 파일 필수 | 1 이상, frame | 디코딩 가능 범위와 차이는 notes/별도 검증 필요 |
| `video.coordinate_system` | string | 템플릿 고정 | `source_pixel` | 다른 좌표계 혼용 금지 |
| `video.position_unit` | string | 템플릿 고정 | `px` | meter나 reference pixel 기록 금지 |

### 2.4 `sampling`

| JSON 경로 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `sampling.frame_index_origin` | integer | 템플릿 고정 | `0` | 1 기반 번호 사용 금지 |
| `sampling.frame_step` | integer 또는 null | 실제 파일 필수 | 1 이상, source frame | 실제 평가 실행값 확인 후 기록 |
| `sampling.evaluation_fps` | number 또는 null | 실제 파일 필수 | 0보다 큼, frame/s | 원칙적으로 `source_fps / frame_step`; 차이는 근거 필요 |
| `sampling.timestamp_rule` | string | 필수 | 기본 `frame_index / source_fps` | 다른 규칙은 버전·근거를 명시해야 함 |

### 2.5 `scope`

| JSON 경로 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `scope.object_classes` | string 배열 | 필수 | `person`, `bicycle`, `motorcycle`, `car`, `bus`, `truck`, `tricycle` | 새 클래스는 스키마 개정 필요 |
| `scope.in_scope_regions` | string 배열 또는 null | annotation 시작 전 필수 | 승인된 region ID | 전 화면이면 명시적으로 `full_frame` 사용 |
| `scope.region_definition_path` | path 또는 null | 조건부 | region 파일을 쓰면 필수 | 경로 없는 임의 구역명 금지 |
| `scope.region_definition_sha256` | sha256 또는 null | 조건부 | region 파일을 쓰면 필수 | checksum 불일치 시 평가 중단 |
| `scope.interaction_pair_gt_purpose` | string | 템플릿 고정 | `observation_denominator_only` | 안전지표 결과 저장 금지 |

### 2.6 `annotation`

| JSON 경로 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `annotation.protocol_path` | path | 필수 | 본 규약 경로 | 다른 규약이면 schema/version 명시 필요 |
| `annotation.blind_original_video_first` | boolean | 필수 | `true` | false이면 독립 GT로 확정하지 않음 |
| `annotation.observation_methods` | string 배열 | 템플릿 고정 | `manual`, `interpolated` | 다른 방법은 스키마 개정 필요 |
| `annotation.visibility_statuses` | string 배열 | 템플릿 고정 | 네 가시성 상태 | 삭제·이름변경 금지 |
| `annotation.denominator_excluded_visibility_statuses` | string 배열 | 템플릿 고정 | `fully_occluded`, `not_observable` | 개별 파일에서 임의 변경 금지 |
| `annotation.reviewers` | string 배열 | 실제 파일 필수 | 한 명 이상 reviewer ID | 개인정보 대신 프로젝트 reviewer ID 권장 |
| `annotation.adjudicator` | string 또는 null | adjudicated 시 필수 | reviewer ID | 자기검토 허용 여부는 추후 승인 |
| `annotation.created_at_utc` | timestamp_utc 또는 null | 실제 파일 필수 | UTC | 로컬시각 금지 |
| `annotation.updated_at_utc` | timestamp_utc 또는 null | 실제 파일 필수 | created 이후 UTC | frozen 후 변경 시 새 버전 필요 |

### 2.7 `automatic_run_lineage`

객체·가시성·위치 GT만 작성하는 동안에는 null을 허용한다. association 또는 auto audit
행을 한 개라도 작성하거나 단계별 지표를 산출할 때는 아래 값을 모두 채워야 한다.

| JSON 경로 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `automatic_run_lineage.evaluation_run_id` | id 또는 null | association/audit 시 필수 | 한 실행계보 ID | CSV와 불일치하면 오류 |
| `automatic_run_lineage.git_commit` | string 또는 null | association/audit 시 필수 | 40자 Git commit 권장 | dirty 상태면 별도 변경 checksum 필요 |
| `automatic_run_lineage.config_path` | path 또는 null | association/audit 시 필수 | 사용 설정파일 | 파일 부재 시 비교 불가 |
| `automatic_run_lineage.config_sha256` | sha256 또는 null | association/audit 시 필수 | 설정 checksum | 불일치 시 다른 run으로 처리 |
| `automatic_run_lineage.model_weights_path` | path 또는 null | association/audit 시 필수 | 사용 weights | 모델을 쓰지 않는 run만 null 허용 |
| `automatic_run_lineage.model_weights_sha256` | sha256 또는 null | association/audit 시 필수 | weights checksum | 불일치 시 다른 run으로 처리 |
| `automatic_run_lineage.raw_tracker.artifact_path` | path 또는 null | association/audit 시 필수 | `tracks.csv` | 다른 단계 파일 금지 |
| `automatic_run_lineage.raw_tracker.artifact_sha256` | sha256 또는 null | association/audit 시 필수 | CSV checksum | 불일치 시 중단 |
| `automatic_run_lineage.raw_tracker.summary_path` | path 또는 null | association/audit 시 필수 | `summary.json` | 부재 시 실행 파라미터 검증 불가 |
| `automatic_run_lineage.raw_tracker.summary_sha256` | sha256 또는 null | association/audit 시 필수 | summary checksum | 불일치 시 중단 |
| `automatic_run_lineage.filtered.artifact_path` | path 또는 null | filtered 비교 시 필수 | `filtered_tracks.csv` | raw와 같은 run이어야 함 |
| `automatic_run_lineage.filtered.artifact_sha256` | sha256 또는 null | filtered 비교 시 필수 | CSV checksum | 불일치 시 중단 |
| `automatic_run_lineage.filtered.summary_path` | path 또는 null | filtered 비교 시 필수 | `filter_summary.json` | 제거사유 추적에 필요 |
| `automatic_run_lineage.filtered.summary_sha256` | sha256 또는 null | filtered 비교 시 필수 | summary checksum | 불일치 시 중단 |
| `automatic_run_lineage.merged.artifact_path` | path 또는 null | merged 비교 시 필수 | `filtered_tracks_merged.csv` | filtered와 같은 run이어야 함 |
| `automatic_run_lineage.merged.artifact_sha256` | sha256 또는 null | merged 비교 시 필수 | CSV checksum | 불일치 시 중단 |
| `automatic_run_lineage.merged.report_path` | path 또는 null | merged 비교 시 필수 | `continuation_report.json` | ID 연결 추적에 필요 |
| `automatic_run_lineage.merged.report_sha256` | sha256 또는 null | merged 비교 시 필수 | report checksum | 불일치 시 중단 |

### 2.8 `files`

| JSON 경로 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `files.objects` | path | 필수 | `gt_objects.csv` | 실제 파일 존재 필요 |
| `files.visibility_intervals` | path | 필수 | `gt_visibility_intervals.csv` | 실제 파일 존재 필요 |
| `files.observations` | path | 필수 | `gt_observations.csv` | 헤더만인 초기 단계 허용 |
| `files.track_associations` | path | 필수 | `gt_track_associations.csv` | association 전 헤더만 허용 |
| `files.interaction_pairs` | path | 필수 | `gt_interaction_pairs.csv` | pair 검토 전 헤더만 허용 |
| `files.auto_track_audit` | path | 필수 | `auto_track_audit.csv` | audit 전 헤더만 허용 |

## 3. `gt_objects.csv`

실제 물리 객체당 한 행이다. 자동 track ID 필드는 의도적으로 없다.

| 필드 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `schema_version` | string | 필수 | `object_track_gt_v1` | 다른 값 오류 |
| `gt_dataset_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `video_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `gt_object_id` | id | 필수 | 영상 내 고유 | 중복 오류; 자동 ID 재사용 금지 |
| `object_class` | string | 필수 | manifest class 목록 | 모호하면 `review_status=uncertain`; 임의 클래스 추가 금지 |
| `first_visible_frame_index` | integer | 필수 | 0 이상, frame | 평가구간과 교차해야 함 |
| `last_visible_frame_index` | integer | 필수 | first 이상, frame | 원본 범위 밖 오류 |
| `first_visible_timestamp_seconds` | number | 필수 | 0 이상, s | frame/FPS 불일치 오류 |
| `last_visible_timestamp_seconds` | number | 필수 | first 이상, s | frame/FPS 불일치 오류 |
| `origin_zone` | string | 선택 | 승인 region ID | 불명확하면 빈 값과 notes 사용 |
| `destination_zone` | string | 선택 | 승인 region ID | 관측 전 이탈하면 빈 값 허용 |
| `in_scope` | boolean | 필수 | `true`, `false` | false이면 exclusion_reason 필수 |
| `exclusion_reason` | string | 조건부 | `out_of_region`, `outside_time_window`, `class_out_of_scope`, `not_reliably_identifiable`, `other` | in_scope=true면 빈 값; `other`는 notes 필수 |
| `occlusion_summary` | string | 필수 | `none`, `partial`, `full`, `mixed`, `not_observable`, `uncertain` | 세부 구간은 visibility 파일에 기록 |
| `reviewer` | string | 조건부 | reviewer ID | 공통 검토상태 규칙 적용 |
| `review_status` | string | 필수 | 공통 검토상태 | uncertain은 확정 분모 제외 |
| `review_timestamp_utc` | timestamp_utc | 조건부 | UTC | 공통 검토상태 규칙 적용 |
| `notes` | string | 선택 | 자유서술 | 불확실·other 사유에는 필수 |

## 4. `gt_visibility_intervals.csv`

같은 객체의 interval은 시간상 겹치지 않아야 하며 객체의 평가대상 구간을 설명해야 한다.

| 필드 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `schema_version` | string | 필수 | `object_track_gt_v1` | 다른 값 오류 |
| `gt_dataset_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `video_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `gt_object_id` | id | 필수 | objects에 존재 | 미등록 참조 오류 |
| `visibility_interval_id` | id | 필수 | 데이터셋 내 고유 | 중복 오류 |
| `start_frame_index` | integer | 필수 | 0 이상, frame | 객체 전체 범위 밖 오류 |
| `end_frame_index` | integer | 필수 | start 이상, frame | 객체 전체 범위 밖 오류 |
| `start_timestamp_seconds` | number | 필수 | 0 이상, s | frame/FPS 불일치 오류 |
| `end_timestamp_seconds` | number | 필수 | start 이상, s | frame/FPS 불일치 오류 |
| `visibility_status` | string | 필수 | `visible`, `partially_occluded`, `fully_occluded`, `not_observable` | 다른 값 오류 |
| `in_scope` | boolean | 필수 | `true`, `false` | false이면 denominator도 false |
| `denominator_eligible` | boolean | 필수 | `true`, `false` | fully_occluded/not_observable/in_scope=false이면 반드시 false |
| `occlusion_reason` | string | 조건부 | `vegetation`, `vehicle`, `person`, `structure`, `frame_boundary`, `image_quality`, `ambiguous_identity`, `other` | visible은 빈 값 허용; other는 notes 필수 |
| `annotation_method` | string | 필수 | `manual`, `adjudicated` | 자동 가시성 추정값은 GT로 사용 금지 |
| `reviewer` | string | 조건부 | reviewer ID | 공통 검토상태 규칙 적용 |
| `review_status` | string | 필수 | 공통 검토상태 | uncertain interval은 분모 제외 |
| `review_timestamp_utc` | timestamp_utc | 조건부 | UTC | 공통 검토상태 규칙 적용 |
| `notes` | string | 선택 | 자유서술 | 예외·불확실 사유에는 필수 |

## 5. `gt_observations.csv`

위치는 `source_pixel` 좌표만 사용한다. 한 객체·한 프레임당 최대 한 행이다.

| 필드 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `schema_version` | string | 필수 | `object_track_gt_v1` | 다른 값 오류 |
| `gt_dataset_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `video_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `gt_object_id` | id | 필수 | objects에 존재 | 미등록 참조 오류 |
| `frame_index` | integer | 필수 | 객체의 유효 구간, frame | 같은 객체·프레임 중복 오류 |
| `timestamp_seconds` | number | 필수 | 0 이상, s | frame/FPS 불일치 오류 |
| `object_class` | string | 필수 | objects의 class와 동일 | 불일치 오류; 자동 class 기록 금지 |
| `x1` | number | 필수 | 0 이상, px | 프레임 폭 밖이면 오류 |
| `y1` | number | 필수 | 0 이상, px | 프레임 높이 밖이면 오류 |
| `x2` | number | 필수 | `x2 > x1`, px | 프레임 폭 밖이면 오류 |
| `y2` | number | 필수 | `y2 > y1`, px | 프레임 높이 밖이면 오류 |
| `foot_x` | number | 필수 | 원본 프레임 x, px | 박스와 명백히 불일치하면 재검토 |
| `foot_y` | number | 필수 | 원본 프레임 y, px | 접지점 수정 시 notes 권장 |
| `coordinate_system` | string | 필수 | `source_pixel` | reference/world 좌표 금지 |
| `position_unit` | string | 필수 | `px` | 다른 단위 오류 |
| `visibility_status` | string | 필수 | `visible`, `partially_occluded` | fully_occluded/not_observable 행 생성 금지 |
| `observation_method` | string | 필수 | `manual`, `interpolated` | 다른 값 오류 |
| `interpolation_span_frames` | integer | 조건부 | 1 이상, frame | interpolated이면 필수; manual이면 빈 값 |
| `in_scope` | boolean | 필수 | `true`, `false` | false 관측은 분모 제외 |
| `reviewer` | string | 조건부 | reviewer ID | 공통 검토상태 규칙 적용 |
| `review_status` | string | 필수 | 공통 검토상태 | interpolated도 검토상태 필요 |
| `review_timestamp_utc` | timestamp_utc | 조건부 | UTC | 공통 검토상태 규칙 적용 |
| `notes` | string | 선택 | 자유서술 | 수정 접지점·보간 예외에는 권장 |

## 6. `gt_track_associations.csv`

GT 객체와 자동 track ID의 연결만 저장한다. false positive는 이 파일의 허용 상태가 아니다.

| 필드 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `schema_version` | string | 필수 | `object_track_gt_v1` | 다른 값 오류 |
| `gt_dataset_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `evaluation_run_id` | id | 필수 | manifest lineage와 동일 | 불일치 오류 |
| `video_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `stage` | string | 필수 | `raw_tracker`, `filtered`, `merged` | `raw_detection` 사용 금지 |
| `source_artifact_sha256` | sha256 | 필수 | 해당 stage CSV checksum | lineage와 불일치 오류 |
| `gt_object_id` | id | 필수 | objects에 존재 | 미등록 참조 오류 |
| `auto_track_id` | integer | 조건부 | 0 이상, 해당 stage ID | matched/uncertain 연결이면 필수; missed이면 빈 값 |
| `match_start_frame_index` | integer | 조건부 | 0 이상, frame | matched이면 필수; missed이면 빈 값 |
| `match_end_frame_index` | integer | 조건부 | start 이상, frame | matched이면 필수; missed이면 빈 값 |
| `match_start_timestamp_seconds` | number | 조건부 | 0 이상, s | matched이면 필수 |
| `match_end_timestamp_seconds` | number | 조건부 | start 이상, s | matched이면 필수 |
| `association_status` | string | 필수 | `matched`, `missed`, `uncertain` | `false_positive` 금지 |
| `coverage_status` | string | 필수 | `complete`, `partial`, `missed`, `uncertain` | 같은 GT·stage의 여러 행은 동일값이어야 함 |
| `fragmentation_status` | string | 필수 | `unfragmented`, `fragmented`, `not_applicable`, `uncertain` | missed이면 not_applicable |
| `identity_status` | string | 필수 | `stable`, `id_switch`, `not_applicable`, `uncertain` | missed이면 not_applicable |
| `class_match` | string | 필수 | `match`, `mismatch`, `not_applicable`, `uncertain` | missed이면 not_applicable |
| `matching_method` | string | 필수 | `manual`, `automatic`, `automatic_reviewed`, `adjudicated` | automatic만으로 확정 평가 금지 |
| `match_score` | number | 선택 | 0~1, unitless | manual/missed는 빈 값 허용; 정의 없는 점수 금지 |
| `reviewer` | string | 조건부 | reviewer ID | 공통 검토상태 규칙 적용 |
| `review_status` | string | 필수 | 공통 검토상태 | 확정 지표는 adjudicated만 사용 |
| `review_timestamp_utc` | timestamp_utc | 조건부 | UTC | 공통 검토상태 규칙 적용 |
| `notes` | string | 선택 | 자유서술 | 불확실·복합오류 설명에 사용 |

### 6.1 association 행 규칙

- `missed`: 객체·stage당 한 행, auto ID와 매칭구간·score는 빈 값,
  `coverage_status=missed`, 나머지 상태는 `not_applicable`이다.
- `fragmented`: 같은 GT 객체·stage에 서로 다른 auto ID의 matched 행이 둘 이상이고 모든
  행의 `fragmentation_status=fragmented`다.
- `id_switch`: 같은 auto ID가 서로 다른 GT 객체와 서로 다른 시간구간에 연결되고 관련
  행의 `identity_status=id_switch`다.
- `complete/partial`은 객체·stage 수준 판정이므로 해당 객체의 여러 association 행에서
  같은 값을 반복한다.
- 자동 클래스가 잘못돼도 공간·identity 연결을 유지하고 `class_match=mismatch`로 기록한다.

## 7. `gt_interaction_pairs.csv`

이 파일은 실제 상호작용쌍의 관측 분모다. 안전지표 계산 필드를 추가하지 않는다.

| 필드 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `schema_version` | string | 필수 | `object_track_gt_v1` | 다른 값 오류 |
| `gt_dataset_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `video_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `interaction_gt_id` | id | 필수 | 데이터셋 내 고유 | 중복 오류 |
| `pedestrian_gt_object_id` | id | 필수 | class가 person인 GT 객체 | 미등록·비보행자 참조 오류 |
| `vehicle_gt_object_id` | id | 필수 | 승인된 차량계열 GT 객체 | 미등록·동일 객체 참조 오류 |
| `start_frame_index` | integer | 필수 | 0 이상, frame | 양 객체 시간범위와 교차해야 함 |
| `end_frame_index` | integer | 필수 | start 이상, frame | 평가구간 밖 오류 |
| `start_timestamp_seconds` | number | 필수 | 0 이상, s | frame/FPS 불일치 오류 |
| `end_timestamp_seconds` | number | 필수 | start 이상, s | frame/FPS 불일치 오류 |
| `interaction_zone` | string | 필수 | 승인 region ID | 미정 구역은 other와 notes 사용 |
| `interaction_basis` | string 또는 세미콜론 목록 | 필수 | `same_interaction_area`, `trajectory_crossing_potential`, `behavioral_influence`, `other_manual` | other_manual은 notes 필수; 세부 성립규칙 승인 전 확정 평가 금지 |
| `observable` | boolean | 필수 | `true`, `false` | 사람이 쌍을 신뢰성 있게 판독 가능한지 의미 |
| `denominator_eligible` | boolean | 필수 | `true`, `false` | observable=false이면 반드시 false |
| `exclusion_reason` | string | 조건부 | `not_observable`, `object_out_of_scope`, `ambiguous_pair`, `outside_time_window`, `other` | denominator=false이면 필수; other는 notes 필수 |
| `reviewer` | string | 조건부 | reviewer ID | 공통 검토상태 규칙 적용 |
| `review_status` | string | 필수 | 공통 검토상태 | adjudicated eligible 행만 분모 사용 |
| `review_timestamp_utc` | timestamp_utc | 조건부 | UTC | 공통 검토상태 규칙 적용 |
| `notes` | string | 선택 | 자유서술 | 운영규칙 경계사례에 권장 |

## 8. `auto_track_audit.csv`

자동 stage의 트랙 자체를 판정한다. 특히 false positive는 이 파일에서만 관리한다.

| 필드 | 형식 | 필수 여부 | 허용값·단위 | 예외처리 |
|---|---|---|---|---|
| `schema_version` | string | 필수 | `object_track_gt_v1` | 다른 값 오류 |
| `gt_dataset_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `evaluation_run_id` | id | 필수 | manifest lineage와 동일 | 불일치 오류 |
| `video_id` | id | 필수 | manifest와 동일 | 불일치 오류 |
| `stage` | string | 필수 | `raw_tracker`, `filtered`, `merged` | 다른 값 오류 |
| `source_artifact_sha256` | sha256 | 필수 | 해당 stage CSV checksum | lineage와 불일치 오류 |
| `auto_track_id` | integer | 필수 | 0 이상, 해당 stage ID | stage 안에서 audit 행 중복 금지 |
| `first_frame_index` | integer | 필수 | 0 이상, frame | 실제 자동 CSV와 불일치 오류 |
| `last_frame_index` | integer | 필수 | first 이상, frame | 실제 자동 CSV와 불일치 오류 |
| `first_timestamp_seconds` | number | 필수 | 0 이상, s | 실제 자동 CSV와 불일치 오류 |
| `last_timestamp_seconds` | number | 필수 | first 이상, s | 실제 자동 CSV와 불일치 오류 |
| `object_class_auto` | string | 필수 | 자동 CSV의 class | GT class로 교체 금지 |
| `audit_status` | string | 필수 | `matched`, `false_positive`, `duplicate`, `out_of_scope`, `uncertain` | false positive를 association에 복제 금지 |
| `false_positive_reason` | string | 조건부 | `background`, `static_structure`, `road_marking`, `vegetation`, `shadow`, `duplicate_detection`, `class_hallucination`, `other` | audit_status=false_positive이면 필수; other는 notes 필수 |
| `related_gt_object_ids` | id 또는 세미콜론 목록 | 조건부 | objects에 존재하는 ID | matched/duplicate이면 필수; false_positive이면 빈 값 |
| `reviewer` | string | 조건부 | reviewer ID | 공통 검토상태 규칙 적용 |
| `review_status` | string | 필수 | 공통 검토상태 | adjudicated만 확정 precision 검토에 사용 |
| `review_timestamp_utc` | timestamp_utc | 조건부 | UTC | 공통 검토상태 규칙 적용 |
| `notes` | string | 선택 | 자유서술 | other·uncertain에는 필수 |

## 9. 파일 간 무결성 규칙

1. 모든 CSV의 `schema_version`, `gt_dataset_id`, `video_id`가 manifest와 같아야 한다.
2. visibility, observation, association, interaction에서 참조하는 GT ID는 objects에
   존재해야 한다.
3. observation은 같은 객체의 `visible` 또는 `partially_occluded` interval 안에 있어야
   한다.
4. `fully_occluded`, `not_observable`, `in_scope=false` interval은
   `denominator_eligible=false`여야 한다.
5. interaction pair는 서로 다른 두 GT 객체를 참조해야 한다.
6. association과 auto audit의 run ID 및 checksum은 manifest lineage와 같아야 한다.
7. association에서 false positive 값을 사용하면 오류다.
8. auto audit의 false positive 행은 `related_gt_object_ids`가 비어 있어야 한다.
9. filtered ID는 같은 run의 raw_tracker ID로 역추적 가능해야 한다.
10. merged 행은 `original_track_id` 또는 continuation report를 통해 filtered ID로
    역추적 가능해야 한다.
11. 서로 다른 실행계보의 stage artifact를 혼합하면 평가를 중단한다.
12. 확정 지표의 분자·분모에는 `review_status=adjudicated`인 행만 사용한다.

## 10. 현재 미결정 값

다음 값은 이 데이터사전이 정하지 않으며 빈 템플릿에 임의 입력하지 않는다.

- 파일럿 영상과 실제 30~60초 구간
- 평가 frame step과 evaluation FPS
- in-scope region 목록
- 클래스 호환규칙
- 자동 association의 IoU·거리·시간 허용오차
- match score 산정법
- 최대 interpolation span
- complete 판정의 coverage·maximum-gap 수치
- 미병합 확정조건
- 상호작용 성립 운영규칙
- reviewer 이중검토 비율과 adjudicator

이 값들은 실제 영상을 확인한 뒤 승인된 규약 버전 또는
`internal_provisional_gate`로 기록한다.
