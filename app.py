
import os
import subprocess
import uuid
import zipfile
import io
import shutil
from pathlib import Path

from groq import Groq
from flask import Flask, request, send_file, jsonify, render_template

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

BASE = Path(__file__).resolve().parent
UPLOAD = BASE / "uploads"
UPLOAD.mkdir(exist_ok=True)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def run_command(command, timeout=1800):
    subprocess.run(
        command, check=True, capture_output=True,
        text=True, timeout=timeout
    )


def stamp(seconds):
    ms = max(0, int(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def transcribe_audio(audio_path, job):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Render မှာ GROQ_API_KEY မတွေ့ပါ။")

    client = Groq(api_key=api_key, timeout=300.0, max_retries=2)

    # အသံကို အရွယ်သေးအောင် ပြောင်းပြီး ၁၀ မိနစ်စီခွဲမည်
    small_audio = UPLOAD / f"{job}_audio.mp3"
    run_command([
        FFMPEG, "-y", "-i", str(audio_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-b:a", "48k", str(small_audio)
    ])

    chunks_dir = UPLOAD / f"{job}_chunks"
    chunks_dir.mkdir()
    run_command([
        FFMPEG, "-y", "-i", str(small_audio),
        "-f", "segment", "-segment_time", "600",
        "-reset_timestamps", "1",
        "-c", "copy", str(chunks_dir / "part_%03d.mp3")
    ])

    segments = []
    try:
        chunks = sorted(chunks_dir.glob("part_*.mp3"))
        if not chunks:
            raise RuntimeError("အသံဖိုင် မရရှိပါ။")

        for index, chunk in enumerate(chunks):
            with open(chunk, "rb") as audio_file:
                result = client.audio.transcriptions.create(
                    file=(chunk.name, audio_file.read()),
                    model="whisper-large-v3-turbo",
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                    language="my",
                    temperature=0
                )

            offset = index * 600
            
            for item in (getattr(result, "segments", None) or []):
                if isinstance(item, dict):
                    text = item.get("text", "").strip()
                    start = item.get("start", 0)
                    end = item.get("end", 0)
                else:
                    text = item.text.strip()
                    start = item.start
                    end = item.end

                if text:
                    segments.append({
                        "start": float(start) + offset,
                        "end": float(end) + offset,
                        "text": text
                    })
        if not segments:
            raise RuntimeError(
                "အသံမှ စာသားမရပါ။ အသံပါသော ဗီဒီယိုဖြင့် ထပ်စမ်းပါ။"
            )

        return segments

    finally:
        small_audio.unlink(missing_ok=True)
        shutil.rmtree(chunks_dir, ignore_errors=True)


def write_srt(segments, path):
    lines = []
    for i, item in enumerate(segments, 1):
        lines.extend([
            str(i),
            f"{stamp(item['start'])} --> {stamp(item['end'])}",
            item["text"],
            ""
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/create", methods=["POST"])
def create():
    if not FFMPEG or not FFPROBE:
        return jsonify(error="FFmpeg မတပ်ဆင်ရသေးပါ။"), 500

    video = request.files.get("video")
    aspect = request.form.get("aspect", "9:16")

    if not video or not video.filename:
        return jsonify(error="ဗီဒီယိုဖိုင် ရွေးပေးပါ။"), 400

    if aspect not in ("9:16", "16:9"):
        return jsonify(error="Video format မမှန်ပါ။"), 400

    job = uuid.uuid4().hex
    src = UPLOAD / f"{job}_input.mp4"
    subs = UPLOAD / f"{job}_subs.srt"
    output = UPLOAD / f"{job}_output.mp4"

    try:
        video.save(src)

        # ဗီဒီယိုထဲက စကားကို အလိုအလျောက် စာသားပြောင်းမည်
        segments = transcribe_audio(src, job)
        write_srt(segments, subs)

        width, height = (
            (1080, 1920) if aspect == "9:16"
            else (1920, 1080)
        )

        subtitle_filter = (
            f"subtitles={subs}:"
            "force_style='FontName=Padauk,FontSize=24,"
            "Outline=2,Shadow=1,Alignment=2,MarginV=45'"
        )

        vf = (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            + subtitle_filter
        )

        run_command([
            FFMPEG, "-y", "-i", str(src),
            "-vf", vf,
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest",
            "-movflags", "+faststart", str(output)
        ])

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
            error="မအောင်မြင်ပါ။ Render Logs ကို စစ်ဆေးပါ။ "
                  "ဗီဒီယိုတိုတစ်ခုဖြင့် ထပ်စမ်းပါ။"
        ), 500

    finally:
        for path in (src, subs, output):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


@app.errorhandler(413)
def too_large(error):
    return jsonify(error="ဗီဒီယိုဖိုင် 500 MB ထက် မကျော်ရပါ။"), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
