# STU: 캠퍼스 회전교차로 보행안전 분석

서울과학대학교 캠퍼스 회전교차로와 주변 무신호 횡단보도 3곳을 촬영한 드론 영상으로
보행자와 차량을 검출·추적하고, 보행자-차량 상호작용과 보행안전 수준을 분석하는 연구
저장소다. 기존 `ST_Round`(Codex 분석)와 `Roundabout`(Claude Code 분석)을 하나로 통합했다.

## 프로젝트 성격

- 분석 대상지는 개선공사가 시작되어 **현장 형상이 이미 바뀌었다.**
- 추가 촬영과 개선 후 촬영은 없다. 이 저장소의 영상 8편은 **개선 전 형상의 유일한 기록**이다.
- 따라서 개선 전후 효과 분석은 범위에서 제외하며, 원본 영상과 보정자료는 재취득할 수 없는
  자료로 취급한다.

## 연구 목표

1. **개선 전 현황 진단**: 무신호 횡단보도 3곳의 보행자·차량 노출, 양보·정지 행태,
   보행자-차량 상호작용과 상충 사례를 검증된 궤적으로 기록한다.
2. **영상 기반 분석 방법론 검증**: 드론 영상에서 검출, 추적, 사람 보정, 사건 생성,
   안전지표 산출까지의 절차와 각 단계의 오차를 정량화한다.

## 자료

| 항목 | 내용 |
|---|---|
| 촬영일 | 2026-06-11 |
| 영상 | DJI_0481~DJI_0488, 8편, 3840×2160, 29.97fps(30000/1001), HEVC |
| 촬영 방식 | 회전교차로 중앙섬 상공 단일 호버링, 고도 약 46.8m(DJI_0483 SRT 기준) |
| 분석 가능 길이 | 약 29.3분. 정본은 `manifests/clips.yaml` |
| 대상 | 회전교차로 접근로 4개, 무신호 횡단보도 3곳(남서·동·북서) |
| 현장 실측 | 접근로별 노면 고저차(섬 기준 최대 2.0m) |

원본 영상, 모델 가중치, 생성 산출물은 Git에 넣지 않는다. 원본의 무결성은
`manifests/raw_videos.csv`의 sha256으로 확인한다.

## 이 자료로 할 수 있는 것과 없는 것

| 분석 | 가능 여부 | 근거 |
|---|---|---|
| 객체·궤적 품질 검증 | 가능 | 블라인드 GT 프로토콜 |
| 보행량·차량량, 상호작용 목록, A/B 선후관계 분류 | 가능 | 검증된 궤적 확보가 전제 |
| 양보·정지·대기 행태 기술통계 | 가능 | 신뢰구간 병기 |
| PET·TTC, 최소거리 | 보조 지표로 가능 | 사람 검토를 거친 사건만 확정 |
| 사건별 `provisional_dpd` | 조건부 | 접근로별 미터 환산 검증이 전제 |
| CEI(PSD<1 통과율) | 불가 | 접근로 상류 30m(D30)가 화면에 들어오지 않음 |
| 지점 PDI, 안전등급 | 불가 | 약 29분 단일 세션. 논문 권고는 최소 4일 |
| 3곳의 통계적 위험 순위 | 불가 | 지점별 조우 표본 부족 |
| 개선 전후 비교 | 불가 | 개선 후 영상 없음 |

자세한 근거는 `docs/methodology/pdi_method_review.md`와
`docs/validation/PHASE1_REGISTRATION_DIAGNOSIS_20260814.md`를 따른다.

## 궤적 확보 전략

기존 분석에서 소형 보행자 미검출, 궤적 분절, person·car·motorcycle 사이의 클래스 전환이
반복 확인됐다. 새 촬영이 없으므로 범용 모델 선택보다 **이 29분을 정확히 측정하는 것**을
목표로 다음 두 방법을 함께 쓴다.

1. **현장 영상 미세조정**: 기존 추적 결과를 초벌 라벨로 쓰고 사람이 수정한 프레임으로
   검출 모델을 미세조정한다. 성능 평가는 학습에 쓰지 않은 클립 또는 구간에서만 한다.
2. **반자동 추적과 사람 보정**: 횡단보도 영향권의 보행자와 관련 차량 궤적은 사람이
   분절 병합, 클래스, 누락 구간을 확인해 `reviewed trajectories`로 확정한다.

진행 순서는 다음과 같다.

1. 블라인드 GT 완성과 현행 기준선(COCO YOLO11m, 클래스별 ByteTrack)의 재현율 측정
2. 미세조정 모델 학습과 동일 GT 비교
3. 사람 보정 도구로 횡단보도 영향권 궤적 확정
4. 확정 궤적으로 횡단사건, 상호작용, 지표 산출

YOLO11m과 YOLO11l의 선택은 2단계의 GT 비교 결과로 결정하며, 그전까지 YOLO11m은
**임시 기준선**이다.

## 분석 파이프라인

```text
raw detections
→ raw tracker trajectories
→ filtered trajectories
→ merged trajectories
→ reviewed trajectories          (횡단보도 영향권, 사람 보정)
→ crossing events
→ interaction candidates
→ reviewed interaction events
→ 행태·노출 지표, PET/TTC/최소거리, provisional_dpd
```

각 단계의 산출물은 별도로 보존한다. 앞 단계의 누락을 뒤 단계에서 숨기지 않는다.

## 좌표와 단위

- `source px`(원본 화소), `reference px`(기준 프레임 화소), `world m`(실세계 미터)를 항상
  구분해 표기한다.
- 정합 기준 프레임은 `DJI_0481` frame 2848이다.
- 접근로별 고저차 때문에 화면 전체에 단일 스케일을 쓰면 스케일 오차가 최대 4.3%로
  허용치 3%를 넘는다. 미터 환산은 **접근로별 스케일**로 하고, 검증 전 값은 `null`로 둔다.
- 개선 전 실측 거리는 다음 자료로 확보한다: 개선공사 설계도서의 현황측량도, 공사 범위 밖에
  남은 고정물(가로등, 맨홀, 건물 모서리 등) 간 실측, 정사영상 교차검증.

## 현재 상태

2026-10-27 기준, 두 저장소의 자료를 통합하는 중이다.

| 기능 | 상태 |
|---|---|
| 슬라이스 검출, 클래스별 ByteTrack, 필터, 분절 병합 | 구현(`src/roundabout/`) |
| ROI 순차점유 PET, 국소 일정속도 TTC 후보 | 구현, 잠정값 |
| 중단 후 재개 가능한 배치, 오프라인 데모 | 구현 |
| 블라인드 객체·궤적 GT | 프로토콜과 검토 도구 준비, 판독 진행 중 |
| 프레임별 영상 정합 | 시제품(`scripts/registration/39_register_frames.py`) |
| 클래스 전환 자기충돌 진단 | 시제품(`scripts/diagnostics/31_verify_flicker_self_collision.py`) |
| raw detection 별도 저장 | 미구현 |
| 설치 의존성 | `pyproject.toml`의 `analysis`, `detection`, `dev`, `demo` extra로 관리. PyTorch는 GPU 드라이버에 맞춰 별도 선설치 |
| 현장 미세조정, 사람 보정 도구 | 미구현 |
| 횡단사건, 상호작용, A0/A1/B0/B1/B2 분류 | 미구현 |
| 접근로별 미터 환산, `provisional_dpd` | 미구현 |

## 디렉터리

```text
STU/
├── AGENTS.md / CLAUDE.md     진입 파일(실행자 Codex, Claude Code는 검토 전용)
├── configs/                  분석 설정, 파라미터 레지스트리(parameters.yaml)
├── manifests/                영상 목록·체크섬(raw_videos.csv), 클립 메타 정본(clips.yaml)
├── data/
│   ├── raw/                  원본 영상(Git 제외)
│   ├── calibration/          영상별 마스크, ROI, 정합 자료
│   ├── registration/         기준점, 프레임별 변환, 정합 진단 원자료
│   ├── telemetry/            ffprobe·SRT 추출값
│   └── ground_truth/         블라인드 GT, 기존 지상검증 조사표
├── src/roundabout/           분석 패키지
├── scripts/                  보조 도구(정합, 진단, 검토, 데모 번들)
├── apps/demo/                오프라인 데모(Streamlit)
├── tests/                    단위·회귀 테스트
├── docs/
│   ├── PROJECT_RULES.md      공통 작업 규칙
│   ├── tasks/                Codex 작업 지시문(TASK-NNN.md)
│   ├── methodology/          방법론, 지표정의서, 구현사양서
│   ├── validation/           검증 결과, 의사결정 기록(DECISION_LOG.md)
│   └── legacy/               통합 전 문서(codex/, claude/)
├── archive/legacy/           통합 전 코드(읽기 전용)
└── outputs/                  생성 산출물(Git 제외)
```

## 설치

Python 3.11 이상을 사용한다. PyTorch는 GPU 드라이버에 맞는 빌드를 **먼저** 설치해야
한다. 순서를 바꾸면 범용 빌드가 설치될 수 있다.

```bash
python3 -m venv .venv
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cu132
.venv/bin/pip install -e '.[analysis,detection,dev,demo]'
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest
```

배치 계획은 쓰기 없이 먼저 확인한다.

```bash
PYTHONPATH=src .venv/bin/python -m roundabout.run_batch --dry-run
```

품질 게이트와 설정 변경이 승인되기 전에는 전체 영상 GPU 배치를 실행하지 않는다.

## 데모

`outputs/demo/current/`의 사전 계산 번들(DJI_0482 220~280초 추적 결과, 수동 확인된
차량-차량 PET 사건 2건)을 GPU와 네트워크 없이 재생한다. 보행자 횡단사건이나 PDI가
구현되었다는 뜻은 아니다.

```bash
PYTHONPATH=src python3 scripts/build_demo_bundle.py
PYTHONPATH=src .venv/bin/streamlit run apps/demo/app.py
```

## 작업 원칙

- 트랙 수나 위험 후보 수의 증가를 품질 향상으로 보지 않는다. 동일한 GT 표본에서 객체
  재현율, 완전 궤적 재현율, 시간 커버리지, 분절, ID 전환, 최대 누락시간, 단계별 생존율,
  상호작용쌍 관측률로 비교한다.
- 결과가 좋아지는 방향으로 임계값을 조정하지 않는다. 변경 시 민감도 분석을 함께 낸다.
- 표본이 부족한 지표는 0이나 빈칸이 아니라 사유 코드로 출력한다.
- 기존 산출물을 덮어쓰지 않는다. 승인된 방법론 결정은 `docs/validation/DECISION_LOG.md`에
  기록한다.
- DPD 계수는 폴란드 자료로 보정된 값이다. 한국 현장 보정값으로 주장하지 않고, 회전 차량에는
  적용하지 않는다. B2는 프로젝트 수정식 `project_corrected_b2_v1`을 쓴다.

전체 규칙은 `docs/PROJECT_RULES.md`를 따른다.

## 통합 이력

| 원 저장소 | 분석 도구 | 통합 시점 HEAD |
|---|---|---|
| `jihorama-hash/ST_Round` (WSL `GPT_Round`) | Codex | `ab2f0ed` (2026-09-07) |
| `jihorama-hash/Roundabout` (WSL `ST_Roundabout`) | Claude Code | `169a267` (2026-09-10) |

두 저장소는 2026-07-28 커밋까지 이력이 같고 이후 갈라졌다. 원 저장소는 읽기 전용 기록으로
보존한다. 파일별 이전 내역은 `docs/validation/MIGRATION_RECORD.md`에 있다.
