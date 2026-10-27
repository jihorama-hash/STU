# 데모 요구사항 초안

## 기본 시나리오

1. 대상지와 분석 목적 소개
2. 원본/검출·추적 영상 비교
3. ROI별 통행량과 상충 발생률 확인
4. 위험 이벤트 선택 후 해당 시점 재생
5. PET/TTC와 판정 근거 확인
6. 개선 전·후 비교

## 실행 모드

- `precomputed`: 사전 계산 결과만 재생, GPU 불필요
- `analysis`: 새 영상을 실제 분석, GPU 필요

초기 데모는 `precomputed`를 기본으로 한다. 화면에는 데이터 버전, 모델 버전,
검증 상태와 분석 한계를 항상 표시한다.

## 표준 입력

- `manifest.json`: 분석 실행 및 모델 정보
- `videos.json`: 영상과 데모 클립 정보
- `tracks.parquet` 또는 `tracks.csv`
- `events.json`
- `roi_summary.json`
- 오버레이 영상과 히트맵 이미지

현재 `outputs/demo/current`에는 COCO YOLO11m 220–280초 구간의 트랙과 ROI 집계가
연결되어 있다. ROI 집계와 PET/TTC 후보는 수동검증 전이므로 `unreviewed`로 표시한다.
