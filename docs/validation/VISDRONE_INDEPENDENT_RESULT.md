# VisDrone 독립 구간 검증 결과

작성일: 2026-07-31 KST  
영상/구간: `DJI_0482.MP4`, 0–60초  
판정: VisDrone V2의 전체 적용과 V3 확장을 보류

## 검증 원칙

대표구간(150–210초)에서 정한 필터를 변경 없이 적용했다. 독립 구간 결과를 보고
임계값을 다시 맞추지 않았으므로 이 결과는 대표구간 튜닝과 분리된 일반화 점검이다.

## 결과

| 지표 | COCO YOLO11m | VisDrone YOLO11m V2 |
|---|---:|---:|
| 처리시간 | 307.4초 | 305.0초 |
| 원시 트랙 | 237 | 645 |
| 필터 후 트랙 | 99 | 193 |
| 필터 후 person 트랙 | 56 | 149 |
| 필터 후 person 관측점 | 2,558 | 7,566 |
| 필터 후 person 5초 이상 | 14 | 39 |
| 30개 표본 실제 객체 | 29 | 28 |
| 30개 표본 precision | 96.7% | 93.3% |
| 수동 기준 트랙 coverage | 8/8 | 8/8 |

30개 표본은 지속시간 구간과 클래스를 나눠 뽑은 품질 점검 표본이며 전체 트랙에 대한
불편 추정치는 아니다. 8개 기준도 완전 프레임별 객체 주석이 아니라 기존 수동 기준 트랙의
포착 여부이므로 recall 대신 reference-track coverage로 기록한다.

## 확인된 실패

- COCO `car #5`: 과속방지턱 또는 노면표시를 약 60초간 차량으로 유지했다.
- VisDrone `car #36`: 중앙 화단 수목을 약 54.8초간 차량으로 유지했다.
- VisDrone `truck #257`: 도로변 시설물 또는 정류장 구조물을 truck으로 판정했다.

따라서 최소 지속시간과 전역 공간확산만으로 장기 고정 오탐을 안정적으로 제거할 수 없다.
VisDrone 표본 precision은 COCO보다 3.4%p 낮아 사전 허용 기준(최대 3%p 저하)을 0.4%p
초과했다.

## 결론과 다음 단계

VisDrone은 같은 속도에서 장기 person 트랙을 14개에서 39개로 늘렸고 기준 트랙도 모두
포착했다. 그러나 독립 표본 precision 게이트를 근소하게 통과하지 못했고 고정 오탐 필터의
일반화 실패도 확인됐다. 따라서 현재 단계에서는 전체 영상 분석, 데모 기본 모델 채택,
30 epoch V3 학습을 시작하지 않는다.

다음 비교 전에 중앙 화단과 고정 노면표시를 명시적 제외 마스크로 분리하고, 새 독립 구간에서
한 번 더 검증한다. 데모에는 모델명을 명시하고 사전 계산 결과만 사용하며, 현재 VisDrone
결과는 `experimental`로 표시한다.

후속 220–280초 재검증에서도 VisDrone 표본 precision은 COCO보다 3.3%p 낮았고 새로운
횡단보도 표시 오탐이 확인됐다. 상세 내용은
`docs/validation/VISDRONE_REVALIDATION_RESULT.md`를 참조한다.

## 산출물

- COCO: `outputs/analysis/independent/DJI_0482_0_60_yolo11m/`
- VisDrone: `outputs/analysis/independent/DJI_0482_0_60_visdrone_yolo11m_v2/`
- 기준점 비교: `outputs/analysis/independent/DJI_0482_0_60_reference_comparison/`
- 독립 기준: `data/ground_truth/independent_references_DJI_0482_0_60.csv`
