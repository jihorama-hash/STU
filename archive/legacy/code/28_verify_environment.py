"""새 분석 장비(WSL2/Windows)의 환경을 한 번에 점검한다.

새 PC에서 git clone 후 가장 먼저 실행할 스크립트.

    python src/28_verify_environment.py

점검 항목:
  1. Python 버전
  2. 필수 패키지 설치 여부
  3. GPU 인식 + 실제 연산 (is_available()만으로는 부족 - RTX 50 계열은
     wheel에 sm_120 커널이 없으면 연산 시점에 실패한다)
  4. 영상 디코딩 속도 (WSL2의 /mnt/? 경로는 느려서 병목이 될 수 있음)
  5. 데이터 존재 여부
  6. 기존 분석 결과 재현 (환경이 올바른지 최종 확인)

각 항목은 [PASS]/[WARN]/[FAIL]로 표시되고, FAIL이 하나라도 있으면
종료 코드 1을 반환한다.
"""

from __future__ import annotations

from _paths import BASE

import platform
import subprocess
import sys
import time
from pathlib import Path


results: list[tuple[str, str, str]] = []

# Windows 콘솔(cp949)에서 한글-기호 출력이 깨지지 않도록 강제 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f": {detail}" if detail else ""))


def check_python() -> None:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro} ({platform.system()})"
    if v.major == 3 and 10 <= v.minor <= 12:
        record("PASS", "Python 버전", detail)
    elif v.major == 3 and v.minor > 12:
        record("WARN", "Python 버전", f"{detail} - 3.12 권장 (일부 패키지 wheel 미제공 가능)")
    else:
        record("FAIL", "Python 버전", f"{detail} - 3.10~3.12 필요")


def check_packages() -> None:
    required = ["torch", "cv2", "numpy", "ultralytics", "sahi"]
    optional = ["supervision", "pandas", "openpyxl"]
    for mod in required + optional:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "?")
            record("PASS", f"패키지 {mod}", ver)
        except ImportError as exc:
            status = "FAIL" if mod in required else "WARN"
            record(status, f"패키지 {mod}", f"미설치 ({exc.__class__.__name__})")


def check_gpu() -> None:
    try:
        import torch
    except ImportError:
        record("FAIL", "GPU", "torch 미설치로 확인 불가")
        return

    if not torch.cuda.is_available():
        record(
            "FAIL",
            "GPU 인식",
            "torch.cuda.is_available()=False - CPU 전용 torch가 설치됐거나 "
            "WSL2에서 GPU 패스스루가 안 되는 상태. "
            "pip install torch --index-url https://download.pytorch.org/whl/cu128 로 재설치",
        )
        return

    name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
    record("PASS", "GPU 인식", f"{name} (sm_{cap[0]}{cap[1]}, {total_gb:.1f}GB, torch {torch.__version__})")

    # is_available()이 True여도 커널이 없으면 여기서 실패한다 (RTX 50 계열 흔한 함정)
    try:
        a = torch.randn(2048, 2048, device="cuda")
        torch.cuda.synchronize()
        t0 = time.time()
        for _ in range(10):
            a = a @ a.clamp(-1, 1)
        torch.cuda.synchronize()
        elapsed = time.time() - t0
        record("PASS", "GPU 실연산", f"2048x2048 matmul 10회 {elapsed:.2f}초")
    except Exception as exc:  # noqa: BLE001
        record(
            "FAIL",
            "GPU 실연산",
            f"{type(exc).__name__}: {exc} - 이 GPU용 커널이 없는 wheel. "
            "cu128 이상 빌드로 재설치 필요",
        )


def check_video_io() -> None:
    try:
        import cv2
    except ImportError:
        record("FAIL", "영상 디코딩", "cv2 미설치로 확인 불가")
        return

    candidates = sorted((BASE / "record").glob("*.MP4")) + sorted((BASE / "record").glob("*.mp4"))
    if not candidates:
        record("WARN", "영상 디코딩", f"{BASE / 'record'} 에 영상 없음 - 데이터 이전 후 재실행")
        return

    video = candidates[0]
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        record("FAIL", "영상 디코딩", f"{video.name} 열기 실패")
        return
    n = 120
    t0 = time.time()
    read = 0
    for _ in range(n):
        ok, _frame = cap.read()
        if not ok:
            break
        read += 1
    cap.release()
    elapsed = time.time() - t0
    fps = read / elapsed if elapsed > 0 else 0.0
    detail = f"{video.name}: {read}프레임 {elapsed:.1f}초 ({fps:.1f} fps 디코딩)"

    # WSL2에서 /mnt/ 경로는 9P 프로토콜로 느리다
    on_mnt = str(video).startswith("/mnt/")
    if fps < 8:
        record("WARN", "영상 디코딩 속도", detail + (" - /mnt 경로가 병목. ext4로 복사 권장" if on_mnt else " - 느림"))
    else:
        record("PASS", "영상 디코딩 속도", detail + (" (/mnt 경로)" if on_mnt else ""))


def check_data() -> None:
    record("PASS", "프로젝트 루트", str(BASE))
    expected = {
        "record": "원본 영상",
        "runs": "분석 산출물",
        "calib": "ROI-정합-마스크 정의",
        "src": "분석 코드",
    }
    for folder, desc in expected.items():
        path = BASE / folder
        if path.is_dir():
            count = sum(1 for _ in path.iterdir())
            record("PASS", f"폴더 {folder}", f"{desc} ({count}개 항목)")
        else:
            status = "WARN" if folder in {"record", "runs"} else "FAIL"
            record(status, f"폴더 {folder}", f"없음 - {desc}")


def check_reproduction() -> None:
    """기존 분석을 재실행해 동일 결과가 나오는지 확인 (환경 정합성 최종 관문)."""
    tracks = BASE / "runs" / "DJI_0482_sahi_step3_final" / "tracks_pixel.csv"
    script = BASE / "src" / "25_compute_pet_directional.py"
    if not tracks.exists() or not script.exists():
        record("WARN", "결과 재현", "기준 데이터(0482 궤적) 없음 - 데이터 이전 후 재실행")
        return

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [sys.executable, str(script), "--tracks", str(tracks), "--output-dir", tmp],
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        record("FAIL", "결과 재현", f"실행 실패: {proc.stderr.strip().splitlines()[-1] if proc.stderr else '?'}")
        return

    out = proc.stdout.strip()
    expected = "tracks=870 events=24 (pv=17, vv=7)"
    if expected in out:
        record("PASS", "결과 재현", expected + " 일치")
    else:
        record("FAIL", "결과 재현", f"불일치 - 기대: {expected} / 실제: {out}")


def main() -> int:
    print("=" * 72)
    print("분석 환경 점검")
    print("=" * 72)

    for section, fn in [
        ("1. Python", check_python),
        ("2. 패키지", check_packages),
        ("3. GPU", check_gpu),
        ("4. 데이터", check_data),
        ("5. 영상 I/O", check_video_io),
        ("6. 결과 재현", check_reproduction),
    ]:
        print(f"\n--- {section} ---")
        fn()

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print("\n" + "=" * 72)
    print(f"결과: PASS {len(results) - len(fails) - len(warns)} / WARN {len(warns)} / FAIL {len(fails)}")
    if fails:
        print("\n[해결 필요]")
        for _s, name, detail in fails:
            print(f"  - {name}: {detail}")
    if warns:
        print("\n[확인 권장]")
        for _s, name, detail in warns:
            print(f"  - {name}: {detail}")
    if not fails:
        print("\n환경 정상. 다음 단계(15fps 벤치마크)로 진행 가능합니다.")
    print("=" * 72)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
