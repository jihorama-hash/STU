# GPT_Round 문서 개정 적용 메모

## 개정 판단

이번 개정은 프로젝트를 새로 만드는 것이 아니다. 기존 회전교차로 드론 분석을 첫 검증사례로 유지하면서 상위 목적과 작업절차를 무신호 횡단보도 보행안전 분석까지 확장한다.

코드 검토에서 확인한 주요 사실:

- `detect_track.py`는 추적된 관측점을 `tracks.csv`로 저장하지만 추적 전 raw detection을 별도 저장하지 않는다.
- `filter_tracks.py`와 `merge_track_fragments.py`는 각각 별도 CSV와 요약/연결 보고를 생성한다.
- `analyze_risk.py`는 crossing event나 PDI 분류가 아니라 ROI 점유 기반 잠정 PET/TTC 후보를 생성한다.
- Homography 이후 좌표와 `maximum_encroachment_distance_pixels` 명칭 사이의 단위 정합을 확인해야 한다.
- 제공된 테스트는 핵심 유틸리티를 검증하지만 객체사건/완전궤적/상호작용쌍 재현율은 검증하지 않는다.

## 권장 배치

```text
GPT_Round/
├── AGENTS.md
├── README.md
└── docs/
    ├── methodology/
    │   ├── REBUILD_PLAN.md
    │   └── pdi_method_review.md
    └── validation/
        ├── OBJECT_TRACK_RECALL_METHOD_REVIEW.md
        └── DECISION_LOG.md
```

`pyproject.toml`의 배포 패키지명 `roundabout-safety`와 Python 모듈 경로 `roundabout`은 현재 코드 호환성을 위해 이번 문서 개정만으로 바꾸지 않는다.

## Codex CLI 적용 프롬프트

```text
먼저 현재 브랜치와 git status를 확인하고 기존 파일을 덮어쓰지 말라.

제공된 개정안과 저장소의 다음 파일을 diff로 비교하라.
- AGENTS.md
- README.md
- docs/methodology/REBUILD_PLAN.md
- docs/methodology/pdi_method_review.md

현재 코드와 맞지 않는 경로 또는 명령이 있으면 수정 제안만 제시하라.
OBJECT_TRACK_RECALL_METHOD_REVIEW.md와 DECISION_LOG.md는 삭제하거나 축약하지 말라.
pyproject.toml과 분석 코드는 이번 단계에서 변경하지 말라.

다음을 표로 보고한 뒤 승인을 기다려라.
1. 파일별 주요 변경
2. 현재 코드로 확인된 근거
3. 유지되는 기존 내용
4. 새로 추가되는 연구규칙
5. 문서 간 충돌 또는 미확인 사항
```

승인 후 문서만 적용하고 테스트는 현재 기준선 확인용으로 실행한다. 문서 변경 자체를 이유로 전체 영상 GPU 배치를 실행하지 않는다.
