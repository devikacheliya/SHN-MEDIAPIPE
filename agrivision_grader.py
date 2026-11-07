r"""
AgriVision: Produce Ripeness & Defect Grader
=============================================

What this script does
---------------------
1. Opens the live webcam and reads frames with OpenCV.
2. Converts each frame from BGR to HSV (better for color detection).
3. Builds color masks for green (unripe) and red/yellow (ripe) produce.
4. Finds the largest produce contour and measures it.
5. Finds dark spots inside the item and calculates a defect percentage.
6. Shows a Grade A / Grade B / Reject badge plus diameter and color stats.

Controls
--------
- Press Q or Esc in the video window to quit.

Run in PowerShell
-----------------
    cd "C:\Users\devik\OneDrive\Desktop\mediapipe-project"
    .\venv\Scripts\Activate.ps1
    python .\agrivision_grader.py

If PowerShell blocks the activation script for this session only:
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\venv\Scripts\Activate.ps1

No virtual environment yet? Create one first:
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install opencv-python numpy

Tips for best results
---------------------
- Use one fruit/vegetable and a plain, well-lit background.
- Keep the camera at a fixed distance if you rely on the mm estimate.
- The HSV and grade thresholds below are intentionally easy to adjust.
"""

import os
import time

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# 1. USER SETTINGS - change these first when tuning the project
# ---------------------------------------------------------------------------
CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
WINDOW_NAME = "AgriVision - Produce Ripeness & Defect Grader"

# OpenCV HSV ranges: H is 0-179, S and V are 0-255.
# Green / yellow-green = unripe.
GREEN_LOWER = np.array((35, 45, 30), dtype=np.uint8)
GREEN_UPPER = np.array((90, 255, 255), dtype=np.uint8)

# Red wraps around the end of OpenCV's hue scale, so we need two red ranges.
RED_LOWER_1 = np.array((0, 90, 45), dtype=np.uint8)
RED_UPPER_1 = np.array((9, 255, 255), dtype=np.uint8)
RED_LOWER_2 = np.array((165, 90, 45), dtype=np.uint8)
RED_UPPER_2 = np.array((179, 255, 255), dtype=np.uint8)

# Yellow/orange produce (banana, lemon, yellow pepper) is also considered ripe.
YELLOW_LOWER = np.array((10, 80, 60), dtype=np.uint8)
YELLOW_UPPER = np.array((34, 255, 255), dtype=np.uint8)

# A contour must contain at least this many pixels to count as produce.
# Lower it if your camera is far from the fruit; raise it if you see noise.
MIN_ITEM_AREA = 2500

# Dark pixels (low brightness) inside the item are treated as surface defects.
DARK_V_MAX = 65
DEFECT_EDGE_MARGIN = 5        # pixels ignored around the outline (avoids shadows)
MIN_DEFECT_AREA = 25         # ignore tiny dark specks

# Approximate camera calibration. Measure a known object to improve this:
#   mm_per_pixel = known_width_mm / width_in_pixels
# Example: a 25 mm coin appears 100 px wide -> 25 / 100 = 0.25 mm/px.
MM_PER_PIXEL = 0.25

# Grade rules. Grade A needs a ripe, uniform item and almost no defects.
GRADE_A_MIN_PURITY = 85.0     # % of colored pixels in the dominant color
GRADE_A_MIN_RIPE = 75.0       # % of colored pixels that are ripe red/yellow
GRADE_A_MAX_DEFECT = 3.0      # % of the item area
# Grade B is still usable but less ripe, less uniform, or slightly damaged.
GRADE_B_MIN_PURITY = 60.0
GRADE_B_MIN_RIPE = 40.0
GRADE_B_MAX_DEFECT = 8.0


# ---------------------------------------------------------------------------
# 2. CAMERA AND COLOR MASK HELPERS
# ---------------------------------------------------------------------------
def open_camera():
    """Open the webcam and prefer DirectShow on Windows for faster startup."""
    if os.name == "nt":
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(CAMERA_INDEX)

    # Some Windows camera drivers do not support DirectShow. Try the default.
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(CAMERA_INDEX)

    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # reduce lag where supported
    return cap


def build_hsv_masks(frame):
    """Return HSV data and clean masks for green, ripe, and all produce colors."""
    # Slight blur reduces pixel noise in the masks.
    blurred = cv2.GaussianBlur(frame, (5, 5), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

    # Mask 1: unripe green produce.
    green_mask = cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER)

    # Mask 2: ripe red/yellow produce. Red needs two hue ranges.
    red_mask_1 = cv2.inRange(hsv, RED_LOWER_1, RED_UPPER_1)
    red_mask_2 = cv2.inRange(hsv, RED_LOWER_2, RED_UPPER_2)
    red_mask = cv2.bitwise_or(red_mask_1, red_mask_2)
    yellow_mask = cv2.inRange(hsv, YELLOW_LOWER, YELLOW_UPPER)
    ripe_mask = cv2.bitwise_or(red_mask, yellow_mask)

    # Clean up tiny color noise in each mask before measuring percentages.
    small_kernel = np.ones((3, 3), dtype=np.uint8)
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_OPEN, small_kernel)
    ripe_mask = cv2.morphologyEx(ripe_mask, cv2.MORPH_OPEN, small_kernel)

    # Combine both color classes, then close small holes caused by highlights.
    produce_mask = cv2.bitwise_or(green_mask, ripe_mask)
    open_kernel = np.ones((5, 5), dtype=np.uint8)
    close_kernel = np.ones((9, 9), dtype=np.uint8)
    produce_mask = cv2.morphologyEx(produce_mask, cv2.MORPH_OPEN, open_kernel)
    produce_mask = cv2.morphologyEx(produce_mask, cv2.MORPH_CLOSE, close_kernel)

    return hsv, green_mask, ripe_mask, produce_mask


# ---------------------------------------------------------------------------
# 3. GRADE RULES AND FRAME ANALYSIS
# ---------------------------------------------------------------------------
def evaluate_grade(color_purity_pct, ripe_pct, defect_pct):
    """Turn the three measurements into a grade, badge color, and short reason."""
    # Decide a helpful rejection reason first.
    if defect_pct > GRADE_B_MAX_DEFECT:
        reject_reason = "Too many dark surface defects"
    elif ripe_pct < GRADE_B_MIN_RIPE:
        reject_reason = "Mostly unripe (green)"
    elif color_purity_pct < GRADE_B_MIN_PURITY:
        reject_reason = "Uneven mix of ripe/unripe color"
    else:
        reject_reason = "Below Grade B thresholds"

    # Grade A: mostly ripe, strongly uniform, and nearly defect-free.
    if (color_purity_pct >= GRADE_A_MIN_PURITY
            and ripe_pct >= GRADE_A_MIN_RIPE
            and defect_pct <= GRADE_A_MAX_DEFECT):
        return "Grade A", (0, 150, 0), "Ripe, uniform color, clean surface"

    # Grade B: usable produce with some color variation or small defects.
    if (color_purity_pct >= GRADE_B_MIN_PURITY
            and ripe_pct >= GRADE_B_MIN_RIPE
            and defect_pct <= GRADE_B_MAX_DEFECT):
        return "Grade B", (0, 170, 255), "Minor color variation or defects"

    # Everything else is rejected for this ripeness/quality check.
    return "Reject", (0, 0, 220), reject_reason


def analyze_frame(frame):
    """Detect the largest produce item and return its measurements or None."""
    hsv, green_mask, ripe_mask, produce_mask = build_hsv_masks(frame)

    # Find external outlines. We grade only the largest valid item.
    contours, _ = cv2.findContours(
        produce_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None

    produce_contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(produce_contour) < MIN_ITEM_AREA:
        return None

    # A filled mask lets us count pixels inside the whole item, including
    # dark defects that were not part of either color mask.
    item_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.drawContours(item_mask, [produce_contour], -1, 255, cv2.FILLED)
    item_area = cv2.countNonZero(item_mask)
    if item_area == 0:
        return None

    # Count ripe and unripe colored pixels inside the detected item only.
    ripe_pixels = cv2.countNonZero(cv2.bitwise_and(ripe_mask, item_mask))
    green_pixels = cv2.countNonZero(cv2.bitwise_and(green_mask, item_mask))
    colored_pixels = ripe_pixels + green_pixels
    if colored_pixels == 0:
        return None

    ripe_pct = 100.0 * ripe_pixels / colored_pixels
    green_pct = 100.0 * green_pixels / colored_pixels

    # Color purity = share belonging to the dominant color class.
    # A half-red/half-green item therefore has low purity.
    color_purity_pct = 100.0 * max(ripe_pixels, green_pixels) / colored_pixels

    # Surface defects: dark pixels well inside the item boundary.
    # Eroding the item mask ignores dark background/shadow at the outline.
    dark_lower = np.array((0, 0, 0), dtype=np.uint8)
    dark_upper = np.array((179, 255, DARK_V_MAX), dtype=np.uint8)
    dark_mask = cv2.inRange(hsv, dark_lower, dark_upper)

    kernel_size = DEFECT_EDGE_MARGIN * 2 + 1
    inner_mask = cv2.erode(
        item_mask, np.ones((kernel_size, kernel_size), dtype=np.uint8)
    )
    defect_mask = cv2.bitwise_and(dark_mask, inner_mask)
    defect_mask = cv2.morphologyEx(
        defect_mask, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8)
    )

    # Remove tiny dark blobs that are probably noise, not real bruises.
    defect_contours, _ = cv2.findContours(
        defect_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    clean_defects = np.zeros_like(defect_mask)
    kept_defects = []
    for spot in defect_contours:
        if cv2.contourArea(spot) >= MIN_DEFECT_AREA:
            cv2.drawContours(clean_defects, [spot], -1, 255, cv2.FILLED)
            kept_defects.append(spot)

    defect_area = cv2.countNonZero(clean_defects)
    defect_pct = 100.0 * defect_area / item_area

    # Diameter estimate using the smallest circle around the produce outline.
    (center_x, center_y), circle_radius = cv2.minEnclosingCircle(produce_contour)
    diameter_px = int(round(circle_radius * 2))
    diameter_mm = diameter_px * MM_PER_PIXEL

    # Ripeness label is separate from the quality badge and is easier to read.
    if ripe_pct >= 70.0:
        ripeness = "Ripe"
    elif ripe_pct >= 35.0:
        ripeness = "Turning / mixed"
    else:
        ripeness = "Unripe"

    grade, grade_color, reason = evaluate_grade(
        color_purity_pct, ripe_pct, defect_pct
    )

    return {
        "grade": grade,
        "grade_color": grade_color,
        "reason": reason,
        "ripeness": ripeness,
        "ripe_pct": ripe_pct,
        "green_pct": green_pct,
        "color_purity_pct": color_purity_pct,
        "defect_pct": defect_pct,
        "diameter_px": diameter_px,
        "diameter_mm": diameter_mm,
        "area_px": item_area,
        "contour": produce_contour,
        "defect_contours": kept_defects,
        "bbox": cv2.boundingRect(produce_contour),
        "center": (int(center_x), int(center_y)),
        "radius": max(1, int(circle_radius)),
    }


# ---------------------------------------------------------------------------
# 4. ON-SCREEN UI
# ---------------------------------------------------------------------------
def draw_scene(frame, result):
    """Draw the produce outline, measurements, and the grade panel on a frame."""
    height, width = frame.shape[:2]

    # Scale the overlay up/down with the webcam resolution.
    scale = width / 1280.0
    small_font = max(0.45, 0.62 * scale)
    badge_font = max(0.70, 1.20 * scale)
    note_font = max(0.40, 0.52 * scale)
    small_thick = max(1, int(round(2 * scale)))
    badge_thick = max(2, int(round(3 * scale)))

    def px(value):
        """Convert a design measurement (based on 1280 px width) to this frame."""
        return int(round(value * scale))

    # Draw the detected item first so the info panel always stays legible.
    if result is not None:
        grade_color = result["grade_color"]
        x, y, box_w, box_h = result["bbox"]

        cv2.drawContours(
            frame, [result["contour"]], -1, grade_color,
            max(2, px(3)), cv2.LINE_AA
        )
        cv2.rectangle(
            frame, (x, y), (x + box_w, y + box_h),
            grade_color, max(1, px(2)), cv2.LINE_AA
        )

        # Outline bruises/dark spots detected inside the produce.
        if result["defect_contours"]:
            cv2.drawContours(
                frame, result["defect_contours"], -1, (255, 0, 255),
                max(1, px(2)), cv2.LINE_AA
            )

        # Draw a diameter line across the minimum enclosing circle.
        center_x, center_y = result["center"]
        radius = result["radius"]
        line_y = min(height - 1, max(0, center_y))
        x1 = max(0, center_x - radius)
        x2 = min(width - 1, center_x + radius)
        tick = max(4, px(8))
        cv2.line(frame, (x1, line_y), (x2, line_y),
                 (255, 255, 0), max(1, px(2)), cv2.LINE_AA)
        cv2.line(frame, (x1, line_y - tick), (x1, line_y + tick),
                 (255, 255, 0), max(1, px(2)), cv2.LINE_AA)
        cv2.line(frame, (x2, line_y - tick), (x2, line_y + tick),
                 (255, 255, 0), max(1, px(2)), cv2.LINE_AA)

    # Semi-transparent dark info panel in the top-left corner.
    panel_left, panel_top = px(20), px(20)
    panel_right = min(width - px(20), px(740))
    panel_bottom = px(300)
    overlay = frame.copy()
    cv2.rectangle(overlay, (panel_left, panel_top),
                  (panel_right, panel_bottom), (20, 20, 20), cv2.FILLED)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    cv2.rectangle(frame, (panel_left, panel_top),
                  (panel_right, panel_bottom), (180, 180, 180),
                  max(1, px(1)), cv2.LINE_AA)

    # The colored badge changes with the result.
    if result is None:
        badge_label = "NO PRODUCE"
        badge_color = (0, 120, 200)
        badge_text_color = (255, 255, 255)
    else:
        badge_label = result["grade"].upper()
        badge_color = result["grade_color"]
        # Black text is easier to read on the bright amber Grade B badge.
        badge_text_color = (20, 20, 20) if result["grade"] == "Grade B" else (255, 255, 255)

    cv2.rectangle(frame, (px(40), px(38)), (px(340), px(105)),
                  badge_color, cv2.FILLED, cv2.LINE_AA)
    cv2.putText(frame, badge_label, (px(55), px(88)),
                cv2.FONT_HERSHEY_SIMPLEX, badge_font,
                badge_text_color, badge_thick, cv2.LINE_AA)

    if result is None:
        cv2.putText(frame, "No produce detected.", (px(40), px(150)),
                    cv2.FONT_HERSHEY_SIMPLEX, small_font,
                    (255, 255, 255), small_thick, cv2.LINE_AA)
        cv2.putText(frame, "Place one fruit or vegetable in view.",
                    (px(40), px(188)), cv2.FONT_HERSHEY_SIMPLEX,
                    small_font, (220, 220, 220), small_thick, cv2.LINE_AA)
        cv2.putText(frame, "Use a plain background and even lighting.",
                    (px(40), px(226)), cv2.FONT_HERSHEY_SIMPLEX,
                    small_font, (220, 220, 220), small_thick, cv2.LINE_AA)
        cv2.putText(frame, "Green = unripe  |  Red/yellow = ripe.",
                    (px(40), px(264)), cv2.FONT_HERSHEY_SIMPLEX,
                    note_font, (180, 220, 180), small_thick, cv2.LINE_AA)
    else:
        cv2.putText(
            frame,
            f"Diameter: {result['diameter_px']} px  |  ~{result['diameter_mm']:.1f} mm",
            (px(40), px(145)), cv2.FONT_HERSHEY_SIMPLEX, small_font,
            (255, 255, 255), small_thick, cv2.LINE_AA
        )
        cv2.putText(
            frame,
            f"Color purity: {result['color_purity_pct']:.1f}%  |  "
            f"Defects: {result['defect_pct']:.1f}%",
            (px(40), px(185)), cv2.FONT_HERSHEY_SIMPLEX, small_font,
            (255, 255, 255), small_thick, cv2.LINE_AA
        )
        cv2.putText(
            frame,
            f"Ripeness: {result['ripeness']}  |  "
            f"Ripe color: {result['ripe_pct']:.1f}%",
            (px(40), px(225)), cv2.FONT_HERSHEY_SIMPLEX, small_font,
            (220, 220, 220), small_thick, cv2.LINE_AA
        )
        cv2.putText(
            frame, f"Assessment: {result['reason']}",
            (px(40), px(268)), cv2.FONT_HERSHEY_SIMPLEX, note_font,
            (200, 200, 200), max(1, int(round(1.5 * scale))), cv2.LINE_AA
        )

    # Helpful hint along the bottom of the window.
    hint = "AgriVision  |  Q / Esc = quit  |  Use one item on a plain background"
    hint_x, hint_y = px(20), height - px(18)
    cv2.putText(frame, hint, (hint_x + 1, hint_y + 1),
                cv2.FONT_HERSHEY_SIMPLEX, note_font, (0, 0, 0),
                small_thick + 2, cv2.LINE_AA)
    cv2.putText(frame, hint, (hint_x, hint_y),
                cv2.FONT_HERSHEY_SIMPLEX, note_font,
                (255, 255, 255), small_thick, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# 5. MAIN PROGRAM
# ---------------------------------------------------------------------------
def main():
    """Open the webcam, process frames, and shut everything down safely."""
    cap = open_camera()
    if not cap.isOpened():
        print("[ERROR] Could not open the webcam.")
        print("         Close other camera apps and check CAMERA_INDEX at the top.")
        cap.release()
        return

    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or FRAME_WIDTH
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or FRAME_HEIGHT
    print(f"[INFO] Camera opened at {actual_width}x{actual_height}.")
    print("[INFO] Press Q or Esc in the video window to quit.")

    # Scale the window down if needed so it fits comfortably on screen.
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    display_width = min(1100, actual_width)
    display_height = max(1, int(display_width * actual_height / actual_width))
    cv2.resizeWindow(WINDOW_NAME, display_width, display_height)

    missing_frames = 0
    try:
        while True:
            ok, frame = cap.read()

            # Handle an empty frame without crashing the loop.
            if not ok or frame is None:
                missing_frames += 1
                if missing_frames == 1:
                    print("[WARN] Camera returned an empty frame; retrying...")
                if missing_frames >= 30:
                    print("[ERROR] No frames received after 30 attempts. Stopping.")
                    break
                time.sleep(0.05)
                continue
            missing_frames = 0

            # Mirror the frame so moving left/right feels natural on screen.
            frame = cv2.flip(frame, 1)

            result = analyze_frame(frame)
            draw_scene(frame, result)
            cv2.imshow(WINDOW_NAME, frame)

            # waitKey also lets OpenCV update the window and read key presses.
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:  # 27 is the Esc key
                break
    finally:
        # These run even if an error occurs, freeing the camera cleanly.
        cap.release()
        cv2.destroyAllWindows()
        print("[INFO] Camera released. AgriVision closed.")


if __name__ == "__main__":
    main()
