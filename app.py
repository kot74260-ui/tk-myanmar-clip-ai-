import asyncio
import subprocess
import uuid
import re
import zipfile
import io
import shutil
from pathlib import Path

import edge_tts
from flask import Flask, request, send_file, jsonify, render_template

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

BASE = Path(__file__).resolve().parent
UPLOAD = BASE / "uploads"
UPLOAD.mkdir(exist_ok=True)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def get_duration(path):
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
         str(path)],
        capture_output=True, text=True, check=True, timeout=60
    )
    return max(float(result.stdout.strip()), 1.0)


def make_srt(script, duration, path):
    text = re.sub(r"\s+", " ", script).strip()
    chunks = [
        text[i:i + 35]
        for i in range(0, len(text), 35)
    ]
    if not chunks:
        chunks = [""]

    total_chars = sum(max(len(c), 1) for c in chunks)
    elapsed = 0.0
    entries = []

    def stamp(seconds):
        ms = int(seconds * 1000)
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    for i, chunk in enumerate(chunks, 1):
        part = duration * max(len(chunk), 1) / total_chars
        start = elapsed
        end = min(duration, elapsed + part)
        entries.append(
            f"{i}\n{stamp(start)} --> {stamp(end)}\n{chunk}\n"
        )
        elapsed = end

    path.write_text("\n".join(entries), encoding="utf-8")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/create", methods=["POST"])
def create():
    if not FFMPEG or not FFPROBE:
        return jsonify(error="FFmpeg မတပ်ဆင်ရသေးပါ။ Dockerfile ကို ပြင်ရန်လိုပါသည်။"), 500

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
    subs = UPLOAD / f"{job}_subs.srt"
    output = UPLOAD / f"{job}_output.mp4"

    try:
        video.save(src)

        async def make_voice():
            voice = edge_tts.Communicate(
                script, voice="my-MM-NilarNeural"
            )
            await voice.save(str(audio))

        asyncio.run(make_voice())

        duration = get_duration(audio)
        make_srt(script, duration, subs)

        width, height = (
            (1080, 1920) if aspect == "9:16"
            else (1920, 1080)
        )

        vf = (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"subtitles={subs}:force_style="
            "'FontName=Padauk,FontSize=24,"
            "Outline=2,Shadow=1,Alignment=2,MarginV=45'"
        )

        command = [
            FFMPEG, "-y", "-i", str(src), "-i", str(audio),
            "-vf", vf, "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest",
            "-movflags", "+faststart", str(output)
        ]

        subprocess.run(
            command, check=True, capture_output=True, timeout=1800
        )

        memory_file = io.BytesIO()
        with zipfile.ZipFile(
            memory_file, "w", zipfile.ZIP_DEFLATED
        ) as archive:
            archive.write(output, "TK_Myanmar_Clip_AI.mp4")
            archive.write(subs, "Myanmar_Subtitles.srt")

        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name="TK_Myanmar_Clip_AI.zip"
        )

    except Exception:
        app.logger.exception("Video creation failed")
        return jsonify(
            error="မအောင်မြင်ပါ။ Render Logs ကို စစ်ဆေးပါ။"
        ), 500

    finally:
        for path in (src, audio, subs, output):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


@app.errorhandler(413)
def too_large(error):
    return jsonify(
        error="ဗီဒီယိုဖိုင် 500 MB ထက် မကျော်ရပါ။"
    ), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
