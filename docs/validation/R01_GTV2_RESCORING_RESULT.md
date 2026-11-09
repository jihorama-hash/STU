# R01 GT v2 변환 및 기준선 재채점 결과

- 기준일: 2026-11-09
- 상태: 사용자 일관성 점검 전, 단일 검토자 draft
- 데이터셋: `DJI_0482_R01_detection_box_v2`
- 자동 실행: TASK-007 A `r01_detection_only_20261104_02/A`; TASK-006 `_02` `r01_baseline_yolo11m_full_20261103_02`
- GPU 추론·재실행 없음. 저장된 detections와 tracker 결과만 CPU로 재채점했다.

## 검증 및 canonical

작업 파일 검증은 관측 964, skip 6, 전체 anchor 970, missing 0으로 통과했다. 기대값은 anchors 970, observations 964, skips 6, ignore 110(person 107, car 1, motorcycle 2), 평가 분모 854(person 636, car 184, motorcycle 34), action kept 82 / adjusted 162 / redrawn 715 / new 5와 일치한다.

| canonical 파일 | 행 수 | SHA-256 |
|---|---:|---|
| `gt_objects.csv` | 50 | `a444cdb63db2bcf2d52c34d17a9355b5ee17bc0603d450267a9bd00f666cc6c7` |
| `gt_visibility_intervals.csv` | 143 | `9fdf22524f0d39ba256968fcac298c7706ed643dbf40318ecf28a5aa3d0827a9` |
| `gt_observations.csv` | 964 | `45bc6179abc9a3ad2a6b66070ec9332a1558efa896fc1f0955ed20580ade7559` |
| `gt_observation_skips.csv` | 6 | `88730bf5ec2482f8edf3be2595b7f1a3dbeb607cfb85472e5e3294992c023a24` |

각 해시는 `ground_truth_manifest.json`의 `frozen_files`와 독립 대조했다. 스냅샷 해시는 기록됐지만, 검토자가 1명이므로 `dataset_status=draft`다. v1 파일·태그·manifest 및 객체·visibility 원본은 수정하지 않았다.

## 승인된 skip 예외 대조

- v1 skip 유지, 사유 변경 → `occluded_more_than_marked`: M002@5876, P004@4886, P019@5126, P027@5890, P026@5846.
- v1 skip → v2 ignore 박스(`revision_action=new`): P005@5966, P007@4522, P017@5200, P018@5216, P019@5166.
- v1 박스 → v2 skip: P027@5876 (`occluded_more_than_marked`).
- P020@5454: v1 박스 → v2 ignore 박스(`redrawn`).

네 항목 모두 v2 작업 파일과 일치한다. visibility 정본은 건드리지 않았다.

## 라벨 변경 및 상자 면적

행은 v2 observations 기준이며 ignore는 action과 별도 집계했다.

| 클래스 | kept | adjusted | redrawn | new | ignore |
|---|---:|---:|---:|---:|---:|
| person | 68 | 105 | 565 | 5 | 107 |
| car | 6 | 53 | 126 | 0 | 1 |
| motorcycle | 8 | 4 | 24 | 0 | 2 |
| 합계 | 82 | 162 | 715 | 5 | 110 |

paired non-ignore 관측 854개의 면적비(box area v2 / v1) 분위수:

| 클래스 | n | P10 | P25 | 중앙값 | P75 | P90 |
|---|---:|---:|---:|---:|---:|---:|
| person | 636 | 0.414 | 0.519 | 0.634 | 0.800 | 1.000 |
| car | 184 | 0.561 | 0.685 | 0.740 | 0.796 | 0.856 |
| motorcycle | 34 | 0.261 | 0.387 | 0.495 | 0.947 | 1.000 |
| 전체 | 854 | 0.418 | 0.544 | 0.663 | 0.800 | 1.000 |

v1 `notes`에서 `foot_adjusted`인 51행의 발점 효과는 상자 재작성 효과와 분리했다. 기존 v1 foot 좌표에서 기존 v1 박스의 하단 중앙으로 재계산한 차이는 중앙값 Δx=-32.34 px, Δy=-21.36 px이며, 이동거리 중앙값은 47.19 px다. 별도 상자 변경 효과는 위 면적비 분포다. foot 점은 위치 재계산 대상이며 detection/trajectory의 IoU 박스 면적 계산에는 사용하지 않았다.

v1과 v2 좌표가 같은데 action이 `adjusted` 또는 `redrawn`인 행은 3건이다: P034@5722, P034@5846, P034@5876 (모두 redrawn).

## 검출기 단독 재채점

매칭은 TASK-007 그대로 클래스별 P/R과 클래스 무관 일대일 Hungarian 진단, IoU 0.5 공식 및 0.3 민감도다. precision은 완전 프레임만, recall 분모는 해당 버전의 유효 관측 전체다. v1은 960개·54 complete frames, v2는 854개·56 complete frames여서 수치는 표본과 완전 프레임 수가 다르다. 표의 P/R은 conf 0.15 / IoU 0.5이며 FP는 audit 전이다.

| 클래스 | GT 분모 v1→v2 | P v1→v2 | R v1→v2 | AP50 v1→v2 |
|---|---:|---:|---:|---:|
| person | 739→636 | 0.482→0.731 | 0.245→0.409 | 0.261→0.643 |
| car | 185→184 | 0.414→0.469 | 0.692→0.804 | 0.571→0.675 |
| motorcycle | 36→34 | 0.800→0.714 | 0.222→0.235 | 0.212→0.274 |
| 전체 | 960→854 | 0.454→0.613 | 0.330→0.487 | — |

전체 P/R은 클래스 무관 Hungarian 결과이며, AP는 클래스별 COCO 평가다. 전체 AP는 TASK-007 v1의 `all` 단위와 v2 평가 집계가 동등하지 않아 표에서 제외했다. P/R 상세의 conf .25 및 IoU .3은 각 run의 `pr_metrics.csv`에 기록했다.

`rider_inside_vehicle` (미매칭 person, GT motorcycle 박스 겹침, conf .15/.25; 포함률 기준 30%/50%/70%):

| conf | IoU | 30% | 50% 주 기준 | 70% |
|---:|---:|---:|---:|---:|
| 0.15 | 0.5 | 10 | 10 | 10 |
| 0.15 | 0.3 | 10 | 10 | 10 |
| 0.25 | 0.5 | 3 | 3 | 3 |
| 0.25 | 0.3 | 3 | 3 | 3 |

## 궤적 재채점

원본 TASK-006과 같은 anchor-time, class-agnostic framewise Hungarian IoU 매칭 및 호환표를 적용했다. v1 분모 960, v2 분모 854이며 ignore 중첩 자동 박스는 미매칭 FP에서 제외했다. v1 프레임 지표는 54 complete frames, v2는 56개다. 따라서 버전 간 지표 차이는 GT 수정과 분모·complete-frame 집합 차이를 함께 포함한다.

### 전체 (raw_tracker / filtered·merged)

| IoU | 버전 | 앵커 재현율 raw / filtered | Precision raw / filtered | HOTA 평균 raw / filtered | IDF1 raw / filtered |
|---:|---|---:|---:|---:|---:|
| 0.5 | v1 (960) | 0.244 / 0.227 | 0.536 / 0.625 | 0.270 / 0.269 | 0.306 / 0.304 |
| 0.5 | v2 (854) | 0.367 / 0.342 | 0.723 / 0.847 | 0.393 / 0.397 | 0.429 / 0.438 |
| 0.3 | v1 (960) | 0.349 / 0.322 | 0.761 / 0.880 | 0.270 / 0.269 | 0.431 / 0.437 |
| 0.3 | v2 (854) | 0.404 / 0.375 | 0.790 / 0.917 | 0.393 / 0.397 | 0.461 / 0.470 |

### 클래스별 앵커 재현율 (raw_tracker / filtered·merged)

| 클래스 | IoU | v1 | v2 |
|---|---:|---:|---:|
| person | 0.5 | 0.150 / 0.147 | 0.269 / 0.261 |
| person | 0.3 | 0.257 / 0.245 | 0.303 / 0.289 |
| car | 0.5 | 0.638 / 0.562 | 0.745 / 0.658 |
| car | 0.3 | 0.751 / 0.665 | 0.793 / 0.712 |
| motorcycle | 0.5 | 0.139 / 0.139 | 0.147 / 0.147 |
| motorcycle | 0.3 | 0.167 / 0.139 | 0.176 / 0.147 |

`filtered`와 `merged` 수치는 이번 평가에서 일치했다. 세 단계 × 두 IoU의 상세 MOTA, IDSW, DetA/AssA/LocA 등은 결과 산출물에 있다. 대표 출력 경로는 `outputs/evaluation/r01_gtv1_scoring_20261103_02/` 및 `outputs/evaluation/r01_gtv2_scoring_20261109_ignorefix/`다.

## Visibility 경계 재확인 후보 (수정 없음)

`visibility_status=visible` 구간에 걸친 ignore 관측 33건:

`M001@4556, M001@4570, P003@4766, P003@4792, P005@5850, P006@4946, P006@4950, P007@4494, P008@4450, P009@4450, P011@4416, P013@4416, P014@4356, P016@4818, P016@5006, P017@4826, P017@4856, P018@5156, P018@5168, P019@4776, P019@4866, P019@4924, P020@4864, P020@5004, P020@5396, P020@5416, P021@4864, P021@5002, P022@5048, P023@5816, P024@4956, P027@5828, P037@5820`.

`partially_occluded` visibility 구간에 걸친 skip 5건: `M002@5876, P019@5126, P026@5846, P027@5876, P027@5890`.

추가 경계 후보: `visibility_status=visible` 구간 안의 skip `P004@4886`.

이 목록은 정본의 시간 경계와 annotation을 대조해 사용자 확인 대상으로만 작성했다. visibility/object 정본은 수정하지 않았다.

## 일관성 점검

**30-anchor 일관성 점검 보류(사용자 결정 2026-11-09), GT v2는 단일 검토자 자료로 검토자 내 일관성 미측정**.

## 실행 및 한계

- `.venv/bin/pytest`: 111 passed.
- 작업 검증: `PYTHONPATH=src .venv/bin/python scripts/ground_truth/revise_detection_gt_v2.py --validate-only` 및 viewer `--validate-only --revision-v2` 통과.
- 검출 재채점: `PYTHONPATH=src .venv/bin/python scripts/diagnostics/43_score_r01_detection_v2.py`; 기존 detections만 읽음.
- 궤적 재채점: `PYTHONPATH=src .venv/bin/python -m roundabout.evaluate_object_track --config configs/evaluation_object_track_v2_ignorefix.yaml --root .`; GPU 사용 안 함.
- 단일 검토자 draft이며 자동 association/precision은 사람 adjudication 전 잠정값이다. 표본은 DJI_0482의 약 60초 구간이다. v1/v2의 분모 및 완전 프레임이 달라 순수 라벨 변화만의 인과효과로 해석할 수 없다.
- 19건의 ignore 영역은 자동 추정이 visibility·skip·앞뒤 manual box로부터 해소되지 않아 보조 목록에 남았다. ignore는 위치 평가 분모에서 제외했고, 매칭되지 않은 자동 박스 중 호환 ignore에 IoA가 임계값 이상 겹치는 항목은 FP에서 제외했다.

## 커밋 전 추가 회귀 게이트 (2026-11-09)

### v1 회귀 검사

현재 코드로 v1을 재채점해 기존 결과와 대조했다. TASK-006 `_02` metrics JSON은 run ID를 정규화한 뒤 완전히 일치했다. v1 평가에는 ignore가 없어 분모 메타데이터 필드를 출력하지 않도록 했으며, v2 ignore 평가 결과에는 계속 해당 필드가 기록된다. TASK-007 A v1 회귀도 통과했다: summary JSON 동일, P/R CSV 16행 바이트 단위 동일, unmatched CSV 301건 바이트 단위 동일.

재채점 출력은 `outputs/evaluation/r01_gtv1_scoring_20261109_ignorefix_regression2/` 및 `outputs/evaluation/r01_detection_v1_currentcode_regression_20261109_02/A/`다. 검출기는 기존 detections를 사용했고 추론은 하지 않았다.

### 개선 원인 분해 (conf .15, IoU .5)

조건 (b)는 v2의 964개 box를 모두 일반 GT로 평가했고, (c)는 v2 기준에서 ignore 110개를 분모에서 제외했다. 검출기 precision은 complete frames에서 계산했고, recall은 전체 유효 anchor에서 계산했다. 궤적 값은 raw tracker anchor recall이다.

| 지표 / 클래스 | (a) v1 GT | (b) v2 box, ignore 포함 | (c) 정식 v2, ignore 제외 |
|---|---:|---:|---:|
| 검출기 recall - 전체 | 317/960 = 0.330 | 419/964 = 0.435 | 416/854 = 0.487 |
| 검출기 recall - person | 181/739 = 0.245 | 263/743 = 0.354 | 260/636 = 0.409 |
| 검출기 recall - car | 128/185 = 0.692 | 148/185 = 0.800 | 148/184 = 0.804 |
| 검출기 recall - motorcycle | 8/36 = 0.222 | 8/36 = 0.222 | 8/34 = 0.235 |
| raw tracker anchor recall - 전체 | 234/960 = 0.244 | 313/964 = 0.325 | 313/854 = 0.367 |
| raw tracker - person | 111/739 = 0.150 | 171/743 = 0.230 | 171/636 = 0.269 |
| raw tracker - car | 118/185 = 0.638 | 137/185 = 0.741 | 137/184 = 0.745 |
| raw tracker - motorcycle | 5/36 = 0.139 | 5/36 = 0.139 | 5/34 = 0.147 |

(a)→(b)는 검토된 v2 box와 anchor 처리 변경을 포함한 차이다. (b)→(c)는 ignore 관측을 평가 분모에서 제외한 효과다. c에서 recall이 오르는 부분은 분모 축소 영향도 포함하며 자동 시스템의 검출 성능이 변했다는 뜻은 아니다. b와 c의 검출기 true-positive 수 차이는 person 3건이며 car·motorcycle은 같다.

### 경계 후보 추가

사용자 요청에 따라 visible 구간 안 skip `P004@4886`을 경계 재확인 목록에 추가했다. visibility 정본은 고치지 않았다.
