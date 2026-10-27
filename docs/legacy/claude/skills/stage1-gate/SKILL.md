---
name: stage1-gate
description: 페이즈 4~5 — 트랙 건전성 자동 진단(T-1)과 Stage 1 검증 게이트(V-B 위치 RMSE, V-B2 검지율, V-D 속도). 통과 전에는 어떤 지표도 산출하지 않는다
disable-model-invocation: true
---

# 페이즈 4~5 — 트랙 건전성과 Stage 1 게이트

근거: 작업지시서 페이즈 4·5, 지표정의서 v0.3 §7.1, 구현사양서 §9.1

**이 게이트를 통과하기 전에는 지표를 산출하지 않는다.** 강행 시 모든 값 `null` + `status='GATE_FAILED'`.

## 페이즈 4 — T-1 트랙 건전성 (전수 자동, 게이트 아님)

기존 `31_verify_flicker_self_collision.py` 를 여기에 편입한다.

| 지표 | 정의 | 경고 임계 (YAML `validation.stage1_warning`) |
|---|---|---|
| `n_tracks` | 클립별 트랙 수 | — |
| `frag_ratio` | 수명 < 1 s 트랙 비율 | > 0.30 |
| `gap_ratio` | 트랙 내 프레임 공백 비율 | > 0.10 |
| `class_flicker_rate` | `class_unstable=True` 트랙 비율 | > 0.05 |
| `id_switch_candidates` | 시공간적으로 이어지는 서로 다른 track_id 쌍 수 | > 0.1 건/트랙 |
| `overlap_dup_rate` | 동일 위치·시각에 2개 이상 트랙이 겹치는 비율 | > 0.05 |

→ `runs/validation/track_health.csv`

**단편화가 심하면 상호작용이 중복 계수되어 분모 NI 가 부풀려진다.** 경고가 뜨면 그 사실을 명확히 보고하되, 게이트 중단 사유는 아니다. 해당 트랙에 `review_required` 를 단다.

## 페이즈 5 — Stage 1 게이트

### 5-1. 표본 프레임 추출 (자동)

8클립에서 균등 무작위로 `validation.stage1_gate.sample_frames`(100)프레임을 뽑는다. 난수 시드를 고정하고 기록한다.

각 프레임을 원본 해상도 PNG 로 저장하고, 라벨링 서식(프레임당 객체 행)을 만든다.

→ `survey/labeling/frames/`, `survey/labeling/label_sheet.xlsx`

### 5-2. 수동 라벨링 (**사용자 작업**)

100프레임의 **모든 객체**에 대해 클래스와 바운딩박스를 기록한다. 자동 검출 결과를 미리 채워 넣지 말 것 — 편향된다. 빈 서식으로 제공한다.

여기서 멈추고 사용자에게 서식을 전달한다.

### 5-3. 대조 산출 (자동)

```
헝가리안 매칭 (IoU ≥ validation.stage1_gate.match_iou = 0.30)
→ CW 구역 내 객체의 중심좌표 RMSE  (V-B)
→ 검지율 recall = 매칭된 GT / 전체 GT       (V-B2)
→ 오검지율 = 매칭 안 된 검출 / 전체 검출     (V-B2)
```

**CW 구역 내**로 한정하는 이유: 지표가 실제로 쓰이는 영역의 정확도가 중요하고, 화면 주변부는 렌즈 왜곡이 섞인다. 전체 화면 RMSE 도 참고로 함께 낸다.

### 5-4. V-D 속도 정확도

궤적 미분과 독립적으로, 알려진 구간거리(D30→D20 = 10 m 등)를 통과하는 데 걸린 시간으로 평균속도를 구해 대조한다. 표본은 직진 등속 구간을 통과한 차량 20건 이상.

### 5-5. 게이트 판정

```
gate = {
  'V-A' : scale_error         < 0.03,
  'V-A2': registration_resid  < 0.05 m,     # 페이즈 1 결과
  'V-D' : speed_error         < 1.0 km/h,
  'V-B' : rmse_cw             < 0.10 m,
  'V-B2': recall >= 0.95 and fp_rate <= 0.05,
}
```

→ `runs/validation/validation_report.md`

## 불합격 시 — 원인을 정확히 짚어라

| 증상 | 원인 | 되돌아갈 곳 |
|---|---|---|
| V-A2 불합격 | 호버 표류 | **페이즈 1 정합.** 검지 모델을 아무리 바꿔도 통과 못 한다 |
| V-B 불합격 · V-A2 합격 | 검지 박스 정밀도 | 검지 모델·해상도·NMS |
| V-B2 recall 낮음 | 작은 객체 누락 | 입력 해상도, 타일링 추론, conf 임계 |
| V-B2 오검지 높음 | 그림자·노면표시 오검출 | conf 임계, 클래스 필터 |
| `class_flicker_rate` 높음 | 추적기 클래스 진동 | 트랙 단위 클래스 확정으로 흡수(페이즈 6). 게이트 사유 아님 |
| V-D 불합격 · V-B 합격 | 시간축 문제(VFR, fps 오기) | `clips.yaml` fps 재확인 |

## 완료 조건

**체크포인트 D 에서 멈춘다.** 게이트 판정표와 불합격 시 원인 진단을 보고한다.
