# 객체·궤적 Ground Truth 작성 규약

문서 상태: Gate 1 규약 초안

스키마 버전: `object_track_gt_v1`

적용 범위: 객체·궤적 관측품질 평가용 ground truth

## 1. 목적과 제외 범위

이 규약은 실제 객체를 기준으로 `raw_tracker`, `filtered`, `merged` 궤적의
관측품질을 비교하기 위한 ground truth와 검토자료의 작성 원칙을 정의한다. 주요
평가대상은 객체사건 포착, 궤적 완전성, 시간 커버리지, 최대 연속 누락,
fragmentation, ID switch, 필터 생존 및 병합 정확성이다.

이 단계에서는 다음 작업을 하지 않는다.

- 대표 5분 전체 ground truth 작성
- 객체·궤적 평가모듈 구현
- 모델, FPS, 검출·추적·필터·병합 임계값 변경
- PET, TTC, PDI 또는 새로운 안전지표 구현·변경
- 기존 ground truth와 기존 평가 산출물 변경·삭제

보행자-차량 상호작용 ground truth는 안전지표 계산 결과가 아니다. 사람이 확인한
실제 상호작용쌍의 관측 분모를 제공하여, 양쪽 객체의 유효궤적이 확보됐는지를 나중에
평가하기 위한 자료다.

## 2. 최초 파일럿 범위

최초 파일럿은 5분 전체가 아니라 연속된 30~60초 구간으로 한다. 구간은 다음 조건을
충족하는지 실제 원본 영상을 먼저 확인한 뒤 선정한다.

- 보행자와 차량이 모두 관측됨
- 최소 한 건의 수동 확인 가능한 보행자-차량 상호작용쌍이 포함됨
- 가시, 부분가림 및 필요한 경우 완전가림 사례를 판정할 수 있음
- 객체의 등장·이탈과 주요 이동구간을 시간순으로 검토할 수 있음

현재 규약에서는 영상 ID, 시작·종료 프레임, 시작·종료시각을 확정하지 않는다. 선정
후 `ground_truth_manifest.json`에 실제 값과 선정 근거를 기록한다. 자동 오버레이나
자동 후보 건수를 기준으로 구간을 먼저 고르지 않는다.

## 3. 파일 구성과 역할

현재 파일 구조는 향후 평가시스템이 읽고 검증할 canonical 저장 구조다. canonical 파일의
모든 열이 필수라는 뜻은 사람이 모든 값을 직접 입력한다는 뜻이 아니다. 최초 30~60초
파일럿에서는 사람이 실제 판단이 필요한 원자료만 작성하고 나머지는 원본 영상, manifest,
다른 GT 계층 또는 향후 평가 프로그램에서 생성한다.

| 파일 | 역할 | 생성·작성 단계 |
|---|---|---|
| `ground_truth_manifest.json` | 영상·표본·좌표·샘플링·체크섬·실행계보 메타데이터 | blind GT에서는 선정 판단과 기본 메타데이터만 작성 |
| `gt_objects.csv` | 실제 물리 객체 목록과 객체 수준 범위 | 최초 blind GT 필수 |
| `gt_visibility_intervals.csv` | 객체별 가시성 및 평가분모 포함 구간 | 최초 blind GT 필수 |
| `gt_observations.csv` | 특정 프레임의 위치관측과 manual/interpolated 구분 | 최초 blind GT 필수 |
| `gt_interaction_pairs.csv` | 실제 보행자-차량 상호작용쌍 분모 | 객체 ID를 확정한 뒤 작성 |
| `gt_track_associations.csv` | GT 객체와 단계별 자동 track ID의 시간구간 연결 | blind GT 동결 후 평가 단계에서 생성·검토 |
| `auto_track_audit.csv` | 자동 트랙의 false positive·중복·범위외 판정 | blind GT 동결 후 평가 단계에서 생성·검토 |

저장소의 `.template.*` 파일은 헤더와 구조만 제공한다. 실제 파일을 만들 때 템플릿을
복사하고, 파일명에서 `.template`을 제거하며, manifest의 `gt_dataset_id`와
`schema_version`을 모든 CSV에 동일하게 기록한다.

### 3.1 필드 역할 분류

모든 manifest 및 CSV 필드는 다음 한 범주에 속한다. 필드별 분류는
`DATA_DICTIONARY.md`를 따른다.

| 범주 | 의미 |
|---|---|
| `manual_required` | 객체 identity, class, 가시성, 위치, 상호작용쌍처럼 사람이 반드시 판단하는 원자료 |
| `auto_generated` | timestamp, duration, FPS 파생값, 체크섬, 반복 ID, 분모 포함 여부, 평가 판정처럼 원자료나 프로그램에서 생성하는 값 |
| `optional_future` | 최초 파일럿에는 요구하지 않고 향후 확장 또는 상세 검토에서 선택적으로 쓰는 값 |

`auto_generated` 필드는 사람이 CSV 셀에 반복 입력하지 않는다. 프로그램이 아직 없으면
canonical 파일 생성 전까지 비워 두거나 관련 후속 파일을 헤더만 유지한다. 자동 판정값은
향후 사람이 검토·adjudicate할 수 있지만 최초 값은 원자료로부터 생성되어야 한다.

## 4. 작성 순서와 자동결과 독립성

1. 원본 영상만 보고 평가 가능 여부와 파일럿 구간을 선정한다.
2. blind GT에 필요한 manifest 값만 기록하고 자동 파생값은 생성 대상으로 남긴다.
3. 자동 박스·track ID·위험후보를 숨긴 상태에서 `gt_objects.csv`를 작성한다.
4. 객체별 가시·가림·판독불가 구간을 `gt_visibility_intervals.csv`에 작성한다.
5. 공간 매칭에 필요한 수동 위치를 `gt_observations.csv`에 작성한다.
6. 객체·가시성·위치 GT를 검토하고 객체 ID를 1차 동결한다.
7. 동결된 객체 ID로 실제 상호작용쌍을 `gt_interaction_pairs.csv`에 기록한다.
8. 이후 자동 단계별 결과를 공개하고 `gt_track_associations.csv`를 생성·검토한다.
9. 연결되지 않은 자동 트랙을 `auto_track_audit.csv`에서 판정하고 최종 불일치를 adjudicate한다.

`gt_objects.csv`, `gt_visibility_intervals.csv`, `gt_observations.csv`에는 자동
track ID를 기록하지 않는다. 자동결과와의 연결은 반드시
`gt_track_associations.csv`로 분리한다.

## 5. 식별자, 시간 및 좌표 규칙

### 5.1 식별자

- `gt_dataset_id`: 하나의 동결 가능한 GT 묶음을 식별한다.
- `gt_object_id`: 영상 안의 실제 물리 객체 한 개에 부여하는 영구 ID다.
- `visibility_interval_id`: 한 객체의 연속된 가시성 상태 구간 ID다.
- `interaction_gt_id`: 실제 보행자-차량 쌍 한 건의 ID다.
- `evaluation_run_id`: GT와 대조할 한 자동실행 계보의 ID다.
- `auto_track_id`: 해당 자동 단계 산출물 안에서만 유효하다.

여러 사람이 붙어 이동하더라도 신뢰성 있게 구분할 수 있으면 개인별 ID를 부여한다.
구분할 수 없으면 임의 분할하지 않고 `notes`와 `review_status=uncertain`으로 남긴다.

### 5.2 프레임과 시각

- `frame_index`는 원본 영상의 0 기반 프레임 번호다.
- 구간의 시작·종료 프레임은 모두 포함하는 폐구간이다.
- `timestamp_seconds = frame_index / source_fps`를 기본으로 한다.
- 컨테이너 타임스탬프를 별도 사용하면 manifest에 산정법을 바꿔 기록한다.
- 사람은 의미 있는 시작·종료 프레임을 판단하고 timestamp와 duration은 자동 생성한다.
- source FPS는 원본 영상에서 자동 추출하고 evaluation FPS는 승인된 frame step으로부터
  자동 생성한다.
- frame step은 승인 전까지 `pending`으로 유지한다. FPS와 frame step을 추정하거나
  임의 기본값으로 채우지 않는다.

### 5.3 좌표계

객체 GT 위치의 기본 좌표계는 원본 영상의 `source_pixel`이다.

- 원점: 원본 프레임 좌상단
- x축: 오른쪽 방향
- y축: 아래쪽 방향
- 박스: `x1, y1` 포함 좌상단과 `x2, y2` 우하단
- 발점: 박스 하단 중앙 또는 사람이 수정한 실제 접지점
- 단위: `px`

reference-image pixel이나 world coordinate를 사용하려면 별도 좌표 필드와 변환 버전이
필요하다. 이 v1 템플릿의 위치 필드에 서로 다른 좌표계를 혼용하지 않는다.

## 6. GT 계층

### 6.1 객체 수준

`gt_objects.csv`는 실제 객체의 존재와 전체 범위를 정의한다. 자동 track ID나 자동
판정은 포함하지 않는다. 객체가 자동 결과에서 완전히 누락돼도 반드시 객체 목록에는
남아 있어야 한다.

`in_scope=false` 객체는 존재는 기록하되 평가분모에서 제외한다. 제외사유는 빈 값으로
두지 않는다.

### 6.2 가시성 구간 수준

한 객체의 시간축은 상태가 바뀔 때마다 별도 구간으로 나눈다.

| `visibility_status` | 정의 | 기본 분모 처리 |
|---|---|---|
| `visible` | 사람이 객체와 위치를 신뢰성 있게 판독 가능 | 포함 |
| `partially_occluded` | 일부 가림이 있으나 동일 객체와 위치를 판독 가능 | 포함 |
| `fully_occluded` | 객체가 완전히 가려져 위치를 직접 판독할 수 없음 | 제외 |
| `not_observable` | 화질·화면경계·모호성 등으로 사람도 신뢰성 있게 판독 불가 | 제외 |

`fully_occluded`와 `not_observable`은 `denominator_eligible=false`여야 한다.
`in_scope=false` 구간도 분모에서 제외한다. 예외가 필요하면 규약을 먼저 개정하고 결정
근거를 기록해야 하며 개별 행에서 임의로 뒤집지 않는다.

사람은 `visibility_status`와 필요한 scope 판단을 기록한다. `denominator_eligible`은
그 원자료에서 자동 생성하며 사람이 별도로 판정하거나 반복 입력하지 않는다.

같은 객체의 visibility interval은 겹치면 안 된다. 상태 사이의 시간 공백은 의도된
것인지 확인하고, 공백이 평가구간 안이라면 누락된 구간을 추가하거나 제외근거를 남긴다.

### 6.3 위치관측 수준

`gt_observations.csv`는 공간 매칭 또는 경로 검토에 필요한 프레임 위치를 저장한다.

- `manual`: 사람이 해당 프레임에서 직접 지정한 위치
- `interpolated`: 앞뒤의 유효한 manual 관측 사이에서 생성한 위치

interpolated 관측은 양쪽 manual anchor가 동일 객체임이 확정된 구간에서만 허용한다.
완전가림 또는 `not_observable` 구간을 가로질러 보간하지 않는다. 허용할 최대 보간
프레임 수는 파일럿 전에 별도 승인하며, 현재 규약에서 임의로 정하지 않는다.
`interpolation_span_frames`에는 두 anchor 사이의 프레임 간격을 기록한다.

`fully_occluded` 또는 `not_observable` 상태에는 추정 위치를 실제 관측처럼 기록하지
않는다. 위치가 없으면 관측행을 만들지 않고 visibility interval만 유지한다.

사람은 객체, 관측 프레임과 위치를 판단한다. timestamp, 반복되는 class·scope·가시성,
기본 발점, 좌표계·단위 및 interpolation span은 가능한 원자료에서 자동 생성한다. 사람이
기본 발점을 수정한 경우에만 수정값과 근거를 보존한다.

## 7. 자동 파이프라인 단계와 연결관계

### 7.1 `raw_tracker`

`detect_track.py`가 생성한 `tracks.csv`의 raw tracker trajectory다. 현재 파이프라인은
raw detection을 별도 보존하지 않으므로 `raw_detection` 단계와 혼동하지 않는다.

### 7.2 `filtered`

`filter_tracks.py`가 생성한 `filtered_tracks.csv`다. 유지된 track ID는 원칙적으로
`raw_tracker` ID를 그대로 사용한다. 존재하지 않는 ID의 제거사유는 같은 실행계보의
`filter_summary.json`에서 확인한다.

### 7.3 `merged`

`merge_track_fragments.py`가 생성한 `filtered_tracks_merged.csv`다. 출력 `track_id`는
병합 결과 ID이고, 각 행의 `original_track_id`와 `continuation_report.json` 링크를
사용해 filtered ID로 역추적한다.

### 7.4 실행계보 필수조건

세 단계 비교 전 manifest에 다음 값을 모두 자동 수집하거나 기록하고 검증한다. 이 실행계보
필드는 최초 blind GT 입력대상이 아니다.

- 원본 영상 경로와 SHA-256
- 원본 FPS, 해상도, 프레임 수
- 평가 frame step과 유효 FPS
- Git commit
- 설정파일 경로와 SHA-256
- 모델 가중치 경로와 SHA-256
- 각 단계 CSV 및 summary/report의 경로와 SHA-256
- 하나의 `evaluation_run_id`

서로 다른 실행계보의 CSV를 한 평가에 섞지 않는다. 값이 없거나 체크섬이 맞지 않으면
association과 단계별 비교 결과를 확정하지 않는다.

## 8. GT와 자동 트랙의 association

association은 GT 객체와 한 단계의 자동 track ID가 실제로 같은 객체인 시간구간을
나타낸다. 최초 blind GT를 동결한 뒤 평가 단계에서 자동 후보를 생성하고 사람이 검토한다.
자동 매칭 결과와 사람 판정을 구분하고, 최종 평가에는 adjudicated 결과를 사용한다.

GT 객체가 한 단계에서 완전히 누락되면 `association_status=missed`인 행을 한 개 만들고
`auto_track_id`와 매칭구간은 비워 둔다. GT와 연결되지 않은 자동 트랙의 false positive는
association 상태로 만들지 않고 `auto_track_audit.csv`에 기록한다.

공간 IoU, 발점 거리, 시간 허용오차, 클래스 호환규칙과 자동 match score 정의는 평가기
구현 전에 파일럿 자료로 검토하고 별도 승인한다.

timestamp, coverage, maximum gap, fragment 수, fragmentation, ID switch, class match,
complete·partial·missed 및 단계별 요약 판정은 GT 원자료와 adjudicated association에서
자동 생성한다. 기준이 승인되지 않은 판정은 `pending`으로 유지하며 사람이 임의값을
입력하지 않는다.

## 9. 궤적 판정 정의

이 절의 판정은 사람이 최초 GT CSV에 직접 입력하는 원자료가 아니다. 승인된 규칙에 따라
평가 단계에서 자동 생성한 뒤 사람이 오류사례를 검토한다. 수치 기준이 미정인 판정은
생성하지 않고 `pending` 상태로 남긴다.

### 9.1 `complete`

GT 객체의 분모 포함 가시구간 중 분석에 필요한 전체 경로가 하나의 안정된 객체 identity로
관측되고, 승인된 시간 커버리지 및 최대 누락 기준을 모두 충족한 상태다. 수치 기준은
파일럿 후 `internal_provisional_gate`로 승인하기 전까지 확정하지 않는다.

### 9.2 `partial`

GT 객체가 한 번 이상 올바르게 연결됐지만 `complete` 조건을 충족하지 못한 상태다.
주요 경로 일부 누락, 낮은 시간 커버리지 또는 승인기준을 넘는 연속 누락을 포함한다.

### 9.3 `missed`

GT 객체의 분모 포함 가시구간에서 올바르게 연결된 자동 트랙 관측이 하나도 없는 상태다.
완전가림·판독불가 구간만 존재하는 객체는 `missed` 분모에 넣지 않고 범위 제외 또는
`uncertain`으로 처리한다.

### 9.4 `fragmented`

한 GT 객체의 유효궤적이 같은 단계에서 둘 이상의 자동 track ID로 나뉜 상태다. 실제
fragment 수는 해당 GT 객체와 올바르게 연결된 서로 다른 자동 ID 수이며,
`fragmentation_count = max(0, fragment_count - 1)`로 정의한다. merged 단계에서는
병합 후 ID를 기준으로 다시 계산한다.

### 9.5 `id_switch`

한 자동 track ID가 시간에 따라 서로 다른 실제 GT 객체에 잘못 연결되거나, 객체가
인접한 다른 객체의 identity를 넘겨받은 상태다. 단순 검출 공백 뒤 새 ID가 생겼지만
다른 객체와 identity가 섞이지 않은 경우는 fragmentation이며 ID switch로 중복 판정하지
않는다. 두 현상이 함께 발생하면 각각 기록한다.

### 9.6 클래스 오류

위치와 identity는 같은 객체로 연결되지만 자동 `object_class`가 GT 클래스와 호환되지
않는 상태다. 클래스 호환표는 파일럿 전에 승인한다. 클래스 오류 때문에 실제 객체 연결을
삭제하지 않고 `class_match=mismatch`로 별도 기록한다.

## 10. 필터 및 병합 판정

### 10.1 필터 생존

같은 `evaluation_run_id`에서 GT 객체가 raw_tracker에 올바르게 연결됐고 filtered에도
하나 이상의 올바른 연결이 남으면 실제 객체가 필터에서 생존한 것으로 본다. raw에서
관측되지 않은 객체는 필터 생존율 분모에 넣지 않는다. raw에는 있으나 filtered에 없으면
`filter_summary.json`의 제거사유를 함께 기록한다.

### 10.2 올바른 병합

병합된 모든 `original_track_id`가 같은 GT 객체에 속하고 identity가 섞이지 않으면
올바른 병합이다.

### 10.3 오병합

서로 다른 GT 객체에 속한 filtered ID가 하나의 merged ID로 합쳐지면 오병합이다.

### 10.4 미병합

같은 GT 객체의 분절로 확인된 filtered ID들이 승인된 병합 대상 조건을 충족하지만 merged
단계에서도 둘 이상의 ID로 남으면 미병합 후보로 기록한다. 자동 기하조건을 충족하지 않은
경우까지 오류로 확정할지는 별도 병합 평가규칙에서 결정한다.

## 11. 자동 트랙 audit와 false positive

false positive는 실제 GT 객체에 올바르게 연결되지 않으며 범위 내 실제 객체를 나타내지
않는 자동 트랙이다. 다음과 같이 분리 관리한다.

- association 파일에는 false positive 상태를 사용하지 않는다.
- GT 객체와 연결되지 않은 자동 트랙은 `auto_track_audit.csv`에 한 행씩 기록한다.
- 배경·노면표시·식생·그림자·중복검출·클래스 환각 등 사유를 기록한다.
- 실제 객체지만 GT 범위 밖인 경우 `out_of_scope`로 처리하고 false positive와 구분한다.
- 같은 자동 ID가 여러 실제 객체를 잇는 문제는 false positive가 아니라 ID switch로
  association에 기록한다.

## 12. 상호작용쌍 ground truth

`gt_interaction_pairs.csv`는 사람이 원본 영상에서 확인한 보행자 GT 객체와 차량 GT
객체의 쌍을 저장한다. 이 파일에는 PET, TTC, 위험점수, DPD 또는 PDI를 저장하지 않는다.

`denominator_eligible=true`인 행만 상호작용쌍 관측률의 분모가 된다. 사람도 판독하기
어렵거나 한쪽 객체가 평가범위 밖이면 제외사유를 기록한다. 상호작용 성립의 세부 운영규칙은
파일럿 구간 선정 전에 별도 검토하며, 자동 ROI 후보를 실제 상호작용 GT로 자동 복사하지
않는다.

이 파일은 `gt_objects.csv`의 객체 ID가 검토·확정된 뒤 작성한다. 최초 객체 목록과 동시에
작성하지 않는다. 사람은 실제 pair와 관측구간을 판단하고 timestamp와
`denominator_eligible`은 자동 생성한다.

## 13. 검토상태와 예외처리

허용하는 `review_status`는 다음과 같다.

- `draft`: 1차 작성, 평가 사용 불가
- `reviewed`: 다른 검토자가 확인했으나 불일치 조정 전
- `adjudicated`: 불일치가 해결된 확정값
- `uncertain`: 현재 자료로 확정 불가, 확정 평가에서 제외

필수값 누락, 허용값 위반, 좌표계 불일치, 겹치는 가시성 구간, 존재하지 않는 GT ID 참조,
체크섬 불일치는 오류로 처리한다. 불확실한 값을 0이나 빈 문자열로 임의 대체하지 않는다.
빈 값이 허용되는 필드는 데이터사전의 조건부 규칙을 따른다.

## 14. 파일럿 전에 남은 결정사항

아래 항목은 모두 `pending`이다. `pending`은 미승인값을 임의 숫자나 임시 판정으로
대체하지 않는 workflow 상태를 뜻한다. JSON에서는 관련 값을 `null`로 유지하고, CSV에서는
그 값을 요구하는 후속 행을 아직 생성하지 않는다. 기존 허용값 목록에 문자열 `pending`을
임의로 추가하지 않는다.

다음은 현재 확정하지 않는다.

- 실제 파일럿 영상과 30~60초 시작·종료 구간
- 평가 frame step과 위치 GT 작성 간격
- in-scope 구역과 구역 정의 버전
- 객체 클래스 세부 호환표
- 사람 집단과 탑승자·이륜차의 경계 사례 처리
- automatic matching의 IoU·발점거리·시간 허용오차
- 허용할 최대 interpolation span
- `complete`의 최소 시간 커버리지와 최대 연속 누락 기준
- 미병합을 오류로 확정할 기하·시간 조건
- 상호작용 성립의 세부 운영규칙
- 이중검토 비율과 adjudicator

이 값들은 파일럿 영상을 확인하고 검토 난이도와 오류사례를 본 뒤
`internal_provisional_gate` 또는 버전된 판정규칙으로 승인받는다.

## 15. 완료조건

Gate 1의 규약·템플릿 단계는 다음을 만족할 때 완료로 본다.

1. 모든 CSV 템플릿이 헤더만 포함함
2. manifest 템플릿이 유효한 JSON임
3. 모든 필드가 `DATA_DICTIONARY.md`에 정의됨
4. 좌표·FPS·frame step·체크섬·실행계보 필드가 있음
5. 객체·가시성·위치·association·interaction·auto audit가 분리됨
6. 기존 ground truth와 기존 산출물이 변경되지 않음
7. 파일럿 구간과 미확정 임계값이 임의로 채워지지 않음
