/** Visual tracking between server detections; never used to identify employees. */
export class FaceVideoTracker {
    constructor(video) {
        this.video = video;
        this.canvas = document.createElement("canvas");
        this.canvas.width = 320;
        this.canvas.height = Math.max(1, Math.round(320 * video.videoHeight / video.videoWidth));
        this.context = this.canvas.getContext("2d", { willReadFrequently: true });
        this.tracks = [];
        this.previous = null;
        this.lastFrameTime = 0;
    }

    clear() {
        this.tracks = [];
        this.previous = null;
    }

    snapshot() {
        return this.tracks.map(track => ({ track, box: [...track.box] }));
    }

    update(faces, snapshot, width, height) {
        const now = performance.now();
        const available = snapshot.filter(item => this.tracks.includes(item.track));
        this.tracks = faces.map(face => {
            const box = face.box.map((value, index) => value / (index % 2 ? height : width));
            const cx = box[0] + box[2] / 2;
            const cy = box[1] + box[3] / 2;
            let best = -1;
            let distance = Infinity;
            for (let i = 0; i < available.length; i++) {
                const candidate = available[i];
                // Do not carry a label across two different known employees.
                if (face.employee_id && candidate.track.employee_id && face.employee_id !== candidate.track.employee_id) continue;
                const previous = candidate.box;
                const d = Math.hypot(cx - previous[0] - previous[2] / 2, cy - previous[1] - previous[3] / 2);
                if (d < Math.max(box[2], box[3], previous[2], previous[3]) * 0.6 && d < distance) {
                    best = i;
                    distance = d;
                }
            }
            const matched = best < 0 ? null : available.splice(best, 1)[0];
            // Existing tracks have already followed newer video frames while the RPC ran.
            const track = matched ? matched.track : { box };
            if (matched) {
                // Correct accumulated optical-flow drift using the new detection,
                // while retaining movement since the request was captured.
                for (let i = 0; i < 4; i++) track.box[i] += box[i] - matched.box[i];
            }
            track.employee_id = face.employee_id || null;
            track.name = face.name || "Tidak dikenal";
            track.confidence = face.detection_confidence;
            track.landmarks = (face.landmarks || []).map(([x, y]) => [
                (x / width - box[0]) / box[2], (y / height - box[1]) / box[3],
            ]);
            track.lastDetection = now;
            return track;
        });
    }

    advance(now) {
        if (now - this.lastFrameTime < 70 || this.video.paused || this.video.ended) return;
        this.lastFrameTime = now;
        const width = this.canvas.width, height = this.canvas.height;
        this.context.drawImage(this.video, 0, 0, width, height);
        const pixels = this.context.getImageData(0, 0, width, height).data;
        const gray = new Uint8Array(width * height);
        for (let i = 0; i < gray.length; i++) {
            gray[i] = (pixels[i * 4] * 77 + pixels[i * 4 + 1] * 150 + pixels[i * 4 + 2] * 29) >> 8;
        }
        if (this.previous) {
            for (const track of this.tracks) {
                const [x, y, w, h] = track.box;
                const cx = Math.round((x + w / 2) * width);
                const cy = Math.round((y + h * 0.48) * height);
                const half = Math.max(3, Math.min(8, Math.round(Math.min(w * width, h * height) * 0.18)));
                if (cx - half - 12 < 0 || cx + half + 12 >= width || cy - half - 12 < 0 || cy + half + 12 >= height) continue;
                let bestScore = Infinity, bestX = 0, bestY = 0;
                for (let dy = -12; dy <= 12; dy += 2) {
                    for (let dx = -12; dx <= 12; dx += 2) {
                        let score = 0;
                        for (let py = -half; py <= half; py += 2) {
                            for (let px = -half; px <= half; px += 2) {
                                const index = (cy + py) * width + cx + px;
                                score += Math.abs(this.previous[index] - gray[index + dy * width + dx]);
                            }
                        }
                        // Prefer small movements when the patch is flat or repetitive.
                        score += (Math.abs(dx) + Math.abs(dy)) * (Math.floor(half) + 1) ** 2 * 0.35;
                        if (score < bestScore) { bestScore = score; bestX = dx; bestY = dy; }
                    }
                }
                const samples = (Math.floor(half) + 1) ** 2;
                if (bestScore / samples < 30) {
                    track.box[0] = Math.max(0, Math.min(1 - w, x + bestX / width));
                    track.box[1] = Math.max(0, Math.min(1 - h, y + bestY / height));
                }
            }
        }
        this.previous = gray;
        this.tracks = this.tracks.filter(track => now - track.lastDetection < 1500);
    }
}
