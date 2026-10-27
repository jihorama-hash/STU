# Gate 3-A2 Visibility 입력 방법

이 문서는 R01이 `gate3a2_visibility_R01.csv`를 작성하는 방법을 설명한다. 먼저 객체
inventory를 완료하고 각 `gt_object_id`의 최초·최종 evaluation frame을 확정해야 한다.
이 CSV는 수동 판독용 working sheet이며 아직 canonical
`gt_visibility_intervals.csv`가 아니다.

이번 Gate에서는 bounding box 좌표를 기록하지 않는다.

## 1. 기본 원칙

객체 하나를 최초 frame부터 마지막 frame까지 따라가며 가시성 상태가 바뀔 때마다 구간을
나눈다. 계속 잘 보이는 객체는 한 행이면 충분하다.

모든 시작·종료 frame은 다음 evaluation grid에 있어야 한다.

```text
4196, 4198, 4200, ..., 5994
```

구간 경계는 양 끝을 포함한다. 예를 들어 `4540`까지 `visible`이고 `4542`부터 일부 가림이
시작되면 다음처럼 나눈다.

```text
visible:              ...–4540
partially_occluded:   4542–...
```

## 2. 열별 입력 방법

| 열 | R01 입력 방법 |
|---|---|
| `gt_object_id` | object inventory에 존재하는 ID |
| `start_frame_index` | 해당 상태가 시작되는 evaluation frame |
| `end_frame_index` | 해당 상태가 끝나는 evaluation frame |
| `visibility_status` | 아래 네 허용값 중 하나 |
| `occlusion_reason` | 가림 또는 판독 곤란의 직접 원인 |
| `notes` | identity 판단 근거나 특이사항이 있을 때 입력 |

## 3. Visibility 상태

| 상태 | 판정 기준 | 위치 판독 |
|---|---|---|
| `visible` | 객체와 위치를 신뢰성 있게 판독할 수 있음 | 가능 |
| `partially_occluded` | 일부가 가려졌지만 동일 객체와 위치를 판독할 수 있음 | 가능 |
| `fully_occluded` | 완전히 가려졌지만 전후 흐름상 같은 객체임이 명확함 | 직접 판독 불가 |
| `not_observable` | 경계, 화질, 수목 등으로 사람도 객체 위치나 동일성을 신뢰성 있게 판독할 수 없음 | 신뢰 불가 |

`partially_occluded`와 `fully_occluded`의 차이는 단순히 보이는 면적의 비율이 아니다.
사람이 그 frame에서 동일 객체와 위치를 직접 판독할 수 있으면 `partially_occluded`, 전혀
직접 판독할 수 없으면 `fully_occluded`다.

`not_observable`은 객체가 존재할 가능성만 있고 위치 또는 동일성을 신뢰할 수 없는 경우다.
긴 `not_observable` 구간을 이용해 불확실한 객체를 임의로 연결하지 않는다.

## 4. 구간 연속성

한 객체의 visibility 행은 원칙적으로 object inventory의 전체 frame 범위를 설명해야 한다.

- 첫 interval 시작 = 그 객체의 `first_visible_frame_index`
- 마지막 interval 종료 = 그 객체의 `last_visible_frame_index`
- 인접 interval은 evaluation grid에서 바로 이어짐
- interval끼리 겹치지 않음
- 설명 없는 frame 공백을 만들지 않음

Frame step이 2이므로 한 interval이 `4540`에서 끝나면 다음 interval은 `4542`에서 시작한다.

단, 완전 가림 후 같은 객체인지 확신할 수 없다면 억지로 전체 범위를 연결하지 않는다.
이 경우 object inventory 단계로 돌아가 가림 전 객체를 종료하고, 다시 나타난 대상을 새 ID로
분리하며 `uncertain_reidentification`을 기록한다.

## 5. Occlusion reason

가림 또는 판독 곤란 원인을 사람이 직접 기록한다. 현재 schema에는 고정된 허용값 목록이
없으므로 실제 장면을 설명하는 짧은 용어를 일관되게 사용한다.

권장 표현 예시는 다음과 같다.

- `tree`
- `tree_canopy`
- `vehicle_overlap`
- `pedestrian_overlap`
- `frame_boundary`
- `image_ambiguity`

`visible` 행은 특별한 사유가 없다면 `occlusion_reason`을 비워 둔다. 원인을 확신할 수 없으면
추측하지 말고 `notes`에 판단 곤란 사실을 남긴다.

## 6. 가상 입력 예시

아래는 형식 설명용이며 DJI_0482의 실제 판정이 아니다.

계속 보이는 객체:

```csv
P001,4210,4388,visible,,format_example_only
```

상태가 변하는 객체:

```csv
P002,4500,4540,visible,,format_example_only
P002,4542,4556,partially_occluded,tree,format_example_only
P002,4558,4570,fully_occluded,tree,identity_clear_from_motion
P002,4572,4620,visible,,format_example_only
```

위와 같이 `fully_occluded`로 연결하려면 가림 전후의 시간·위치·진행방향으로 동일 객체임이
명확해야 한다. 불확실하면 P002를 종료하고 재등장 객체에 새 ID를 부여한다.

## 7. 권장 작업 순서

1. Object inventory에서 객체 ID 하나를 선택한다.
2. Viewer의 `g` 키로 그 객체의 첫 frame으로 이동한다.
3. 오른쪽 화살표로 evaluation frame만 따라간다.
4. 상태가 바뀌는 첫 frame을 기록한다.
5. 직전 상태는 그보다 2 작은 evaluation frame에서 종료한다.
6. 마지막 frame까지 반복한다.
7. 같은 ID의 interval에 겹침이나 설명 없는 공백이 없는지 확인한다.
8. 모든 object ID를 반복한다.
9. 다음 명령으로 worksheet를 검사한다.

```bash
PYTHONPATH=src .venv/bin/python scripts/blind_gt_review_viewer.py --validate-only
```

Validator는 상태나 경계를 자동 생성하거나 보정하지 않는다. 이번 Gate에서는
`gt_observations.csv`, bounding box, interpolation 또는 자동 association을 작성하지 않는다.

