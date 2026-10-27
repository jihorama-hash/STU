#!/usr/bin/env bash
# 저장소 루트에 SNAPSHOT.md 를 생성한다.
# 사용자가 "스냅샷 갱신"이라고 요청하면 이 스크립트를 다시 실행한다.
#
# 대상 파일 목록(TARGET_FILES)은 2026-08-13 사용자 확인을 거쳐 고정한 것이다.
# 새 문서를 프로젝트 지식에 올리기로 하면 이 배열에 경로를 추가하고,
# 이 스크립트 자체를 커밋해 목록 변경 이력을 남긴다.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

TARGET_FILES=(
  "CLAUDE.md"
  "clips.yaml"
  "DJI_0483_INTEGRITY_VERIFICATION.md"
  "MIGRATION_PLAN.md"
  "PHASE0_CHECKPOINT_A_REPORT.md"
  "docs/무신호횡단보도_작업지시서_ClaudeCode_v01.md"
  "docs/무신호횡단보도_작업지시서_ClaudeCode_v02.md"
  "docs/무신호횡단보도_구현사양서_v01.md"
  "docs/무신호횡단보도_구현사양서_v02_CEI개정분.md"
  "docs/무신호횡단보도_파라미터_v02.yaml"
  "docs/무신호횡단보도_지표정의서_v03.md"
  "docs/무신호횡단보도_지표정의서_v04_CEI개정분.md"
  "docs/06_ClaudeCode_전달지시문_자기완결형_v01.md"
  "docs/참고문헌_R01_InDeV_D3_1_Surrogate_Measures_of_Safety_2018.md"
)

OUT="SNAPSHOT.md"
GENERATED_AT=$(date '+%Y-%m-%d %H:%M:%S %Z')
BRANCH=$(git rev-parse --abbrev-ref HEAD)
COMMIT_HASH=$(git rev-parse --short HEAD)
COMMIT_SUBJECT=$(git log -1 --pretty=%s)

UNTRACKED=()
ROWS=()

for f in "${TARGET_FILES[@]}"; do
  if [ ! -f "$f" ]; then
    ROWS+=("| \`$f\` | (파일 없음) | - | - |")
    continue
  fi
  MTIME=$(date -r "$f" '+%Y-%m-%d %H:%M:%S')
  HASH=$(sha256sum "$f" | cut -c1-8)
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    TRACKED="tracked"
  else
    TRACKED="untracked"
    UNTRACKED+=("$f")
  fi
  ROWS+=("| \`$f\` | ${MTIME} | \`${HASH}\` | ${TRACKED} |")
done

{
  echo "# SNAPSHOT"
  echo
  echo "생성 시각: ${GENERATED_AT}"
  echo
  echo "## git 상태"
  echo
  echo "- 브랜치: ${BRANCH}"
  echo "- 최신 커밋: \`${COMMIT_HASH}\` ${COMMIT_SUBJECT}"
  echo
  echo "## 프로젝트 지식 대상 파일"
  echo
  echo "| 경로 | 최종 수정 시각 | sha256(앞 8자리) | git 추적 |"
  echo "|---|---|---|---|"
  for row in "${ROWS[@]}"; do
    echo "$row"
  done
  echo
  echo "## untracked 파일"
  echo
  if [ "${#UNTRACKED[@]}" -gt 0 ]; then
    echo "다음 대상 파일은 아직 git에 추적되고 있지 않다:"
    echo
    for f in "${UNTRACKED[@]}"; do
      echo "- \`$f\`"
    done
  else
    echo "없음 (대상 파일 전부 git 추적 중)"
  fi
} > "$OUT"

echo "생성 완료: $OUT"
