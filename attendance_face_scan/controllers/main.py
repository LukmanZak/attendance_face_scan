"""Public kiosk endpoint for local face matching and attendance."""

import base64
import binascii
import logging
import uuid

from odoo import _, http
from odoo.http import request

from odoo.addons.hr_attendance.controllers.main import HrAttendance as AttendanceController

from ..models.face_engine import (
    FaceModelUnavailable,
    FaceScanImageError,
    get_face_engine,
)

_logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_DATA_URL_LENGTH = 14 * 1024 * 1024
DEFAULT_MATCH_THRESHOLD = 0.363
DEFAULT_AMBIGUITY_MARGIN = 0.05


def _error(code, message):
    return {"status": "error", "code": code, "message": message}


def _decode_image_data_url(value):
    if not isinstance(value, str) or len(value) > MAX_DATA_URL_LENGTH:
        raise FaceScanImageError("invalid_image", "Image is larger than the allowed size.")
    try:
        header, encoded = value.split(",", 1)
    except ValueError as exc:
        raise FaceScanImageError("invalid_image", "Image data is not valid.") from exc
    mime_types = {
        "data:image/jpeg;base64": "image/jpeg",
        "data:image/png;base64": "image/png",
    }
    if header.lower() not in mime_types:
        raise FaceScanImageError("invalid_image", "Only JPG and PNG images are supported.")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise FaceScanImageError("invalid_image", "Image data is not valid.") from exc
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise FaceScanImageError("invalid_image", "Image is larger than the allowed size.")
    return image_bytes


class AttendanceFaceScanController(http.Controller):
    @http.route(
        "/hr_attendance/face_scan",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
    )
    def face_scan(self, token=None, image_data=None):
        company = AttendanceController._get_company(token) if token else request.env["res.company"]
        if not company:
            return _error("invalid_kiosk", _("This attendance kiosk link is not valid."))

        try:
            image_bytes = _decode_image_data_url(image_data)
            embedding = get_face_engine().embedding_from_bytes(image_bytes)
        except FaceScanImageError as exc:
            messages = {
                "invalid_image": _("Choose a JPG or PNG image up to 10 MB."),
                "no_face": _("No face was found. Choose a clear photo with one visible face."),
                "multiple_faces": _("The image must contain only one face."),
            }
            return _error(exc.code, messages.get(exc.code, _("The selected image could not be processed.")))
        except FaceModelUnavailable:
            _logger.exception("Face scan models are not ready.")
            return _error("model_unavailable", _("The face scan service is not ready."))
        except Exception:
            _logger.exception("Unexpected error while creating a kiosk face embedding.")
            return _error("scan_failed", _("The image could not be processed. Please try again."))

        return self._match_embedding(company, embedding)

    @http.route("/hr_attendance/face_scan_frame", type="jsonrpc", auth="public", methods=["POST"])
    def face_scan_frame(self, token=None, image_data=None, session_uid=None):
        company = AttendanceController._get_company(token) if token else request.env["res.company"]
        if not company:
            return _error("invalid_kiosk", _("This attendance kiosk link is not valid."))
        if session_uid is not None:
            try:
                if not isinstance(session_uid, str) or str(uuid.UUID(session_uid)) != session_uid:
                    raise ValueError()
            except ValueError:
                return _error("invalid_session", _("Invalid video session."))
            if company.attendance_kiosk_use_pin or company.attendance_capture_check_in:
                return _error("policy_requires_confirmation", _("Automatic video attendance is unavailable while kiosk PIN or check-in photo capture is enabled."))
        try:
            faces = get_face_engine().faces_from_bytes(_decode_image_data_url(image_data))
            results = []
            for face in faces:
                match = self._match_embedding(company, face["embedding"])
                item = {
                    "box": face["box"],
                    "landmarks": face["landmarks"],
                    "detection_confidence": face["detection_confidence"],
                }
                if match.get("status") == "success":
                    employee = request.env["hr.employee"].sudo().browse(match["employee_id"])
                    item.update(employee_id=employee.id, name=employee.name)
                    if session_uid:
                        try:
                            with request.env.cr.savepoint():
                                geo = AttendanceController._get_geoip_response(
                                    "kiosk", device_tracking_enabled=company.attendance_device_tracking,
                                )
                                item.update(request.env["attendance.face.video.event"].sudo().process_video_match(
                                    company, employee, session_uid, geo,
                                ))
                        except Exception:
                            _logger.exception("Automatic attendance failed for employee %s", employee.id)
                            item["action"] = "error"
                results.append(item)
            return {"status": "success", "faces": results}
        except FaceScanImageError:
            return _error("invalid_image", _("The video frame could not be processed."))
        except FaceModelUnavailable:
            _logger.exception("Face scan models are not ready.")
            return _error("model_unavailable", _("The face scan service is not ready."))
        except Exception:
            _logger.exception("Error processing video frame")
            return _error("scan_failed", _("The video frame could not be processed."))

    def _match_embedding(self, company, embedding):
        matches = request.env["attendance.face.embedding"].sudo().best_matches(company, embedding, limit=2)
        if not matches:
            return _error("no_match", _("This face is not recognized."))

        best_employee_id, best_similarity, _matched_image_sha256, _matched_model_version = matches[0]
        best_similarity = float(best_similarity)
        second_similarity = float(matches[1][1]) if len(matches) > 1 else None
        threshold = self._get_parameter_float(
            "attendance_face_scan.match_threshold",
            DEFAULT_MATCH_THRESHOLD,
        )
        ambiguity_margin = self._get_parameter_float(
            "attendance_face_scan.ambiguity_margin",
            DEFAULT_AMBIGUITY_MARGIN,
        )
        if best_similarity < threshold:
            return _error("no_match", _("This face is not recognized."))
        if second_similarity is not None and best_similarity - second_similarity < ambiguity_margin:
            return _error("ambiguous_match", _("The match is unclear. Try another photo."))

        employee = request.env["hr.employee"].sudo().browse(best_employee_id).exists()
        if not employee or not employee.active or employee.company_id != company:
            return _error("no_match", _("This face is not recognized."))

        # Identification only: the kiosk handles PIN, confirmation and attendance
        # through the same flow as a manually selected employee.
        return {"status": "success", "employee_id": employee.id}

    @staticmethod
    def _get_parameter_float(key, default):
        value = request.env["ir.config_parameter"].sudo().get_float(key, default)
        return value if 0.0 <= value <= 1.0 else default
