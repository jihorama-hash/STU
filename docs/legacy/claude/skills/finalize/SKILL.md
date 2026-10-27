---
name: finalize
description: 페이즈 10~11 — 사용자가 작성한 육안 판독 서식을 집계해 V-F/V-G/V-C 를 산출하고, 최종 산출물을 조립한다
disable-model-invocation: true
---

# 페이즈 10~11 — Stage 2 집계와 최종 조립

근거: 작업지시서 페이즈 10·11, 구현사양서 §7.3·§10, 지표정의서 v0.3 §7.2·§8

## 페이즈 10 — Stage 2 집계 (`46_validation.py`)

사용자가 채운 `survey/review_sheet_{clip}.xlsx` 8개를 읽어 집계한다.

```
V-F 유형 일치율 = mean(auto_type == human_type)        [AUTO 행만]
                  Cohen's κ 병기                        합격 ≥ 0.90
V-G 회수율      = AUTO 행 수 / (AUTO + MANUAL_ADDED 행 수)
                  단, human_type == 'NOT_INTERACTION' 인 AUTO 행은 분자에서 제외
                                                        합격 ≥ 0.90
오검출률        = NOT_INTERACTION 행 수 / AUTO 행 수
V-C 3변수 정확도 = 표본 20건 대조. S_m < 0.15 m, V_m < 1 km/h, PET < 0.2 s
검지 이슈       = detection_issue 유형별 건수 / 총 행 수
```

**추가로 반드시 낼 것**

- `confidence = 애매` 행의 비율. 높으면 판정 기준 자체가 불명확하다는 신호다
- `detection_issue != NONE` 이 특정 클립·특정 횡단보도에 몰려 있는지. 몰려 있으면 페이즈 1 회전 성분 진단과 대조
- 유형 혼동행렬 (auto × human). **어떤 유형끼리 헷갈리는지**가 A/B 판정 부호나 A0/B0 경계 조건 문제를 드러낸다
- 조우 판정의 `excluded_no_intent` **오분류율** (지표정의서 §2.4 요구사항)

→ `runs/validation/stage2_report.md`, `runs/validation/confusion_matrix.csv`

## 페이즈 11 — 최종 조립 (`48_report.py`)

### 산출물

| 파일 | 내용 |
|---|---|
| `interactions.csv` / `interactions_rejected.csv` | 상호작용 원장 |
| `encounters.csv` | 조우·준수도 |
| `track_health.csv` | T-1 |
| `indicators_by_crosswalk.csv` | 횡단보도별 전 지표 + `status` |
| `pdi_summary.csv` | NI·유형구성비·유형별 평균 DPD·P-PDI·JDI |
| `sensitivity_summary.csv` | V-E1~E5 |
| `validation_report.md` / `stage2_report.md` | Stage 1·2 |
| `*.meta.json` | provenance |
| `DISCREPANCY_LOG.md` | 과거 수치와의 불일치 |

`indicators_by_crosswalk.csv` 필수 컬럼:
`cw_id, indicator_id, value, unit, status, ci_low, ci_high, n, evidence_grade, note`

### 리포트 배치 (지표정의서 §8.1)

```
최상단  : L1 결격 항목 (있으면 [즉시 시정 대상])
본문    : V 계열 준수도(표본 충족 시) / P 계열 / X 계열
          D 계열 — 유형 구성비, S_m·V_m·a₅ 분포, DPD 분포
          [보행 억제] 플래그 판정
          JDI 및 P-7
부록    : S 계열(PET·RTTC), 민감도, 검증 결과, 이벤트 로그 요약
판단불가: P-PDI 값, 심각 상충 빈도, EVT — 명시적으로 "판단 불가(사유)" 출력
```

### 최종 병기 4종 — 통합 금지

```
P-PDI [%]  +  [보행 억제] 플래그  +  L1 적법성 결격  +  JDI [%]
```

**가중합 종합점수를 만들지 않는다.** 가중치 근거가 없다(`reporting.forbid_single_composite_score: true`).

### 고정 수록 문구 (`reporting.fixed_disclaimers`)

1. DPD 는 설문 기반 인지위험이며 상해위험이 아니다. DPD 0.5 는 사망확률 50 % 가 아니다.
2. 30분 단일 세션이므로 P-PDI 절대값은 판단 불가. 절차 검증과 상대 비교에만 사용.
3. 연직 시점 촬영으로 보행자 주시·스마트폰 사용(P-9·P-10)은 산출 불가.
4. 회전 차량 상호작용은 PDI 적용 대상이 아니다.

### 마지막 자가점검

`/guard` 를 실행해 절대규칙 위반이 없는지 확인한 뒤 마무리한다.

## 완료 조건

최종 산출물 목록과 `status != 'OK'` 인 지표의 사유별 건수를 보고한다. `CLAUDE.md` 의 "현재 상태"를 갱신한다.
