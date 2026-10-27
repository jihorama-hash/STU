# AGENTS.md (Codex)

이 저장소의 실행자는 Codex다. 규칙은 `docs/PROJECT_RULES.md` 하나이며, 이 파일에는 규칙을
따로 두지 않는다.

## 시작 전에 읽을 것

1. 사용자가 지정한 작업 지시문 `docs/tasks/TASK-NNN.md`
2. `docs/PROJECT_RULES.md`: 공통 작업 규칙
3. `README.md`: 프로젝트 성격, 할 수 있는 분석과 없는 분석, 현재 상태
4. `docs/validation/DECISION_LOG.md`: 최신 승인 결정
5. 지시문이 가리키는 `docs/methodology/`, `docs/validation/` 문서

## 작업 방식

- 지시문 범위 안에서만 작업하고, 체크포인트에서 멈춰 보고한다.
- 브랜치는 `task/NNN-짧은설명`을 쓴다.
- 끝나면 지시문의 "완료 보고"를 채우고, README "현재 상태"와 `DECISION_LOG.md`를 갱신한다.

## 자주 쓰는 명령

```bash
.venv/bin/pytest
PYTHONPATH=src .venv/bin/python -m roundabout.run_batch --dry-run
PYTHONPATH=src python3 scripts/build_demo_bundle.py
```

전체 영상 GPU 배치와 모델 학습은 사용자 승인 전에는 실행하지 않는다.
