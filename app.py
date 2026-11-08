"""AgriVision - Flask entrypoint for Vercel.

The browser captures a webcam snapshot (or uploads an image) and sends it to
POST /api/grade. This Python function runs the OpenCV analysis and returns the
annotated image plus grade metrics.
"""

import base64

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request

from agrivision_grader import analyze_frame, draw_scene

# public/ is served as static assets by Vercel and by this Flask app locally.
app = Flask(__name__, static_folder="public", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit

MAX_IMAGE_SIDE = 1280
GRADE_KEYS = {"Grade A": "a", "Grade B": "b", "Reject": "reject"}


def _limit_image_size(frame):
    """Downscale large phone photos so analysis stays fast."""
    height, width = frame.shape[:2]
    longest_side = max(height, width)
    if longest_side <= MAX_IMAGE_SIDE:
        return frame

    scale = MAX_IMAGE_SIDE / longest_side
    new_size = (int(round(width * scale)), int(round(height * scale)))
    return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)


def _annotated_data_url(frame, result):
    """Encode the annotated BGR frame as a browser-friendly JPEG data URL."""
    draw_scene(
        frame,
        result,
        footer_text="AgriVision  |  One item  |  Plain background  |  Even lighting",
    )
    ok, encoded = cv2.imencode(
        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
    )
    if not ok:
        raise RuntimeError("Could not encode the annotated image.")

    image_b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{image_b64}"


@app.get("/")
def index():
    """Serve the single-page frontend."""
    return render_template("index.html")


@app.get("/api/health")
def health():
    """Small endpoint useful for deployment checks."""
    return jsonify({"status": "ok", "service": "agrivision"})


@app.post("/api/grade")
def grade():
    """Analyze one uploaded image and return the result as JSON."""
    upload = request.files.get("image")
    if upload is None:
        return jsonify({"error": "No image was uploaded."}), 400

    raw_bytes = upload.read()
    if not raw_bytes:
        return jsonify({"error": "The uploaded image is empty."}), 400

    frame = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"error": "That file is not a readable image."}), 400

    try:
        frame = _limit_image_size(frame)
        result = analyze_frame(frame)
        image_data_url = _annotated_data_url(frame, result)

        if result is None:
            return jsonify({
                "detected": False,
                "grade": "No produce",
                "grade_key": "none",
                "reason": (
                    "No fruit or vegetable was detected. Use one item, a plain "
                    "background, and bright even lighting."
                ),
                "image": image_data_url,
            })

        return jsonify({
            "detected": True,
            "grade": result["grade"],
            "grade_key": GRADE_KEYS.get(result["grade"], "reject"),
            "reason": result["reason"],
            "diameter_px": int(result["diameter_px"]),
            "diameter_mm": round(float(result["diameter_mm"]), 1),
            "color_purity_pct": round(float(result["color_purity_pct"]), 1),
            "defect_pct": round(float(result["defect_pct"]), 1),
            "ripeness": result["ripeness"],
            "ripe_pct": round(float(result["ripe_pct"]), 1),
            "image": image_data_url,
        })
    except Exception:
        app.logger.exception("AgriVision analysis failed")
        return jsonify({
            "error": "Could not analyze this image. Please try another photo."
        }), 500


@app.errorhandler(413)
def image_too_large(_error):
    """Return JSON instead of Flask's default HTML 413 page."""
    return jsonify({"error": "Image is too large. Please use one under 10 MB."}), 413


if __name__ == "__main__":
    # Local development only. Vercel loads the `app` object automatically.
    app.run(debug=True, host="127.0.0.1", port=5000)
