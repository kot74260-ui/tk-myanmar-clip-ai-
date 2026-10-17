
import asyncio
import subprocess
import uuid
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from flask import Flask, request, send_file, jsonify, render_template

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

BASE = Path(__file__).resolve().parent
UPLOAD = BASE / "uploads"
UPLOAD.mkdir(exist_ok=True)

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/create", methods=["POST"])
def create():
    video = request.files.get("video")
    script = request.form.get("script", "").strip()
    aspect = request.form.get("aspect", "9:16")

    if not video or not video.filename:
        return jsonify(error="ဗီဒီယိုဖိုင် ရွေးပေးပါ။"), 400

    if not script:
        return jsonify(error="မြန်မာစာသား ထည့်ပေးပါ။"), 400

    if aspect not in ("9:16", "16:9"):
        return jsonify(error="Video format မမှန်ပါ။"), 400

    job = uuid.uuid4().hex
    src = UPLOAD / f"{job}_input.mp4"
    audio = UPLOAD / f"{job}_voice.mp3"
    output = UPLOAD / f"{job}_output.mp4"

    try:
        video.save(src)

        async def make_voice():
            voice = edge_tts.Communicate(
                script,
                voice="my-MM-NilarNeural"
            )
            await voice.save(str(audio))

        asyncio.run(make_voice())

        width, height = (1080, 1920) if aspect == "9:16" else (1920, 1080)

        command = [
            FFMPEG, "-y",
            "-i", str(src),
            "-i", str(audio),
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(output)
        ]

        subprocess.run(command, check=True, capture_output=True, timeout=600)

        return send_file(
            output,
            as_attachment=True,
            download_name="TK_Myanmar_Clip_AI.mp4"
        )

    except Exception:
        app.logger.exception("Video creation failed")
        return jsonify(
            error="မအောင်မြင်ပါ။ Hosting Logs ကို စစ်ဆေးပါ။"
        ), 500

    finally:
        for path in (src, audio, output):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


@app.errorhandler(413)
def too_large(error):
    return jsonify(error="ဗီဒီယိုဖိုင် 100 MB ထက် မကျော်ရပါ။"), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
