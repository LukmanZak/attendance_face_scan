let landmarker;
const base = "/attendance_face_scan/static/lib/mediapipe";

self.onmessage = async ({ data }) => {
    if (data.type === "init") {
        try {
            const { FaceLandmarker, FilesetResolver } = await import(`${base}/vision_bundle.mjs`);
            const files = await FilesetResolver.forVisionTasks(`${base}/wasm`);
            landmarker = await FaceLandmarker.createFromOptions(files, {
                baseOptions: { modelAssetPath: `${base}/face_landmarker.task` },
                runningMode: "IMAGE",
                numFaces: 1,
                minFaceDetectionConfidence: 0.5,
                minFacePresenceConfidence: 0.5,
                minTrackingConfidence: 0.5,
            });
            self.postMessage({ type: "ready" });
        } catch (error) {
            self.postMessage({ type: "error", message: String(error) });
        }
    } else if (data.type === "frame") {
        try {
            if (!landmarker) return;
            const faces = [];
            const image = data.bitmap;
            const canvas = new OffscreenCanvas(256, 256);
            const context = canvas.getContext("2d");
            for (const box of (data.boxes || []).slice(0, 5)) {
                const [x, y, w, h] = box;
                const side = Math.min(Math.max(w * image.width, h * image.height) * 2.2, image.width, image.height);
                if (side < 10) continue;
                const left = Math.max(0, Math.min(image.width - side, (x + w / 2) * image.width - side / 2));
                const top = Math.max(0, Math.min(image.height - side, (y + h / 2) * image.height - side / 2));
                context.drawImage(image, left, top, side, side, 0, 0, 256, 256);
                const result = landmarker.detect(canvas);
                if (result.faceLandmarks.length) {
                    faces.push(result.faceLandmarks[0].map(({ x: px, y: py }) => [
                        (left + px * side) / image.width, (top + py * side) / image.height,
                    ]));
                }
            }
            self.postMessage({
                type: "result",
                generation: data.generation,
                faces,
            });
        } catch (error) {
            self.postMessage({ type: "error", message: String(error) });
        } finally {
            data.bitmap.close();
        }
    }
};
