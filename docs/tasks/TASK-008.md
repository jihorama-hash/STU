# TASK-008: 라벨 규칙 도입과 R01 GT v2 박스 재검토

- 상태: ready
- 작성: Aside / 승인: 사용자 / 작성일: 2026-11-05
- 브랜치: task/008-gt-v2-label-rules

## 목적

미세조정 전에 박스 작성 규칙(`docs/validation/DETECTION_LABEL_RULES.md`)을 확정한다. 그 규칙으로 R01 위치 GT
960개 박스를 다시 검토해 GT v2를 만든다. 현재 COCO YOLO11m을 GT v2로 다시 채점해 미세조정 비교의 기준선을 만든다.
미세조정은 이 TASK에 포함하지 않는다(다음 TASK).

## 사용자 결정 (2026-11-05)

1. D1 클래스: COCO 기준(person, bicycle, car, motorcycle, bus, truck). 버스는 영상 후반부에 나온다.
2. D2 부분 가림: 보이는 부분만 박스. 절반 미만이 보이거나, 절반 이상 보여도 육안으로 인식할 수 없으면 무시영역.
3. D3 양산: `person` + `umbrella` 속성.
4. D4 이륜차(자전거 포함): 차체와 탑승자(운전자·동승자 모두)를 합친 박스 하나. 탑승자 `person` 박스는 그리지 않는다. COCO와 다른 규칙이다. 탑승자가 차체를 가리는 것은 무시영역 판정 대상이 아니다.
7. 무시영역 박스는 추정 범위를 넉넉하게 그려도 되며 위치 지표에 쓰지 않는다.
8. 기타(2026-11-05 승인): 밴은 `car`, 픽업·화물차는 `truck`. 재검토 모드에서 `V` 비활성. 미세조정은 다음 TASK로 분리.
5. D5 GT 수정 범위: 960개 전수 재검토.
6. R01 GT는 평가 전용이며 학습에 넣지 않는다(PROJECT_RULES §4).

## 읽을 문서

- `docs/PROJECT_RULES.md`, `docs/validation/DECISION_LOG.md`
- `docs/validation/DETECTION_LABEL_RULES.md`(이 TASK에서 추가)
- `docs/validation/OBJECT_TRACK_GT_PROTOCOL.md`, `data/ground_truth/object_track_v1/DATA_DICTIONARY.md`
- `data/ground_truth/object_track_v1/review/BOX_INPUT_GUIDE.md`, `apps/demo/gt_box_annotation.py`
- `docs/tasks/TASK-006.md`, `docs/tasks/TASK-007.md`, `docs/validation/R01_DETECTION_ONLY_RESULT.md`

## 운영 규칙

- A. **GT v1은 바꾸지 않는다.** 태그 `gt-r01-v1`(ed72492)의 파일과 manifest 해시를 그대로 둔다. v2는 새 경로·새
  `gt_dataset_id`·새 manifest로 만든다. 경로와 ID 이름은 Codex가 제안한다.
- B. v2 재검토도 블라인드다. 도구는 자동 검출·추적 결과를 읽거나 표시하지 않는다. 재검토 대상 선정에 AI 결과를 쓰지 않는다.
- C. 객체 목록, visibility 구간, skip 10건은 v1을 그대로 쓴다. 재검토 중 경계가 맞지 않으면 v1 때처럼 skip으로
  보류하고, 입력이 끝난 뒤 따로 보고한다. 재검토 중 visibility 작업표를 고치지 않는다.
- D. 새 필드는 규칙 문서 9절(`ignore`, `attributes`, `label_source`, `revision_action`)을 따른다. 스키마가 바뀌면
  schema_version을 올리고 DATA_DICTIONARY에 정의를 추가한다.
- E. 무시영역(`ignore=true`) 박스는 평가 분모에서 빼고, 겹치는 검출은 오탐으로 세지 않는다(TASK-007 사용자 결정 2와
  같은 방식). v1 분모 960과 v2 분모를 함께 보고한다.
- F. D4에 따라 GT `motorcycle`·`bicycle` 박스 안의 `person` 검출(탑승자)은 오탐으로 세지 않고 `rider_inside_vehicle`로
  따로 집계한다. TASK-007 사용자 결정 1의 "탑승자 검출은 정탐" 문구는 이 규칙으로 대체되므로 DECISION_LOG에 기록한다.
  판정 기준은 GT 매칭 후 남은 person 검출에만 적용한다. person 검출 박스 면적 중 GT bicycle/motorcycle 박스와 겹치는 비율 50% 이상을 `rider_inside_vehicle`로 분류한다(2026-11-05 체크포인트 1 사용자 승인). 설정은 `configs/evaluation_detection_v2.yaml`의 근거등급 C 값으로 관리하며, 30%·50%·70% 민감도별 건수를 confidence 및 IoU 기준과 함께 보고한다. 50%를 주 기준으로 유지한다.

## 범위

### 1단계: 규칙 문서와 재검토 도구

1. 첨부한 규칙 초안을 `docs/validation/DETECTION_LABEL_RULES.md`로 추가한다. 내용은 바꾸지 않는다.
   문서 위계나 기존 규약과 충돌하는 부분이 있으면 고치지 말고 보고한다.
2. 박스 입력 도구에 v2 재검토 모드를 추가한다.
   - 각 anchor에서 v1 박스를 편집 가능한 초기 박스로 보여준다.
   - 그대로 저장하면 `revision_action=kept`, 조정하면 `adjusted`, 새로 그리면 `redrawn`으로 기록한다.
   - 단축키로 `ignore`와 `umbrella`를 켜고 끈다. 키 배정은 Codex가 제안한다.
   - 재검토 모드에서는 `V`(복사 후 즉시 저장)를 끈다. `C`는 유지한다.
   - 발점 검증으로 저장을 막지 않는다.
   - 진행률(검토 완료/960, kept·adjusted·redrawn·ignore 수)을 화면에 표시한다.
3. v2 작업 파일 검증기와 canonical 변환기를 추가한다(v1 변환기는 수정하지 않는다).
4. 일관성 점검 모드: 무작위 30개 anchor를 기존 박스를 숨긴 채 다시 그리게 하고 IoU를 계산한다. 난수 시드를 기록한다.
5. 테스트(`unittest.TestCase`, pytest): 재검토 기록값, ignore 처리, v1 파일 불변(SHA-256), 검증기 오류 사례.
6. `BOX_INPUT_GUIDE.md`에 재검토 모드 사용법을 추가한다. 실행 위치(WSL 저장소 루트)와 정상 출력을 적는다.
7. **체크포인트 1**: 변경 파일, 테스트 결과, 실행 명령을 보고하고 대기한다.

### 2단계: 사용자 재검토(사람 작업)

- 사용자가 960개를 재검토한다. Codex는 입력하지 않는다.
- 입력을 마칠 때마다 사용자가 작업 파일을 커밋한다(v1 방식과 같음).

### 3단계: v2 변환과 기준선 재채점

1. 검증기 통과 후 v2 canonical과 manifest를 만들고 SHA-256을 기록한다.
2. v1 대비 변화를 요약한다: 클래스별 kept/adjusted/redrawn/ignore 수, 박스 면적 변화(중앙값, 분위).
   v1 `foot_adjusted` 51행은 v2에서 박스 하단 중앙으로 재계산되므로, 박스 변경 효과와 구분해 별도 항목으로 보고한다.
3. **GPU 재실행 없이** TASK-007 A 실행(_02)의 `detections.csv`와 TASK-006 `_02` 추적 결과를 GT v2로 다시 채점한다.
   지표와 매칭 규칙은 TASK-006·TASK-007과 같다. v1 결과와 나란히 보고한다.
4. 일관성 점검 결과(IoU 분포)를 보고한다. 점검은 재검토 완료 뒤 사용자가 날을 바꿔 한다.
5. `rider_inside_vehicle`은 50% 기준을 적용하고, 설정에 기록된 30%·50%·70% 민감도 건수를 confidence operating point와 IoU 기준별로 나란히 보고한다. 이 집계는 GT 매칭 후 남은 person 검출에 한정한다.
5. **체크포인트 2**: 결과 요약을 보고하고 대기한다.

### 하지 않을 일

- GT v1 파일, 태그, manifest 수정
- 객체 목록·visibility 정본 수정
- 학습 라벨 작성, 미세조정, 전체 영상 GPU 실행
- 검출·추적·필터 설정 변경
- 체크포인트 보고 없이 커밋·병합

## 체크포인트

1. 1단계 끝: 코드·테스트·실행 명령 보고 후 대기
2. 3단계 끝: v2 요약, 재채점 결과, 일관성 점검 보고 후 대기
3. 커밋 전: 변경 파일 목록과 diff 요약 보고 후 대기(코드, 데이터, 산출물은 커밋을 나눈다)

## 완료 조건

- 전체 `.venv/bin/pytest` 통과
- GT v2 canonical, manifest, SHA-256 기록
- v1/v2 나란히 비교한 재채점 결과 문서
- `DECISION_LOG.md`에 2026-11-05 라벨 규칙 결정(D1~D5)과 GT v2 생성 기록
- README "현재 상태" 갱신

## 완료 보고(Codex 작성)

- 변경 파일:
- 실행한 명령과 결과:
- 바뀐 설정과 영향 단계:
- 한계와 미해결:
