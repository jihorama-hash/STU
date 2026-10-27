---
name: indicators
description: 페이즈 8~9 — P-PDI·JDI·준수도·행태·노출 지표 산출, 민감도 분석(V-E1~E5), 그리고 육안 검토용 오버레이 영상과 판독 서식 생성
disable-model-invocation: true
---

# 페이즈 8~9 — 지표 산출과 검토 자산

근거: 작업지시서 페이즈 8·9, 구현사양서 §6·§7, 지표정의서 v0.3 §4·§5

## 페이즈 8 — 지표 산출 (`45_indicators.py`)

### 8-1. PDI / JDI

```
base = interactions[(event_class=='I') & (~turning)]
NI   = len(base)
P_PDI_pct = base.dpd.sum() / NI * 100

jay  = interactions[(event_class=='E-2x') & (~turning)]
JDI_pct = jay.dpd.sum() / len(jay) * 100
```

**출력 명칭 강제**: 컬럼명 `P_PDI_pct`, 리포트 표기 **"P-PDI (폴란드 계수 기준 참조값)"**. `PDI` 단독 명칭 금지.

**반드시 함께 내는 값** (`reporting.pdi_mandatory_companions`)
- `NI` (분모)
- 유형 구성비 `n_A0/n_A1/n_B0/n_B1/n_B2` 와 비율
- 유형별 평균 DPD
- 안전 상호작용 비율 `(n_A0+n_B0)/NI`

> 원 논문에서 Warsaw–Wrocław PDI 격차(6.05 % vs 3.99 %)의 상당 부분이 DPD 값이 아니라 **안전 상호작용 비율 차이(25.4 % vs 50.4 %)** 에서 왔다. 단일 백분율만 내면 반드시 오독된다.

**P-PDI 값 자체는 리포트에 쓰지 않는다.** `status = REQUIRES_LONGER_OBS` 로 출력하고 참조값으로만 보관한다(30분 단일 세션, 원저자 권고 최소 4일). 분포·유형 구성비는 정상 보고.

**PDI 와 JDI 를 합산하지 않는다.** 나란히 낸다.

### 8-2. 결측 처리

| 상황 | 처리 |
|---|---|
| B2 인데 `a5_valid=False` | 분모 NI 에는 포함, 분자에서 제외. `n_B2_invalid` 별도 보고. 5 % 초과 시 경고 |
| `collision=True` | DPD 미산출, 별도 목록 + 육안 확인 필수 |
| `class_unstable=True` | 산출하되 `review_required`. 결과는 잠정 |
| `turning=True` | PDI·JDI 제외. 준수도·노출에는 포함 |

### 8-3. V·P·X 계열

- **V-1~V-4 준수도**: 분모는 조우 E-1. `dependent_stop` 과 E-2x 제외. v_stop 3값 변동폭 병기
- **V-5 v85, V-6, V-7 감속 프로파일**: **V-7 을 우선 산출한다.** 조우 있음/없음 두 집단의 곡선이 겹치면 "운전자가 보고도 반응하지 않는다"는 뜻이고, 표본이 적어도 시각적으로 강력한 증거가 된다
- **P-1~P-8**: P-9·P-10 은 `NOT_OBSERVABLE` 로 고정 출력
- **X-1~X-5**: 분모는 `observation.total_duration_s`(클립 공백 제외). `observed_hours` 와 관측 시간대 한정 문구 동반

### 8-4. 표본 판정 자동화

```
n < 30  → INSUFFICIENT_SAMPLE   (숫자 보고 금지)
n < 100 → TREND_ONLY            (95 % CI 반드시 병기)
PDI     → REQUIRES_LONGER_OBS   (항상)
```

`status != 'OK'` 인 행의 `value` 는 **반드시 null**. 0 을 쓰지 않는다.

### 8-5. 보행 억제 판정

3개 지점뿐이라 지점 간 백분위가 성립하지 않는다. **`PENDING_VERIFICATION` 으로 출력**하고, 판정 규칙과 구성요소 값(상호작용 밀도·중앙 대기시간·gap 거부 수·횡단 포기 수)만 표로 낸다. 규칙은 구현해 두되 자동 판정을 확정 결과로 쓰지 않는다.

### 8-6. 민감도 분석 (`46_validation.py`)

| 코드 | 대상 | 후보값 |
|---|---|---|
| V-E1 | 보행자 치수 w_p | 0.40 / 0.50 / 0.75 m |
| V-E2 | 평활화 윈도우 | 0.3 / 0.5 / 1.0 s |
| V-E3 | 군집 거리 | 1.5 / 2.0 / 3.0 m |
| V-E4 | v_stop | 0.2 / 0.3 / 0.5 m/s |
| V-E5 | 차폭 W_v | ±0.2 m |

각 변형의 baseline 대비 `NI`, `P_PDI`, `mean_dpd`, `SR` 변화량을 표로. `sensitivity_variant` 로 구분해 저장하고 baseline 과 섞지 않는다.

→ `runs/.../sensitivity_summary.csv`

## 페이즈 9 — 육안 검토 자산 (`47_review_assets.py`)

### 9-1. 오버레이 영상

| 항목 | 사양 |
|---|---|
| 해상도 | **원본 유지.** 다운스케일하면 작은 객체 누락을 사람이 못 본다 |
| 객체 | 박스 + `track_id` + 확정 클래스 + 순간속도 [km/h] |
| 색상 | 차량군/보행자/PM·자전거 구분. `class_unstable` 은 별도 색 + 점선 |
| ROI | CW(실선)·CW_ext(점선)·WZ·SW·RW·A5·SL·TURN 상시 표시 + 범례 |
| 시각 | `clip_id`, 프레임번호, 타임코드 burn-in |
| 상호작용 | t_m ±0.5 s 동안 두 객체를 잇는 선 + `event_id` + 유형 + DPD |
| 출력 | **클립별 개별 파일.** 이어붙이지 않는다(타임코드 혼동) |

### 9-2. 판독 서식

`survey/review_sheet_{clip_id}.xlsx` — 구현사양서 §7.2 컬럼 전체.

**행의 단위가 "알고리즘 후보"가 아니라 "사람이 본 상호작용"이다.** 자동 검출분을 미리 채우되 판독자가 행을 **추가**할 수 있어야 한다(`source = MANUAL_ADDED`).

첫 시트에 판독 지침 5개 항목을 수록한다.

## 완료 조건

지표 요약과 민감도 표를 보고하고, 오버레이·판독 서식을 사용자에게 전달한다. 이어서 사용자의 Stage 2 육안 검토(2~3시간)를 기다린다.
