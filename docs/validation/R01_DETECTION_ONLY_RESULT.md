# R01 객체 검출 단독 평가 결과 — 진행 중

### 현재 상태

- `_01` 출력은 `detections.csv.meta.json`과 `tile_diagnostics.csv.meta.json`이 없다. 파일은 보존하고 `meta 없음, 사용 안 함`으로 표시했으며 지표 산출에 사용하지 않는다.
- 설치된 `supervision` 버전은 **0.29.1**이다. 설치 소스를 확인했으며, ByteTrack의 신규 트랙 임계값(`track_activation_threshold + 0.1`), 저점수 연결 구간, IoU 0.5 연결 후 원본 검출 박스를 반환하는 동작을 확인했다.
- `_01`의 타일 진단 CSV 900행에서 타일별 박스 수 최댓값은 **27/300**이며 `max_det` 도달 타일은 0개다. confidence threshold는 해당 산출물에 기록되지 않아 사후 확인할 수 없다.
- 새 A 실행 목표 ID는 `r01_detection_only_20261104_02`다. 실행 및 재현성 대조 결과는 아직 없다.
- 다음 실행의 검출 프레임은 공통 격자 60개와 `gt_observations.csv`의 모든 프레임의 합집합이다. 현재 GT로 계산하면 총 236개(격자 밖 176개, 모두 짝수)다. 재현율과 TASK-006 raw tracker 재현성 대조에는 전체 236개를 쓰고, Precision·AP는 완전 프레임 54개만 쓴다.
- 클래스별 P/R은 클래스별 매칭으로 계산한다. ByteTrack 손실 분해 및 TASK-006 비교는 클래스 무관 Hungarian 매칭 후 클래스 호환표를 적용한다.
- 손실 분해에서 트랙이 GT와 매칭되더라도 conf 0.15 이상 원시 검출이 같은 GT와 매칭되지 않으면 범주 ④로 처리하지 않고 재현성 이상으로 별도 집계한다.
- COCO AP는 `areaRng=all`, `maxDets=5000` 한 값으로 산출한다. 무시 대상은 `iscrowd=1` GT로 넣고, P/R에서도 COCO crowd 규칙과 같은 detection-area overlap 방식으로 제외 건수를 집계한다.

## 다음 단계

GPU에서 새 ID로 A를 실행하고, 실행 메타데이터의 device·입력 해시·설정 해시를 확인한 뒤 TASK-006의 `raw_tracker/tracks.csv`와 IoU 0.99 재현성 대조를 수행한다. 결과가 일치하면 A 지표, 누락 원인 분해, 감사용 오탐 목록과 오버레이를 추가한다.
