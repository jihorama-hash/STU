# TASK-001: 이전 직후 정리(의존성, 원본 체크섬, 클립 메타 메모)

- 상태: 구현·검증 완료(커밋 확인 대기)
- 작성: Aside / 승인: 사용자 / 작성일: 2026-10-27
- 브랜치: task/001-post-migration-cleanup

## 목적

STU 통합 직후 남은 기록·설정 불일치 세 가지를 정리한다. 분석 코드, 파라미터 값, 산출물은 바꾸지 않는다.

## 읽을 문서

- `docs/PROJECT_RULES.md`
- `docs/validation/MIGRATION_RECORD.md` 7절
- `manifests/raw_videos.csv`, `manifests/clips.yaml`
- `pyproject.toml`, `requirements.txt`

## 범위

### 1. 검출 의존성을 `pyproject.toml`에 반영

- 현재 `analysis` extra에는 numpy, opencv-python-headless, pandas만 있다. 그런데
  `src/roundabout/detect_track.py`는 `torch`, `ultralytics`, `supervision`을 import한다.
- `detection` extra를 새로 만들어 `ultralytics`, `supervision<0.30`을 넣는다. `supervision<0.30` 제한의
  이유(0.30에서 ByteTrack 제거)를 주석으로 남긴다.
- `src/`, `scripts/`, `apps/`, `tests/`에서 실제 import하는 서드파티 패키지를 전수 확인해, 누락된 것이 있으면
  알맞은 extra에 추가한다. `archive/`는 대상이 아니다.
- `torch`는 extra에 넣지 않는다. GPU 드라이버에 맞는 빌드를 먼저 설치해야 하므로 README 설치 절차를 따른다.
- `requirements.txt`는 지우지 않고, 맨 위에 "`pyproject.toml`이 기준이며 이 파일은 보조"라는 주석을 단다.
- README 설치 절차의 extra 이름이 바뀌었으면 맞춘다.

### 2. 원본 파일 체크섬 기록

- `data/raw/before/`의 실제 파일(링크 대상)을 대상으로 한다. 파일을 수정·이동·재인코딩하지 않는다.
- `manifests/raw_videos.csv`에 `DJI_0483.MP4`(원본) 행을 같은 형식으로 추가한다.
- 기존 8행의 크기와 sha256을 다시 계산해 일치하는지 확인하고 결과만 보고한다. 불일치가 있으면 고치지 말고
  멈춰서 보고한다.
- SRT 8개는 새 파일 `manifests/raw_telemetry.csv`(`video_id,filename,size_bytes,sha256`)에 기록한다.

### 3. `manifests/clips.yaml`의 서로 맞지 않는 메모 정리

- 같은 파일 안에서 `telemetry` 블록은 "8클립 전부 SRT 확보(2026-08-13)"인데, `site`와 `DJI_0483` 메모에는
  "8클립 중 유일하게 SRT 보유", "나머지 7클립은 SRT 없음"이 남아 있다. 이 메모를 현재 사실에 맞게 고치고,
  고친 사실과 날짜를 주석으로 남긴다.
- **값은 바꾸지 않는다.** `altitude_agl_m` 등 `null`인 값은 그대로 두고, 클립별 고도 확인이 후속 과제라는
  주석만 단다.
- 분석 가능 길이의 차이(`configs/baseline.json`은 DJI_0488을 118.0초, `clips.yaml`은 119.19초)는 고치지
  말고 완료 보고에 적는다. 어느 쪽을 쓸지는 사용자가 정한다.

### 하지 않을 일

- `scripts/registration/39_register_frames.py`, `scripts/diagnostics/31_*`의 경로 재배선(후속 작업)
- 분석 코드, `configs/` 값, `data/calibration/`, `data/ground_truth/` 수정
- GPU 실행, 모델 다운로드

## 체크포인트

1. 2번에서 기존 8개 영상의 sha256 확인이 끝나면, 불일치 여부를 보고한다. 불일치가 있으면 그 자리에서 멈춘다.
2. 커밋 전에 바뀐 파일 목록과 diff 요약을 보고하고 사용자 확인을 받는다.

## 완료 조건

- `.venv/bin/pytest` 통과(기존 테스트 기준)
- `pip install -e '.[analysis,detection,dev,demo]'`가 오류 없이 의존성을 해석
- README "현재 상태"에서 바뀐 항목이 있으면 갱신
- `docs/validation/MIGRATION_RECORD.md` 7절의 해당 항목에 완료 표시
- 아래 완료 보고 작성 후 이 파일을 함께 커밋

## 완료 보고(Codex 작성)

- 변경 파일: `.gitignore`, `pyproject.toml`, `requirements.txt`, `README.md`, `manifests/raw_videos.csv`, `manifests/raw_telemetry.csv`, `manifests/clips.yaml`, `docs/validation/MIGRATION_RECORD.md`, `docs/tasks/TASK-001.md`
- 실행한 명령과 결과: 기존 8개 영상의 크기·SHA-256 재계산 모두 일치. 사용자가 같은 `.venv`에 PyTorch cu132와 나머지 의존성을 직접 설치함. 최초 설치 시도는 PyTorch 선설치 전 일반 PyPI PyTorch/CUDA 다운로드를 시작해 중단했고, dry-run은 sandbox의 PyPI DNS 제한으로 build dependency를 받지 못했음. Codex 환경에서 `.venv/bin/pytest` 최종 재실행 결과 **38 passed, 0 failed (2.47초)**. 테스트 환경은 Python 3.14.6, pytest 8.4.2. `.venv/bin/python` 확인값은 torch 2.14.1+cu132, CUDA runtime 13.2, `torch.cuda.is_available()=False`, GPU 미노출. 사용자는 터미널에서 `torch.cuda.is_available()=True`를 직접 확인했다고 보고했으며 GPU 모델명은 제공하지 않음. Codex 환경의 False는 sandbox GPU 접근 제한으로 판단함. 이번 단위 테스트는 GPU가 필요하지 않음.
- sha256 재확인 결과: 기존 8개 전부 manifest와 일치. 원본 `DJI_0483.MP4`와 SRT 8개의 크기 및 SHA-256을 manifest에 추가함.
- DJI_0488 분석 길이 차이: `configs/baseline.json`은 118.0초, `manifests/clips.yaml`은 119.185733초. 값은 변경하지 않았으며 적용 기준은 사용자 결정 대기.
- 한계와 미해결: Codex sandbox에서 GPU가 노출되지 않아 `torch.cuda.is_available()`는 False로 관측되지만 GPU가 필요 없는 이번 테스트의 완료 조건에는 영향 없음. `altitude_agl_m` 등 null 값은 유지했고 클립별 고도 확인은 후속 과제. 전체 분석 길이 기준 일원화와 등록/진단 스크립트 경로 재배선은 범위 밖.
