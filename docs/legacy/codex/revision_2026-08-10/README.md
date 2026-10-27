# GPT_Round — Vision AI 기반 교통안전 분석

`GPT_Round`는 영상에서 보행자와 차량을 검출·추적하고, 검증 가능한 궤적·사건·대리안전지표를 산출하는 연구 프로젝트다. 기존 회전교차로 드론 영상은 첫 개발·검증 사례로 유지하며, 장기적으로 한국의 이면도로·아파트 단지·학교 캠퍼스·대규모 공단 등에 설치된 무신호 횡단보도의 보행안전 분석으로 확장한다.

## 현재 상태

- COCO YOLO11m과 ByteTrack을 현재 기준선으로 사용한다.
- 현재 배치는 `검출·추적 → 필터 → 궤적 병합 → ROI 위험후보`를 실행한다.
- 원시 추적, 필터 및 병합 궤적은 별도 CSV로 보존한다.
- 현재 코드는 raw detection 별도 저장, 보행자 횡단사건, A0/A1/B0/B1/B2 분류, 정식 PDI를 아직 구현하지 않았다.
- 현행 PET는 ROI 순차점유 간격, TTC는 국소 일정속도 가정에 따른 잠정 후보값이다.
- 기존 중간 결과와 후보 건수는 검증된 안전성 결과로 간주하지 않는다.

## 연구 목표와 분석계층

1. 노출도: 보행량, 차량량, 실제 상호작용 수
2. 운영·행태: 대기시간, 횡단경로, 양보·감속·정지
3. 상충위험: PET, TTC, 최소거리, 급감속
4. 시설·환경: 시야가림, 주정차, 조명, 보도 장애

분석 단위는 보행자의 접근부터 횡단완료까지인 `crossing event`와, 한 보행자와 한 접근차량의 관계인 `interaction event`를 구분한다.

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

각 단계는 앞 단계의 누락을 숨기지 않도록 별도 산출물과 요약을 보존한다.

## PDI 적용범위

보유한 30분 영상은 논문이 권고한 정식 PDI 관측기간과 대표성을 충족하지 않는다. 따라서 현재 단계에서는 지점 PDI나 안전등급을 산출하지 않는다. A/B 선후관계 및 A1/B1/B2 개념, 입력변수 산출 가능성, 수동 확인된 일부 사건의 `provisional_dpd`만 탐색적으로 검토한다.

B2에는 논문의 인쇄오류를 바로잡은 다음 식을 사용한다.

\[
DPD_{B2}=\frac{1}{1+\exp(0.561a_5+2.713)}
\]

여기서 감속 시 \(a_5<0\)이다. 자세한 조건은 `docs/methodology/pdi_method_review.md`를 따른다.

## 주요 디렉터리

- `src/roundabout/`: 분석 패키지
- `configs/`: 기준선과 시험 설정
- `data/calibration/`: ROI, 마스크, Homography
- `data/ground_truth/`: 수동판독·검증자료
- `docs/methodology/`: 방법론과 구축계획
- `docs/validation/`: 검증결과와 의사결정 기록
- `outputs/analysis/`: 재생성 가능한 단계별 결과
- `apps/demo/`: 검증상태를 표시하는 오프라인 데모
- `archive/legacy/`, `docs/legacy/`: 과거 자료

## 첫 확인

```bash
PYTHONPATH=src python3 -m roundabout.inventory --config configs/baseline.json
.venv/bin/pytest
PYTHONPATH=src .venv/bin/python -m roundabout.run_batch --dry-run
```

품질 게이트와 설정 변경이 승인되기 전에는 전체 영상 GPU 배치를 실행하지 않는다.

## 검증 원칙

트랙 수 또는 자동 위험후보 수의 증가는 성능 향상을 뜻하지 않는다. 동일한 수동검토 표본에서 객체사건 재현율, 완전 궤적 재현율, 시간 커버리지, fragmentation, ID switch, 최대 누락시간, 단계별 생존율 및 보행자-차량 상호작용쌍 관측률을 비교한다.
