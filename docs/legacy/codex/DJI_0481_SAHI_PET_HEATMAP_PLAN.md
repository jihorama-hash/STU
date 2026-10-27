# DJI_0481.MP4 SAHI 객체인식/추적 및 PET Heatmap 작성 계획서

## 1. 목적

`record/DJI_0481.MP4` 드론 영상을 대상으로 SAHI 방식의 분할 추론을 적용해 보행자 및 차량류 객체를 검출하고, 프레임 간 추적 ID를 부여한 뒤, 보행자-차량 상충 지점의 PET(Post Encroachment Time)를 산정한다. 최종 산출물은 객체 궤적 CSV, PET 이벤트 CSV, PET 공간 Heatmap 이미지 및 검증용 시각화 영상으로 한다.

## 2. 기존 코드 참고 사항

현재 작업 폴더에는 다음 코드가 존재한다.

- `src/01_yolo11s_bytetrack_to_csv_1280p.py`
  - YOLO11 + ByteTrack 기반 전체 영상 추적
  - 산출물: `runs/*_tracks_pixel.csv`
  - 주요 컬럼: `frame_id`, `time_sec`, `track_id`, `class_name`, `confidence`, `x1`, `y1`, `x2`, `y2`, `cx`, `cy`, `anchor_x`, `anchor_y`, `foot_x`, `foot_y`
- `src/01R_yolo11s_bytetrack_to_csv.py`
  - bbox 하단 중앙점을 `foot_x`, `foot_y`로 저장하는 기존 추적 코드
- `src/02_DJI0484_sahi_sample_detect.py`
  - SAHI 방식의 sliced YOLO 검출 샘플 코드
  - 현재 기본 경로가 `C:\Home\Roundabout` 및 `DJI_0484.MP4` 기준이므로 `D:\Roundabout` 및 `DJI_0481.MP4` 기준으로 수정 필요
  - 현재는 검출 CSV 생성까지 가능하나 추적 ID 부여는 없음
- `src/02_count_volume_by_class.py`
  - 추적 CSV에서 class별 교통량 및 track summary 산정

## 3. 분석 대상 및 경로

- 기준 폴더: `D:\Roundabout`
- 입력 영상: `D:\Roundabout\record\DJI_0481.MP4`
- 모델 후보:
  - 1차: `D:\Roundabout\yolo11m.pt`
  - 속도 우선 테스트: `D:\Roundabout\yolo11s.pt`
- 권장 출력 폴더:
  - `runs/DJI_0481_sahi/`

## 4. 전체 처리 흐름

1. 영상 메타데이터 확인
   - FPS, 해상도, 전체 프레임 수, 영상 길이 확인
   - SAHI slice 크기 및 overlap 결정

2. SAHI 샘플 검출
   - `DJI_0481.MP4`에서 균등 간격 샘플 프레임 10-20장을 선택
   - `slice_width=1024`, `slice_height=1024`, `overlap=0.20`을 기본값으로 적용
   - 작은 보행자 검출이 부족하면 `conf=0.15-0.25`, `imgsz=1024-1280` 범위에서 비교
   - 산출물:
     - `runs/DJI_0481_sahi_sample/detections_pixel_sample.csv`
     - `runs/DJI_0481_sahi_sample/samples/frame_*.jpg`

3. SAHI 전체 프레임 검출
   - 샘플 결과가 양호하면 전체 프레임에 SAHI 검출 적용
   - class는 기존 코드와 동일하게 `person`, `bicycle`, `car`, `motorcycle`, `bus`, `truck` 사용
   - slice별 중복 박스는 classwise NMS로 병합
   - 산출물:
     - `runs/DJI_0481_sahi/detections_pixel.csv`
     - `runs/DJI_0481_sahi/summary_by_frame_class.csv`
     - 필요 시 `runs/DJI_0481_sahi/DJI_0481_sahi_annotated.mp4`

4. 검출 결과 기반 추적 ID 부여
   - 기존 YOLO `model.track()`은 원본 프레임 단위 추론에는 적합하지만, SAHI로 병합된 검출 결과에는 직접 적용하기 어렵다.
   - 따라서 SAHI 검출 CSV를 입력으로 받는 별도 tracker 단계를 둔다.
   - 권장 방식:
     - 1차: `supervision.ByteTrack` 또는 ByteTrack 구현체를 이용해 frame별 `xyxy`, `confidence`, `class_id`를 전달
     - 대안: IoU + 거리 기반 간단 추적기를 사용하되, ID switch가 많으면 ByteTrack으로 교체
   - 추적 대표점은 드론 고각 영상 특성을 고려해 다음을 모두 저장한다.
     - `cx`, `cy`: bbox 중심
     - `foot_x`, `foot_y`: bbox 하단 중앙점
     - `anchor_x`, `anchor_y`: PET/Heatmap에 사용할 대표점
   - 산출물:
     - `runs/DJI_0481_sahi/tracks_pixel.csv`
     - `runs/DJI_0481_sahi/tracks_annotated.mp4`

5. 좌표 보정 및 분석 영역 설정
   - PET는 시간 차이뿐 아니라 동일한 상충 공간을 통과했는지 판단해야 하므로 분석 좌표계를 정해야 한다.
   - 최소 구현:
     - 픽셀 좌표 기준으로 횡단보도, 회전부, 접근로 등 상충 ROI polygon을 수동 지정
     - 각 track의 `anchor_x`, `anchor_y`가 ROI 내부에 들어간 시각을 산정
   - 권장 구현:
     - 영상 내 기준점 4개 이상을 이용해 homography를 계산
     - `anchor_x`, `anchor_y`를 지면 좌표 `world_x`, `world_y`로 변환
     - 거리 기반 PET 및 Heatmap grid를 실세계 단위로 산정

6. PET 산정
   - PET 정의:
     - 동일 상충영역 또는 동일 상충 셀을 먼저 통과한 객체가 영역을 벗어난 시각과, 뒤따르는 상충 객체가 영역에 진입한 시각의 차이
     - `PET = next_entry_time - previous_exit_time`
   - 기본 상충쌍:
     - pedestrian vs vehicle
     - 필요 시 bicycle/motorcycle을 vehicle로 포함
   - 이벤트 산정 절차:
     - track별 ROI/cell 진입 시각과 이탈 시각 계산
     - class_kind를 `pedestrian`, `vehicle`로 구분
     - 같은 ROI/cell에서 서로 다른 class_kind가 순차 통과한 경우 PET 계산
     - `PET >= 0`이고 분석 임계값 이내인 이벤트만 저장
   - 권장 임계값:
     - near conflict: `PET <= 1.5s`
     - caution: `1.5s < PET <= 3.0s`
     - normal: `PET > 3.0s`
   - 산출물:
     - `runs/DJI_0481_sahi/pet_events.csv`
     - 주요 컬럼: `event_id`, `roi_id`, `first_track_id`, `first_class_kind`, `first_exit_sec`, `second_track_id`, `second_class_kind`, `second_entry_sec`, `pet_sec`, `event_x`, `event_y`, `severity`

7. PET Heatmap 생성
   - `pet_events.csv`의 `event_x`, `event_y`, `pet_sec`를 이용해 공간 Heatmap 생성
   - Heatmap 값 정의 후보:
     - 위험도 중심: `risk = max(0, PET_THRESHOLD - pet_sec)`
     - 빈도 중심: PET 이벤트 count
     - 평균 PET 중심: cell별 평균 PET
   - 권장 최종 지도:
     - 원본 배경 프레임 위에 `PET <= 3.0s` 이벤트의 위험도 Heatmap overlay
     - 색상은 낮은 PET일수록 강한 빨강으로 표시
   - 산출물:
     - `runs/DJI_0481_sahi/pet_heatmap.png`
     - `runs/DJI_0481_sahi/pet_heatmap_cells.csv`
     - 선택 산출물: `runs/DJI_0481_sahi/pet_events_overlay.mp4`

## 5. 구현 파일 구성안

기존 코드를 보존하고 `DJI_0481` 분석용으로 다음 파일을 추가하는 것을 권장한다.

- `src/03_DJI0481_sahi_detect.py`
  - `02_DJI0484_sahi_sample_detect.py`를 기반으로 경로와 실행 옵션 정리
  - 샘플/전체 프레임 검출 CSV 생성
- `src/04_track_sahi_detections.py`
  - `detections_pixel.csv` 입력
  - ByteTrack 또는 IoU 기반 추적으로 `tracks_pixel.csv` 생성
- `src/05_define_conflict_zones.py`
  - ROI polygon 및 선택적 homography 설정 파일 생성
  - 산출물: `runs/DJI_0481_sahi/conflict_zones.json`
- `src/06_compute_pet.py`
  - `tracks_pixel.csv`와 `conflict_zones.json` 입력
  - `pet_events.csv` 생성
- `src/07_make_pet_heatmap.py`
  - `pet_events.csv`와 배경 프레임 입력
  - Heatmap 이미지 및 cell summary 생성

## 6. 실행 순서 예시

```powershell
python src\03_DJI0481_sahi_detect.py --samples 12
python src\03_DJI0481_sahi_detect.py --all-frames --save-video
python src\04_track_sahi_detections.py --input runs\DJI_0481_sahi\detections_pixel.csv --output runs\DJI_0481_sahi\tracks_pixel.csv
python src\05_define_conflict_zones.py --video record\DJI_0481.MP4 --output runs\DJI_0481_sahi\conflict_zones.json
python src\06_compute_pet.py --tracks runs\DJI_0481_sahi\tracks_pixel.csv --zones runs\DJI_0481_sahi\conflict_zones.json --output runs\DJI_0481_sahi\pet_events.csv
python src\07_make_pet_heatmap.py --events runs\DJI_0481_sahi\pet_events.csv --video record\DJI_0481.MP4 --output runs\DJI_0481_sahi\pet_heatmap.png
```

## 7. 품질 검증 기준

- 샘플 프레임 검증
  - 보행자 누락이 과도하지 않은지
  - 차량 박스가 slice 경계에서 중복/절단되지 않는지
  - 원거리 소형 객체 검출률이 기존 일반 YOLO 추론보다 개선되는지

- 추적 검증
  - 동일 객체의 ID가 길게 유지되는지
  - 교차부에서 ID switch가 빈번하지 않은지
  - 정지/저속 객체가 중복 count되지 않는지

- PET 검증
  - ROI 진입/이탈 시간이 영상에서 육안 확인되는 시점과 맞는지
  - 음수 PET 또는 비현실적으로 큰 PET가 필터링되는지
  - pedestrian-vehicle 외 같은 종류 간 이벤트가 섞이지 않는지

- Heatmap 검증
  - 위험 이벤트 위치가 실제 상충 위치와 겹치는지
  - 낮은 PET 이벤트가 높은 위험도로 표시되는지
  - 배경 영상과 좌표 정렬이 어긋나지 않는지

## 8. 주요 리스크 및 대응

- `DJI_0481.MP4`가 고해상도/장시간 영상이면 전체 SAHI 추론 시간이 길다.
  - 대응: 샘플 프레임으로 파라미터 확정 후 전체 실행, 필요 시 frame stride 옵션 추가
- SAHI 검출 결과에는 tracking ID가 없다.
  - 대응: SAHI 검출 CSV 후처리 tracker를 별도 구현
- PET는 ROI 정의에 민감하다.
  - 대응: 처음에는 픽셀 기반 ROI로 빠르게 산정하고, 필요 시 homography 기반 실세계 좌표로 고도화
- 드론 영상에서 bbox 하단 중앙점이 실제 지면 접점과 다를 수 있다.
  - 대응: `bbox_center`, `foot_point`, `custom_anchor`를 비교해 PET 안정성이 높은 대표점 선택

## 9. 1차 완료 산출물

1차 구현 완료 기준은 다음과 같다.

- `DJI_0481.MP4` 샘플 SAHI 검출 이미지 12장
- 전체 프레임 SAHI 검출 CSV
- SAHI 검출 기반 track CSV
- 수동 ROI 기반 PET 이벤트 CSV
- 원본 프레임 overlay PET Heatmap PNG
- 주요 파라미터와 검증 결과 요약 메모

## 10. SAHI 샘플 확인 결과

2026-06-12에 `DJI_0481.MP4` 대상으로 4개 샘플 프레임을 우선 확인했다.

- 영상 메타데이터:
  - 해상도: `3840x2160`
  - FPS: `29.970`
  - 전체 프레임: `8716`
  - 영상 길이: `290.82초`
- SAHI 설정:
  - `slice_width=1024`
  - `slice_height=1024`
  - `overlap=0.20`
  - `imgsz=1024`
  - frame당 slice 수: `15`
- `conf=0.20` 결과:
  - frame 0: car 1, person 4
  - frame 2905: car 1, person 2
  - frame 5810: car 2, person 2
  - frame 8715: car 3, person 4
  - 처리 시간: 4프레임 약 54초
- `conf=0.15` 결과:
  - frame 0: car 1, person 4
  - frame 2905: car 1, person 3
  - frame 5810: car 2, person 3
  - frame 8715: car 3, person 4
  - 처리 시간: 4프레임 약 52초

`conf=0.15`에서 추가된 보행자 검출은 육안상 실제 보행자에 가까워 PET 분석에는 `conf=0.15`를 우선 적용한다. 현재 속도 기준 전체 8716프레임을 모두 SAHI 처리하면 약 32-37시간이 예상된다. 따라서 1차 PET 검증은 `--frame-step 3`으로 약 10fps 처리하거나, 더 빠른 예비 분석은 `--frame-step 6`으로 약 5fps 처리하는 방식을 권장한다.

현재 추가된 실행 스크립트:

```powershell
python src\03_DJI0481_sahi_detect.py --samples 4 --conf 0.15 --slice-width 1024 --slice-height 1024 --overlap 0.20 --imgsz 1024
python src\03_DJI0481_sahi_detect.py --all-frames --frame-step 3 --conf 0.15 --slice-width 1024 --slice-height 1024 --overlap 0.20 --imgsz 1024
```

## 11. step10 예비 PET 파이프라인 실행 상태

2026-06-12 오전에 `--frame-step 10` 조건의 SAHI 예비 검출을 백그라운드로 시작했다.

- 실행 조건:
  - `--all-frames`
  - `--frame-step 10`
  - `--conf 0.15`
  - `--slice-width 1024`
  - `--slice-height 1024`
  - `--overlap 0.20`
  - `--imgsz 1024`
  - `--no-save-images`
- 출력 폴더:
  - `runs/DJI_0481_sahi_step10/`
- 로그:
  - `runs/DJI_0481_sahi_step10/sahi_step10_stdout.log`
  - `runs/DJI_0481_sahi_step10/sahi_step10_stderr.log`
- 예상 SAHI 처리량:
  - 전체 8716프레임 중 약 872프레임 처리
  - 샘플 속도 기준 약 3-3.5시간

SAHI 검출 종료 후 자동으로 다음 후처리가 실행되도록 대기 프로세스를 시작했다.

```powershell
python src\08_run_step10_pet_pipeline.py --wait --poll-seconds 60 --max-wait-hours 8
```

후처리 실행 순서:

1. `src/05_make_default_conflict_zones.py`
2. `src/04_track_sahi_detections.py`
3. `src/06_compute_pet.py`
4. `src/07_make_pet_heatmap.py`

후처리 로그:

- `runs/DJI_0481_sahi_step10/pet_pipeline_stdout.log`
- `runs/DJI_0481_sahi_step10/pet_pipeline_stderr.log`

예상 최종 산출물:

- `runs/DJI_0481_sahi_step10/detections_pixel.csv`
- `runs/DJI_0481_sahi_step10/tracks_pixel.csv`
- `runs/DJI_0481_sahi_step10/conflict_zones.json`
- `runs/DJI_0481_sahi_step10/pet_events.csv`
- `runs/DJI_0481_sahi_step10/pet_risk_by_roi.csv`
- `runs/DJI_0481_sahi_step10/pet_heatmap.png`
- `runs/DJI_0481_sahi_step10/pet_heatmap_cells.csv`

## 12. PET 위험도 산정 로직 보완

PET 대상 상충쌍을 다음과 같이 확장했다.

- `vehicle_vehicle`
  - car, bus, truck, motorcycle, bicycle 간 상충
- `pedestrian_vehicle`
  - person과 vehicle 계열 간 상충

제외 대상:

- pedestrian-pedestrian
- class_kind가 `other`인 객체
- 동일 track_id 간 비교

PET 이벤트는 같은 ROI 안에서 먼저 통과한 객체의 이탈 시각과 뒤따르는 객체의 진입 시각 차이로 산정한다.

```text
PET = second_entry_sec - first_exit_sec
```

기본 유효 범위:

- `0 <= PET <= 5.0초`

이벤트별 위험점수는 다음 구조로 계산한다.

```text
pet_score = (max_pet_sec - pet_sec) / max_pet_sec * 100
risk_score = pet_score * conflict_weight
```

기본 conflict weight:

- `vehicle_vehicle`: `1.0`
- `pedestrian_vehicle`: `1.5`

최종 `risk_score`는 `0-100` 범위로 clip한다. 따라서 PET가 짧고, 차량-보행자 상충일수록 높은 점수를 갖는다. 대상지가 학교, Campus, Complex 등 보행자 중심 공간이므로 차량-보행자 상충 가중치를 `1.5`로 적용한다.

PET event는 다음 두 범위로 구분한다.

- `final`: `PET <= 3.0초`
- `reference`: `3.0초 < PET <= 5.0초`

`reference` event는 CSV에 보존해 참고 분석에 사용하지만, ROI별 최종 위험도와 기본 Heatmap에는 반영하지 않는다.

위험등급:

- `high`: `risk_score >= 80`
- `medium`: `50 <= risk_score < 80`
- `low`: `0 < risk_score < 50`
- `none`: `risk_score = 0`

추가 산출물:

- `pet_events.csv`
  - 이벤트별 `conflict_type`, `pet_score`, `conflict_weight`, `risk_score`, `risk_level` 포함
- `pet_risk_by_roi.csv`
  - ROI별 이벤트 수, 차량-차량 이벤트 수, 차량-보행자 이벤트 수, 위험점수 합계/최대/평균, 평균 PET, 최소 PET, 최종 위험등급 포함
- `pet_heatmap_cells.csv`
  - cell별 이벤트 수, 상충 유형별 개수, 위험점수 합계/최대/평균, 평균 PET 포함

Heatmap은 단순 PET 차이값이 아니라 `risk_score`를 누적해 생성한다.

최종 본 분석 기준:

- 시간 샘플링: `--frame-step 3`
- 최종 event: `PET <= 3.0초`
- 참고 event: `3.0초 < PET <= 5.0초`
- 포함 상충: `vehicle_vehicle`, `pedestrian_vehicle`
- 보행자 상충 가중치: `1.5`
- 7개 CCTV 영상의 ROI/cell별 `risk_score`를 분석시간으로 정규화한 뒤 평균해 대상지 최종 위험도 산정
- annotated video는 H/W 준비 후 상충 집중 5분 내외 구간만 산출

## 13. DJI_0482.MP4 분석 실행 상태

같은 장소의 다른 시간대 영상으로 `record/DJI_0482.MP4`를 확인했다.

- 해상도: `3840x2160`
- FPS: `29.970`
- 전체 프레임: `8721`
- 영상 길이: `290.99초`

2026-06-12 오후에 `--frame-step 10` 조건으로 예비 분석을 백그라운드 실행했다.

- SAHI 검출 프로세스: PID `26428`
- 후처리 대기 프로세스: PID `26836`
- 출력 폴더:
  - `runs/DJI_0482_sahi_step10/`

실행 조건:

```powershell
python src\03_DJI0481_sahi_detect.py --video record\DJI_0482.MP4 --all-frames --frame-step 10 --conf 0.15 --slice-width 1024 --slice-height 1024 --overlap 0.20 --imgsz 1024 --no-save-images --output-dir runs\DJI_0482_sahi_step10
```

자동 후처리:

```powershell
python src\08_run_step10_pet_pipeline.py --wait --run-dir runs\DJI_0482_sahi_step10 --video record\DJI_0482.MP4 --poll-seconds 60 --max-wait-hours 8
```
