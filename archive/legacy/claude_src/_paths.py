"""프로젝트 루트 경로를 OS에 무관하게 결정한다.

Windows(D:\\Roundabout)와 WSL2(/home/<user>/roundabout, /mnt/d/Roundabout 등)에서
같은 코드가 동작하도록, 하드코딩 대신 이 모듈의 BASE를 사용한다.

우선순위:
1. 환경변수 ROUNDABOUT_BASE (명시적 지정, 데이터를 코드와 다른 위치에 둘 때)
2. 이 파일 기준 상위 폴더 (git clone 후 별도 설정 없이 동작)

사용법:
    from _paths import BASE
    tracks = BASE / "runs" / "DJI_0482_sahi_step3_final" / "tracks_pixel.csv"

WSL2에서 영상만 별도 위치(ext4)에 둔 경우:
    export ROUNDABOUT_BASE=/home/user/roundabout
"""

from __future__ import annotations

import os
from pathlib import Path

_env = os.environ.get("ROUNDABOUT_BASE")
BASE: Path = Path(_env).expanduser().resolve() if _env else Path(__file__).resolve().parents[1]

__all__ = ["BASE"]
