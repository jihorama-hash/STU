---
name: interactions
description: 페이즈 6~7 — 전처리(평활화·트랙 클래스 확정·군집)와 핵심 모듈인 상호작용 산출(t_m·S_m·V_m·a5·유형분류·DPD)및 조우 E-1 판정
disable-model-invocation: true
---

# 페이즈 6~7 — 전처리와 상호작용 산출

근거: 작업지시서 페이즈 6·7, 구현사양서 §3·§4·§5, 지표정의서 v0.3 §1.2·§1.3·§1.6·§2

**선행 조건**: Stage 1 게이트 통과. 미통과 상태면 산출하지 말고 중단한다.

## 페이즈 6 — 전처리 (`41_preprocess_tracks.py`)

### 6-1. 평활화

```
Savitzky-Golay, polyorder=2, window = smoothing.window_s(0.5 s) × fps  (홀수 보정)
속도 v = |dp/dt|,  가속도는 진행방향 성분 a_tangential = (vx·ax + vy·ay)/max(v, eps)
```

**`|a|` 를 쓰지 말 것.** 곡선 주행의 구심가속도가 섞여 a₅ 가 오염된다.
트랙 길이가 윈도우보다 짧으면 `short_track=True` 표시 후 평활화 없이 통과.

### 6-2. 트랙 단위 클래스 확정

```
cls_final     = argmax_c Σ conf(c)                    # 신뢰도 가중 다수결
flicker_ratio = mean(cls_raw != cls_final)
class_unstable = flicker_ratio > 0.20  OR  보행자군↔차량군 전환 1회 이상
```

**프레임 단위 `cls_raw` 를 직접 쓰지 않는다.** `S_m` 이 차폭에 종속되므로 클래스 진동은 S_m 을 0.7 m 이상 흔든다. `class_unstable` 트랙이 관여한 모든 상호작용에 `review_required=True` 를 전파한다.

### 6-3. 군집(group-pedestrian)

```
조건(전부 만족, grouping.min_duration_s 이상 지속):
  중심간 거리 ≤ grouping.distance_m (2.0)
  진행방향 각도차 ≤ 30°
  속도차 ≤ 0.3 m/s
연결성분을 1개 ped_entity_id 로. 단독 보행자도 ped_entity_id 를 갖는다(n=1)
```

**`grouping.run_both_modes: true` — on/off 두 벌로 전체 파이프라인을 돌려 NI·PDI 차이를 보고한다.** 캠퍼스는 교시 pulse 로 군집 비율이 높아 이 정의가 분모를 크게 바꾼다.

## 페이즈 7 — 상호작용 산출 (`43_interactions.py`)

### 7-1. 단위테스트 먼저 (구현사양서 §11)

**코드보다 테스트를 먼저 쓴다.** 특히 아래는 에러 없이 조용히 틀린다.

| ID | 내용 |
|---|---|
| T-1 | `dpd_a1/b1/b2` 가 지표정의서 부록 A 표와 소수 둘째 자리까지 일치 |
| T-2 | 합성 궤적(직교/평행/미교차)에서 t_m 이 정확/정확/None |
| **T-3** | **A/B 판정 부호.** 차량이 먼저 지나면 `A`, 보행자가 먼저면 `B`. **역전 시 전체 결과가 무의미** |
| T-4 | 횡방향 2.0 m, 차폭 1.8, w_p 0.75 → S_m = 0.725 |
| T-5 | v0=8.33 m/s, t_pr 2.5, a 3.4 → D_stop = 31.05 m |
| T-6~T-10 | 클래스 확정·군집·단위 assert·표본판정·provenance |

### 7-2. t_m 과 3변수

```
d_long(t) = (P(t) − F(t))·e_h − w_p/2        F = 차량 전면 중심 = C_v + (L_v/2)·e_h
t_m       = d_long 이 (+)→(−) 로 바뀌는 첫 시각, 선형보간
S_m       = |(P(t_m) − C_v(t_m))·e_l| − W_v/2 − w_p/2
V_m       = |v_v(t_m)|                        # m/s. km/h 넣으면 조용히 틀린다 → assert
a₅        = min(a_tangential) over A5 구간    # 프레임 < 3 이면 a5_valid=False
```

- **선형보간 필수.** 30 fps·30 km/h 에서 1프레임 = 0.28 m
- t_m 미정의 → 상호작용 아님. `interactions_rejected.csv` 에 `NO_TM` 으로 남긴다
- `S_m ≤ 0` → **충돌**. DPD 산출하지 않고 `review_required=True` + 별도 목록. 실제 사고이거나 측위 오차다

### 7-3. 유형 분류

A/B 판정을 **먼저** 하고, 그 결과로 군집의 기준 보행자(A=최선두, B=최후미)를 정한 뒤 S_m 을 계산한다.

```
A0 차량이 앞을 지남 · 보행자 아직 보도        → DPD = 0 (안전, 분모에 포함)
A1 차량이 앞을 지남 · 보행자 차도 위          → DPD_A1(S_m, V_m)
B0 보행자 차도 진입 전 차량 정지              → DPD = 0 (안전, 분모에 포함)
B1 보행자 횡단 중 차량 진입                   → DPD_B1(S_m, V_m)
B2 보행자 횡단 완료 후 차량 진입              → DPD_B2(a₅)
```

`RW`(CW_ext 밖 차도)에서 성립하면 `E-2x`. NI 에서 제외하고 JDI 로 별도 집계.
`TURN` 발생 또는 heading 변화 > 30° 면 `turning=True`. **PDI·JDI 집계 제외**, 로그에는 남긴다.

### 7-4. DPD

계수는 **반드시 YAML `dpd_coefficients` 에서 로드**한다. K-DPD 재보정 시 YAML 만 교체하면 되도록.

```python
DPD_A1 = 1/(1+exp( 1.196*S_m − 0.075*V_m − 0.923))
DPD_B1 = 1/(1+exp( 0.862*S_m − 0.052*V_m))
DPD_B2 = 1/(1+exp( 0.561*a5  + 2.713))   # 원문 식(4) 계수 전치 오타 수정판
```

`DPD_B2` 코드에 **"원문 식(4)는 계수 2개가 전치되어 있음. 근거: claude/03_PDI_DPD_검증_및_한국형PoC_v01.md §2.3"** 주석을 반드시 남긴다.

### 7-5. 조우 E-1 (`44_encounters.py`)

```
D_stop = v0·t_pr + v0²/(2a)         # v0 = D30~D20 평균속도
t0     = CW 진입 가장자리 상류 D_stop 지점 통과 시각
조우   = t0 시점에 보행개체가 WZ ∪ CW 에 존재
```

- `t_pr` 은 2.5 s(AASHTO)와 **1.5 s 두 값으로 병행 산출**
- 횡단 의사 없음 배제 규칙 적용, `excluded_no_intent` 표시
- 종속 정지(선행 차량 정지에 의한 정지) → `dependent_stop=True`, 준수도 분모에서 제외
- 준수도: STOP / YIELD / NO_YIELD. **v_stop 을 0.2/0.3/0.5 세 값으로 모두 산출**

### 7-6. 출력

`interactions.csv` (구현사양서 §4.7 스키마 전체), `interactions_rejected.csv`(사유 포함), `encounters.csv`
각각 `.meta.json` provenance 동반.

**제외된 후보 쌍을 반드시 남긴다.** 무엇을 버렸는지 보이지 않으면 회수율을 논할 수 없다.

## 완료 조건 — 체크포인트 E

**여기서 이 프로젝트가 무엇을 보고할 수 있는지 결정된다.** 다음을 보고하고 멈춘다.

```
NI (상호작용 총수)            : ____
유형 구성비 A0/A1/B0/B1/B2    : ____   (안전 상호작용 비율 포함)
E-1 조우 건수 (t_pr 2.5 / 1.5): ____   → 30 미만이면 준수율 숫자 보고 금지
E-2x 건수                     : ____
충돌(S_m ≤ 0) 건수            : ____   → 전부 육안 확인 대상
review_required 건수          : ____
제외 후보 쌍과 사유 분포       : ____
group_mode on/off 간 NI 차이  : ____
```

이어서 표본 판정(`sample_status`)을 실행해 **어떤 지표를 숫자로 낼 수 있는지 확정**한다.
