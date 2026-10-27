# 오프라인 데모

이 디렉터리에는 검증된 분석 산출물을 읽는 UI를 둔다. 현재 첫 COCO YOLO11m
사전 계산 번들이 연결되어 트랙·관측점·클래스별 통계와 수동 확인된 PET 사건 2건을
표시한다. 사건 탭에는 6초 영상, ROI 오버레이, 시간순 필름스트립과 검증 상태가 나온다.
예시 수치를 실제 분석 결과처럼 표시하지 않는다.

예정 기술 스택은 Python 기반 Streamlit이며, 데모 패키지만 복사해 GPU 없이 실행하는
`precomputed` 모드를 기본으로 한다.

## 실행

```bash
python3 -m pip install -e '.[demo]'
streamlit run apps/demo/app.py
```

결과 패키지가 없으면 빈 상태와 안내문만 표시한다. 임의의 예시 통계를 실제 결과처럼
표시하지 않는다.

번들 재생성:

```bash
PYTHONPATH=src python3 scripts/build_demo_bundle.py
```

현재 개요 번들의 추적 상태는 `track-validated`이며, 사건 탭에는 별도 수동검토를
통과한 `confirmed` PET 사건만 표시한다. TTC는 영상평면 참고값으로 명시한다.
