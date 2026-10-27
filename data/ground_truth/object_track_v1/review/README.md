# Gate 3-A2 Blind Object Inventory — R01

이 디렉터리의 CSV는 R01 수동 판독용 working sheet이며 canonical GT가 아니다.
`gt_objects.csv`, `gt_visibility_intervals.csv`, `gt_observations.csv`에는 이 검토가
끝나기 전까지 행을 추가하지 않는다.

## Blind 원칙

원본 `data/raw/before/DJI_0482.MP4`만 사용한다. YOLO 결과, 자동 class, detection box,
track ID, trajectory, confidence, ROI 자동 판정, interaction 후보 및 자동 결과가 포함된
영상이나 표는 열지 않는다.

평가 grid는 다음 900개 source frame으로 고정한다.

```text
4196, 4198, 4200, ..., 5994
```

객체와 visibility 경계는 반드시 이 grid에서 선택한다. validator는 잘못된 값을 경고할
뿐 값을 추론하거나 수정하지 않는다.

## Viewer 실행

GUI가 포함된 OpenCV와 desktop display가 필요하다. `opencv-python-headless`만 설치된
환경에서는 창을 열 수 없다.

```bash
PYTHONPATH=src .venv/bin/python scripts/blind_gt_review_viewer.py
```

Worksheet만 검증하려면 GUI 없이 실행한다.

```bash
PYTHONPATH=src .venv/bin/python scripts/blind_gt_review_viewer.py --validate-only
```

### 조작법

| 키 | 동작 |
|---|---|
| `←` / `→` | 이전/다음 evaluation frame |
| `Shift+←` / `Shift+→` | 약 1초 이전/다음; backend가 modifier를 전달하지 않으면 `A` / `D` 사용 |
| `J` / `L`, `PageUp` / `PageDown` | 약 5초 이전/다음 |
| `Space` 또는 `p` | evaluation frame 연속재생/일시정지 |
| `g` | terminal에서 특정 source frame으로 이동; 홀수 또는 범위 밖 값은 거부 |
| `+` / `-` / `0` | 확대/축소/전체화면 맞춤 |
| 마우스 왼쪽 클릭 | 확대 중심 이동 |
| `v` | working sheet 검증, terminal에 경고 출력 |
| `h` 또는 `?` | terminal에 도움말 출력 |
| `q` 또는 `Esc` | 종료 |

Viewer는 원본 3840×2160 frame을 읽어 화면 크기에 맞춰 표시한다. 확대는 표시 viewport만
바꾸며 원본이나 worksheet를 수정하지 않는다. 화면에는 frame index, PTS, grid 상태만
표시한다.

## 객체 ID

| Class | ID |
|---|---|
| `person` | `P001`, `P002`, ... |
| `bicycle` | `B001`, `B002`, ... |
| `car` | `C001`, `C002`, ... |
| `motorcycle` | `M001`, `M002`, ... |
| `bus` | `BUS001`, `BUS002`, ... |
| `truck` | `T001`, `T002`, ... |

ID는 자동 track ID와 관련이 없다. 여러 사람이 같이 걸어도 각각 기록하고, 자전거 또는
motorcycle 탑승자는 사람과 탑승수단을 별도 객체로 기록한다. 동일 객체임이 확실하지
않으면 연결하지 않고 새 ID를 부여한 뒤 `notes`에 `uncertain_reidentification`을 남긴다.

## R01 검토 절차

### Pass 1 — Object inventory

140–200초 전체를 반복 재생한다. 실제 물리 객체를 class별로 식별하고 provisional ID를
부여한다. 움직이지 않는 명확한 차량도 포함한다. class 자체를 신뢰성 있게 판별할 수 없는
형상은 억지로 객체로 만들지 않는다.

`gate3a2_object_inventory_R01.csv`에 다음 수동 판정만 입력한다.

```text
gt_object_id, object_class, first_visible_frame_index,
last_visible_frame_index, in_scope, exclusion_reason, notes
```

### Pass 2 — First/last frame

각 객체의 최초·최종 가시 frame을 evaluation grid에서 확정한다. raw 홀수 frame에서 처음
나타났다면 다음 grid frame에서 실제로 보이는지 확인한 뒤 그 짝수 frame을 기록한다.

### Pass 3 — Visibility intervals

`gate3a2_visibility_R01.csv`에 객체별 상태 구간을 기록한다. 허용 상태는 다음 네 개다.

- `visible`
- `partially_occluded`
- `fully_occluded`
- `not_observable`

상태 경계도 evaluation grid에 있어야 한다. 완전 가림 중 동일성을 확신할 수 없다면 긴
`fully_occluded` interval을 추정하지 않고 ID를 분리한다.

## 입력 예시

아래 행은 형식 설명용이며 DJI_0482에서 실제로 확인된 객체가 아니다. working sheet에
복사하지 않는다.

```csv
P001,person,4210,4388,true,,format_example_only
P001,4210,4388,visible,,format_example_only
```

이번 Gate에서는 bounding box, foot point, interpolation, association 또는 성능지표를
작성하지 않는다.
