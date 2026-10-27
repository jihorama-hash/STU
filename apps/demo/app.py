"""Offline dashboard for validated, precomputed analysis results."""

from __future__ import annotations

import os
from pathlib import Path
import json

import streamlit as st

from roundabout.demo_bundle import load_bundle


st.set_page_config(
    page_title="회전교차로 교통안전 분석",
    page_icon="🚦",
    layout="wide",
)

st.title("회전교차로 교통안전 분석")
st.caption("검증된 드론 영상 결과 · COCO YOLO11m · 오프라인 데모")

default_bundle = os.environ.get("ROUNDABOUT_DEMO_BUNDLE", "outputs/demo/current")
bundle_dir = Path(st.sidebar.text_input("데모 패키지", default_bundle))

try:
    bundle = load_bundle(bundle_dir)
except (FileNotFoundError, ValueError, OSError) as exc:
    st.info(
        "아직 검증된 데모 패키지가 없습니다. 분석·수동검증을 통과한 결과가 "
        "`outputs/demo/current`에 생성되면 이 화면에서 표시됩니다."
    )
    st.code(str(exc))
    st.stop()

status = bundle.validation_status
if status not in {"validated", "track-validated"}:
    st.warning(f"이 데이터의 검증 상태는 '{status}'입니다. 확정 결과로 인용하지 마세요.")
elif status == "track-validated":
    st.success("추적 표본검증과 확정 PET 사건 검토를 완료한 데모입니다.")
else:
    st.success("수동검증을 통과한 분석 패키지입니다.")

summary_path = bundle.root / str(bundle.manifest["track_summary"])
summary = json.loads(summary_path.read_text(encoding="utf-8"))
validated_events = []
event_assets = []
if "validated_events" in bundle.manifest:
    validated_events = json.loads(
        (bundle.root / str(bundle.manifest["validated_events"])).read_text(
            encoding="utf-8"
        )
    )
if "event_assets" in bundle.manifest:
    event_assets = json.loads(
        (bundle.root / str(bundle.manifest["event_assets"])).read_text(
            encoding="utf-8"
        )
    )

left, middle, right, event_count = st.columns(4)
left.metric("검증 트랙", summary["tracks"])
middle.metric("관측점", summary["observations"])
right.metric(
    "30개 표본 precision",
    f"{summary['manual_review']['sample_precision_percent']:.1f}%",
)
event_count.metric("확정 PET 사건", len(validated_events))

overview_tab, event_tab, roi_tab, provenance_tab = st.tabs(
    ["분석 개요", "확정 사건", "ROI 집계", "검증 정보"]
)

with overview_tab:
    st.subheader("클래스별 추적 결과")
    st.dataframe(
        [
            {"클래스": key, "트랙": value["tracks"], "관측점": value["observations"]}
            for key, value in summary["by_class"].items()
        ],
        hide_index=True,
        width="stretch",
    )
    st.info(
        "개요 통계는 독립 검증된 220–280초 구간입니다. 확정 사건 예시는 "
        "별도로 검증한 0–60초 구간에서 제공합니다."
    )

roi_summary = json.loads(
    (bundle.root / str(bundle.manifest["roi_summary"])).read_text(encoding="utf-8")
)
with event_tab:
    if not validated_events:
        st.info("이 번들에는 확정 사건이 없습니다.")
    else:
        asset_by_id = {item["event_id"]: item for item in event_assets}
        selected_id = st.selectbox(
            "사건 선택",
            [event["event_id"] for event in validated_events],
            format_func=lambda event_id: asset_by_id.get(event_id, {}).get(
                "title", event_id
            ),
        )
        event = next(
            item for item in validated_events if item["event_id"] == selected_id
        )
        asset = asset_by_id.get(selected_id, {})
        a, b, c, d = st.columns(4)
        a.metric("PET", f"{event['pet_seconds']:.3f}초")
        b.metric("발생 시각", f"{event['timestamp_seconds']:.3f}초")
        c.metric("교차각", f"{event['crossing_angle_degrees']:.1f}°")
        d.metric("검증 상태", "확정")
        st.caption(
            f"ROI: {event['roi_id']} · 차량 #{event['first_track_id']} / "
            f"#{event['second_track_id']} · 최근접 "
            f"{event['encroachment_distance_pixels']:.1f}px"
        )
        clip = bundle.root / str(asset.get("clip", ""))
        if clip.is_file():
            st.video(str(clip))
        else:
            st.warning("사건 영상 클립을 생성해야 합니다.")
        image_left, image_right = st.columns(2)
        roi_frame = bundle.root / str(asset.get("roi_frame", ""))
        filmstrip = bundle.root / str(asset.get("filmstrip", ""))
        if roi_frame.is_file():
            image_left.image(str(roi_frame), caption="ROI·행위자·최근접 위치")
        if filmstrip.is_file():
            image_right.image(str(filmstrip), caption="시간순 궤적 필름스트립")
        st.warning(
            "TTC는 영상평면 속도 기반 참고값입니다. 확정 판정은 PET와 "
            "필름스트립 수동검토를 기준으로 합니다."
        )

with roi_tab:
    st.subheader("ROI별 통행량 후보")
    st.dataframe(
        [
            {
                "ROI": row["roi_name"],
                "고유 트랙": row["unique_tracks"],
                "보행자": row["pedestrian_tracks"],
                "차량": row["vehicle_tracks"],
            }
            for row in roi_summary
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption("기존 ROI 정합을 이용한 220–280초 구간 집계입니다.")

with provenance_tab:
    st.subheader("검증 및 재현 정보")
    st.json(bundle.manifest, expanded=False)
    st.caption(
        "자동 후보와 확정 사건은 분리되어 있습니다. 확정 사건만 데모의 "
        "사건 탐색기에 표시됩니다."
    )
