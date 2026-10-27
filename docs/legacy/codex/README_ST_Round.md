# GPT_Round — Vision AI 기반 교통안전 분석

`GPT_Round`는 영상에서 보행자와 차량을 검출·추적하고, 검증 가능한
궤적·사건·대리안전지표를 산출하는 연구 프로젝트다. 기존 회전교차로 드론 영상은 첫
개발·검증 사례로 유지하며, 장기적으로 한국의 이면도로·아파트 단지·학교 캠퍼스·대규모
공단 등에 설치된 무신호 횡단보도의 보행안전 분석으로 확장한다. 분석 결과와 오프라인
데모는 동일한 표준 산출물을 사용한다.

## 현재 상태와 프로젝트 이력

- 프로젝트를 재현성과 데모 활용을 기준으로 재구축했다.
- COCO YOLO11m과 클래스별 ByteTrack을 현재 분석·데모 기준선으로 확정했다.
- 현재 배치는 `검출·추적 → 필터 → 궤적 병합 → ROI 위험후보`를 실행한다.
- raw tracker trajectory인 `tracks.csv`, 필터 궤적, 병합 궤적은 별도 CSV로
  보존한다.
- 현재 코드는 raw detection 별도 저장, 보행자 횡단사건,
  A0/A1/B0/B1/B2 분류, 정식 PDI를 구현하지 않았다.
- 현재 PET는 같은 ROI의 순차점유 간격으로 생성한 잠정 후보값이다.
- 현재 TTC는 국소 일정속도 가정으로 계산한 영상평면의 잠정 후보값이다.
- 대표 60초 구간과 독립 구간에서 모델·필터를 비교했고, COCO YOLO11m을
  기준선으로 선택했다. VisDrone 시험 결과와 보류 결정은
  `docs/validation/DECISION_LOG.md`에 보존한다.
- DJI_0482를 제외한 7개 영상의 고정 설정 배치 산출물이
  `outputs/analysis/full/`에 있으며, 기존 산출물은 새 품질 게이트의 확정 결과가 아니라
  재현·검토 대상 기준선이다.
- 기존 코드와 문서는 `archive/legacy/`, `docs/legacy/`에 원형 보존되어 있다.
  기존 중간 결과와 자동 후보 건수만으로 안전분석 품질이 검증되었다고 간주하지 않는다.

## 연구 목표와 분석계층

1. 노출도: 보행량, 차량량, 실제 상호작용 수
2. 운영·행태: 대기시간, 횡단경로, 양보·감속·정지
3. 상충위험: PET, TTC, 최소거리, 급감속
4. 시설·환경: 시야가림, 주정차, 조명, 보도 장애

목표 분석 단위는 보행자의 접근부터 횡단완료까지인 `crossing event`와, 한 보행자와
한 접근차량의 관계인 `interaction event`를 구분한다. 두 사건 단위는 목표 설계이며
현재 코드에는 구현되지 않았다.

## 목표 파이프라인

```text
raw detections
→ raw tracker trajectories
→ filtered trajectories
→ merged trajectories
→ crossing events
→ interaction candidates
→ reviewed interaction events
→ yielding/PET/TTC/minimum distance
→ provisional PDI-concept screening
```

각 단계는 앞 단계의 누락을 숨기지 않도록 별도 산출물과 요약을 보존한다. 현재 구현 범위는
`raw tracker trajectories`부터 ROI 기반 위험후보까지다.

## PDI 적용범위

보유 자료는 분석 가능 구간 합계가 약 29.31분인 8개 영상 묶음이다. 이는 논문이 권고한
정식 PDI 관측기간과 대표성을 충족하지 않는다. 따라서 현재 단계에서는 지점 PDI나
안전등급을 산출하지 않는다. A/B 선후관계와 A0/A1/B0/B1/B2 분류 가능성, 입력변수
산출 가능성, 수동 확인된 일부 적격 사건의 `provisional_dpd`만 탐색적으로 검토한다.

B2 개념시험에는 프로젝트가 채택한 다음 수정식을 사용한다.

\[
DPD_{B2}=\frac{1}{1+\exp(0.561a_5+2.713)}
\]

여기서 감속 시 \(a_5<0\)이다. 이 식은 아직 현행 Python 코드에 구현되지 않았다. 향후
수동 확인과 실세계 변수 검증을 통과한 사건에만 `provisional_dpd`로 적용하며,
`formula_version`을 함께 저장한다. 자세한 조건은
`docs/methodology/pdi_method_review.md`를 따른다.

## 주요 디렉터리

- `data/raw/before/`: 개선 전 원본 영상 8편, 버전관리 제외
- `data/calibration/`: 영상별 마스크와 기존 ROI·Homography
- `data/ground_truth/`: 수동조사표와 검증 표본
- `src/roundabout/`: 분석 패키지
- `configs/`: 기준선과 시험 설정
- `docs/methodology/`: 방법론과 구축계획
- `docs/validation/`: 검증결과와 의사결정 기록
- `outputs/analysis/`: 재생성 가능한 단계별 분석 결과
- `outputs/demo/`: 데모용 패키지
- `apps/demo/`: 오프라인 데모 UI
- `archive/legacy/`, `docs/legacy/`: 과거 코드·문서·연구 이력

## 설치와 기준선 확인

Python 3.11 이상을 사용한다.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[analysis,dev,demo]'
.venv/bin/pytest
```

`roundabout.inventory`는 지정한 manifest를 새로 쓰는 명령이다. 기존
`manifests/raw_videos.csv`를 덮어쓰지 않고 입력 목록을 비교하려면 임시 경로를 사용한다.

```bash
PYTHONPATH=src python3 -m roundabout.inventory \
  --config configs/baseline.json \
  --output /tmp/gpt_round_raw_videos.csv
```

현재 입력·마스크·Homography·가중치와 단계별 실행 계획은 쓰기 없는 dry-run으로 확인한다.

```bash
PYTHONPATH=src .venv/bin/python -m roundabout.run_batch --dry-run
```

품질 게이트와 설정 변경이 승인되기 전에는 전체 영상 GPU 배치나 재분석을 실행하지 않는다.

## 전체 배치 재개

승인된 기준 설정으로 배치를 실행하면 완료된 단계는 출력 스키마·파라미터와 체크섬을
검증한 뒤 건너뛰고, 실패하거나 유효하지 않은 단계부터 이어서 실행한다.

특정 영상만 계획하려면 다음과 같이 `--videos`를 추가한다.

```bash
PYTHONPATH=src .venv/bin/python -m roundabout.run_batch \
  --dry-run \
  --videos DJI_0485 DJI_0486
```

승인 후 실제 실행할 때만 `--dry-run`을 제거한다. 전체 단계를 새 출력 정체성으로 다시
만들어야 할 때만 `--force`를 사용하며, 기존 기준선 출력은 덮어쓰지 않는다.

## 현재 데모 번들

`outputs/demo/current/`에는 DJI_0482 220–280초 COCO YOLO11m 추적 자료와
0–60초에서 수동 확인된 차량–차량 PET 사건 2건의 검증 자료가 있다. 사건 탭에서 6초
영상, ROI 오버레이, 시간순 필름스트립과 검증 상태를 확인할 수 있다. 이 이력은 현재
보행자 횡단사건이나 PDI가 구현되었다는 뜻이 아니다.

```bash
PYTHONPATH=src python3 scripts/build_demo_bundle.py
PYTHONPATH=src .venv/bin/streamlit run apps/demo/app.py
```

데모는 GPU와 네트워크 연결 없이 사전 계산 결과를 재생하는 구성을 기본으로 하며, 실제
확인 결과, 미검증 후보, 예시자료의 상태를 구분해야 한다.

## 검증 원칙

트랙 수 또는 자동 위험후보 수의 증가는 성능 향상을 뜻하지 않는다. 동일한 수동검토
표본에서 객체사건 재현율, 완전 궤적 재현율, 시간 커버리지, fragmentation, ID switch,
최대 누락시간, 단계별 생존율 및 보행자-차량 상호작용쌍 관측률을 비교한다. PET, TTC,
`provisional_dpd`는 분석 가능한 사건 수, 좌표계, 단위, 검토 상태 및 한계와 함께
보고한다.
