# 전체 영상 PET/TTC 후보 사람 검토 계획

작성일: 2026-08-05 KST  
대상: 전체 분석 7개 영상의 자동 PET/TTC 후보

## 목적과 범위

자동 분석이 만든 119건은 확정 사고나 위험 사건이 아니라 검토 전 후보다. 먼저
`PET ≤ 1.5초`이거나 `접근 중 TTC ≤ 3초`인 사건을 고르고, 같은 영상·ROI·트랙 쌍의
중복을 제거한 56건만 1차 검토한다. TTC는 영상 평면의 순간 속도 근사이므로 TTC만
짧다는 이유로 사건을 확정하지 않는다.

작업용 통합표는
`outputs/validation/full_batch_event_review/review_queue.csv`다. `review_status`와
`review_notes` 열을 채운다. 각 행의 `image_path`에서 1차 검토 이미지를 확인할 수 있다.
이 디렉터리는 생성 산출물이므로 Git에서 제외된다.

## 예상 소요 시간

| 작업 | 규모 | 예상 시간 |
|---|---:|---:|
| ROI 정합 연락판 확인 | 7개 영상 | 10–15분 |
| P1 보행자–차량, PET 1.5초 이하 | 6건 | 5–10분 |
| P2 차량–차량, PET 1.5초 이하 | 23건 | 12–20분 |
| P3 보행자–차량, TTC-only | 10건 | 5–10분 |
| P4 차량–차량, TTC-only | 17건 | 5–10분 |
| 애매한 후보 필름스트립 재검토 | 예상 10–25건 | 15–40분 |
| 결과 정리와 교차 확인 | 1회 | 5–10분 |
| **합계** | **56건 + 애매한 건** | **약 45–90분** |

첫 세션에서는 P1과 P2까지만 검토해도 된다. 이 경우 약 20–30분 안에 PET 기준의
핵심 29건을 먼저 판단할 수 있다. 전체 119건을 같은 깊이로 검토하는 방식은 피한다.

## 영상별 작업표

| 순서 | 영상 | 자동 후보 | 1차 대상 | 사람–차량 | 차량–차량 | 작업 파일 | 진행 상태 |
|---:|---|---:|---:|---:|---:|---|---|
| 1 | DJI_0481 | 42 | 23 | 3 | 20 | `DJI_0481/manifest.csv` | 미시작 |
| 2 | DJI_0486 | 17 | 10 | 6 | 4 | `DJI_0486/manifest.csv` | 미시작 |
| 3 | DJI_0483_Cut | 23 | 11 | 4 | 7 | `DJI_0483_Cut/manifest.csv` | 미시작 |
| 4 | DJI_0487 | 14 | 3 | 3 | 0 | `DJI_0487/manifest.csv` | 미시작 |
| 5 | DJI_0485 | 12 | 4 | 0 | 4 | `DJI_0485/manifest.csv` | 미시작 |
| 6 | DJI_0488 | 8 | 3 | 0 | 3 | `DJI_0488/manifest.csv` | 미시작 |
| 7 | DJI_0484 | 3 | 2 | 0 | 2 | `DJI_0484/manifest.csv` | 미시작 |
| **합계** |  | **119** | **56** | **16** | **40** | `review_queue.csv` | **미시작** |

영상별 파일과 이미지는 모두
`outputs/validation/full_batch_event_review/` 아래에 있다. ROI 정합은
`outputs/validation/video_audit/all_videos_alignment_contact_sheet.jpg`에서 먼저
확인한다.

## 행별 판정 절차

1. 이미지에서 두 트랙이 서로 다른 실제 객체인지 확인한다.
2. 두 객체가 같은 충돌 지점 또는 교차 경로를 통과하는지 확인한다. 같은 큰 ROI에
   있다는 사실만으로 확정하지 않는다.
3. 트랙 ID 분절, 중복 상자, 정지 물체 오탐인지 확인한다.
4. PET가 1.5초 이하라면 시간적 점유 순서가 타당한지 확인한다.
5. 정지 이미지로 판단할 수 없으면 `needs_clip_review`로 표시한다.
6. TTC-only 후보는 필름스트립에서 실제 접근 관계가 확인되더라도 잠정값으로 기록하고,
   TTC 값만으로 `confirmed` 처리하지 않는다.

## `review_status` 입력값

| 값 | 사용 조건 |
|---|---|
| `confirmed` | 서로 다른 객체가 같은 충돌 경로를 순차 점유했고 PET 근거가 타당함 |
| `needs_clip_review` | 정지 이미지로 시간 순서나 트랙 연속성을 판단할 수 없음 |
| `rejected_same_object_fragment` | 한 객체가 두 트랙 ID로 분절 또는 중복 검출됨 |
| `rejected_spatial_separation` | 같은 ROI에 있지만 실제 이동 경로가 충분히 떨어져 있음 |
| `rejected_tracking_error` | ID 전환, 잘못된 상자 또는 기타 추적 오류 |
| `rejected_ttc_only` | PET 근거가 없고 영상 평면 TTC만 짧게 계산됨 |
| `uncertain` | 필름스트립 이후에도 가림 또는 화질 문제로 판단 불가 |

`review_notes`에는 짧은 근거를 남긴다. 예: `same black vehicle split across tracks`,
`pedestrian cleared before vehicle arrival`, `distinct vehicles crossed same point`.

## 2차 필름스트립 검토

1차 표에서 `needs_clip_review`인 행만 영상별 `review_results.csv`로 분리한다. 기존
`scripts/export_event_filmstrips.py`를 사용해 사건 시각 전후 2초의 5프레임
필름스트립을 만든다. 필름스트립 판정 후 `confirmed`, `rejected_*`, `uncertain` 중
하나로 최종 상태를 바꾼다.

최종 보고에서는 다음을 함께 기록한다.

- 검토한 후보 수와 확정·기각·불확실 건수
- 기각 사유별 건수
- 영상별·ROI별 확정 사건 수
- PET 분포
- TTC가 영상 평면 근사라는 제한
- 기존 ROI와 homography를 사용했다는 정합 한계
