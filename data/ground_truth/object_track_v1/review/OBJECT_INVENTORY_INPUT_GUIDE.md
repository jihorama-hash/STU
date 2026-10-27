# Gate 3-A2 객체 Inventory 입력 방법

이 문서는 R01이 `gate3a2_object_inventory_R01.csv`를 작성하는 방법을 설명한다.
이 CSV는 수동 판독용 working sheet이며 아직 canonical `gt_objects.csv`가 아니다.

## 1. 판독 범위

- 원본 영상: `data/raw/before/DJI_0482.MP4`
- 평가 frame: `4196, 4198, 4200, ..., 5994`
- frame 수: 900
- scope: `full_frame`
- class: `person`, `bicycle`, `car`, `motorcycle`, `bus`, `truck`

화면의 보도, 차도, 횡단보도에 있는 객체를 모두 검토한다. 횡단보도 ROI나 차도 여부로
객체를 미리 제외하지 않는다. 움직이지 않는 명확한 정차·주차 차량도 포함한다.

Frame `4196`에 이미 화면 안에 있던 객체도 포함한다. 이 객체의 최초 evaluation frame은
`4196`으로 기록하고 `notes`에 `present_at_window_start`를 남긴다.

## 2. 객체 한 개당 한 행

동일한 물리 객체는 inventory에 정확히 한 행만 기록한다. 같은 객체의 가시성 상태가 여러
번 변해도 inventory 행을 반복하지 않는다. 상태 변화는 visibility worksheet에 여러 행으로
작성한다.

여러 사람이 함께 이동해도 사람마다 별도 객체다. 탑승자와 탑승수단도 별도 객체로 기록한다.

- 자전거 1대와 탑승자 1명: `B001`과 `P001`
- Motorcycle 1대와 운전자 1명: `M001`과 `P002`
- Motorcycle 동승자가 명확히 보이면: 별도 `person` ID 추가
- 자동차·버스·트럭 내부 탑승자: GT 대상 아님

탑승자 존재 또는 class를 신뢰성 있게 판별할 수 없으면 추측해 추가하지 않는다.

## 3. ID 부여 규칙

Class별로 독립된 일련번호를 사용한다.

| Class | ID 형식 |
|---|---|
| `person` | `P001`, `P002`, ... |
| `bicycle` | `B001`, `B002`, ... |
| `car` | `C001`, `C002`, ... |
| `motorcycle` | `M001`, `M002`, ... |
| `bus` | `BUS001`, `BUS002`, ... |
| `truck` | `T001`, `T002`, ... |

권장 번호 순서는 다음과 같다.

1. 먼저 등장한 객체부터 번호를 부여한다.
2. 같은 evaluation frame에서 처음 등장하면 화면 왼쪽에서 오른쪽 순으로 부여한다.
3. 좌우 위치가 거의 같으면 위쪽에서 아래쪽 순으로 부여한다.
4. 한 번 부여한 ID는 이후 객체의 화면상 순서가 바뀌어도 유지한다.

ID는 자동 track ID와 아무 관계가 없다.

## 4. 열별 입력 방법

| 열 | R01 입력 방법 |
|---|---|
| `gt_object_id` | 위 class별 ID 규칙으로 직접 부여한다. 중복 금지 |
| `object_class` | 허용된 여섯 class 중 사람이 직접 판정한 값 |
| `first_visible_frame_index` | 해당 객체를 처음 확인할 수 있는 evaluation frame |
| `last_visible_frame_index` | 해당 객체를 마지막으로 확인할 수 있는 evaluation frame |
| `in_scope` | 원칙적으로 `true` |
| `exclusion_reason` | `in_scope=false`인 특별한 경우에만 반드시 입력 |
| `notes` | 최초 위치·외형·진행방향·탑승관계·identity 불확실성 등 식별 단서 |

첫 frame과 마지막 frame은 반드시 `4196 + 2k` 형태여야 한다. 홀수 raw frame에서 처음
보이더라도 다음 evaluation frame에서 실제로 보일 때 그 짝수 frame을 기록한다.

## 5. 포함과 제외

다음 객체는 포함한다.

- 화면 전체에서 class를 신뢰성 있게 판별할 수 있는 승인 class 객체
- 보도 통행 보행자
- 차도 또는 횡단보도 통행 보행자
- 일부 가려졌지만 사람 또는 차량임을 판별할 수 있는 객체
- 명확한 정차·주차 차량

다음 형상은 억지로 객체로 만들지 않는다.

- 처음부터 끝까지 class를 판별할 수 없을 정도로 작은 형상
- 화면 경계 일부만 보여 class 판정이 불가능한 형상
- 가림 때문에 어떤 승인 class인지 한 번도 확인할 수 없는 대상

실제 객체로 확인했지만 특별한 평가 제외 사유가 있을 때만 `in_scope=false`와 구체적인
`exclusion_reason`을 사용한다. 단순히 판독이 어렵다는 이유로 임의 제외하지 않는다.

## 6. 동일성 및 재식별

일시적으로 가려져도 시간, 위치, 진행방향상 같은 객체임이 명확하면 기존 ID를 유지한다.
같은 객체인지 확신하기 어려우면 사람의 추측으로 연결하지 않는다.

1. 가림 전 객체의 `last_visible_frame_index`를 마지막 신뢰 가능한 frame으로 끝낸다.
2. 다시 나타난 대상을 새 ID로 기록한다.
3. 새 행의 `notes`에 `uncertain_reidentification`을 남긴다.

외형만으로 동일성을 단정하지 않는다. 자동 tracker가 해결해야 할 재식별을 GT 작성자가
추측으로 대신하지 않는다.

## 7. 형식 예시

아래는 입력 형식만 설명하는 가상 예시이며 DJI_0482의 실제 객체 판정이 아니다.

```csv
P001,person,4196,4238,true,,present_at_window_start; dark_top; eastbound
B001,bicycle,4300,4460,true,,ridden_by_P002
P002,person,4300,4460,true,,rider_of_B001
```

관계 표시는 현재 별도 열이 없으므로 `notes`에만 기록한다. 새 class나 새 열을 만들지 않는다.

## 8. 권장 작업 순서

1. 전체 구간을 재생하여 등장 객체를 class별로 메모한다.
2. 객체마다 provisional ID를 부여한다.
3. 각 객체의 첫 등장 부근으로 이동해 정확한 첫 evaluation frame을 찾는다.
4. 마지막 등장 부근으로 이동해 정확한 마지막 evaluation frame을 찾는다.
5. `notes`에 구분 가능한 단서를 짧게 기록한다.
6. ID 중복과 한 객체의 중복 행이 없는지 확인한다.
7. 다음 명령으로 worksheet를 검사한다.

```bash
PYTHONPATH=src .venv/bin/python scripts/blind_gt_review_viewer.py --validate-only
```

Validator는 잘못된 값을 경고할 뿐, 사람 입력을 추론하거나 자동 수정하지 않는다.

