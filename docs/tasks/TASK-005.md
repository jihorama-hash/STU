# TASK-005: R01 위치 GT v1 동결 및 무결성 기록

- 상태: ready
- 작성: Codex / 승인: 사용자 / 작성일: 2026-11-02
- 브랜치: task/005-r01-gt-v1-freeze

## 목적

R01 객체·가시성·위치 정본을 v1으로 동결해 버전과 파일 무결성을 manifest 및 결정 기록에 남긴다.
단일 검토자 자료이므로 동결 버전이 기록되어도 `dataset_status`와 행별 `review_status`는 `draft`를 유지한다.

## 읽을 문서

- `docs/PROJECT_RULES.md`
- `README.md`
- `docs/validation/DECISION_LOG.md`
- `data/ground_truth/object_track_v1/DATA_DICTIONARY.md`
- `data/ground_truth/object_track_v1/ground_truth_manifest.json`

## 범위

1. 정본 `gt_objects.csv` 50행, `gt_visibility_intervals.csv` 143행, `gt_observations.csv` 960행을 검증한다.
2. 각 정본 CSV의 SHA-256을 계산한다. 이번 동결 대상은 위 세 파일이며 아직 생성되지 않은 association·interaction·audit 파일은 포함하지 않는다.
3. manifest에 `frozen_version: v1`과 정본 파일별 경로·SHA-256을 기록하고, `dataset_status=draft`를 유지한다.
4. `DATA_DICTIONARY.md`에 동결 메타데이터 필드를 정의하고, `DECISION_LOG.md`에 동결 결정·단일 검토자 상태·해시를 기록한다.
5. README 현재 상태를 갱신한다. 변경 요약과 해시를 사용자에게 보여 주고 확인을 받은 뒤 커밋·push한다.
6. 승인 후 annotated Git tag `gt-r01-v1`을 만들고 원격에 push한다.

## 하지 않을 일

- 정본 관측·객체·가시성 값을 수정하거나 `review_status`/`dataset_status`를 승격하지 않는다.
- association, interaction, auto-track audit을 생성하지 않는다.
- 파일 해시 산출 뒤 정본 CSV를 다시 쓰거나 변환하지 않는다.

## 체크포인트

1. 파일별 행 수·SHA-256과 manifest/DECISION_LOG diff를 먼저 보고하고 사용자 확인을 기다린다.
2. 확인 전에는 커밋·push 및 Git tag 생성을 하지 않는다.

## 완료 조건

- 세 정본 CSV의 경로·SHA-256이 manifest와 DECISION_LOG에서 일치한다.
- `dataset_status` 및 행별 검토상태가 `draft`다.
- `gt-r01-v1` 태그가 해당 동결 커밋을 가리키고 원격에 존재한다.
- README 현재 상태, manifest, 데이터 사전, DECISION_LOG가 서로 일치한다.

## 완료 보고(Codex 작성)

- 변경 파일:
- 파일별 행 수 및 SHA-256:
- 검증 결과:
- 커밋 및 태그:
- 한계와 미해결:
