# DJI_0482 대표 60초 모델 비교

## 범위

- 원본: `data/raw/before/DJI_0482.MP4`
- 구간: 150.0–210.0초
- 유효 FPS: 14.985
- 검출: SAHI 방식 1024px 슬라이스 15개, overlap 0.20
- 추적: 클래스별 ByteTrack

## 결과

YOLO11l은 YOLO11m보다 27% 느렸고 보행자 트랙 분절 지표를 개선하지 못했다.
따라서 YOLO11m을 다음 수동검증 단계의 기준선으로 사용한다.

이 판정은 모델 정확도 합격을 의미하지 않는다. 0.5초 미만 트랙을 후처리에서 제외하고,
남은 보행자·차량 표본의 실제 검출 여부와 ID 연속성을 사람이 확인해야 한다.

육안검토에서 과속방지 노면표시가 45초 동안 `car`로 유지된 고정 오탐이 발견됐다.
따라서 지속시간 필터만으로 품질을 확보할 수 없으며 이동거리와 공간 마스크 검증이 필요하다.

## 산출물

- `outputs/analysis/baseline/DJI_0482_150_210_yolo11m/`
- `outputs/analysis/baseline/DJI_0482_150_210_yolo11l/`

각 디렉터리에는 `tracks.csv`, `summary.json`, `track_quality.json`, 육안검토 프레임과
contact sheet가 있다.
