# Phase B 착수 현황 점검 및 실행 계획서

작성일: 2026-07-29
선행 문서: `PHASE_A_FINDINGS.md`(파일럿 검증), `PHASE_B_WORK_PLAN.md`(본분석 전체 설계),
`INTERIM_RISK_REPORT.md`(스크리닝 분석)

본 문서는 "영상 간 위치 검토(정합)를 포함한 준비가 끝났다"는 전제를 실제로 확인하고,
지금 이 상태에서 Phase B 본분석을 착수하기 위해 남은 일을 순서대로 정리한다.
전체 설계·근거는 `PHASE_B_WORK_PLAN.md`를 따르며, 이 문서는 "지금 뭘 해야 하는가"에 집중한다.

---

## 1. 준비 상태 점검 결과

### 1.1 영상 간 위치 검토(정합) — ✅ 확인됨

`calib/alignment_homographies.json`에 8편 전 영상의 homography가 DJI_0481 기준으로
계산되어 있고, 실제 `/home/jiho/STECH/record/`의 8개 파일(DJI_0481~0488, DJI_0483은
`_Cut` 편집본)과 1:1 대응한다.

| 영상 | inliers | 비고 |
|---|---:|---|
| DJI_0481 | 기준(항등행렬) | — |
| DJI_0482 | 602 | |
| DJI_0483_Cut | 650 | |
| DJI_0484 | 595 | |
| DJI_0485 | 532 | |
| DJI_0486 | 690 | |
| DJI_0487 | 525 | |
| DJI_0488 | 482 | |

inlier 수가 모두 480개 이상으로 충분해 지난번 정합 결과는 유효하다고 판단한다.
`calib/roadway_mask.png` 해상도(3840×2160)도 실제 DJI_0481 영상 해상도와 일치함을
오늘 확인했다.

**다만 이것은 "픽셀 기준틀 정합"이지, Phase B 6.3절이 요구하는 GCP 기반 실세계(m) 좌표계는
아니다.** 개선 전 단독 분석(중간 보고서)에는 이 정합만으로 충분하지만, 개선 후 비교
시점에는 GCP가 반드시 필요하다 (1.2절 참고).

### 1.2 그 외 준비 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| 환경(GPU/패키지) | ✅ 완료 | 오늘 `28_verify_environment.py` 전체 PASS, RTX 5060 Ti 실연산 확인 |
| 원본 영상 8편 | ✅ 존재 | `/home/jiho/STECH/record/` — 단, 프로젝트 폴더(`ST_Roundabout`) 밖에 있음 |
| 차도 마스크 | ✅ 존재 | `calib/roadway_mask.png` |
| ROI 정의 | △ 부분 완료 | `calib/rois_split.json` — 횡단보도 진입/진출 분리는 되어 있으나, Phase B가 요구하는 회전부 진입/순환/진출 3분할은 미완성 |
| 지상검증 조사표 | ✅ 존재 | `survey/지상검증_수동조사표_v2.xlsx` |
| GCP 실세계 좌표계 | ❌ 없음 | `calib/gcp_homography.json` 미존재 — 현장 실측 필요 |
| 폴더 구조(4.1절) | ❌ 없음 | `record/before`, `edited/`, `models/`, `runs/` 전부 미생성 |
| 검출 모델(yolo11m 이상) | ❌ 없음 | STECH에 `yolo11n.pt`만 있음 — 사양 미달 |
| SAHI+ByteTrack 결합 코드 | ❌ 없음 | 아래 2.2절 참고 |

---

## 2. 코드 현황 — 무엇이 아직 파일럿 방식인가

### 2.1 확인 방법
`src/*.py` 전체에서 추적기 구현을 확인했다.

### 2.2 결과
- `src/04_track_sahi_detections*.py`: SAHI 검출 결과에 대해 **그리디 IoU 매칭**을 직접
  구현한 커스텀 추적기 사용 중 (`--max-distance`, `--min-iou` 파라미터). Phase A에서
  분절의 주범으로 지목된 바로 그 방식(P5) — **폐기 대상, 아직 안 바뀜.**
- `src/01_yolo11s_bytetrack_to_csv*.py`: Ultralytics 내장 ByteTrack을 쓰지만 SAHI 슬라이싱
  없이 전체 프레임에 대해서만 동작, 대상도 8편이 아닌 다른 영상(DJI_0477 등) 기준의
  실험 코드.
- **결론**: "SAHI 슬라이스 검출 + ByteTrack 추적"이 한 파이프라인으로 결합된 스크립트가
  아직 없다. Phase B 7장 (1)(2)단계의 핵심 작업이며, 실제 분석을 돌리기 전 반드시
  코드로 완성해야 하는 부분이다.

---

## 3. 실행 계획 (우선순위 순)

### A. 지금 즉시 결정할 것 — 데이터 경로

영상이 `/home/jiho/STECH/record`에 있고 프로젝트는 `/home/jiho/ST_Roundabout`이다.
`src/_paths.py`는 기본적으로 `ST_Roundabout/record`를 찾으므로 둘 중 하나를 선택해야 한다.

1. `ROUNDABOUT_BASE=/home/jiho/STECH` 환경변수로 STECH를 분석 루트로 지정
   (단, `src/`, `calib/`, `survey/`는 STECH에 없으므로 이 방식은 그대로 쓸 수 없음 — 실제로는
   `record/`만 심볼릭 링크하거나 `ROUNDABOUT_BASE`를 쓰지 않고 영상만 이관/링크하는 편이 맞다)
2. **권장**: `ST_Roundabout/record/before/`를 만들고 8개 영상을 이동(또는 이관하며 HDD
   원본 백업 유지, 4.2절 규칙)

### B. 이번 주 내 (코드/환경 작업 — 바로 착수 가능)

1. 위 A 결정에 따라 `record/before/`, `edited/`, `models/`, `runs/` 폴더 구조 생성
2. `yolo11m.pt`(필요 시 `11l`/`11x`) 확보
3. GPU 추론 벤치마크 실측 (Work Plan 3.3절) → 처리시간 계획(10장) 보정
4. **SAHI 검출 + ByteTrack 결합 스크립트 작성** — 기존 `03_DJI0481_sahi_detect.py`(검출)과
   ultralytics ByteTrack을 통합, `04_track_sahi_detections.py`(그리디 IoU)를 대체

### C. 병행 — 현장 작업 (코드와 무관, 지금이 마지막 기회)

5. **GCP 4점 이상 현장 실측** → `calib/gcp_homography.json` 생성. 공사가 시작되면 개선 전
   기준 지물이 사라질 수 있으므로 **이 항목이 시간상 가장 급하다.**

### D. 이어서

6. 회전부 ROI를 진입/순환/진출 3분할로 재정의 (`calib/rois_split.json` 확장)
7. 검출 모델 단계적 개선(대형 모델 → VisDrone 가중치 → 조건부 미세조정) — 각 단계
   지상검증 게이트(recall ≥0.85) 통과 확인
8. DJI_0481~0488 8편 15fps 전량 재분석 → 상충 지상검증(정탐률 ≥70%) → 중간(개선 전) 보고서

---

## 4. 결론

"영상 간 위치를 검토해서 준비를 완료했다"는 부분은 **확인됐다** —
`calib/alignment_homographies.json`이 8편 전체에 대해 신뢰할 만한 정합 결과(inlier
480개 이상)를 담고 있고, 실제 STECH의 영상 파일과 정확히 대응한다.

다만 이것으로 "본분석 착수 준비 완료"는 아니다. 남은 것은 코드 작업(ByteTrack 통합,
폴더 구조, 모델 확보)과 현장 작업(GCP 실측) 두 갈래이며, 그중 **GCP 실측은 공사 전
지금이 아니면 다시 할 수 없으므로 최우선으로 일정을 잡을 것을 제안한다.**
