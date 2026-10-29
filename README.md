# Attendance Face Scan

Modul Odoo 20 untuk scan wajah dari video, pencocokan pegawai, pencatatan absensi, dan sinkronisasi ke Google Sheets. Deteksi menggunakan YuNet dan SFace, dengan titik wajah MediaPipe dan pencocokan embedding melalui pgvector.

## Perbandingan deteksi wajah

| Pegawai | Foto tanpa deteksi | Hasil deteksi dari video |
| --- | --- | --- |
| Maya Carter | ![Maya tanpa deteksi](screenshots/maya-before.png) | ![Deteksi Maya](screenshots/maya-detection.png) |
| Daniel Brooks | ![Daniel tanpa deteksi](screenshots/daniel-before.png) | ![Deteksi Daniel](screenshots/daniel-detection.png) |

Persentase menunjukkan skor deteksi wajah. Titik biru menunjukkan landmark wajah.

## Bukti

Absensi di Odoo:

![Absensi Odoo](screenshots/odoo-attendance.png)

Data di Google Sheets:

![Google Sheets](screenshots/google-sheets.png)

## Kebutuhan

Odoo 20, modul hr_attendance, PostgreSQL dengan pgvector, dependensi pada requirements-face.txt, dan model YuNet/SFace. Konfigurasi URL Apps Script dan token melalui variabel FACE_SHEETS_URL dan FACE_SHEETS_TOKEN.

## Cara kerja

1. Pengguna memilih dan memutar video MP4 atau WebM di kiosk Odoo.
2. Browser mengambil frame video, mengecilkannya hingga sisi terpanjang maksimal 640 piksel, lalu mengirim frame JPEG ke server Odoo.
3. YuNet mendeteksi wajah, kotak dan lima titik wajah. SFace menyelaraskan wajah dan membuat embedding 128 dimensi yang dinormalisasi.
4. Odoo membandingkan embedding dengan embedding foto pegawai menggunakan cosine similarity dan indeks HNSW pgvector. Hasil harus melewati ambang kecocokan dan jarak minimum dari kandidat berikutnya.
5. Jika dikenali, sistem mencatat masuk atau pulang sesuai status absensi saat itu. Per sesi video, tiap pegawai diproses sekali dan ada jeda 60 detik antaraksi absensi otomatis.
6. Event absensi masuk ke antrean. Job Odoo berjalan setiap menit dan mengirim event ke Apps Script untuk dicatat di Google Sheets.

MediaPipe Face Landmarker berjalan di browser untuk tampilan titik wajah. Pelacakan di browser membantu kotak mengikuti gerakan di antara respons server; pengenalan identitas tetap dilakukan oleh SFace di server. Angka **Deteksi 94%** menunjukkan skor deteksi wajah YuNet, bukan tingkat keyakinan identitas pegawai.

## Hasil pengukuran lokal

Pengukuran berikut dilakukan pada mesin pengembang dengan Intel Core i5-1335U (10 core, 12 logical processor), RAM 15,7 GiB, Docker, dan OpenCV 4.14.0. Pengujian memanggil deteksi dan pembuatan embedding secara langsung, tanpa membuat absensi baru.

| Pengukuran | Hasil |
| --- | --- |
| Ukuran gambar uji | 250 × 295 piksel, satu wajah |
| Memuat model | 196,6 ms |
| Proses gambar pertama | 56,2 ms |
| Median 11 proses berikutnya | 11,4 ms; minimum 10,5 ms; maksimum 15,1 ms |
| Model YuNet / SFace | Sekitar 0,22 MiB / 36,9 MiB |
| Kontainer Odoo saat diam | Sekitar 285 MiB RAM; CPU 0,02% saat sampel |
| Kontainer PostgreSQL saat diam | Sekitar 126 MiB RAM; CPU 0,00% saat sampel |

Ini **bukan** waktu dari awal video sampai absensi tercatat. Pengukuran belum mencakup browser, MediaPipe, pengiriman frame, pencarian database, pencatatan absensi, atau sinkronisasi Sheets. Gambar uji lebih kecil daripada batas frame 640 piksel dan hanya berisi satu wajah; hasil dapat berbeda menurut ukuran frame, jumlah wajah, suhu dan beban mesin. Belum ada pengukuran FPS, latensi end-to-end, konsumsi CPU saat scan, penggunaan GPU, maupun pengujian banyak pengguna bersamaan. Angka CPU di atas hanyalah satu sampel saat sistem diam, bukan kapasitas yang dijamin.

## Risiko dan penanganan

| Risiko atau kendala | Kondisi saat ini dan penanganan |
| --- | --- |
| Video rekaman diputar ulang | **Belum ada liveness atau pemeriksaan keaslian**. Rekaman dapat memicu absensi lagi setelah jeda. Gunakan untuk demo atau lingkungan tepercaya; untuk penggunaan produksi, perlukan mekanisme verifikasi tambahan dan tinjau kecocokannya dengan kebutuhan. |
| Salah mengenali atau gagal mengenali | Sistem memakai ambang similarity default 0,363 dan selisih minimal 0,05 dengan kandidat kedua; keduanya dapat diatur. Nilai ini belum divalidasi pada dataset pegawai pengguna. Ukur false acceptance dan false rejection pada kondisi nyata sebelum menentukan ambang; sediakan koreksi dan cara absensi alternatif. |
| Wajah buram, tertutup, kecil, atau pencahayaan buruk | Deteksi dapat gagal atau titik bergeser. Gunakan video dan foto profil yang jelas; bila titik MediaPipe tidak tersedia atau wajah terlalu kecil, tampilan dapat menggunakan lima titik YuNet. |
| Persentase pada kotak | Skor pada layar adalah skor deteksi wajah, bukan probabilitas orang yang cocok. Tidak boleh digunakan sebagai bukti bahwa identitas benar dengan persentase tersebut. |
| Aksi berulang atau kiosk bersamaan | Ada penguncian per pegawai, pembatasan satu aksi per sesi dan jeda 60 detik. Perlindungan ini tidak mencegah pemutaran ulang setelah jeda dan bukan pengganti verifikasi identitas. |
| Status masuk dan pulang | Aksi otomatis mengikuti status absensi terakhir. Video yang diputar kembali dapat mengubah status menjadi pulang atau masuk; periksa dan koreksi catatan bila diperlukan. |
| PIN atau foto check-in diaktifkan | Scan video otomatis ditolak saat kebijakan tersebut aktif, agar tidak melewati konfirmasi kiosk. Gunakan metode absensi yang sesuai kebijakan. |
| Google Sheets atau internet gagal | Event yang belum terkirim tetap mengantre dan dicoba pada job berikutnya. Setiap event memiliki ID tetap untuk membantu Apps Script menolak duplikasi. Pantau log dan antrean; sinkronisasi tidak dijamin langsung. |
| Beban dan antrean meningkat | Job mengambil maksimal 50 event per siklus dan mengirim satu per satu dengan timeout 20 detik per permintaan. Keterlambatan dapat bertambah ketika layanan lambat atau antrean besar. Batas kapasitas riil belum diuji. |
| Privasi dan keamanan | Foto pegawai dan embedding merupakan data sensitif. Batasi akses, tentukan masa simpan dan penghapusan, amankan backup dan jaringan, serta gunakan metode alternatif sesuai kebijakan organisasi. Frame video tidak disimpan sebagai bukti oleh alur scan video ini. |
| URL kiosk dan token | Lindungi URL kiosk, token Apps Script dan file `.env`; batasi akses jaringan dan tinjau endpoint publik sebelum produksi. Jangan menyimpan token di repositori. Token yang pernah dibagikan harus diganti di Apps Script dan konfigurasi Odoo. |
| Skala dan kualitas model | Belum diuji untuk banyak kiosk, banyak wajah sekaligus, atau representasi pegawai yang beragam. Lakukan uji beban dan uji akurasi pada data yang relevan sebelum menetapkan kapasitas. |

## Biaya dan batas layanan

- Deteksi dan embedding berjalan secara lokal; implementasi ini tidak memanggil API AI berbayar per scan dan tidak memerlukan API key AI. Tetap ada biaya perangkat, listrik, internet, penyimpanan, backup, pemeliharaan, dan tenaga pengelola.
- Biaya Odoo bergantung pada edisi, lisensi dan cara hosting yang digunakan. Jangan menganggap deployment ini otomatis bebas biaya lisensi; periksa kontrak dan [harga Odoo](https://www.odoo.com/pricing).
- Google Apps Script dan Google Sheets memiliki batas layanan dan kuota yang bergantung pada jenis akun serta dapat berubah. Melampaui batas dapat menyebabkan kegagalan atau keterlambatan; lihat [kuota Apps Script](https://developers.google.com/apps-script/guides/services/quotas). Kuota Sheets API tidak otomatis sama dengan kuota layanan SpreadsheetApp yang dipakai Apps Script.
- Tidak ada estimasi nominal bulanan yang dapat dipastikan tanpa jumlah pegawai, frekuensi scan, jam operasional, jenis lisensi, tarif listrik dan pilihan hosting. Biaya pengembangan, dukungan dan pengujian keamanan juga belum dihitung.
