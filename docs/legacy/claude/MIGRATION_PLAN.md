# 기존 코드/산출물 처리 방침 (페이즈 0-4)

작성일 2026-08-10 | 근거 문서 `docs/무신호횡단보도_구현사양서_v01.md` 부록,
`docs/무신호횡단보도_작업지시서_ClaudeCode_v01.md` 페이즈 0

**아직 코드는 고치지 않았다.** 이 문서는 분류 제안이며, 사용자 확인 후 실제 작업(페이즈 1
이후)에 반영한다. 특히 "확인 필요" 항목은 반드시 사용자 판단을 받고 진행한다.

---

## 0. 부록 원문 (구현사양서 §부록, 그대로 인용 — 명시적 지정)

| 기존 자산 | 처리 |
|---|---|
| `27_make_interim_outputs.py`의 `min_vehicle_distance()` | **폐기.** S_m으로 대체 |
| `31_verify_flicker_self_collision.py` | **유지·승격.** T-1 자동 진단에 편입 |
| `32_validate_crosswalk_groundtruth.py` | **재작성.** 집계 단위가 "상충 판정"→"상호작용 인벤토리" |
| `33_make_groundtruth_survey_template.py` | **재작성.** §7.2 서식으로 |
| PET 상충 검출 로직 | **보조로 강등, 유지** |
| `jaywalkers.csv`의 `vehicle_nearby` | **폐기.** JDI로 대체 |
| `risk_table_by_roi.csv` | **재정의** |
| 교차각 필터(40°) | **제거** |
| 회전부 ROI 10개 | **유지.** `TURN`으로 등록, PDI 집계에서만 제외 |

아래 표는 이 9개 항목을 골격으로, 나머지 파일들을 구현사양서 §0(역할 분담)·§4(상호작용
산출)·§9(검증)의 서술로부터 **추론**해 확장한 것이다. "근거" 열이 "명시"인 행은 위 표
원문 그대로이고, "추론"인 행은 내 판단이니 틀렸으면 정정 바란다.

---

## 1. `src/` 스크립트 분류

### 1-A. v0.3와 무관하게 이미 legacy (Phase A pilot / Phase B 중간에 대체됨)

이 그룹은 이번 전환과 상관없이 Phase A→B 과정에서 이미 폐기 판정을 받은 것들이다
(CLAUDE.md 서술 근거). v0.3 전환이 이 판정을 바꾸지 않는다.

| 파일 | 근거 |
|---|---|
| `01_yolo11s_bytetrack_to_csv.py` / `01R_*` / `*_1280p.py` / `*_y2.py` | Phase A pilot, `29`로 대체됨 |
| `02_DJI0484_sahi_sample_detect.py` | Windows 경로 하드코딩 pilot, CLAUDE.md가 "패턴 따르지 말 것"으로 명시 |
| `03_DJI0481_sahi_detect.py` | slicing 로직만 `29`에 흡수, 파일 자체는 pilot |
| `04_track_sahi_detections.py` / `_m0615.py` | greedy-IoU 트래커, 파편화 원인으로 지목되어 ByteTrack(`29`)으로 교체됨 |
| `06_compute_pet.py` / `_m0615.py` | PET pilot, `25`로 대체됨 |
| `08_run_step10_pet_pipeline.py` / `09_run_final_pet_pipeline.py` / `11_run_remaining_final_queue.py` / `12_run_step10_m0615_deduped_one.py` | pilot subprocess 오케스트레이션, `run_phase_b_*.sh`로 대체됨 |
| `10_make_combined_pet_outputs.py` / `16_make_combined_step10_pet_outputs.py` / `17_make_ttc_adjusted_risk_outputs.py` / `18_make_roi_normalized_risk_report.py` / `19_make_ped_vehicle_roi_risk_table.py` | `27`이 이미 대부분 흡수 |
| `15_compare_step3_step10_pet_events.py` / `22_quantify_step3_vs_step10.py` | Phase A fps 민감도 분석, 역사적 기록용 |

**제안**: 이 그룹은 삭제하지 말고 그대로 둔다(과거 비교 근거로서의 가치, CLAUDE.md에 이미
그렇게 명시됨). v0.3 관점에서는 "관여 없음"으로 분류.

### 1-B. v0.3 전환으로 새로 처리가 필요한 것

| 파일 | 분류 | 근거 | 비고 |
|---|---|---|---|
| `25_compute_pet_directional.py` | **재작성(부분)** | 명시(교차각 필터 제거) + 명시(PET 보조 강등) | 40° 각도 필터 제거, 출력을 canonical에서 부록/보조 산출물로 격하. 골격(PET 계산 자체)은 유지 |
| `26_validate_interim_vs_groundtruth.py` | **확인 필요** — 잠정 유지(보조) | 추론 | PET이 보조로 남으므로 이 검증도 보조 트랙으로 남을 수 있으나, `32`가 상호작용 인벤토리 기준으로 전면 재작성되면서 검증 주 경로가 아예 바뀜. PET 보조 산출물도 이 스크립트로 계속 검증할지, 아니면 검증 자체를 생략할지 결정 필요 |
| `27_make_interim_outputs.py` | **분해 필요 — 파일 전체가 부록에 명시되지 않음** | `min_vehicle_distance()`만 명시, 나머지는 추론 | 아래 1-B-1 참고. 함수 단위로 쪼개서 각기 다른 신규 모듈로 이관해야 할 것으로 보임 |
| `24_make_split_crosswalk_rois.py` | **폐기** | 추론 | 진입/진출 분할 + 차량방향 자동라벨링 방식 자체가 v0.3 ROI 스키마(CW/CW_ext/WZ, t_m 기반 방향판정)와 양립 불가. 페이즈 3의 신규 디지타이징 도구가 대체 |
| `05_make_default_conflict_zones.py` | **폐기** | 추론 | "PET 검증용 초벌 폴리곤"이 문서 주석에 명시됨. v0.3 ROI(`CW` 등)는 얼룩말무늬 외곽선에 엄격히 맞춰야 해서 이 초벌 폴리곤을 베이스로 쓰기 부적절 |
| `30_filter_min_duration_tracks.py` | **확인 필요** | 추론 | ghost 트랙(≤2점) 제거 로직. v0.3의 T-1(`frag_ratio`)은 "진단"이지 "삭제"가 아니고, §3.1은 짧은 트랙을 지우지 않고 `short_track=True`만 달고 통과시킴. 필터링 자체를 없앨지, 사전 필터로 유지할지 결정 필요 |
| `13_preview_conflict_zones.py` | **재작성** | 추론 | ROI 미리보기 개념 자체는 필요(페이즈 3에서 "오버레이 미리보기 반드시 확인"). 다만 ROI 스키마가 바뀌므로 그리는 대상을 새로 구현해야 함 |
| `14_preview_pet_events.py` | **유지(보조)** | 추론 | PET이 보조 산출물로 남는 한 QA용으로 계속 쓸 수 있음. 우선순위 낮음 |
| `07_make_pet_heatmap.py` | **유지(보조)** | 추론 | 위와 동일 논리 |
| `20_make_pedestrian_trajectory_overlay.py` | **확인 필요** | 추론 | `47_review_assets.py`(오버레이 영상, 원본 해상도·burn-in 등 상세 사양 있음)가 사실상 전면 재작성을 요구. 이 파일을 출발점으로 쓸지, 처음부터 새로 짤지 결정 필요 |
| `21_measure_frame_alignment.py` | **확인 필요** | 추론 | 첫/중간/마지막 프레임만 보는 3점 정합 진단. `39_register_frames.py`(전 프레임 정합)가 방법론적으로 상위호환이라 파이프라인에서는 대체되지만, "정합 전 잔차가 이 정도로 컸다"는 착수 전 근거 자료로 남겨둘 가치는 있음. 폐기할지 진단용으로 남길지 결정 필요 |
| `23_make_track_verification_overlays.py` | **확인 필요** | 추론 | `20`과 동일 논리 — `47_review_assets.py`와 역할이 겹침 |
| `02_count_volume_by_class.py` | **재사용 후보(경로 수정)** | 추론 | 단순 클래스별 통행량 카운트. v0.3 지표 체계(X 계열 등)와 직접 충돌하지 않아 입력 경로만 맞추면 재사용 가능해 보임. 다만 v0.3 지표정의서의 통행량 정의와 완전히 일치하는지는 미확인 |

**1-B-1. `27_make_interim_outputs.py` 함수별 세부 분해 (부록에 없는 부분, 전부 추론)**

| 함수 | 현재 역할 | 제안 |
|---|---|---|
| `min_vehicle_distance()` | 무단횡단자-차량 근접도 | **폐기** (명시) |
| `estimate_h_to_ref()` | 클립 간(DJI_0481 기준) 호모그래피 정합 | **해소(2026-08-13) — 폐기, 기능은 `39_register_frames.py`에 흡수.** 근거: §5 확인 필요 #1 종결 사유 참고 |
| `point_in_polygon()`, `point_to_polygon_dist()`, `nearest_crosswalk_over_path()` | ROI 판정 유틸 | **재사용** — `42_geometry.py`의 `point_in()` 등으로 그대로 이식 가능해 보임 |
| `draw_heatmap()` | 밀도 히트맵 생성 | **유지(보조)** — v0.3 필수 산출물 목록에는 없지만 부가 시각화로 남길 수 있음 |
| `main()`의 roadway mask 자동 생성(차량 궤적 기반) | 도로면 마스크 | **폐기** — v0.3에서는 `RW`를 페이즈 3에서 수동 디지타이징하므로 자동 생성이 불필요해짐 |
| `main()`의 무단횡단자 식별·ROI 집계 | 리포트 집계 | **폐기, `43~45`로 대체** |

### 1-C. 유지·승격 (명시)

| 파일 | 처리 |
|---|---|
| `31_verify_flicker_self_collision.py` | 유지·승격 → T-1 자동 진단에 편입 |

### 1-D. 재작성 (명시)

| 파일 | 처리 |
|---|---|
| `32_validate_crosswalk_groundtruth.py` | 재작성 → §7.3 집계(V-F/V-G) 기준 |
| `33_make_groundtruth_survey_template.py` | 재작성 → §7.2 `review_sheet_{clip}.xlsx` 서식 |

### 1-E. 그대로 재사용 (v0.3 방법론과 무관한 인프라/베이스 파이프라인)

| 파일 | 근거 |
|---|---|
| `29_sahi_bytetrack_pipeline.py` | 탐지+추적 방식(YOLO11+SAHI+ByteTrack) 자체는 바뀌지 않음. 다만 §1.1 데이터 계약(특히 `clip_id`, `t` 컬럼) 형식과 정확히 맞는지는 `40_load_and_validate.py`로 검증 필요 |
| `28_verify_environment.py` | 환경 검증, 방법론과 무관 |
| `_paths.py` | 경로 처리, 방법론과 무관 |
| `pick_points.py` | **재사용 후보(수정)** — 대화형 포인트 피킹 UI 자체는 재사용하되, `rois_v03.json` 스키마(CW/CW_ext/WZ/SL/A5/D20/D30/TURN)에 맞게 출력 구조를 확장해야 함. 처음부터 새로 만들지 이걸 확장할지는 구현 시점에 판단 |
| `run_phase_b_batch_l_mt09.sh` 등 | `29` 실행용이므로 그대로 재사용. 39~48 신규 모듈용 오케스트레이션은 별도 신규 작성 필요 |

---

## 2. `calib/` (ROI/캘리브레이션 데이터)

| 자산 | 분류 | 비고 |
|---|---|---|
| `calib/rois_split.json`의 회전부(로터리) ROI | **유지 → `TURN`으로 마이그레이션** | 명시("회전부 ROI 10개 유지"). **사용자 확인(2026-08-10): 로터리 4개, 횡단보도 3개소가 맞음 — 부록의 "10개"는 표현 오류(횡단보도 분할 6개+로터리 4개=10 전체를 가리킨 것으로 추정). TURN 마이그레이션 대상은 로터리 4개** |
| `calib/rois_split.json`의 횡단보도 진입/진출 분할 ROI | **폐기(재digitize)** | v0.3 `CW`는 "얼룩말무늬 외곽선에 엄격히, 여유폭 금지"가 원칙이라 기존 폴리곤(진입/진출 분할, 여유 있게 잡힌 형태로 추정)을 그대로 못 씀 |
| `calib/alignment_homographies.json` | **해소(2026-08-13) — 폐기(파일은 보존).** `39_register_frames.py` 산출물(`registration/transforms_{clip_id}.npz`)로 대체 | 위 1-B-1의 `estimate_h_to_ref()`와 동일 쟁점. 이 파일을 여전히 직접 참조하는 `25_compute_pet_directional.py`(`load_roadway_checker()`)·`31_verify_flicker_self_collision.py`는 39 산출물로 재배선 필요 — 이 자체는 확인 필요 #1과 별개의 후속 구현 작업 |
| `calib/roadway_mask.png` | **폐기** | `RW`를 수동 디지타이징으로 대체 |

---

## 3. `runs/` 산출물

| 자산 | 분류 | 비고 |
|---|---|---|
| `runs/before_l_mt09/<video>/detections_pixel.csv`, `tracks_pixel.csv` | **재사용 후보(스키마 검증 필요)** | v0.3 §1.1 데이터 계약과 열 이름·의미가 정확히 일치하는지 `40_load_and_validate.py`로 확인 전까지는 "재사용 확정"이 아님 |
| `tracks_pixel_filtered.csv` | 30번과 동일 — **확인 필요** | |
| `pet_directional/*` (25 산출물) | **유지(보조)**, 단 각도필터 제거 후 재산출 필요 | |
| `combined_interim/jaywalkers.csv`의 `vehicle_nearby` | **폐기** (명시) | |
| `combined_interim/jaywalk_crosswalk_risk_summary*.csv` | **폐기** | `vehicle_nearby` 기반 산출물이라 함께 폐기 |
| `combined_interim/risk_table_by_roi.csv` | **재정의** (명시) | |
| `combined_interim/groundtruth_crosswalk_validation.csv` | **폐기 → 32 재작성판으로 재산출** | |
| `combined_interim/heatmap_*.jpg` | **유지(보조)** | |
| `combined_interim/jaywalk_trajectories.jpg` | **확인 필요** | 무단횡단 개념 자체는 v0.3에도 `E-2x`로 남아있어 시각화 가치는 있으나, 좌표계가 정합 후(`x_ref`)로 바뀌므로 재생성 필요 |

---

## 4. `survey/` (지상검증 수기 자료)

| 자산 | 분류 | 비고 |
|---|---|---|
| `지상검증_수동조사표_*.xlsx` (8편, PET 상충 판정 기준) | **폐기(신규 서식으로 대체)** | 판정 범주 자체가 "상충 유형/PET/교차각"에서 "A0/A1/B0/B1/B2 + human_side + ped_on_roadway + detection_issue" 등으로 전면 교체됨(§7.2). 기존 xlsx의 원본 관찰(사용자가 영상을 직접 본 판단) 자체는 참고 가치가 있으나, 파일 구조를 그대로 재사용할 수는 없음 |
| `지상검증_수동조사표_v2.xlsx` | 위와 동일 | |

---

## 5. 확인 필요 항목 요약 (사용자 판단 요청)

1. ~~**`27`의 `estimate_h_to_ref()`(클립 간 정합)**~~ — **해소(2026-08-13): 27번은 폐기, 기능은 39번에 흡수.**
   근거: 파라미터 YAML `site.hover_group_count: 1`, `site.shared_scale: true` — 8클립 전부
   **하나의 물리적 호버링 위치·하나의 캘리브레이션**이라는 게 이미 확정값이다. 따라서 "8클립을
   공통 좌표계로 묶는" 문제와 "클립 내 프레임별 호버 표류를 보정하는" 문제는 애초에 별개
   문제가 아니라 같은 문제다 — 호버 그룹이 여럿이었다면(예: 3개 지점을 각기 다른 위치에서
   촬영) 그룹 간을 잇는 별도 단계가 필요했겠지만, 그룹이 1개이므로 기준 프레임 하나에 대해
   전 클립·전 프레임을 정합하면 클립 내 보정과 클립 간 통합이 동시에 끝난다.
   `구현사양서_v01.md` §2.1의 39 설계 자체도 이를 전제한다: 기준 프레임을 "클립 1개 안에서"가
   아니라 8클립 전체 후보 중 하나로 고르고(`clip_id`를 함께 기록하는 이유), 그 위에서
   "프레임별"(전 클립에 걸쳐) 변환을 추정한다. 실제로 현재 페이즈 1 1-1에서 선택된 기준
   프레임(DJI_0481 @ t≈95.0s)도 8클립을 대표하는 단일 기준으로 채택된 것이지 클립별로 8개를
   고른 게 아니다. 또한 27의 `estimate_h_to_ref()`가 산출하는 변환의 적용 방향(`apply_h(h, x,
   y)`로 각 클립의 원본 픽셀 좌표 → DJI_0481 기준를 좌표, `25_compute_pet_directional.py`의
   `load_roadway_checker()`에서 확인)은 39가 만들 `x_ref, y_ref = M^-1 · (x_px, y_px)`와 같은
   방향의 같은 연산이다 — 27은 클립당 첫 프레임 1장 기준으로 이를 성기게(호모그래피, 잔차
   미기록) 했고, 39는 전 프레임에 대해 촘촘하게(similarity, 잔차 V-A2 게이트 검증) 한다는
   정밀도 차이일 뿐, 풀고 있는 문제 자체는 동일하다.
   **잔여 기능 없음.** 다만 `calib/alignment_homographies.json`을 직접 참조하는
   `25_compute_pet_directional.py`·`31_verify_flicker_self_collision.py`는 39 산출물로 재배선이
   필요하다 — 이는 확인 필요 #1의 판단 대상이 아니라 39 구현 완료 후의 별도 후속 작업이다.
   파일(`src/27_make_interim_outputs.py`, `calib/alignment_homographies.json`)은 삭제하지 않고
   보관한다.
2. ~~"회전부 ROI 10개"라는 부록 표현~~ — **해결(2026-08-10)**: 로터리 4개, 횡단보도 3개소가 맞고, 부록의 "10개"는 표현 오류. TURN 마이그레이션 대상은 로터리 4개
3. **`30_filter_min_duration_tracks.py`(ghost 트랙 삭제)** — v0.3 T-1은 삭제가 아니라 진단+플래그 방식인데, 사전 필터링 자체를 없앨지 결정 필요
4. **`21`/`23`/`20`(구 정합진단·오버레이 스크립트)** — 폐기 vs 참고자료로 보존 vs 재작성 출발점, 결정 필요
5. **`26_validate_interim_vs_groundtruth.py`** — PET이 보조로 격하된 후에도 이 검증 스크립트를 계속 돌릴지, PET 보조 산출물은 검증 없이 참고용으로만 둘지 결정 필요

---

## 6. 다음 단계 제안

이 분류안 확인 후, 페이즈 0의 나머지(0-1~0-3: `ffprobe` 메타 추출, `.SRT`/`.LRF` 확인,
`clips.yaml` 작성)로 진행할지 여쭙니다.
