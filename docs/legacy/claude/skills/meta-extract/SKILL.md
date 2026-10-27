---
name: meta-extract
description: 페이즈 0 — 드론 영상 8클립의 촬영 메타를 자동 추출(ffprobe, DJI SRT)해 clips.yaml 을 만들고, 기존 코드를 폐기/재사용/재작성으로 분류한다
disable-model-invocation: true
---

# 페이즈 0 — 메타 자동 추출

근거: `docs/무신호횡단보도_작업지시서_ClaudeCode_v01.md` 페이즈 0, `docs/무신호횡단보도_구현사양서_v01.md` §1.2

**사용자 입력 없이 전부 자동으로 수행한다.** 지금까지 "확인 필요"로 남아 있던 촬영 메타 대부분을 여기서 얻는다.

## 작업

### 0-1. ffprobe 인벤토리

8개 영상 전부에 대해 추출한다.

```
fps (r_frame_rate 를 유리수로 정확히), 해상도, duration, 코덱,
creation_time (format tags 와 stream tags 양쪽 확인), 파일크기, 비트레이트
```

→ `runs/meta/clips_probe.csv`

**주의**: `avg_frame_rate` 와 `r_frame_rate` 가 다를 수 있다. VFR 이면 그 사실을 명시하고, 프레임별 PTS 를 뽑아 실제 프레임 간격 분포를 보고할 것. **VFR 이면 `t = frame/fps` 가정이 깨진다.**

### 0-2. DJI 텔레메트리 확인

영상과 같은 폴더에서 `.SRT`, `.LRF`, `.DAT` 동반 파일을 찾는다. 있으면 파싱한다.

```
프레임/초 단위: latitude, longitude, rel_alt(상대고도), abs_alt,
                gimbal pitch/yaw/roll, iso/shutter/fnum, focal_len
```

→ `runs/meta/clips_telemetry.csv`

**있으면 큰 소득이다.**
- `rel_alt` 로 스케일 계수를 광학식으로 직접 구할 수 있다
- **위경도 시계열의 변동이 곧 호버 표류량**이다. 위경도를 로컬 미터 좌표(예: UTM 52N)로 변환해 기준점 대비 변위 시계열과 RMSE·P95·max 를 산출하라. 이것으로 **페이즈 1 정합의 필요성을 착수 전에 수치로 확인**할 수 있다
- GPS 절대정확도는 낮다(±1~2 m). 절대값이 아니라 **변동 경향**만 본다

없으면 그 사실을 기록하고 이미지 기반 정합만으로 진행한다(정확도는 오히려 이쪽이 높다).

### 0-3. clips.yaml 생성

```
gap_to_next_s = 다음 클립 creation_time − (현재 creation_time + duration)
observation.total_duration_s = Σ duration_s        # 공백 제외
```

`site.hover_group: A` (8클립 전부 동일 위치, 2026-08-09 확인). 스케일·ROI 는 1벌만 만든다.

creation_time 이 없거나 신뢰할 수 없으면 **추정하지 말고** 그 사실을 보고한다. 이 값 없이는 X-1·X-2·X-4 시간당 환산이 불가하다.

→ `clips.yaml`

### 0-4. 마이그레이션 분류

`src/` 와 `runs/` 를 훑어 구현사양서 부록 "기존 코드 처리 방침" 기준으로 분류한다.

| 분류 | 기준 |
|---|---|
| 폐기 | v0.3 에서 개념 자체가 사라진 것 (`min_vehicle_distance`, `vehicle_nearby`, 교차각 필터) |
| 재사용 | 그대로 쓰거나 승격 (`31_verify_flicker_self_collision.py`) |
| 재작성 | 집계 단위가 바뀐 것 (`32_`, `33_`) |
| 보조 강등 | 유지하되 부록으로 (PET 상충 검출) |

→ `MIGRATION_PLAN.md`

## 완료 조건

**여기서 멈추고 체크포인트 A 를 보고한다.** 코드를 고치거나 ROI 를 그리거나 지표를 산출하지 않는다.

보고 항목:
1. 총 실관측시간 [분], 클립별 duration·fps
2. 클립 간 공백 (각각 + 합계). VFR 여부
3. `.SRT` 유무. 있으면 **GPS 기반 호버 표류량 (RMSE / P95 / max, m)** 과 시계열 그래프
4. 마이그레이션 분류 결과 요약 (건수)
5. clips.yaml 에서 여전히 비어 있는 항목

보고 후 `CLAUDE.md` 의 "현재 상태" 블록을 갱신한다.
