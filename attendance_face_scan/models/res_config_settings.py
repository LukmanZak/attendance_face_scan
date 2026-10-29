from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    face_scan_match_threshold = fields.Float(
        string="Minimum Face Similarity",
        default=0.363,
        config_parameter="attendance_face_scan.match_threshold",
        groups="hr_attendance.group_hr_attendance_manager",
        help="A scan is accepted only when its cosine similarity reaches this value.",
    )
    face_scan_ambiguity_margin = fields.Float(
        string="Minimum Candidate Gap",
        default=0.05,
        config_parameter="attendance_face_scan.ambiguity_margin",
        groups="hr_attendance.group_hr_attendance_manager",
        help="Reject a scan when the best and second-best employee scores are closer than this gap.",
    )

    @api.constrains("face_scan_match_threshold", "face_scan_ambiguity_margin")
    def _check_face_scan_thresholds(self):
        for settings in self:
            if not 0.0 <= settings.face_scan_match_threshold <= 1.0:
                raise ValidationError(_("Minimum Face Similarity must be between 0 and 1."))
            if not 0.0 <= settings.face_scan_ambiguity_margin <= 1.0:
                raise ValidationError(_("Minimum Candidate Gap must be between 0 and 1."))

    def action_rebuild_face_scan_index(self):
        if not self.env.user.has_group("hr_attendance.group_hr_attendance_manager"):
            raise AccessError(_("Only Attendance Administrators can rebuild the face index."))
        result = self.env["hr.employee"].sudo()._rebuild_face_scan_index()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Face Index Rebuilt"),
                "message": _(
                    "%(indexed)s indexed, %(unindexed)s need a usable profile photo.",
                    indexed=result["indexed"],
                    unindexed=result["unindexed"],
                ),
                "type": "success",
                "sticky": False,
            },
        }
