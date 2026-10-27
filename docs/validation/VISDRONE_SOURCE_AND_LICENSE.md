# VisDrone 출처 및 이용조건 확인

확인일: 2026-07-30

## 출처

- 공식 저장소: <https://github.com/VisDrone/VisDrone-Dataset>
- Ultralytics 데이터 설정:
  <https://docs.ultralytics.com/datasets/detect/visdrone>
- 학술 인용: Zhu et al., *Detection and Tracking Meet Drones Challenge*,
  IEEE TPAMI 44(11), 2022, DOI 10.1109/TPAMI.2021.3119563

## 확인 결과

- 공식 저장소는 데이터 다운로드와 학술 인용 정보를 제공한다.
- 확인 시점에 저장소에는 표준 LICENSE 파일이 보이지 않았다.
- Ultralytics 데이터 문서도 VisDrone 데이터 항목을 `No license`로 표시한다.
- Ultralytics의 데이터 변환 설정과 코드에는 AGPL-3.0 고지가 있다.

## 현재 허용 범위

이번 작업에서는 VisDrone을 내부 연구·성능검증용으로만 다운로드하고 학습한다.
VisDrone 원본 데이터, 변환 라벨, 미세조정 가중치는 공개 데모 패키지에 포함하지 않는다.

외부 공개, 배포 또는 상업적 데모에 사용하기 전에는 데이터 권리자에게 이용조건을 확인하고,
Ultralytics 코드·모델의 라이선스도 별도로 검토해야 한다.
