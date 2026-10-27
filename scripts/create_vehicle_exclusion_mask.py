"""Create narrowly scoped vehicle false-positive exclusion zones."""

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "data/calibration/legacy/roadway_mask.png"
OUTPUT = ROOT / "data/calibration/vehicle_false_positive_exclusion_mask.png"
PREVIEW = ROOT / "outputs/validation/vehicle_false_positive_exclusion_mask.png"


def main() -> None:
    reference = cv2.imread(str(REFERENCE), cv2.IMREAD_GRAYSCALE)
    if reference is None:
        raise FileNotFoundError(REFERENCE)
    mask = np.zeros_like(reference)

    # Foot-point neighborhoods of independently confirmed static false tracks:
    # COCO car #5 (road marking) and VisDrone car #36 (center-island vegetation).
    cv2.ellipse(mask, (3704, 1774), (55, 35), 0, 0, 360, 255, -1)
    cv2.ellipse(mask, (1918, 1016), (65, 45), 0, 0, 360, 255, -1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUTPUT), mask)
    cv2.imwrite(str(PREVIEW), mask)
    print(OUTPUT)


if __name__ == "__main__":
    main()
