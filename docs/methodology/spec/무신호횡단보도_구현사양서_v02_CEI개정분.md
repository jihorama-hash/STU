# 구현 사양서 v0.2 — CEI 개정분

작성일 2026-08-10 | **본 문서는 `무신호횡단보도_구현사양서_v01.md` 에 추가·대체되는 개정분이다.** v0.1 의 나머지 조항(데이터 계약, 정합, 전처리, 상호작용, provenance)은 그대로 유효하다.

**상위 문서** `무신호횡단보도_지표정의서_v04_CEI개정분.md` | **파라미터** `무신호횡단보도_파라미터_v02.yaml`

---

## 0A. 명명 병기 규약 (2026-08-10 확정) — 구현에 직접 영향

지표정의서 v0.4 §5A.0 의 규약을 코드에 강제한다.

| 위치 | 규칙 |
|---|---|
| `49_cei.py` **모듈 docstring 첫 줄** | `"""PSD(Proportion of Stopping Distance, Allen et al. 1978) 기반 정지가능성 지수. 본 과제 명칭 CEI(Counterfactual Exposure Index). PSD<1 이면 정지 불가."""` |
| **CSV 컬럼명** | `CEI_rate_pct` 유지 (기존 코드 정합) |
| **데이터 사전 `data_dictionary.md`** | `CEI_rate_pct` 행의 설명란에 **"= PSD<1 통과율 (Allen et al. 1978, 임계 1)"** 병기 **의무** |
| **리포트 렌더러** | 표·그림의 지표명은 YAML `reporting.cei_label` 을 읽어 출력한다. **하드코딩 금지** |
| **검증** | `48_report.py` 는 출력물에 `CEI` 문자열이 있고 같은 표/절에 `PSD` 가 없으면 **경고를 발생**시킨다 (`dual_naming_required: true`) |
| **각주 자동 삽입** | `reporting.fixed_disclaimers` 의 CEI 신조어 고지 2건을 모든 리포트에 자동 삽입 |

```python
# 49_cei.py 상단에 고정
NAMING = {
    'canonical': 'PSD<1 통과율 (CEI)',
    'basis': 'Allen, Shin & Cooper (1978), TRR 667:67-74. PSD >= 1 required to stop safely.',
    'coined_by_project': True,   # CEI 는 본 과제 신조어. 기존 문헌 지표명 아님
}
```

---

## 0. 개정 요약

| 구분 | 내용 |
|---|---|
| **신규 모듈** | `49_cei.py` (CEI 산출), `50_ranking.py` (부트스트랩 서열 안정성) |
| **개정 모듈** | `42_geometry.py` (P_v 유틸 추가), `45_indicators.py` (CEI 결과 통합), `48_report.py` (서열 확률표 출력) |
| **실행 순서 변경** | CEI 는 **V-A · V-A2 · V-D** 게이트만 통과하면 산출한다. V-B / V-B2 / T-1 을 기다리지 않는다 |
| **v0.1 §9.1 게이트 규칙 개정** | 게이트를 **지표군별로 분리** (§9.1A) |

---

## 9.1A 개정 — 게이트를 지표군별로 분리한다

v0.1 은 Stage 1 게이트 5개를 모두 통과해야 어떤 지표도 산출하지 못하게 했다. CEI 는 보행자 궤적을 쓰지 않으므로 이 규칙이 과도하다.

```python
GATE_REQUIREMENTS = {
    # 지표군          : 필요한 게이트 항목
    'cei'            : ['V-A', 'V-A2', 'V-D'],
    'compliance'     : ['V-A', 'V-A2', 'V-D'],           # 차량 궤적만 사용
    'exposure'       : ['V-A', 'V-A2', 'V-B2'],          # 계수 지표
    'interaction'    : ['V-A', 'V-A2', 'V-D', 'V-B', 'V-B2'],   # PDI/IP/DPD
    'pedestrian'     : ['V-A', 'V-A2', 'V-B', 'V-B2'],   # P 계열
}

def gate_ok(group, gate_results):
    return all(gate_results[g] for g in GATE_REQUIREMENTS[group])

# 미통과 지표군은 값 null + status='GATE_FAILED', 통과 지표군은 정상 산출
```

**규칙 3(구현사양서 v0.1 §0)을 다음으로 대체한다.**

> 지표를 산출하기 전에 **해당 지표군의 게이트 요건**을 확인한다. 미통과 지표군만 `GATE_FAILED` 로 막고, 통과한 지표군은 산출한다. 어떤 게이트가 어떤 지표를 막았는지 `validation_report.md` 에 명시한다.

---

## 12A. 신규 모듈 `49_cei.py`

### 12A.1 입력

| 입력 | 출처 | 비고 |
|---|---|---|
| 차량 궤적 (정합 좌표 `x_ref`,`y_ref` → 실좌표) | `41_preprocess_tracks.py` | 평활화 후 |
| `P_v` 기준선 | `calib/rois_v03.json` | CEI-G 는 `D30` 을 그대로 사용 |
| `SL` (없으면 `CW` 진입 가장자리) | `calib/rois_v03.json` | 정지 목표선 |
| `cei` 파라미터 블록 | `파라미터_v02.yaml` | t_r, a_d, 민감도 조합 |

### 12A.2 대상 차량 선정 — 분모 정의

```
for each crosswalk cw, each direction dir:
    대상 = 차량군 트랙 중
           ① P_v(dir) 기준선을 통과했고
           ② SL(dir) 또는 CW 진입 가장자리까지 진행했으며
           ③ turning == False
           ④ class_final ∈ vehicle_group          (bicycle/pm 은 mounted 여부로 판정)
    제외 = 회전 차량, 정차 후 재출발(주차 진입출), 트랙 수명 < min_track_s
```

> **핵심: 보행자 유무를 묻지 않는다.** 조우 여부·상호작용 여부와 무관하게 **전 차량이 분모**다. 이것이 CEI 의 전부다. 조우 필터를 넣는 순간 지표의 존재 이유가 사라진다.

**종속 정지 처리**: 선행 차량 때문에 감속·정지한 차량은 `dependent = True` 로 표시하되 **분모에서 제외하지 않는다.** 대신 `dependent` 제외 버전을 병행 산출해 차이를 보고한다 (`cei.exclude_dependent` 파라미터).

### 12A.3 핵심 계산

```python
import math

def v_safe(d, t_r, a_d):
    """정지가능 최대 접근속도 [m/s].  d = v*t_r + v^2/(2*a_d) 의 양의 해."""
    return -a_d * t_r + math.sqrt((a_d * t_r) ** 2 + 2 * a_d * d)

def ssd(v, t_r, a_d):
    """정지필요거리 [m].  v [m/s]."""
    return v * t_r + v * v / (2 * a_d)

def cei_row(track, cw, dir_, prm):
    t_r, a_d = prm['t_r'], prm['a_d']

    t_pv = crossing_time(track, P_v[cw][dir_])      # P_v 기준선 통과 시각 (선형보간)
    if t_pv is None:
        return None, 'NO_PV_CROSSING'

    V   = speed(track, t_pv)                         # [m/s]
    d   = dist_along_path(track, t_pv, SL[cw][dir_]) # 경로 따라 잰 잔여거리 [m]
    if d <= 0:
        return None, 'PV_DOWNSTREAM_OF_SL'

    vs  = v_safe(d, t_r, a_d)
    SER = V / vs
    PSD = d / ssd(V, t_r, a_d)
    cr  = 1.0 - min(1.0, PSD)

    return dict(V_ms=V, V_kmh=V*3.6, d_m=d,
                v_safe_ms=vs, v_safe_kmh=vs*3.6,
                SER=SER, PSD=PSD, cr=cr,
                stoppable=(SER <= 1.0)), None
```

**구현 주의 4가지**

1. **`d` 는 직선거리가 아니라 궤적을 따라 잰 경로거리**다. 접근부가 곡선이면 직선거리가 과소평가된다.
2. **`t_pv` 는 선형보간**으로 구한다. 30 km/h 에서 1프레임(30 fps)은 0.28 m 다.
3. **단위 assert 필수** — `V` 는 m/s. km/h 를 넣으면 SER 이 3.6배가 되어 조용히 틀린다.
4. `SER > 1 ⟺ PSD < 1` 은 수학적 항등식이다. **단위테스트로 고정**한다(T-11).

### 12A.4 CEI-G 와 CEI-S

```python
P_V_MODE = {
    'G': lambda cw, dir_: rois[cw]['D30'][dir_],           # 기하 기준. 오늘 산출
    'S': lambda cw, dir_: rois[cw]['P_v_sight'][dir_],     # 시거 반영. 현장조사 후
}
# 'S' 는 rois 에 P_v_sight 가 없으면 status='REQUIRES_FIELD_SURVEY' 로 스킵
```

### 12A.5 지점 지표 집계

```python
def aggregate(rows, prm):
    n = len(rows)
    return {
        'n_vehicles'   : n,
        'CEI_rate_pct' : 100 * mean(not r['stoppable'] for r in rows),   # C-1
        'SER_50'       : percentile([r['SER'] for r in rows], 50),       # C-2
        'SER_85'       : percentile([r['SER'] for r in rows], 85),
        'v_safe_kmh'   : rows[0]['v_safe_kmh'],   # d 가 지점 상수면 상수      C-3
        'V85_approach' : percentile([r['V_kmh'] for r in rows], 85),     # C-4
        'CEI_mean'     : mean(r['cr'] for r in rows),                    # C-5
        'excess_kmh'   : percentile([r['V_kmh'] for r in rows],85) - rows[0]['v_safe_kmh'],  # C-6
        'ci_low', 'ci_high' : wilson_ci(CEI_rate, n, 0.95),
        'status'       : sample_status(n, kind='cei'),
    }
```

- `CEI_rate` 의 신뢰구간은 **Wilson 구간**을 쓴다 (정규근사는 극단 비율에서 부정확).
- `v_safe` 는 d 가 차량마다 다를 수 있으면(경로 차이) 중앙값과 범위를 함께 보고한다.

### 12A.6 민감도 4조합 (V-E6) — 필수

```python
CEI_VARIANTS = [
    {'id': 'base',       't_r': 1.0, 'a_d': 3.4},
    {'id': 'tr15',       't_r': 1.5, 'a_d': 3.4},
    {'id': 'hard_brake', 't_r': 1.0, 'a_d': 5.0},
    {'id': 'tr15_hard',  't_r': 1.5, 'a_d': 5.0},
]
# 4조합 전부에서 3지점 서열이 유지되는지 확인 → sensitivity_summary.csv 의 rank_stable 컬럼
```

**서열이 조합에 따라 뒤집히면 그 사실 자체를 결과로 보고한다.** 좋아 보이는 조합을 고르지 않는다.

### 12A.7 출력 `cei_vehicles.csv` (1행 = 1차량)

| 컬럼 | 설명 |
|---|---|
| `veh_id` | `{clip_id}_{track_id}` |
| `clip_id`, `cw_id`, `direction` | |
| `veh_class` | 확정 클래스 |
| `variant_id` | base / tr15 / hard_brake / tr15_hard |
| `pv_mode` | G / S |
| `t_pv`, `t_pv_frame` | P_v 통과 시각·프레임 (육안 대조용) |
| `V_ms`, `V_kmh` | P_v 통과 속도 |
| `d_m` | P_v → SL 경로거리 |
| `v_safe_ms`, `v_safe_kmh` | 안전 최대 접근속도 |
| `SER`, `PSD`, `cr` | 속도초과비 / 정지거리비 / 반사실 위험도 |
| `stoppable` | SER ≤ 1 |
| `dependent` | 선행차 기인 감속 |
| `t_r`, `a_d` | 사용한 가정값 (재현성) |
| `reject_reason` | 제외 시 사유 |

**출력 `cei_summary.csv`** — 1행 = (횡단보도 × 방향 × variant × pv_mode). §12A.5 집계값 전부 + `status` + CI.

---

## 12B. 신규 모듈 `50_ranking.py` — 부트스트랩 서열 안정성

```python
def rank_stability(site_rows, metric='CEI_rate', B=10000, seed=20260810):
    """site_rows: {site_id: [차량 행 리스트]}.  지점별 독립 복원추출."""
    rng = np.random.default_rng(seed)
    counter = Counter()
    for _ in range(B):
        vals = {s: statistic(rng.choice(rows, size=len(rows), replace=True), metric)
                for s, rows in site_rows.items()}
        order = tuple(sorted(vals, key=vals.get, reverse=True))   # 위험 높은 순
        counter[order] += 1
    return {order: cnt / B for order, cnt in counter.most_common()}
```

- **`seed` 를 YAML 에 고정**한다. 실행마다 결과가 달라지면 provenance 가 무의미하다.
- 지점별 **독립** 복원추출이다. 전체를 섞지 않는다.
- 동일 절차를 `IP_risky_share`(유형 구성비), `SER_85` 에도 적용해 **3개 지표의 서열이 일치하는지** 확인한다. 일치하면 결론이 강해지고, 어긋나면 그 사실을 보고한다.

**출력 `ranking_stability.csv`**: `metric, variant_id, order, probability, n_bootstrap, seed`

---

## 12C. 개정 모듈

### `42_geometry.py` 추가

```python
def crossing_time(track, line):
    """궤적이 기준선을 통과하는 시각. 부호변화 지점 선형보간. 미통과면 None."""

def dist_along_path(track, t_from, line_to):
    """t_from 부터 line_to 통과 시각까지 궤적 호길이 적분 [m]."""
```

### `45_indicators.py` 개정

- `cei_summary.csv` 를 `indicators_by_crosswalk.csv` 에 병합
- 신규 지표 ID `C-1` ~ `C-6` 등록
- **§5A.6 교차표 산출**: `CEI_rate` 와 `SR`(V-1 완전정지율)을 각각 3지점 중앙값 기준으로 이분해 2×2 배치 → `countermeasure_matrix.csv`
  - `SR` 이 `INSUFFICIENT_SAMPLE` 이면 교차표는 `PENDING_VERIFICATION` 으로 출력하되, **CEI 축 값은 그대로 낸다**

### `48_report.py` 개정

최종 보고 세트를 다음으로 교체한다 (지표정의서 v0.4 §8.4).

```
[1] 서열 확률표        ranking_stability.csv
[2] 지표값 + CI        CEI_rate, SER_85, v_safe, V85_approach, excess_kmh
[3] 민감도 4조합       서열 유지 여부
[4] 대책 방향 교차표   countermeasure_matrix.csv
[5] 억제 패널          SP-1~SP-6
[6] L1 적법성 결격
[참조] P-PDI, IP 구성비, DPD 분포  ← 값 해석 금지, 분포만
```

---

## 11A. 단위테스트 추가

| ID | 대상 | 내용 |
|---|---|---|
| **T-11** | `v_safe` / `ssd` 항등식 | 임의 v, d 에 대해 `SER > 1 ⟺ PSD < 1` 이 항상 성립 |
| **T-12** | `v_safe` 값 | d=30, t_r=1.0, a=3.4 → 11.28 m/s (40.6 km/h). 지표정의서 표 5A-1 과 일치 |
| **T-13** | `ssd` 값 | v=8.33 m/s(30 km/h), t_r=1.0, a=3.4 → 18.5 m |
| **T-14** | 단위 | `cei_row` 에 km/h 를 넣으면 assert 실패 |
| **T-15** | `crossing_time` | 합성 궤적에서 기준선 통과 시각이 프레임 사이 값으로 보간되는가 |
| **T-16** | `dist_along_path` | 곡선 경로에서 직선거리보다 큰 값이 나오는가 |
| **T-17** | `rank_stability` | 동일 seed 로 두 번 실행 시 결과 동일 (재현성) |

---

## 부록. 기존 코드 재사용

| 기존 자산 | CEI 에서의 처리 |
|---|---|
| `44_encounters.py` 의 `d_stop(v0)` | **그대로 재사용.** `ssd()` 와 동일 식. 단 **파라미터가 다르다** — 조우는 `encounter.*`(t_r 2.5), CEI 는 `cei.*`(t_r 1.0). **같은 함수에 다른 블록을 넣는다.** 하드코딩 절대 금지 |
| D30 / SL ROI | **그대로 재사용.** CEI-G 는 신규 디지타이징 불필요 |
| 속도 산출 로직 | 그대로 재사용 |
| 보행자 궤적·군집·클래스 확정 | **CEI 에서는 사용하지 않는다** |
