"""Protected audit records for successful kiosk face scans."""

from datetime import timedelta
import logging
import os

import pytz
import requests

from odoo import fields, models


FACE_SCAN_GROUPS = "hr_attendance.group_hr_attendance_manager"
_logger = logging.getLogger(__name__)


class AttendanceFaceScan(models.Model):
    _name = "attendance.face.scan"
    _description = "Attendance Face Scan Evidence"
    _order = "scan_time desc, id desc"

    name = fields.Char(required=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", required=True, index=True, ondelete="cascade")
    attendance_id = fields.Many2one(
        "hr.attendance",
        required=True,
        index=True,
        ondelete="cascade",
        groups=FACE_SCAN_GROUPS,
    )
    action = fields.Selection(
        [("check_in", "Check In"), ("check_out", "Check Out")],
        required=True,
        index=True,
        groups=FACE_SCAN_GROUPS,
    )
    scan_time = fields.Datetime(required=True, default=fields.Datetime.now, index=True, groups=FACE_SCAN_GROUPS)
    similarity = fields.Float(required=True, digits=(5, 4), groups=FACE_SCAN_GROUPS)
    request_uid = fields.Char(required=True, copy=False, index=True, groups=FACE_SCAN_GROUPS)
    scan_image = fields.Binary(
        string="Scan Image",
        required=True,
        attachment=True,
        groups=FACE_SCAN_GROUPS,
    )

    _company_request_unique = models.Constraint(
        "unique(company_id, request_uid)",
        "This face scan request has already been recorded.",
    )


class AttendanceFaceVideoEvent(models.Model):
    _name = "attendance.face.video.event"
    _description = "Automatic Video Attendance Event"
    _order = "id desc"

    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", required=True, index=True, ondelete="cascade")
    session_uid = fields.Char(required=True, index=True)
    action = fields.Selection([
        ("check_in", "Check In"), ("check_out", "Check Out"),
        ("cooldown", "Cooldown"), ("no_action", "No Change"),
    ], required=True)
    attendance_id = fields.Many2one("hr.attendance", ondelete="set null")
    scan_time = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    # Existing events predate the integration and must not be sent retroactively.
    sheets_synced = fields.Boolean(default=True, index=True, copy=False)
    _session_employee_unique = models.Constraint(
        "unique(company_id, employee_id, session_uid)",
        "This employee has already been processed in this video session.",
    )

    def _cron_sync_google_sheets(self):
        url = os.environ.get("FACE_SHEETS_URL")
        token = os.environ.get("FACE_SHEETS_TOKEN")
        if not url or not token:
            return
        database_uuid = self.env["ir.config_parameter"].sudo().get_str("database.uuid")
        if not database_uuid:
            _logger.error("Cannot sync face scan events without database.uuid")
            return
        events = self.sudo().search([
            ("action", "in", ["check_in", "check_out"]),
            ("sheets_synced", "=", False),
        ], order="id", limit=50)
        for event in events:
            local_time = pytz.utc.localize(event.scan_time).astimezone(pytz.timezone("Asia/Jakarta"))
            payload = {
                "token": token,
                "event_id": f"odoo-{database_uuid}-{event.id}",
                "nama": event.employee_id.name,
                "waktu": local_time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "masuk" if event.action == "check_in" else "pulang",
            }
            try:
                response = requests.post(url, json=payload, timeout=20)
                response.raise_for_status()
                result = response.json()
                if result.get("success") is not True:
                    _logger.warning("Google Sheets rejected face event %s: %s", event.id, result.get("error", "unknown error"))
                    break
                event.sheets_synced = True
            except (requests.RequestException, ValueError):
                _logger.exception("Could not sync face event %s to Google Sheets", event.id)
                break

    def process_video_match(self, company, employee, session_uid, geo_information):
        # A non-blocking per-employee lock prevents duplicate toggles and deadlocks
        # when multiple kiosks see the same faces concurrently.
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (773382, employee.id))
        if not self.env.cr.fetchone()[0]:
            return {"action": "busy"}
        events = self.sudo()
        previous = events.search([
            ("company_id", "=", company.id), ("employee_id", "=", employee.id),
            ("session_uid", "=", session_uid),
        ], limit=1)
        if previous:
            return {"action": previous.action, "repeat": True}
        recent = events.search([
            ("company_id", "=", company.id), ("employee_id", "=", employee.id),
            ("action", "in", ["check_in", "check_out"]),
            ("scan_time", ">=", fields.Datetime.now() - timedelta(seconds=60)),
        ], limit=1)
        action = "cooldown"
        attendance = self.env["hr.attendance"].sudo()
        if not recent:
            employee.invalidate_recordset(["attendance_state", "last_attendance_id"])
            before = employee.attendance_state
            employee._attendance_action_change(geo_information)
            employee.invalidate_recordset(["attendance_state", "last_attendance_id"])
            after = employee.attendance_state
            action = ("check_in" if after == "checked_in" else "check_out") if before != after else "no_action"
            attendance = employee.last_attendance_id
        events.create({
            "company_id": company.id, "employee_id": employee.id,
            "session_uid": session_uid, "action": action,
            "attendance_id": attendance.id or False,
            "sheets_synced": action not in ("check_in", "check_out"),
        })
        return {"action": action, "repeat": False}
