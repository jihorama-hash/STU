# STU 통합 이전 기록

작성일: 2026-10-27
대상: `jihorama-hash/ST_Round`(WSL `GPT_Round`, Codex) + `jihorama-hash/Roundabout`(WSL `ST_Roundabout`, Claude Code) → `jihorama-hash/STU`

## 1. 원칙

1. 원 저장소는 지우거나 고치지 않는다. 읽기 전용 기록으로 보존한다.
2. 이전은 각 원 저장소의 **작업 트리**(커밋되지 않은 로컬 변경 포함)에서 복사한다. 이전 시점의
   HEAD와 미커밋 변경 목록은 `migration_filemap.tsv`와 함께 기록한다.
3. 코드 골격은 ST_Round를 따른다. Roundabout의 자료·명세·진단은 역할에 맞는 위치로 옮긴다.
4. 같은 경로에 내용이 다른 파일이 오면 덮어쓰지 않고 `__A`/`__B` 접미사로 둘 다 남긴다.
5. 내용이 같은 중복 파일은 ST_Round 쪽 하나만 남긴다.
6. 원본 영상, 가중치, 생성 산출물, 대용량 진단 이미지, 저작권 자료는 Git에 넣지 않는다.
   로컬에서는 `data/raw/`, `models/`, `outputs/`, `references/`(모두 Git 제외)에 연결해 둔다.
7. 이번 단계에서는 **파일 이동만** 한다. 코드 수정, 경로 재배선, 설정 통합은 다음 단계에서
   커밋을 분리해 진행한다.

## 2. ST_Round(Codex) → STU

| 원 경로 | STU 경로 | 비고 |
|---|---|---|
| `src/roundabout/`, `tests/`, `configs/`, `apps/`, `scripts/` | 동일 | 코드 골격 |
| `pyproject.toml`, `.vscode/` | 동일 | |
| `manifests/raw_videos.csv` | 동일 | DJI_0483 원본 행은 후속 추가 |
| `data/calibration/`, `data/ground_truth/` | 동일 | |
| `docs/methodology/`, `docs/validation/` | 동일 | 활성 문서 |
| `docs/legacy/*` | `docs/legacy/codex/*` | |
| `revision_2026-08-10/*` | `docs/legacy/codex/revision_2026-08-10/*` | |
| `archive/legacy/*` | 동일 | 공통 조상 코드 01~28 포함 |
| `AGENTS.md`, `README.md` | `docs/legacy/codex/AGENTS_ST_Round.md`, `README_ST_Round.md` | 새 파일로 교체 |
| `.gitignore` | 새로 작성 | 두 저장소 규칙 통합 |

## 3. Roundabout(Claude Code) → STU

| 원 경로 | STU 경로 | 비고 |
|---|---|---|
| `clips.yaml`, `clips_probe.csv` | `manifests/` | 클립 메타 정본 |
| `clips_telemetry.csv` | `data/telemetry/` | 57,307행 |
| `docs/무신호횡단보도_파라미터_v02.yaml` | `configs/parameters.yaml` | v0.2.3. `baseline.json`과 통합은 후속 |
| `docs/무신호횡단보도_지표정의서_*`, `구현사양서_*` | `docs/methodology/spec/` | CEI 산출 불가 반영 개정 필요 |
| `claude/03_PDI_DPD_검증_및_한국형PoC_v01.md` | `docs/methodology/pdi_dpd_verification_v01.md` | B2 수정식 근거 |
| `docs/참고문헌_R01_*.md` | `docs/references/` | 공개 보고서 변환본 |
| `claude/*.pdf`(PDI 논문) | `references/`(Git 제외) | 저작권 |
| `docs/PHASE1_REGISTRATION_DIAGNOSIS_20260814.md` | `docs/validation/` | CEI 불가, 접근로별 스케일 근거 |
| `DJI_0483_INTEGRITY_VERIFICATION.md`, `PHASE0_CHECKPOINT_A_REPORT.md` | `docs/validation/` | |
| `docs/` 나머지(작업지시서, 06 전달지시문, 파라미터 v01) | `docs/legacy/claude/` | |
| 루트 보고서(`PHASE_*`, `MIGRATION_PLAN.md`, `SNAPSHOT.md` 등) | `docs/legacy/claude/` | ST_Round와 같은 내용이면 생략 |
| `CLAUDE.md`, `README.md` | `docs/legacy/claude/CLAUDE_ST_Roundabout.md`, `README_Roundabout.md` | 새 파일로 교체 |
| `.claude/skills/*` | `docs/legacy/claude/skills/*` | 구 CEI 페이즈 기준이라 비활성화. 규칙 개정 후 재작성 |
| `calib/rois_split.json` | `data/calibration/rois_split.json`(정본) + `legacy_claude/` | 2026-10-27 결정. 10개 구역 |
| `calib/*` 나머지 | `data/calibration/legacy_claude/` | ST_Round 판과 내용이 다름(아래 5절) |
| `calib/reference_frame.png`(41MB) | `outputs/legacy_claude/calib/`(Git 제외) | DJI_0481 frame 2848에서 재생성 가능 |
| `registration/*.json`, `*.csv` | `data/registration/` | 기준점, 프레임별 변환 |
| `registration/diagnostic_*.json` | `data/registration/diagnostics/` | |
| `registration/**/*.png`(약 90장) | `outputs/legacy_claude/registration_figures/`(Git 제외) | 최대 10MB/장 |
| `src/39_register_frames.py` | `scripts/registration/` | 경로 재배선 전에는 실행 불가 |
| `src/31_verify_flicker_self_collision.py` | `scripts/diagnostics/` | 경로 재배선 전에는 실행 불가 |
| `src/` 나머지 | `archive/legacy/claude_src/` | 29~33 포함, 01~28은 Claude 수정판 |
| `scripts/generate_snapshot.sh` | `docs/legacy/claude/tools/` | |
| `survey/*.xlsx` | `data/ground_truth/legacy_survey/` | 원 판독 기록, 상호작용 형식 변환은 후속 |
| `survey/track_overlays_DJI_0482/`, `ROI Study/`, 메모 txt | 생략 | ST_Round와 동일 |
| `requirements.txt` | 루트 | `pyproject.toml`에 검출 의존성이 없어 당분간 병행 |

## 4. Git 밖 로컬 자료 연결

| 원 위치 | STU 위치 | 방식 |
|---|---|---|
| `GPT_Round/data/raw/before/*` | `data/raw/before/` | 심볼릭 링크(기본) |
| `ST_Roundabout/record/before/*` | `data/raw/before/` | 이름이 겹치고 크기가 같으면 생략, 다르면 `from_claude/` |
| `GPT_Round/models/*`, `ST_Roundabout/models/*` | `models/` | 같은 규칙 |
| `GPT_Round/outputs/` | `outputs/legacy_codex` | 링크 |
| `ST_Roundabout/runs/` | `outputs/legacy_claude_runs` | 링크 |
| Claude 진단 스크립트(`/tmp/claude-1000/.../scratchpad/*.py`) | `archive/legacy/claude_diagnostics/` | 남아 있을 때만 |

원 폴더를 지우기 전에는 반드시 `LINK_MODE=copy`로 다시 실행하거나 별도 백업한다.

## 5. 이전과 함께 들어가는 새 문서

| 파일 | 위치 |
|---|---|
| `README.md` | 루트 |
| `AGENTS.md`, `CLAUDE.md` | 루트. 둘 다 `docs/PROJECT_RULES.md`를 가리키는 진입 파일 |
| `PROJECT_RULES.md` | `docs/` |
| `TASKS_README.md` | `docs/tasks/README.md`. 작업 지시문 형식 |
| `MIGRATION_RECORD.md`(이 문서) | `docs/validation/` |
| 2026-10-27 결정 5건 | `docs/validation/DECISION_LOG.md` 끝에 추가 |

## 6. ROI 정본 결정(2026-10-27)

ST_Roundabout 판을 정본으로 한다. ST_Round 판과의 차이:

- 북서 횡단보도 진입측·진출측 폴리곤이 서로 바뀌어 있다.
- 횡단보도 6개 구역의 `label_votes`가 갱신됐다.
- 동측·북측 회전부 진입 상충구역 2개가 추가됐다(8개 → 10개).

ST_Round `outputs/analysis/full/`은 구 ROI 결과이므로 재사용 시 북서 횡단보도의 진입·진출 라벨을
다시 매핑한다.

## 7. 후속 작업(이전 후 별도 커밋)

1. (완료: 이전에 포함) `AGENTS.md`, `CLAUDE.md`, `docs/PROJECT_RULES.md`
2. (완료: 이전에 포함) ROI 정본 결정
3. 남은 보정자료 정본 결정: `alignment_homographies.json`, `roadway_mask.png`
4. 설정 통합: `configs/baseline.json`(JSON)과 `configs/parameters.yaml`(YAML)을 하나로
5. `manifests/raw_videos.csv`에 DJI_0483 원본과 SRT의 sha256 추가, 분석 길이 기준을 `clips.yaml`로 일원화
6. `pyproject.toml`에 `detection` 의존성(ultralytics, supervision<0.30, sahi) 추가
7. `39_register_frames.py`, `31_*` 경로 재배선 후 `src/roundabout/` 모듈로 편입, 테스트 추가
8. 지표정의서·구현사양서 개정: CEI 산출 불가, 접근로별 스케일, 궤적 확보 전략 반영
9. 원 저장소 두 곳을 GitHub에서 Archive 처리
