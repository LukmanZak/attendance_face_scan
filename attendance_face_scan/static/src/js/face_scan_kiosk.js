import kiosk from "@hr_attendance/public_kiosk/public_kiosk_app";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
import { FaceVideoTracker } from "@attendance_face_scan/js/face_video_tracker";

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

patch(kiosk.kioskAttendanceApp.prototype, {
    async onFaceVideoSelected(event) {
        const input = event.target;
        const file = input.files?.[0];
        input.value = "";
        if (!file) return;
        if (file.size > 100 * 1024 * 1024 || !/\.(mp4|webm)$/i.test(file.name)) {
            this.displayNotification("Pilih video MP4 atau WebM maksimal 100 MB.");
            return;
        }
        this.closeFaceVideo?.();
        const panel = document.createElement("div");
        panel.className = "o_face_video_panel";
        const video = document.createElement("video");
        video.controls = true;
        video.muted = true;
        video.playsInline = true;
        const canvas = document.createElement("canvas");
        canvas.className = "o_face_video_overlay";
        const stage = document.createElement("div");
        stage.className = "o_face_video_stage";
        stage.append(video, canvas);
        const message = document.createElement("p");
        message.textContent = "Putar video; pegawai yang dikenali akan dicatat otomatis.";
        const choices = document.createElement("div");
        const close = document.createElement("button");
        close.type = "button";
        close.className = "btn btn-secondary";
        close.textContent = "Tutup video";
        panel.append(stage, message, choices, close);
        input.closest(".o_face_scan_options").append(panel);
        const url = URL.createObjectURL(file);
        video.src = url;
        const sessionUid = crypto.randomUUID();
        const reported = new Set();
        let stopped = false;
        let generation = 0;
        let timer;
        let animation;
        let tracker;
        let meshFaces = [];
        let meshUpdatedAt = 0;
        let workerReady = false;
        let workerBusy = false;
        let lastMeshRequest = 0;
        let landmarkWorker;
        try {
            landmarkWorker = new Worker(
                "/attendance_face_scan/static/lib/mediapipe/face_landmark_worker.js?v=2"
            );
            landmarkWorker.onmessage = ({ data }) => {
                if (stopped) return;
                if (data.type === "ready") {
                    workerReady = true;
                } else if (data.type === "result") {
                    workerBusy = false;
                    if (data.generation === generation && !video.paused) {
                        meshFaces = data.faces;
                        meshUpdatedAt = performance.now();
                    }
                } else if (data.type === "error") {
                    workerReady = false;
                    workerBusy = false;
                    meshFaces = [];
                    console.warn("Face Landmarker unavailable:", data.message);
                }
            };
            landmarkWorker.onerror = () => { workerReady = false; meshFaces = []; };
            landmarkWorker.postMessage({ type: "init" });
        } catch (error) {
            console.warn("Face Landmarker unavailable:", error);
        }
        video.addEventListener("seeking", () => {
            generation++;
            meshFaces = [];
            tracker?.clear();
            canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
        });
        video.addEventListener("pause", () => { generation++; meshFaces = []; tracker?.clear(); });
        const cleanup = () => {
            stopped = true;
            clearTimeout(timer);
            cancelAnimationFrame(animation);
            landmarkWorker?.terminate();
            video.pause();
            video.removeAttribute("src");
            video.load();
            URL.revokeObjectURL(url);
            panel.remove();
            if (this.closeFaceVideo === cleanup) this.closeFaceVideo = null;
        };
        this.closeFaceVideo = cleanup;
        close.onclick = cleanup;
        video.onerror = () => { message.textContent = "Video tidak dapat dibuka oleh browser."; };
        const frame = document.createElement("canvas");
        const meshBox = (points) => {
            const xs = points.map(point => point[0]);
            const ys = points.map(point => point[1]);
            const minX = Math.min(...xs), maxX = Math.max(...xs);
            const minY = Math.min(...ys), maxY = Math.max(...ys);
            const paddingX = (maxX - minX) * 0.10, paddingY = (maxY - minY) * 0.10;
            const left = Math.max(0, minX - paddingX), top = Math.max(0, minY - paddingY);
            return [left, top, Math.min(1, maxX + paddingX) - left, Math.min(1, maxY + paddingY) - top];
        };
        const drawFace = (context, box, face, points, relativePoints = false) => {
            const [x, y, w, h] = box;
            const px = x * canvas.width, py = y * canvas.height;
            context.strokeStyle = face?.employee_id ? "#00e676" : "#ffb300";
            context.lineWidth = Math.max(2, canvas.width / 250);
            context.strokeRect(px, py, w * canvas.width, h * canvas.height);
            context.font = `${Math.max(12, Math.round(canvas.width / 40))}px sans-serif`;
            const confidence = Number.isFinite(face?.confidence)
                ? ` · Deteksi ${Math.round(face.confidence * 100)}%` : "";
            const label = (face?.name || "Wajah") + confidence;
            const labelY = py >= 23 ? py - 5 : py + 17;
            context.lineWidth = 3;
            context.strokeStyle = "#000";
            context.strokeText(label, px, labelY);
            context.fillStyle = face?.employee_id ? "#00e676" : "#ffb300";
            context.fillText(label, px, labelY);
            context.fillStyle = "#00e5ff";
            for (const point of points || []) {
                const pointX = relativePoints ? x + point[0] * w : point[0];
                const pointY = relativePoints ? y + point[1] * h : point[1];
                context.beginPath();
                context.arc(pointX * canvas.width, pointY * canvas.height, 1.2, 0, Math.PI * 2);
                context.fill();
            }
        };
        const draw = (now) => {
            if (stopped || !panel.isConnected) { if (!stopped) cleanup(); return; }
            if (tracker) {
                if (!video.paused && !video.ended) tracker.advance(now);
                const context = canvas.getContext("2d");
                context.clearRect(0, 0, canvas.width, canvas.height);
                const available = [...tracker.tracks];
                const meshes = now - meshUpdatedAt < 600 ? meshFaces : [];
                for (const points of meshes) {
                    if (!points.length) continue;
                    const box = meshBox(points);
                    const [x, y, w, h] = box;
                    let best = -1, bestDistance = Infinity;
                    for (let i = 0; i < available.length; i++) {
                        const other = available[i].box;
                        const dx = x + w / 2 - other[0] - other[2] / 2;
                        const dy = y + h / 2 - other[1] - other[3] / 2;
                        const distance = Math.hypot(dx, dy);
                        if (distance < Math.max(w, h, other[2], other[3]) * 0.5 && distance < bestDistance) {
                            best = i;
                            bestDistance = distance;
                        }
                    }
                    const face = best < 0 ? null : available.splice(best, 1)[0];
                    drawFace(context, box, face, points);
                }
                for (const face of available) {
                    if (!face.displayBox) face.displayBox = [...face.box];
                    for (let i = 0; i < 4; i++) {
                        face.displayBox[i] += (face.box[i] - face.displayBox[i]) * 0.45;
                    }
                    drawFace(context, face.displayBox, face, face.landmarks, true);
                }
            }
            if (workerReady && tracker?.tracks.length && !workerBusy && !video.paused && !video.ended && now - lastMeshRequest >= 100) {
                workerBusy = true;
                lastMeshRequest = now;
                const capturedGeneration = generation;
                const boxes = tracker.tracks.map(track => [...track.box]);
                createImageBitmap(video).then(bitmap => {
                    if (stopped || capturedGeneration !== generation) {
                        bitmap.close();
                        workerBusy = false;
                        return;
                    }
                    landmarkWorker.postMessage({ type: "frame", bitmap, generation: capturedGeneration, boxes }, [bitmap]);
                }).catch(() => { workerBusy = false; });
            }
            animation = requestAnimationFrame(draw);
        };
        animation = requestAnimationFrame(draw);
        const scan = async () => {
            if (stopped || !panel.isConnected) { if (!stopped) cleanup(); return; }
            if (!video.paused && !video.ended && video.videoWidth) {
                const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
                frame.width = Math.round(video.videoWidth * scale);
                frame.height = Math.round(video.videoHeight * scale);
                if (!tracker) {
                    tracker = new FaceVideoTracker(video);
                    canvas.width = frame.width;
                    canvas.height = frame.height;
                }
                frame.getContext("2d").drawImage(video, 0, 0, frame.width, frame.height);
                const scanGeneration = generation;
                const trackingSnapshot = tracker.snapshot();
                try {
                    const result = await rpc("/hr_attendance/face_scan_frame", {
                        token: this.props.token, image_data: frame.toDataURL("image/jpeg", 0.8),
                        session_uid: sessionUid,
                    });
                    if (stopped || !panel.isConnected) { if (!stopped) cleanup(); return; }
                    if (scanGeneration !== generation) {
                        timer = setTimeout(scan, 0);
                        return;
                    }
                    if (result.status !== "success") {
                        tracker.clear();
                        message.textContent = result.message || "Frame tidak dapat diproses.";
                    } else {
                        tracker.update(result.faces, trackingSnapshot, frame.width, frame.height);
                        for (const face of result.faces) {
                            const reportKey = `${face.employee_id}:${face.action}`;
                            if (face.employee_id && face.action && face.action !== "busy" && !reported.has(reportKey)) {
                                reported.add(reportKey);
                                const line = document.createElement("p");
                                const labels = {
                                    check_in: "Check-in berhasil", check_out: "Check-out berhasil",
                                    cooldown: "Diabaikan: tunggu 60 detik setelah scan sebelumnya, lalu pilih video lagi",
                                    no_action: "Tidak ada perubahan (periksa pengaturan absensi Odoo)",
                                    error: "Gagal mencatat absensi; akan dicoba lagi",
                                };
                                line.textContent = `${face.name}: ${labels[face.action] || face.action}`;
                                choices.append(line);
                            }
                        }
                        message.textContent = result.faces.length ? "Wajah dikenali diproses otomatis; hasil tampil di bawah." : "Belum ada wajah terdeteksi.";
                    }
                } catch (error) {
                    tracker.clear();
                    message.textContent = error?.message || "Scan video gagal.";
                }
            }
            if (!stopped) timer = setTimeout(scan, video.paused || video.ended ? 250 : 80);
        };
        scan();
    },
    async onFaceImageSelected(event) {
        const input = event.target;
        const file = input.files?.[0];
        input.value = "";
        if (!file || this.faceScanBusy) {
            return;
        }
        if (!["image/jpeg", "image/png"].includes(file.type) || file.size > MAX_IMAGE_BYTES) {
            this.displayNotification("Pilih file JPG atau PNG dengan ukuran maksimal 10 MB.");
            return;
        }
        this.faceScanBusy = true;
        this.ui.block();
        try {
            const imageData = await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result);
                reader.onerror = () => reject(new Error("File tidak dapat dibaca."));
                reader.readAsDataURL(file);
            });
            const result = await rpc("/hr_attendance/face_scan", {
                token: this.props.token,
                image_data: imageData,
            });
            if (result.status === "success" && result.employee_id) {
                await this.kioskEmployeeSelected(result.employee_id);
            } else {
                this.displayNotification(result.message || "Wajah tidak dikenali.");
            }
        } catch (error) {
            this.displayNotification(error?.data?.message || error?.message || "Scan gagal. Coba lagi.");
        } finally {
            this.faceScanBusy = false;
            this.ui.unblock();
        }
    },
});
