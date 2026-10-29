# Attendance Face Scan

Modul Odoo 20 untuk scan wajah dari video, pencocokan pegawai, pencatatan absensi, dan sinkronisasi ke Google Sheets. Deteksi menggunakan YuNet dan SFace, dengan titik wajah MediaPipe dan pencocokan embedding melalui pgvector.

## Bukti

Absensi di Odoo:

![Absensi Odoo](screenshots/odoo-attendance.png)

Data di Google Sheets:

![Google Sheets](screenshots/google-sheets.png)

## Kebutuhan

Odoo 20, modul hr_attendance, PostgreSQL dengan pgvector, dependensi pada requirements-face.txt, dan model YuNet/SFace. Konfigurasi URL Apps Script dan token melalui variabel FACE_SHEETS_URL dan FACE_SHEETS_TOKEN.
