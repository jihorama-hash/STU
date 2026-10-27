# Windows 노트북용 Blind-GT Reviewer

이 묶음은 Gate 3-A2 Pass 3 visibility interval 수동 판독용이다. 자동 검출,
자동 track, overlay, ROI 및 interaction 후보는 포함하지 않는다. Reviewer는 영상을
보여줄 뿐 worksheet 값을 자동 생성하거나 수정하지 않는다.

## 1. 노트북으로 옮길 파일

Windows bundle 전체와 원본 `DJI_0482.MP4`를 같은 외장 저장장치로 옮긴다. 영상은
노트북에서 다음 위치에 두어야 한다.

```text
data\raw\before\DJI_0482.MP4
```

공식 working worksheet는 다음 두 파일이다.

```text
data\ground_truth\object_track_v1\review\gate3a2_object_inventory_R01.csv
data\ground_truth\object_track_v1\review\gate3a2_visibility_R01.csv
```

임시 `Object_Review.xlsx`와 `_T.csv`는 bundle에 포함하지 않는다.

## 2. 최초 1회 설치

1. Windows용 64-bit Python 3.11 이상을 설치한다.
2. 인터넷에 연결된 상태에서 `scripts\windows\setup_blind_gt_review.bat`를 더블클릭한다.
3. 설치가 완료되면 `scripts\windows\verify_source_video.bat`를 실행한다.

설치 과정은 bundle 내부의 `.venv-review`에 `numpy`와 headless OpenCV만 설치한다.
YOLO, model weight 또는 자동 분석 package는 설치하지 않는다.

## 3. 매 작업 시작

1. `scripts\windows\run_blind_gt_review.bat`를 더블클릭한다.
2. 기본 브라우저에서 `http://127.0.0.1:8502`가 자동으로 열린다.
3. `gate3a2_visibility_R01.csv`를 Excel 또는 UTF-8 CSV 편집기로 별도 연다.
4. 원본 영상만 보면서 visibility interval을 입력한다.

검은 명령창은 reviewer 서버다. 작업 중에는 닫지 않는다. 종료할 때 그 창에서
`Ctrl+C`를 누른다. 포트 8502를 이미 다른 프로그램이 사용하면 그 프로그램을 먼저
종료한다.

## 4. 저장 및 검증

- CSV 헤더와 열 순서를 바꾸지 않는다.
- CSV 형식과 UTF-8 인코딩을 유지한다.
- Excel에서 저장할 때 `CSV UTF-8 (쉼표로 분리)` 형식을 사용한다.
- 상태 경계는 `4196, 4198, ..., 5994` grid에 둔다.
- 허용 상태는 `visible`, `partially_occluded`, `fully_occluded`,
  `not_observable`이다.

저장 후 `scripts\windows\validate_blind_gt_worksheets.bat`를 실행한다. Validator는
경고만 보고하며 사람의 값을 수정하거나 추정하지 않는다.

작업을 마칠 때 수정한 `gate3a2_visibility_R01.csv`를 원래 연구 PC로 복사한다.
파일을 덮어쓰기 전에 날짜가 포함된 백업 사본을 별도로 보관한다.
