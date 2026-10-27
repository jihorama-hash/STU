# 기존 자료 재배치 기록

작성일: 2026-07-30

기존 자료는 삭제하거나 내용 변경하지 않고 새 구조로 이동했다. 원본 영상은 이동 전
SHA-256을 기록하고 이동 후 `manifests/raw_videos.csv`를 다시 생성해 동일성을 확인했다.

| 기존 위치 | 새 위치 | 취급 |
|---|---|---|
| `record/` | `data/raw/before/` | 원본, 버전관리 제외 |
| `calib/` | `data/calibration/legacy/` | 재검증 전 참고자료 |
| `survey/` | `data/ground_truth/` | 수동검증 원자료 |
| `src/*.py` | `archive/legacy/code/` | 과거 코드 원형 보존 |
| `ROI Study/` | `archive/legacy/roi_study/` | 과거 미리보기 |
| 루트의 과거 계획서·보고서 | `docs/legacy/` | 연구 이력 |
| 과거 텍스트 메모 | `archive/legacy/notes/` | 원형 보존 |

Git 메타데이터가 실행 환경에서 읽기 전용이어서 인덱스에 `git mv`를 기록하지는 못했다.
파일 내용은 그대로이며, 향후 쓰기 가능한 환경에서 추가하면 Git의 rename detection으로
이동 이력을 확인할 수 있다.
