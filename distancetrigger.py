import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# 1. Initialize MediaPipe Landmarker
base_options = python.BaseOptions(model_asset_path='hand_landmarker.task')
options = vision.HandLandmarkerOptions(
    base_options=base_options,
    num_hands=1
)
detector = vision.HandLandmarker.create_from_options(options)

# 2. Distance Function
def calculate_distance(landmark_a, landmark_b, image_width, image_height):
    pt_a = np.array([landmark_a.x * image_width, landmark_a.y * image_height])
    pt_b = np.array([landmark_b.x * image_width, landmark_b.y * image_height])
    return np.linalg.norm(pt_a - pt_b)

# 3. Open Webcam
cap = cv2.VideoCapture(0)

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        continue

    # Mirror frame & convert to RGB
    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    # Wrap in MediaPipe Image format
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
    results = detector.detect(mp_image)

    if results.hand_landmarks:
        for hand_landmarks in results.hand_landmarks:
            thumb_tip = hand_landmarks[4]
            index_tip = hand_landmarks[8]
            
            dist = calculate_distance(thumb_tip, index_tip, w, h)

            thumb_pos = (int(thumb_tip.x * w), int(thumb_tip.y * h))
            index_pos = (int(index_tip.x * w), int(index_tip.y * h))

            # Draw circles on thumb and index finger
            if dist < 35:
                cv2.circle(frame, thumb_pos, 12, (0, 0, 255), -1)
                cv2.circle(frame, index_pos, 12, (0, 0, 255), -1)
                cv2.line(frame, thumb_pos, index_pos, (0, 0, 255), 3)
                cv2.putText(frame, "PINCH DETECTED!", (50, 80), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            else:
                cv2.circle(frame, thumb_pos, 8, (0, 255, 0), -1)
                cv2.circle(frame, index_pos, 8, (0, 255, 0), -1)
                cv2.line(frame, thumb_pos, index_pos, (255, 255, 0), 2)

            cv2.putText(frame, f"Distance: {int(dist)} px", (50, 40), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    # Display image window
    cv2.imshow("Real-Time Gesture Trigger", frame)

    # Press 'q' or Esc to close window
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == 27:
        break

cap.release()
cv2.destroyAllWindows()