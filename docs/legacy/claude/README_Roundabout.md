# ST_Roundabout

## 환경 설정

Python 3.10~3.12 기준.

### 1. torch / torchvision 설치 (먼저)

GPU 드라이버에 맞는 CUDA 휠을 `requirements.txt`보다 먼저 설치한다. 이 워크스테이션은 CUDA 13.2 기준:

```
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu132
```

### 2. 나머지 의존성 설치

```
pip install -r requirements.txt
```

`ultralytics`와 `sahi`는 둘 다 torch/torchvision을 의존성으로 갖고 있다. 1번을 먼저 실행하지 않으면 pip이 PyPI 기본 인덱스의 일반 torch 빌드를 끌어와 방금 설치한 CUDA 휠을 덮어쓴다. 이미 요구 버전을 만족하는 torch가 설치되어 있으면 pip은 건드리지 않으므로, 순서를 지키는 것이 중요하다.

### 3. 환경 점검

```
python src/28_verify_environment.py
```

Python 버전, 필수 패키지 설치 여부, GPU 인식 및 실연산, 영상 디코딩 속도, 데이터 존재 여부, 기존 분석 결과 재현까지 한 번에 점검한다.
