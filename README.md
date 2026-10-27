Vision AI 기반 교통안전 분석 연구 프로젝트

STU 프로젝트는 드론 영상에서 보행자와 차량을 검출·추적하고, 교통 상호작용과 잠재적 위험 상황을 분석하기 위한 Vision AI 기반 연구 프로젝트입니다. 현재는 회전교차로 드론 영상을 활용한 검증을 수행하고 있으며, 향후 무신호 횡단보도, 이면도로, 아파트 단지, 학교 캠퍼스, 산업단지 등 다양한 보행 환경으로 확장할 계획입니다.

🎯 연구 목표

본 프로젝트는 실제 사고 데이터가 아닌 영상 기반 행동 데이터를 활용하여 교통안전성을 평가하는 것을 목표로 합니다.

주요 분석 대상은 다음과 같습니다.

보행자 및 차량 검출
다중 객체 추적(Object Tracking)
이동 궤적(Trajectory) 생성
보행자-차량 상호작용 분석
PET(Post Encroachment Time) 분석
TTC(Time To Collision) 분석
위험 후보 이벤트 식별
PDI(Pedestrian Danger Index) 적용 가능성 검토

현재 구현 범위는 객체 추적 결과 생성부터 ROI 기반 위험 후보 추출까지입니다. 정식 보행자 횡단사건(Crossing Event) 및 PDI 산출은 아직 구현되지 않았습니다.

📊 분석 계층
1. 노출도(Exposure)
보행량
차량량
실제 상호작용 수
2. 운영·행태(Operation & Behavior)
대기시간
횡단경로
양보 행동
감속 및 정지 행동
3. 상충위험(Safety Conflict)
PET
TTC
최소거리
급감속
4. 시설·환경(Environment)
시야 가림
불법 주정차
조명 조건
보도 장애물

🔄 목표 분석 파이프라인
Plain Text
Raw Detections
↓
Raw Tracker Trajectories
↓
Filtered Trajectories
↓
Merged Trajectories
↓
Crossing Events
↓
Interaction Candidates
↓
Reviewed Interaction Events
↓
Yielding / PET / TTC / Minimum Distance
↓
Provisional PDI Screening

각 단계는 재현성과 검증을 위해 별도의 산출물로 저장됩니다.

🛠 기술 스택
Computer Vision
YOLO11m (COCO)
ByteTrack
AI / Data Analysis
Python
PyTorch
OpenCV
NumPy
Pandas
Visualization & Demo
Streamlit

현재 기준선(Baseline)은 COCO YOLO11m + 클래스별 ByteTrack 조합입니다.

📂 프로젝트 구조
Plain Text
STU/
│
├── data/
│ ├── raw/
│ ├── calibration/
│ └── ground_truth/
│
├── src/
│ └── roundabout/
│
├── configs/
│
├── docs/
│ ├── methodology/
│ ├── validation/
│ └── legacy/
│
├── outputs/
│ ├── analysis/
│ └── demo/
│
├── apps/
│ └── demo/
│
└── archive/

⚙️ 환경 설정
Python 버전
Shell
Python 3.10 ~ 3.12

권장:

Shell
Python 3.11

1. PyTorch 설치

GPU 드라이버에 맞는 CUDA 버전을 먼저 설치합니다.

예시(CUDA 13.2):

Shell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu132

2. 프로젝트 설치
Shell
python -m venv .venv
 
.venv/bin/pip install -e ".[analysis,dev,demo]"

또는

Shell
pip install -r requirements.txt

3. 환경 확인
Shell
python src/28_verify_environment.py

환경 검사 내용:

Python 버전
필수 패키지
GPU 인식
CUDA 연산
영상 디코딩 성능
데이터 존재 여부
분석 결과 재현성

✅ 현재 구현 상태
객체 검출(Object Detection)
객체 추적(Object Tracking)
궤적 필터링
궤적 병합
ROI 기반 위험 후보 추출
단계별 CSV 산출물 저장
미구현 항목
Crossing Event 생성
Interaction Event 생성
보행자 횡단사건 분석
A0/A1/B0/B1/B2 자동 분류
정식 PDI 산출
공식 DPD 모델 적용

🚧 연구 진행 현황

현재 보유 데이터:

드론 영상 8개
분석 가능 구간 약 29.31분

현재 데이터 규모는 정식 PDI 산출을 위한 관측 기간 및 대표성을 충족하지 않으므로, 안전등급 산출은 수행하지 않습니다. 대신 PDI 적용 가능성과 입력 변수 산출 가능성을 탐색적으로 검토하고 있습니다.

🎥 Demo

현재 Demo Bundle에는 다음 자료가 포함됩니다.

DJI_0482 추적 결과
ROI 오버레이
차량-차량 PET 검증 사례
시간순 이벤트 필름스트립

실행:

Shell
PYTHONPATH=src python scripts/build_demo_bundle.py
 
PYTHONPATH=src streamlit run apps/demo/app.py

Demo는 사전 계산된 결과를 재생하는 방식으로 동작하며 GPU나 네트워크 연결이 필요하지 않습니다.

📈 검증 원칙

프로젝트는 단순히 추적 수 또는 위험 후보 수를 늘리는 것을 목표로 하지 않습니다.

주요 평가 지표는 다음과 같습니다.

객체 사건 재현율
완전 궤적 재현율
시간 커버리지
Fragmentation
ID Switch
최대 누락 시간
단계별 생존율
보행자-차량 상호작용 관측률

PET, TTC, DPD 결과는 분석 가능 사건 수, 좌표계, 단위, 검토 상태 및 한계를 함께 보고합니다.

🔮 향후 연구 계획
보행자 횡단사건 자동 생성
Interaction Event 생성
Yielding 분석
정식 PET/TTC 분석
PDI 모델 적용
무신호 횡단보도 분석 확장
이면도로 및 생활도로 안전성 평가