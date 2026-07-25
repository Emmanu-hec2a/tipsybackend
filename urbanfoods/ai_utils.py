import cv2
import mediapipe as mp
import numpy as np
from django.core.files.base import ContentFile
import logging

logger = logging.getLogger(__name__)

# Initialize MediaPipe Face Detection
mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)

def validate_face_in_image(image_file):
    """
    Backend AI Guard: Validates that a human face is actually present in the uploaded file.
    Uses MediaPipe for high-speed, lightweight server-side verification.
    """
    try:
        # 1. Read image from Django UploadedFile
        file_bytes = np.frombuffer(image_file.read(), np.uint8)
        image_file.seek(0) # Reset pointer for later use
        
        image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        if image is None:
            return False, "Invalid image format"

        # 2. Convert to RGB (MediaPipe requirement)
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # 3. Process with AI
        results = face_detection.process(image_rgb)

        # 4. Check results
        if results.detections:
            count = len(results.detections)
            logger.info(f"AI Face Guard: Validated {count} face(s) in upload.")
            return True, f"Face validated ({count})"
        
        logger.warning("AI Face Guard: No face detected in uploaded image.")
        return False, "No human face detected in the image."

    except Exception as e:
        logger.error(f"AI Face Guard Error: {str(e)}")
        # In case of AI failure, we fall back to manual review (fail-open for UX, or fail-closed for security)
        # For Tipsy, we'll fail-closed to maintain the "Bulletproof" standard.
        return False, f"AI Validation Error: {str(e)}"
