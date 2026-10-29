from odoo import fields, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    face_scan_ids = fields.One2many(
        "attendance.face.scan",
        "attendance_id",
        string="Face Scan Evidence",
        groups="hr_attendance.group_hr_attendance_manager",
        readonly=True,
    )
