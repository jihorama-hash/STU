# 작업 지시문

Codex에 맡기는 작업은 이 폴더의 `TASK-NNN.md` 파일 하나로 정의한다. 사용자는 Codex에 다음 한 줄만
전달한다.

```text
docs/tasks/TASK-NNN.md를 읽고 docs/PROJECT_RULES.md에 따라 수행해.
```

## 번호와 상태

- 번호는 001부터 순서대로 쓰고 재사용하지 않는다.
- 상태: `draft`(작성 중) → `ready`(전달 가능) → `in_progress` → `checkpoint`(보고 후 대기) →
  `done` 또는 `cancelled`

## 형식

```markdown
# TASK-NNN: 제목

- 상태: ready
- 작성: Aside / 승인: 사용자 / 작성일: YYYY-MM-DD
- 브랜치: task/NNN-짧은설명

## 목적
한두 문장.

## 읽을 문서
- 경로 목록

## 범위
- 할 일
- 하지 않을 일(명시)

## 체크포인트
1. 멈추고 보고할 지점과 보고 내용

## 완료 조건
- 테스트, 산출물, 문서 갱신 항목

## 완료 보고(Codex 작성)
- 변경 파일:
- 실행한 명령과 결과:
- 바뀐 설정과 영향 단계:
- 한계와 미해결:
```
