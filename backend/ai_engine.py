import os
import sys
import cv2
import numpy as np
import wave
import re


class LocalAIEngine:
    """Local AI engine that attempts multiple offline transcription backends.

    Strategy:
    1. If OpenVINO-based `openvino_genai.WhisperPipeline` is available and the
       expected model folder exists, use it.
    2. Else, try the `whisper` Python package (OpenAI Whisper) if installed.
    3. As a last resort, return a helpful error message guiding the user to
       install dependencies or provide a local model.
    """

    def __init__(self):
        self.app_dir = self._get_runtime_dir()
        self.model_dir = os.path.join(self.app_dir, "models")
        self.ov_whisper_path = os.path.join(self.model_dir, "whisper-tiny-ov")
        self.ov_pipeline = None
        self.whisper_model = None
        self.face_cascade = None
        self.pytesseract = None
        self.ocr_available = False
        self.initialized = False

    def _get_runtime_dir(self) -> str:
        if getattr(sys, "frozen", False):
            executable_dir = os.path.dirname(sys.executable)
            internal_dir = getattr(sys, "_MEIPASS", executable_dir)
            if os.path.exists(os.path.join(executable_dir, "ffmpeg")):
                return executable_dir
            return internal_dir
        return os.path.dirname(__file__)

    def _resolve_ffmpeg_executable(self) -> str:
        candidates = [
            os.path.join(self.app_dir, "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(self.app_dir, "ffmpeg", "bin", "ffmpeg"),
            os.path.join(os.path.dirname(sys.executable), "ffmpeg", "bin", "ffmpeg.exe") if getattr(sys, "frozen", False) else "",
            os.path.join(os.path.dirname(sys.executable), "ffmpeg", "bin", "ffmpeg") if getattr(sys, "frozen", False) else "",
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return "ffmpeg"

    def _get_face_cascade(self):
        """Lazily load OpenCV face detector used for speaker-like scene hints."""
        if self.face_cascade is not None:
            return self.face_cascade
        try:
            cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            cascade = cv2.CascadeClassifier(cascade_path)
            if cascade.empty():
                self.face_cascade = None
            else:
                self.face_cascade = cascade
        except Exception:
            self.face_cascade = None
        return self.face_cascade

    def lazy_init(self):
        if self.initialized:
            return
        # Try OpenVINO GenAI first (fast on CPU if available)
        try:
            from openvino_genai import WhisperPipeline
            if os.path.exists(self.ov_whisper_path):
                print("Initializing OpenVINO WhisperPipeline from", self.ov_whisper_path)
                self.ov_pipeline = WhisperPipeline(self.ov_whisper_path, device="CPU")
        except Exception:
            # openvino_genai not available or model missing
            self.ov_pipeline = None

        # Next: try python `whisper` package (may need PyTorch)
        if self.whisper_model is None:
            try:
                import whisper
                # Do not load model automatically here; load on demand to avoid
                # large startup times. Use a tiny model by default when asked.
                self.whisper_package = whisper
            except Exception:
                self.whisper_package = None

        # Optional local OCR support via pytesseract.
        try:
            import pytesseract

            # Allow explicit local override for Tesseract executable on Windows.
            tesseract_path = os.environ.get("TESSERACT_CMD", "").strip()
            if tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path

            self.pytesseract = pytesseract
            self.ocr_available = True
        except Exception:
            self.pytesseract = None
            self.ocr_available = False

        self.initialized = True

    def _extract_ocr_text(self, frame: np.ndarray) -> list[str]:
        """Extract on-screen text from a frame using local OCR when available."""
        if not self.ocr_available or self.pytesseract is None:
            return []

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            proc_adaptive = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                11,
            )
            _, proc_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            proc_inv = cv2.bitwise_not(proc_otsu)

            variants = [frame, gray, proc_adaptive, proc_otsu, proc_inv]
            best_lines = []

            for variant in variants:
                text = self.pytesseract.image_to_string(variant, config="--oem 3 --psm 6")
                if not text:
                    continue

                lines = []
                for line in text.splitlines():
                    normalized = re.sub(r"\s+", " ", line).strip()
                    if len(normalized) < 3:
                        continue
                    # Keep lines with letters or digits, skip pure punctuation.
                    if not re.search(r"[A-Za-z0-9]", normalized):
                        continue
                    lines.append(normalized)

                if len(lines) > len(best_lines):
                    best_lines = lines

            return best_lines[:8]
        except Exception:
            return []

    def _extract_audio(self, video_path: str, out_path: str) -> None:
        """Extract audio track from `video_path` into `out_path` using ffmpeg."""
        import subprocess
        ffmpeg_executable = self._resolve_ffmpeg_executable()
        cmd = [
            ffmpeg_executable,
            "-y",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            out_path,
        ]
        subprocess.check_call(cmd)

    def _audio_has_signal(self, wav_path: str) -> bool:
        """Return True when extracted audio has enough energy to contain speech-like content."""
        try:
            with wave.open(wav_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate() or 16000
                if frames <= 0:
                    return False

                duration = frames / float(rate)
                if duration < 0.25:
                    return False

                pcm = wf.readframes(frames)
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            if audio.size == 0:
                return False

            rms = float(np.sqrt(np.mean(np.square(audio))))
            peak = float(np.max(np.abs(audio)))
            voiced_ratio = float(np.mean(np.abs(audio) > 0.015))
            return (rms > 0.004 and peak > 0.03) or voiced_ratio > 0.06
        except Exception:
            return True

    def _looks_like_no_speech(self, text: str, result: dict) -> bool:
        """Treat low-confidence short Whisper outputs as no-speech."""
        normalized = (text or "").strip().lower()
        if not normalized:
            return True

        common_hallucinations = {
            "you",
            "you.",
            "thanks",
            "thank you",
            "thank you.",
            "thanks for watching",
            "thanks for watching.",
            "bye",
            "bye.",
        }
        if normalized in common_hallucinations:
            return True

        if len(normalized.split()) <= 2 and len(normalized) <= 10:
            segments = result.get("segments") or []
            if segments:
                avg_no_speech = float(np.mean([seg.get("no_speech_prob", 0.0) for seg in segments]))
                avg_logprob = float(np.mean([seg.get("avg_logprob", -10.0) for seg in segments]))
                if avg_no_speech >= 0.55 or avg_logprob <= -0.9:
                    return True

        return False

    def run_whisper_stt(self, video_path: str) -> str:
        """Transcribe audio from the provided `video_path`.

        Returns the transcribed text or a helpful error string.
        """
        self.lazy_init()
        if not os.path.exists(video_path):
            return "Error: Requested target video file missing."

        # 1) OpenVINO path
        if self.ov_pipeline is not None:
            try:
                # The OpenVINO pipeline may accept a video path directly
                return self.ov_pipeline.transcribe(video_path)
            except Exception as e:
                print("OpenVINO transcription failed:", e)

        # 2) whisper package path
        if getattr(self, "whisper_package", None) is not None:
            try:
                # Extract audio to a temporary WAV then run whisper
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    self._extract_audio(video_path, tmp_path)
                except Exception as e:
                    return f"Error extracting audio with ffmpeg: {e}"

                try:
                    if not self._audio_has_signal(tmp_path):
                        return "(no speech detected)"

                    model = self.whisper_package.load_model("tiny")
                    result = model.transcribe(
                        tmp_path,
                        temperature=0,
                        no_speech_threshold=0.6,
                        compression_ratio_threshold=2.4,
                        condition_on_previous_text=False,
                    )
                    text = result.get("text", "").strip()
                    if self._looks_like_no_speech(text, result):
                        return "(no speech detected)"
                    return text or "(no speech detected)"
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
            except Exception as e:
                print("Whisper transcription failed:", e)

        # 3) fallback: provide guidance
        return (
            "Transcription unavailable: no supported local engine detected. "
            "Install 'openvino_genai' with a local OpenVINO whisper model or "
            "install 'whisper' (pip install -U openai-whisper) and make sure "
            "ffmpeg is on PATH, then restart the backend."
        )

    def _detect_graph_signal(self, frame: np.ndarray) -> bool:
        """Heuristic graph detector for chart-like panels in a frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 180)

        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=30,
            minLineLength=20,
            maxLineGap=14,
        )
        if lines is None:
            return False

        min_dim = min(frame.shape[0], frame.shape[1])
        min_line_len = max(40.0, 0.12 * float(min_dim))

        horizontal = 0
        vertical = 0
        diagonal = 0
        long_count = 0
        for line in lines[:, 0, :]:
            x1, y1, x2, y2 = line
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0 and dy == 0:
                continue
            length = float(np.hypot(dx, dy))
            if length < min_line_len:
                continue

            long_count += 1
            angle = abs(np.degrees(np.arctan2(dy, dx)))
            if angle <= 15 or angle >= 165:
                horizontal += 1
            elif 75 <= angle <= 105:
                vertical += 1
            else:
                diagonal += 1

        # Charts typically expose axis-like lines plus non-axis trend lines.
        return (horizontal >= 1 and vertical >= 1 and diagonal >= 1 and long_count >= 4) or (vertical >= 2 and diagonal >= 2 and long_count >= 5)

    def _detect_flag_like_region(self, frame: np.ndarray) -> bool:
        """Detect likely flag regions by rectangular multi-band color patterns."""
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Include both saturated colors and bright low-saturation areas (e.g. white stripe).
        sat_mask = cv2.inRange(hsv, (0, 60, 50), (179, 255, 255))
        white_mask = cv2.inRange(hsv, (0, 0, 170), (179, 70, 255))
        candidate_mask = cv2.bitwise_or(sat_mask, white_mask)
        kernel = np.ones((5, 5), np.uint8)
        candidate_mask = cv2.morphologyEx(candidate_mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(candidate_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        def _band_signature(roi_hsv: np.ndarray):
            if roi_hsv.size == 0:
                return None
            s = roi_hsv[:, :, 1]
            v = roi_hsv[:, :, 2]
            non_dark = v > 45
            if float(np.mean(non_dark)) < 0.6:
                return None

            colorful = (s > 70) & non_dark
            colorful_ratio = float(np.mean(colorful))
            if colorful_ratio >= 0.12:
                hues = roi_hsv[:, :, 0][colorful]
                hue_bins = np.bincount((hues // 30).astype(np.int32), minlength=6)
                return ("hue", int(np.argmax(hue_bins)))

            mean_s = float(np.mean(s[non_dark]))
            mean_v = float(np.mean(v[non_dark]))
            if mean_s < 65 and mean_v > 130:
                return ("white", 0)
            return None

        def _has_flag_bands(roi_hsv: np.ndarray) -> bool:
            rh, rw = roi_hsv.shape[:2]
            if rh < 24 or rw < 24:
                return False

            h_step = rh // 3
            w_step = rw // 3
            if h_step < 8 or w_step < 8:
                return False

            horizontal_bands = [
                roi_hsv[0:h_step, :],
                roi_hsv[h_step : 2 * h_step, :],
                roi_hsv[2 * h_step :, :],
            ]
            vertical_bands = [
                roi_hsv[:, 0:w_step],
                roi_hsv[:, w_step : 2 * w_step],
                roi_hsv[:, 2 * w_step :],
            ]

            for bands in (horizontal_bands, vertical_bands):
                signatures = [_band_signature(band) for band in bands]
                if any(signature is None for signature in signatures):
                    continue
                # Need at least two distinct bands, with at least one colorful hue band.
                if len(set(signatures)) >= 2 and any(signature[0] == "hue" for signature in signatures):
                    return True

            return False

        def _has_tricolor_composition(roi_hsv: np.ndarray) -> bool:
            hch = roi_hsv[:, :, 0]
            sch = roi_hsv[:, :, 1]
            vch = roi_hsv[:, :, 2]

            non_dark = vch > 50
            if float(np.mean(non_dark)) < 0.6:
                return False

            red = (((hch <= 12) | (hch >= 168)) & (sch > 80) & (vch > 60) & non_dark)
            blue = ((hch >= 95) & (hch <= 140) & (sch > 80) & (vch > 60) & non_dark)
            white = ((sch < 60) & (vch > 150) & non_dark)

            red_ratio = float(np.mean(red))
            blue_ratio = float(np.mean(blue))
            white_ratio = float(np.mean(white))

            return red_ratio >= 0.06 and blue_ratio >= 0.06 and white_ratio >= 0.06

        min_area = 0.01 * h * w
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue

            x, y, bw, bh = cv2.boundingRect(contour)
            if bh == 0:
                continue
            ratio = bw / float(bh)
            if ratio < 1.2 or ratio > 2.8:
                continue

            rect_area = float(bw * bh)
            if rect_area <= 0:
                continue
            fill_ratio = area / rect_area
            if fill_ratio < 0.6:
                continue

            roi_hsv = hsv[y : y + bh, x : x + bw]
            if _has_flag_bands(roi_hsv) or _has_tricolor_composition(roi_hsv):
                return True

        # Fallback: coarse window scan helps when contour regions merge with nearby graphics.
        window_heights = [max(48, h // 5), max(64, h // 4)]
        for win_h in window_heights:
            win_w = int(win_h * 1.6)
            if win_w >= w or win_h >= h:
                continue

            step_y = max(10, win_h // 2)
            step_x = max(10, win_w // 2)
            for y0 in range(0, h - win_h + 1, step_y):
                for x0 in range(0, w - win_w + 1, step_x):
                    roi_hsv = hsv[y0 : y0 + win_h, x0 : x0 + win_w]
                    if _has_flag_bands(roi_hsv) or _has_tricolor_composition(roi_hsv):
                        return True

        return False

    def _detect_ui_layout(self, frame: np.ndarray) -> bool:
        """Detect dense interface-like regions (windows, panes, terminal layout)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = cv2.magnitude(grad_x, grad_y)
        edge_density = float(np.mean(grad_mag > 45.0))
        return edge_density > 0.055

    def _detect_face_presence(self, frame: np.ndarray) -> bool:
        """Detect whether a human face is visible in the frame."""
        cascade = self._get_face_cascade()
        if cascade is None:
            return False

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(36, 36),
        )
        return len(faces) > 0

    def run_vision_analysis(self, video_path: str) -> dict:
        """Analyze sampled frames for graph-like panels and visible objects."""
        self.lazy_init()
        if not os.path.exists(video_path):
            return {"objects": [], "graphs_detected": False}

        cap = cv2.VideoCapture(video_path)
        frame_count = 0
        graph_hits = 0
        flag_hits = 0
        ui_hits = 0
        face_hits = 0
        sampled = 0
        ocr_hits = 0
        ocr_text_counter = {}

        max_frames = 900
        sample_stride = 6

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame_count > max_frames:
                break

            # Sub-sample to keep inference responsive for local CPU execution.
            if frame_count % sample_stride == 0:
                sampled += 1
                if self._detect_graph_signal(frame):
                    graph_hits += 1
                if self._detect_flag_like_region(frame):
                    flag_hits += 1
                if self._detect_ui_layout(frame):
                    ui_hits += 1
                if sampled % 2 == 0 and self._detect_face_presence(frame):
                    face_hits += 1
                if sampled % 3 == 0:
                    ocr_lines = self._extract_ocr_text(frame)
                    if ocr_lines:
                        ocr_hits += 1
                        for line in ocr_lines:
                            ocr_text_counter[line] = ocr_text_counter.get(line, 0) + 1

            frame_count += 1

        cap.release()

        graph_ratio = (graph_hits / sampled) if sampled else 0.0
        flag_ratio = (flag_hits / sampled) if sampled else 0.0
        ui_ratio = (ui_hits / sampled) if sampled else 0.0
        face_ratio = (face_hits / (sampled // 2 if sampled >= 2 else 1)) if sampled else 0.0
        ocr_ratio = (ocr_hits / (sampled // 3 if sampled >= 3 else 1)) if sampled else 0.0

        graphs_found = graph_hits >= 3 and graph_ratio >= 0.2
        flags_found = flag_hits >= 3 and flag_ratio >= 0.2
        ui_scene_found = ui_hits >= 4 and ui_ratio >= 0.35 and face_ratio < 0.3
        speaker_found = face_hits >= 2 and face_ratio >= 0.2

        # When the clip is face-dominant (speaker video), require much stronger
        # evidence before claiming graph/flag detections.
        if speaker_found and ui_ratio < 0.2:
            graphs_found = graph_hits >= 12 and graph_ratio >= 0.6 and ui_ratio >= 0.25
            flags_found = flag_hits >= 12 and flag_ratio >= 0.6 and ui_ratio >= 0.25

        objects = []
        if speaker_found:
            objects.append("Person / speaker (likely)")
        if ui_scene_found:
            objects.append("Dashboard / terminal-style interface")
        if graphs_found:
            objects.append("Line chart / moving graph panel")
        if flags_found:
            objects.append("Country flag (likely)")
        if ocr_hits >= 2 and ocr_ratio >= 0.2:
            objects.append("On-screen text detected (OCR)")

        if not objects:
            objects = ["No high-confidence visual objects detected"]

        description_parts = []
        if graphs_found:
            description_parts.append("chart-like trend visuals are visible")
        if flags_found:
            description_parts.append("a colorful flag-like region appears in multiple frames")
        if speaker_found:
            description_parts.append("a person/speaker is visible in sampled frames")
        if ui_scene_found:
            description_parts.append("the scene resembles a software/dashboard interface")
        if ocr_hits >= 2 and ocr_ratio >= 0.2:
            description_parts.append("readable on-screen text appears in multiple frames")

        if description_parts:
            description = "The video appears to show " + ", and ".join(description_parts) + "."
        else:
            description = "No strong graph or object signature was detected from sampled frames."

        top_ocr_lines = [
            item[0]
            for item in sorted(ocr_text_counter.items(), key=lambda pair: pair[1], reverse=True)[:5]
        ]

        return {
            "objects": objects,
            "graphs_detected": graphs_found,
            "flags_detected": flags_found,
            "description": description,
            "ocr_text": top_ocr_lines,
            "confidence": {
                "sampled_frames": sampled,
                "graph_hits": graph_hits,
                "graph_ratio": round(graph_ratio, 3),
                "flag_hits": flag_hits,
                "flag_ratio": round(flag_ratio, 3),
                "ui_hits": ui_hits,
                "ui_ratio": round(ui_ratio, 3),
                "face_hits": face_hits,
                "face_ratio": round(face_ratio, 3),
                "ocr_hits": ocr_hits,
                "ocr_ratio": round(ocr_ratio, 3),
                "ocr_available": self.ocr_available,
            },
        }