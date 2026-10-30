# R01 위치 박스 입력 안내

이 도구는 원본 영상만 보고 객체 위치를 직접 표시하는 블라인드 GT 입력기다. 자동 검출·추적 결과는 읽거나
표시하지 않는다. 사용자가 그린 박스와 발점만 `gt_observations_R01.csv`에 저장한다.

## 1. 입력 기준

- 객체별 `visible`·`partially_occluded` 분모 포함 구간에서 다음 프레임을 입력한다.
  - 각 구간의 시작 프레임과 끝 프레임
  - 그 사이에서 `(frame_index - 4196)`이 30의 배수인 프레임
- `fully_occluded`와 `not_observable` 구간에는 입력 프레임이 없다.
- 박스와 발점 좌표는 원본 3840×2160 영상 기준이다. 발점은 기본적으로 박스 하단 중앙이다.
- 보간은 하지 않는다. 박스를 찾지 못하거나 신원을 판단하기 어려우면 사유를 선택해 건너뛴다.

## 2. 실행

먼저 WSL(Ubuntu)의 STU 저장소 루트(`/home/jiho/STU`)에서 입력을 검증한다.

```bash
PYTHONPATH=src .venv/bin/python apps/demo/blind_gt_review.py --box-input --validate-only
```

- 실행 위치: WSL(Ubuntu), 저장소 루트
- 기능: 정본 객체·가시성 GT와 기존 작업 관측·건너뛰기 파일을 검사하고 anchor 대비 관측·건너뛰기·미입력 수를 표시한다.
- 정상 결과: `annotation validation: OK`와 함께 `anchors`, `observations`, `skips`, `missing` 수가 표시된다.

검증 후 같은 WSL 터미널에서 서버를 시작한다.

```bash
PYTHONPATH=src .venv/bin/python apps/demo/blind_gt_review.py --box-input
```

- 실행 위치: WSL(Ubuntu), 저장소 루트
- 기능: 로컬 블라인드 입력 서버를 연다. 터미널 창을 켜 둔다.
- 정상 결과: `blind GT box input: http://127.0.0.1:8502`가 표시된다.

Windows 브라우저 주소창에 `http://127.0.0.1:8502`를 입력한다. WSL 터미널에서 서버를 중지할 때는 `Ctrl+C`를
누른다.

## 3. 화면과 입력

- 위쪽에서 객체 ID, class, 객체 메모, 현재 anchor, 객체별 완료 상태와 전체 진행률을 확인한다.
- 페이지는 브라우저 창의 사용 가능한 화면 전체를 채운다. 오른쪽 위 `⛶ 전체 화면`을 누르면 브라우저 전체
  화면 모드로 전환할 수 있다.
- 왼쪽은 전체 원본 프레임이다. 클릭하면 오른쪽 확대창의 중심을 옮기고, 파란 사각형은 확대 범위를 나타낸다.
- 오른쪽 확대 입력창은 원본 프레임을 사용한다. 첫 박스를 입력할 때는 전체 프레임을 클릭해 객체 주변으로
  중심을 옮긴다. 이후에는 같은 객체의 직전 두 GT 박스를 이용해 다음 위치를 선형 예측한다. 확대창 위에서
  마우스 휠을 굴리면 포인터 위치를 중심으로 최대 30배까지 확대·축소한다.
- 확대창에서 기존 박스 안을 드래그하면 박스 전체와 발점이 함께 움직인다(박스 안에서 마우스 커서가 이동 모양으로 바뀐다). 박스 밖을 드래그하면 새 박스를 그린다. `박스 다시 그리기`로 지우고 새 박스를 그릴 수도 있다.
- 발점은 박스 하단 중앙으로 자동 설정된다. `F`를 누른 뒤 확대창에서 박스 안을 클릭하면 발점을 수정한다.
  박스 밖을 클릭하면 저장되지 않고 화면에 안내가 나온다. 수정된 행에는 `foot_adjusted`가 notes에 기록된다.
- `C`는 같은 객체의 직전 수동 GT 박스를 복사한다. 복사한 박스를 저장하면 notes에
  `copied_from_previous`가 기록된다. 복사 후 객체 위치에 맞게 박스를 조정한다.
- `같은 프레임 다른 객체 박스`를 끄거나 켜면 이미 입력한 다른 객체의 박스와 ID 표시를 숨기거나 나타낸다.
- 저장되지 않은 박스가 있을 때 앵커나 객체를 이동하면 확인 경고가 나온다. `Enter`는 박스가 있을 때 저장 후
  다음 anchor로 이동한다. 박스도 건너뛰기도 없는 anchor에서는 이동하지 않는다.
- `K` 또는 건너뛰기 버튼을 눌러 사유를 선택하고 저장한다. 건너뛰기 행에는 관측 박스를 만들지 않는다.
- 정본 visibility GT가 아직 `visible` 또는 `partially_occluded`로 표시하지만 객체가 더 일찍 사라진 경우에도 해당 앵커는 `K`로 기록한다. 객체가 화면 밖으로 나가 찾을 수 없으면 `not_found`, 화면 안에 있으나 가림이 정본보다 심해 위치를 판독할 수 없으면 `occluded_more_than_marked`를 선택한다.
- **박스 입력이 진행 중일 때는 Gate 3-A2 작업표를 수정하지 않는다.** 입력을 모두 마친 뒤 건너뛰기 요약을 확인하고, 원본 영상을 다시 보며 visibility 시작·종료 경계를 재판정한다. 실제 화면 이탈로 객체의 최초·최종 관측 범위가 바뀌면 객체 inventory의 `first_visible_frame_index`/`last_visible_frame_index`도 visibility 전체 범위와 맞춘다. 단순히 skip 사유를 visibility 사유로 복사하지 말고, 실제 상태와 원인을 판정한다.
- 각 확정 입력은 즉시 디스크에 반영되며, 브라우저나 서버를 다시 열어도 저장된 위치부터 이어서 진행한다.

## 4. 단축키

| 키 | 동작 |
|---|---|
| `←` / `→` | 이전 / 다음 anchor |
| `Enter` | 현재 박스 저장 후 다음 anchor; 박스 없이 건너뛰기도 없으면 이동하지 않음 |
| `K` | 건너뛰기 사유 선택 창 열기 |
| `Ctrl+Z` | 현재 anchor의 마지막 입력 변경 되돌리기 |
| `F` | 발점 수정 모드 전환 후 확대창에서 클릭 |
| `C` | 같은 객체의 직전 GT 박스를 복사해 표시한다. 박스 위치·크기를 확인하거나 조정한 뒤 Enter로 저장한다. |
| `V` | 현재 표시 중인 프레임에 직전 GT 박스를 복사하고 즉시 저장한 뒤 다음 anchor로 이동한다. 저장 발점은 복사한 박스에서 다시 계산하고 `copied_from_previous`를 기록한다. 직전 박스가 없으면 아무 행도 저장하지 않는다. |
| `P` | 현재 anchor 전후 1초 원본을 확대창에서 재생/중지 |
| `N` / `Shift+N` | 다음 / 이전 객체 |
| `+` / `-` / `0` | 확대 / 축소 / 기본 배율로 맞춤 |
| `Esc` | 진행 중인 드래그 또는 발점 수정 취소 |

person·bicycle은 3배, car·motorcycle·bus·truck은 1배에서 시작한다. `+`/`-`로 바꾼 배율은 같은 객체의 다음
anchor에서도 유지되며, 객체를 바꾸면 해당 class의 기본 배율로 돌아간다.

`C`는 저장 전에 박스를 조정할 수 있는 복사 동작이고, `V`는 현재 프레임을 확인한 상태에서 한 anchor만 복사·저장하고
다음으로 이동하는 빠른 입력 동작이다. `V`도 각 프레임을 화면에 표시하고 한 번씩 저장한다. 여러 anchor를 보지 않고
일괄 적용하지 않는다.

박스 크기가 같은 객체의 중앙값보다 폭 또는 높이 기준 40% 이상 큰 입력을 확인하려면 WSL 저장소 루트에서 다음을 실행한다.

```bash
PYTHONPATH=src .venv/bin/python apps/demo/blind_gt_review.py --size-outliers
```

이 검사는 객체 ID, 프레임, 박스 크기, 객체별 중앙값 대비 배수를 출력한다. 작업 파일은 수정하지 않는다.

## 5. 저장 파일과 재검증

- 위치 작업 파일: `data/ground_truth/object_track_v1/review/gt_observations_R01.csv`
- 건너뛰기 기록: `data/ground_truth/object_track_v1/review/gt_observation_skips_R01.csv`
- 두 파일은 작업용이다. 정본 `gt_observations.csv`로 변환하지 않는다.
- **입력을 마칠 때마다 두 작업 파일을 함께 커밋하고 push해 원자료를 백업한다.** 서버를 종료한 뒤 WSL 저장소
  루트에서 아래 명령을 실행한다. 입력이 계속 진행 중이어도 각 시점의 작업 상태를 저장할 수 있다.

  ```bash
  git add -- data/ground_truth/object_track_v1/review/gt_observations_R01.csv data/ground_truth/object_track_v1/review/gt_observation_skips_R01.csv
  git commit -m "data: R01 box progress 54/971"
  git push origin task/003-gt-box-annotation-tool
  ```

  다음 백업 때는 커밋 제목의 진행 수치를 최신 관측/전체 앵커 수로 바꾼다. 명령은 작업 브랜치에서 실행하며,
  정본 GT 파일은 이 백업에 포함하지 않는다.
- 박스 범위, 프레임 경계, 객체 class, 중복, visibility 분모와 누락 anchor 수를 다시 검사하려면 WSL 저장소
  루트에서 다음 명령을 실행한다.

```bash
PYTHONPATH=src .venv/bin/python apps/demo/blind_gt_review.py --box-input --validate-only
```

- 정상 결과: 입력 오류가 없으면 `annotation validation: OK`가 출력된다. 아직 남은 anchor는 `missing`으로
  표시되며 이는 작업 진행률이지 입력 오류가 아니다.

## 6. 입력 완료 후 visibility 경계 재검토

박스 입력을 마친 뒤에만 아래 순서로 작업표와 정본 visibility GT를 갱신한다. 변환기는 `gt_objects.csv`,
`gt_visibility_intervals.csv`와 manifest의 변환 시각을 갱신하므로, 실행 전 변경 예정 파일과 백업 위치를 확인한다.

1. WSL 저장소 루트에서 건너뛰기 목록을 객체·사유별로 요약한다.

   ```bash
   PYTHONPATH=src .venv/bin/python apps/demo/blind_gt_review.py --skip-summary
   ```

   객체마다 건너뛴 앵커 프레임이 사유별로 출력된다. 요약은 현재 canonical GT 기준으로 작업 파일을 검증하므로,
   가시성 경계를 수정하기 전에 실행한다.

2. 요약에 나온 프레임을 원본 영상에서 다시 확인한다. `not_found`는 화면 이탈 여부와 실제 마지막 관측 시점을,
   `occluded_more_than_marked`는 가림이 시작된 시점과 `fully_occluded` 전환 시점을 확인한다. 화면 경계·화질 등으로
   신뢰성 있게 판독할 수 없는 구간은 `not_observable` 기준을 적용한다. 판정이 불확실하면 경계를 임의로 추정하지 않는다.

3. 확인 후에만 `gate3a2_visibility_R01.csv`의 경계를 고친다. 객체의 관측 범위가 바뀌면
   `gate3a2_object_inventory_R01.csv`의 시작·종료 프레임도 visibility 구간의 시작·종료와 일치시킨다. 모든 경계는
   짝수 평가 grid에 두고, 객체별 구간을 겹침이나 공백 없이 이어지게 한다. 수정 전 작업표와 현재 canonical CSV의
   사본을 보존하고, `gt_observations_R01.csv` 및 skip 원본은 이 절차에서 자동으로 수정하지 않는다.

4. 변환 전 worksheet 검증을 실행한다.

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/blind_gt_review_viewer.py --validate-only
   ```

   오류가 있으면 먼저 작업표를 검토·수정하고, 통과 전에는 변환하지 않는다.

5. TASK-002 변환을 다시 실행한다. 이 명령은 두 canonical CSV와 manifest의 `updated_at_utc`를 갱신한다.

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/ground_truth/build_canonical_gt.py
   ```

   정상 결과는 `Wrote ... object rows and ... visibility rows.`이다. 매핑 누락이나 worksheet 오류가 있으면 변환이
   중단되며 canonical 파일은 쓰지 않는다.

6. 변환 후 위치 입력 작업을 다시 검증한다.

   ```bash
   PYTHONPATH=src .venv/bin/python apps/demo/blind_gt_review.py --box-input --validate-only
   ```

   경계를 바꿔 denominator 밖으로 빠진 프레임이 기존 관측·skip 작업 파일에 남아 있으면 validator가 해당 행을
   보고한다. 원본 작업 파일을 보존한 상태에서 새 경계와 일치하는지 검토한 뒤에만 정리하고, 요약·검증 결과 및
   수정된 작업표를 검토 기록에 남긴다.
