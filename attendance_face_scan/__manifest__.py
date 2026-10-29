{
    "name": "Attendance Face Scan",
    "summary": "Identify employees with local face embeddings in the attendance kiosk",
    "version": "20.0.1.0.0",
    "category": "Human Resources/Attendances",
    "license": "LGPL-3",
    "depends": ["hr_attendance"],
    "data": [
        "security/ir.access.csv",
        "views/hr_attendance_views.xml",
        "views/res_config_settings_views.xml",
        "views/face_index_views.xml",
        "data/ir_cron.xml",
    ],
    "assets": {
        "hr_attendance.assets_public_attendance": [
            "attendance_face_scan/static/src/js/face_video_tracker.js",
            "attendance_face_scan/static/src/js/face_scan_kiosk.js",
            "attendance_face_scan/static/src/xml/face_scan_kiosk.xml",
            "attendance_face_scan/static/src/scss/face_scan_kiosk.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
