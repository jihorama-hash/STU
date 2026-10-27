
from _paths import BASE
import cv2
from pathlib import Path

IMAGE_PATH = str(BASE / "runs" / "DJI_0488_sahi_step10" / "conflict_zones_preview.jpg")  # ROI를 찍을 이미지 경로로 수정하세요
MAX_DISPLAY_WIDTH = 1600
MAX_DISPLAY_HEIGHT = 900

points: list[tuple[int, int]] = []
display_scale = 1.0


def original_point(display_x, display_y):
    x = int(round(display_x / display_scale))
    y = int(round(display_y / display_scale))
    h, w = img.shape[:2]
    return max(0, min(w - 1, x)), max(0, min(h - 1, y))


def show_image():
    if display_scale == 1.0:
        display_img = img_show
    else:
        display_img = cv2.resize(
            img_show,
            None,
            fx=display_scale,
            fy=display_scale,
            interpolation=cv2.INTER_AREA,
        )
    cv2.imshow("Pick Points", display_img)


def mouse_callback(event, x, y, flags, param):
    global points, img_show
    orig_x, orig_y = original_point(x, y)

    if event == cv2.EVENT_LBUTTONDOWN:
        points.append((orig_x, orig_y))
        print(f"- [{orig_x}, {orig_y}]")

        cv2.circle(img_show, (orig_x, orig_y), marker_radius(), (0, 0, 255), -1)
        cv2.putText(
            img_show,
            f"{len(points)}: ({orig_x},{orig_y})",
            (orig_x + text_offset(), orig_y - text_offset()),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale(),
            (0, 0, 255),
            line_thickness(),
        )
        show_image()

    elif event == cv2.EVENT_RBUTTONDOWN:
        if points:
            removed = points.pop()
            print(f"removed: {removed}")
            redraw()

def redraw():
    global img_show
    img_show = img.copy()

    for i, (x, y) in enumerate(points, start=1):
        cv2.circle(img_show, (x, y), marker_radius(), (0, 0, 255), -1)
        cv2.putText(
            img_show,
            f"{i}: ({x},{y})",
            (x + text_offset(), y - text_offset()),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale(),
            (0, 0, 255),
            line_thickness(),
        )

    if len(points) >= 2:
        for i in range(len(points) - 1):
            cv2.line(img_show, points[i], points[i + 1], (0, 255, 255), line_thickness())

    show_image()


def marker_radius():
    return max(5, int(round(5 / display_scale)))


def text_offset():
    return max(8, int(round(8 / display_scale)))


def font_scale():
    return 0.6 / display_scale


def line_thickness():
    return max(2, int(round(2 / display_scale)))

img = cv2.imread(IMAGE_PATH)
if img is None:
    raise FileNotFoundError(f"이미지를 열 수 없습니다: {IMAGE_PATH}")

height, width = img.shape[:2]
display_scale = min(1.0, MAX_DISPLAY_WIDTH / width, MAX_DISPLAY_HEIGHT / height)
display_width = int(round(width * display_scale))
display_height = int(round(height * display_scale))

img_show = img.copy()

cv2.namedWindow("Pick Points", cv2.WINDOW_AUTOSIZE)
show_image()
cv2.setMouseCallback("Pick Points", mouse_callback)

print(f"원본 크기: {width}x{height}")
print(f"표시 크기: {display_width}x{display_height} (scale={display_scale:.4f})")
print("클릭 좌표는 원본 이미지 기준으로 출력됩니다.")
print("왼쪽 클릭: 좌표 추가")
print("오른쪽 클릭: 마지막 좌표 삭제")
print("q: 종료")
print("클릭한 좌표:")

while True:
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break

cv2.destroyAllWindows()

print("\nYAML에 붙여넣을 좌표:")
for x, y in points:
    print(f"  - [{x}, {y}]")