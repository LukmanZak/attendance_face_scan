"""Keep employee profile-photo embeddings synchronized with Odoo."""

import base64
import binascii
import hashlib
import logging

from odoo import _, api, fields, models

from .face_engine import (
    MODEL_VERSION,
    FaceModelUnavailable,
    FaceScanImageError,
    get_face_engine,
)

_logger = logging.getLogger(__name__)
FACE_SCAN_GROUPS = "hr_attendance.group_hr_attendance_manager"


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    face_scan_index_status = fields.Selection(
        [
            ("missing_photo", "Profile Photo Missing"),
            ("indexed", "Indexed"),
            ("no_face", "No Face Found"),
            ("multiple_faces", "Multiple Faces Found"),
            ("model_unavailable", "Model Unavailable"),
            ("error", "Indexing Error"),
            ("archived", "Archived"),
        ],
        string="Face Scan Index Status",
        default="missing_photo",
        copy=False,
        groups=FACE_SCAN_GROUPS,
    )
    face_scan_indexed_at = fields.Datetime(
        string="Face Scan Indexed At",
        readonly=True,
        copy=False,
        groups=FACE_SCAN_GROUPS,
    )
    face_scan_index_message = fields.Char(
        string="Face Scan Index Details",
        readonly=True,
        copy=False,
        groups=FACE_SCAN_GROUPS,
    )

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        for employee in employees:
            if employee.image_1920:
                employee._update_face_scan_index()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if {"image_1920", "active", "company_id"} & vals.keys():
            for employee in self:
                employee._update_face_scan_index()
        return result

    def _profile_image_bytes(self):
        self.ensure_one()
        image_value = self.image_1920
        if not image_value:
            return b""
        if isinstance(image_value, str):
            return base64.b64decode(image_value, validate=True)
        if isinstance(image_value, bytes):
            try:
                return base64.b64decode(image_value, validate=True)
            except (ValueError, binascii.Error):
                return image_value
        return bytes(image_value)

    def _set_face_scan_status(self, status, message=False, indexed_at=False):
        self.sudo().write(
            {
                "face_scan_index_status": status,
                "face_scan_index_message": message or False,
                "face_scan_indexed_at": indexed_at or False,
            }
        )

    def _remove_face_scan_embedding(self):
        self.env["attendance.face.embedding"].sudo().search(
            [("employee_id", "=", self.id)]
        ).unlink()

    def _update_face_scan_index(self):
        embeddings = self.env["attendance.face.embedding"].sudo()
        for employee in self.sudo():
            if not employee.active:
                embeddings.search([("employee_id", "=", employee.id)]).unlink()
                employee._set_face_scan_status("archived")
                continue

            if not employee.image_1920:
                embeddings.search([("employee_id", "=", employee.id)]).unlink()
                employee._set_face_scan_status("missing_photo")
                continue

            try:
                image_bytes = employee._profile_image_bytes()
                image_sha256 = hashlib.sha256(image_bytes).hexdigest()
                existing = embeddings.search([("employee_id", "=", employee.id)], limit=1)
                if (
                    existing
                    and existing.source_image_sha256 == image_sha256
                    and existing.model_version == MODEL_VERSION
                    and existing.company_id == employee.company_id
                ):
                    employee._set_face_scan_status(
                        "indexed",
                        indexed_at=existing.indexed_at,
                    )
                    continue

                vector = get_face_engine().embedding_from_bytes(image_bytes)
                embeddings.upsert_employee_embedding(employee, vector, image_sha256)
                employee._set_face_scan_status("indexed", indexed_at=fields.Datetime.now())
            except FaceScanImageError as exc:
                embeddings.search([("employee_id", "=", employee.id)]).unlink()
                status = exc.code if exc.code in ("no_face", "multiple_faces") else "error"
                employee._set_face_scan_status(status, str(exc))
            except FaceModelUnavailable as exc:
                embeddings.search([("employee_id", "=", employee.id)]).unlink()
                employee._set_face_scan_status("model_unavailable", str(exc))
            except Exception:
                _logger.exception("Unable to index employee profile photo (employee id %s)", employee.id)
                embeddings.search([("employee_id", "=", employee.id)]).unlink()
                employee._set_face_scan_status("error", _("Could not process the profile photo."))

    @api.model
    def _rebuild_face_scan_index(self):
        employees_model = self.with_context(active_test=False).sudo()
        last_id = 0
        indexed = 0
        unindexed = 0
        while True:
            employees = employees_model.search(
                [("id", ">", last_id)],
                order="id",
                limit=100,
            )
            if not employees:
                break
            for employee in employees:
                employee._update_face_scan_index()
                if employee.face_scan_index_status == "indexed":
                    indexed += 1
                else:
                    unindexed += 1
            last_id = employees[-1].id
        _logger.info("Face scan index rebuild completed: %s indexed, %s unindexed", indexed, unindexed)
        return {"indexed": indexed, "unindexed": unindexed}
