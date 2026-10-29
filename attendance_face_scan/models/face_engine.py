"""Local YuNet/SFace face detection and embedding generation."""

from __future__ import annotations

import functools
import os
from pathlib import Path


MODEL_VERSION = "opencv-sface-2021dec-yunet-2023mar-v1"
EMBEDDING_DIMENSION = 128


class FaceScanImageError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class FaceModelUnavailable(Exception):
    pass


class FaceEngine:
    def __init__(self, model_directory: Path):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise FaceModelUnavailable("OpenCV is not installed in this Odoo image.") from exc

        detector_path = model_directory / "face_detection_yunet_2023mar.onnx"
        recognizer_path = model_directory / "face_recognition_sface_2021dec.onnx"
        if not detector_path.is_file() or not recognizer_path.is_file():
            raise FaceModelUnavailable("The YuNet and SFace model files are missing.")

        self._cv2 = cv2
        self._np = np
        try:
            self._detector = cv2.FaceDetectorYN.create(
                str(detector_path),
                "",
                (320, 320),
                0.9,
                0.3,
                5000,
            )
            self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        except Exception as exc:
            raise FaceModelUnavailable("OpenCV could not load the face models.") from exc

    def embedding_from_bytes(self, image_bytes: bytes) -> list[float]:
        faces = self.faces_from_bytes(image_bytes)
        if not faces:
            raise FaceScanImageError("no_face", "No face was detected.")
        if len(faces) != 1:
            raise FaceScanImageError("multiple_faces", "The image must contain exactly one face.")
        return faces[0]["embedding"]

    def faces_from_bytes(self, image_bytes: bytes) -> list[dict]:
        np = self._np
        cv2 = self._cv2
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise FaceScanImageError("invalid_image", "Image file could not be decoded.")

        height, width = image.shape[:2]
        if not width or not height or width * height > 30_000_000:
            raise FaceScanImageError("invalid_image", "Image dimensions are not supported.")
        if max(width, height) > 1600:
            scale = 1600.0 / max(width, height)
            image = cv2.resize(
                image,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
            height, width = image.shape[:2]

        self._detector.setInputSize((width, height))
        _status, faces = self._detector.detect(image)
        results = []
        for face in ([] if faces is None else faces[:20]):
            try:
                embedding = self._embedding_for_face(image, face)
            except FaceScanImageError:
                continue
            results.append({
                "box": [float(v) for v in face[:4]],
                "landmarks": [[float(face[i]), float(face[i + 1])] for i in range(4, 14, 2)],
                "detection_confidence": float(face[14]),
                "embedding": embedding,
            })
        return results

    def _embedding_for_face(self, image, face):
        np = self._np
        try:
            aligned_face = self._recognizer.alignCrop(image, face)
            feature = self._recognizer.feature(aligned_face).reshape(-1).astype(np.float32)
        except Exception as exc:
            raise FaceScanImageError("invalid_image", "The detected face could not be aligned.") from exc

        if feature.size != EMBEDDING_DIMENSION:
            raise FaceModelUnavailable(
                f"Unexpected SFace embedding size: {feature.size}; expected {EMBEDDING_DIMENSION}."
            )
        norm = float(np.linalg.norm(feature))
        if not norm or not np.isfinite(norm):
            raise FaceScanImageError("invalid_image", "The face embedding is not valid.")
        feature /= norm
        return [float(value) for value in feature]


@functools.lru_cache(maxsize=1)
def get_face_engine() -> FaceEngine:
    model_directory = Path(
        os.environ.get(
            "ODOO_FACE_SCAN_MODEL_DIR",
            "/opt/odoo-face-scan/models",
        )
    )
    return FaceEngine(model_directory)
