# TASK-004: 개선 전후 비교를 연구 범위에 반영(문서)

- 상태: ready
- 작성: Aside / 승인: 사용자 / 작성일: 2026-11-02
- 브랜치: task/004-before-after-scope

## 목적

개선 후 촬영 계획이 확정되어 연구 범위를 "개선 전 현황 진단"에서 "정문 교차로 개선 전후 효과 분석"으로 넓힌다.
문서와 기록만 고친다. 코드, 설정 값, GT 데이터는 바꾸지 않는다.

## 사용자 결정 (2026-11-02)

1. 드론 촬영 지점은 개선안 도면의 정문 교차로(A4, 정문 인근 3)다.
2. 개선공사 완료 후 한 달 이내에 개선 후 드론 촬영을 한다. "다음 촬영 없음"은 개선 전 현황을 다시 찍을 수 없다는 뜻이었다.
3. 시공안은 "정문 교차로 검토안"의 (개선안) 3지교차로다.

## 읽을 문서

- `docs/PROJECT_RULES.md`, `README.md`, `docs/validation/DECISION_LOG.md`
- 사용자가 함께 커밋한 `docs/methodology/AFTER_FILMING_PLAN.md`, `docs/methodology/BEFORE_AFTER_ANALYSIS_PLAN.md`

## 범위

1. `README.md`
   - "프로젝트 성격"과 "연구 목표"를 개선 전후 효과 분석으로 고친다. 개선 전 영상은 여전히 재취득 불가한 기록이다.
   - "할 수 있는 것과 없는 것" 표에서 "개선 전후 비교: 불가"를 "가능(개선 후 촬영 예정, 정문 교차로)"으로 고치고
     두 계획서를 근거로 적는다. CEI·지점 PDI·3곳 통계적 순위 불가는 유지한다.
   - "자료" 표에 개선 전후 도면 3종과 개선 후 촬영 예정을 추가한다.
2. `docs/PROJECT_RULES.md`
   - 1절(프로젝트 전제)과 3절(지표 범위)을 1과 같은 내용으로 고친다.
   - 개선 후 원본(`data/raw/after/`)도 개선 전과 같은 보존 규칙을 적용한다고 적는다.
   - 개선 전후는 같은 파이프라인 버전과 설정으로 분석한다는 규칙을 추가한다.
3. `docs/validation/DECISION_LOG.md`에 위 사용자 결정 3건과 "결과는 개선 패키지 전체 효과로 해석"을 기록한다.
4. 도면 관리
   - 도면 PDF 3종은 Git에 넣지 않는다. 로컬 `references/drawings/`에 두고(이미 `references/`는 Git 제외),
     `manifests/drawings.csv`(`drawing_id,filename,date,description,size_bytes,sha256`)에 기록한다.
   - 원본 위치: `/mnt/d/서울과기대 도면/` (사용자가 복사 명령을 실행하지 않았으면 경로만 확인하고 보고).
5. `docs/validation/MIGRATION_RECORD.md`나 다른 기존 문서의 "전후 비교 불가" 문구를 찾아 목록으로 보고하고, 현재 상태를
   설명하는 문서만 고친다. `docs/legacy/`는 고치지 않는다.

### 하지 않을 일

- 코드, `configs/`, GT 데이터 수정
- 두 계획서 내용 변경(오탈자 외). 고칠 점이 있으면 보고만 한다.

## 체크포인트

1. 커밋 전에 바뀐 문구 요약과 변경 파일 목록을 보고하고 사용자 확인을 받는다.

## 완료 조건

- `.venv/bin/pytest` 통과(문서 변경이지만 기준선 확인)
- 아래 완료 보고 작성 후 커밋, main 병합, push

## 완료 보고(Codex 작성)

- 변경 파일: `README.md`, `docs/PROJECT_RULES.md`, `docs/validation/DECISION_LOG.md`,
  `manifests/drawings.csv`, 이 지시문.
- 바뀐 문구 요약: 연구 범위를 정문 교차로 개선 전후 효과 분석으로 확장하고, 개선 전 영상의 재취득 불가와 개선 후 촬영 예정,
  같은 파이프라인·설정 적용, 개선 패키지 전체 효과 해석을 명시했다. 자료 표에 도면 3종과 개선 후 촬영 계획을 추가했다.
- "전후 비교 불가" 문구 위치와 처리: README 및 PROJECT_RULES 현행 서술을 갱신했다. DECISION_LOG의 2026-10-27 항목은 당시 결정의
  이력으로 보존하고 2026-11-02 결정을 후속 기록으로 추가했다. `docs/validation/MIGRATION_RECORD.md`에는 해당 표현이 없다.
- 한계와 미해결: 개선 후 촬영 전이므로 효과 결과는 아직 산출되지 않았다. 도면 원본은 로컬 `references/drawings/`에 보존하며 Git에는
  올리지 않는다. 대조 지점 부재, 계절 차이, 짧은 적응 기간 및 교차로 형태 변경은 해석 한계로 남는다.
