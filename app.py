
import os
import re
import sys
import uuid
import shutil
import platform
import subprocess
import importlib.util
from pathlib import Path

import streamlit as st

# ============================================================
# 1. APPLICATION CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="ViralClips AI",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

APP_DIR = Path(__file__).resolve().parent
WORK_DIR = Path(os.getenv("VIRALCLIPS_WORKDIR", "/tmp/viralclips_ai"))

DOWNLOAD_DIR = WORK_DIR / "downloads"
OUTPUT_DIR = WORK_DIR / "output"
TEMP_DIR = WORK_DIR / "temp"

for folder in (DOWNLOAD_DIR, OUTPUT_DIR, TEMP_DIR):
    folder.mkdir(parents=True, exist_ok=True)

FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

# ============================================================
# 2. APPLICATION HEADER
# ============================================================

st.title("🎬 ViralClips AI")
st.caption(
    "AI-powered YouTube-to-Shorts generator | "
    "Automatic highlights | Whisper subtitles | FFmpeg rendering"
)

# ============================================================
# 3. DEPENDENCY CHECKS
# ============================================================

YTDLP_AVAILABLE = (
    importlib.util.find_spec("yt_dlp") is not None
)

WHISPER_AVAILABLE = (
    importlib.util.find_spec("faster_whisper") is not None
)

with st.expander("System status", expanded=False):
    st.write("Operating system:", platform.system())
    st.write("FFmpeg:", FFMPEG_PATH or "Not installed")
    st.write("FFprobe:", FFPROBE_PATH or "Not installed")
    st.write("yt-dlp:", "Installed" if YTDLP_AVAILABLE else "Missing")
    st.write(
        "Faster Whisper:",
        "Installed" if WHISPER_AVAILABLE else "Missing"
    )

missing_dependencies = []

if not FFMPEG_PATH:
    missing_dependencies.append("FFmpeg")

if not FFPROBE_PATH:
    missing_dependencies.append("FFprobe")

if not YTDLP_AVAILABLE:
    missing_dependencies.append("yt-dlp")

if not WHISPER_AVAILABLE:
    missing_dependencies.append("faster-whisper")

if missing_dependencies:
    st.warning(
        "Some dependencies are missing: "
        + ", ".join(missing_dependencies)
        + ". Check packages.txt and requirements.txt."
    )

# ============================================================
# 4. HIGHLIGHT DETECTION KEYWORDS
# ============================================================

KEYWORDS = {
    "hyped": 3.0,
    "crazy": 2.5,
    "wow": 2.2,
    "omg": 2.5,
    "no way": 3.0,
    "let's go": 2.5,
    "lets go": 2.5,
    "insane": 2.8,
    "unbelievable": 2.8,
    "what": 0.6,
    "why": 0.5,
    "bro": 0.7,
    "wait": 1.0,
    "never": 1.0,
    "finally": 1.2,
    "secret": 1.2,
    "amazing": 1.5,
    "worst": 1.2,
    "best": 1.0,
    "fail": 1.5,
    "win": 1.0,
    "won": 1.0,
    "lost": 1.0,
    "help": 0.6,
    "seriously": 0.8,
    "really": 0.5,
    "oh my god": 2.5,
    "अरे": 1.0,
    "वाह": 2.0,
    "क्या": 0.5,
    "नहीं": 0.5,
    "भाई": 0.8,
    "जबरदस्त": 2.0,
    "कमाल": 2.0,
    "शानदार": 1.8
}

# ============================================================
# 5. EXECUTABLE AND COMMAND HELPERS
# ============================================================

def find_executable(name):
    path = shutil.which(name)

    if not path:
        raise RuntimeError(
            f"{name} was not found on PATH. "
            f"Current platform: {platform.system()}. "
            "Check the cloud dependencies and deployment logs."
        )

    return path


def run_command(args, timeout=None):
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout
    )

    if result.returncode != 0:
        detail = (
            result.stderr
            or result.stdout
            or "Unknown command error"
        )

        raise RuntimeError(detail[-5000:])

    return result.stdout


# ============================================================
# 6. YOUTUBE VIDEO DOWNLOADER
# ============================================================

def download_video(url):

    if not YTDLP_AVAILABLE:
        raise RuntimeError(
            "yt-dlp is missing. Add yt-dlp to requirements.txt "
            "and redeploy the application."
        )

    find_executable("ffmpeg")
    find_executable("ffprobe")

    download_id = uuid.uuid4().hex[:10]

    output_template = str(
        DOWNLOAD_DIR / f"source_{download_id}.%(ext)s"
    )

    args = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--no-warnings",
        "-f",
        "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format",
        "mp4",
        "--output",
        output_template,
        "--print",
        "after_move:filepath",
        url
    ]

    output = run_command(args)

    possible_files = [
        line.strip()
        for line in output.splitlines()
        if line.strip()
    ]

    for line in reversed(possible_files):
        candidate = Path(line)

        if candidate.exists() and candidate.is_file():
            return candidate

    matching_files = sorted(
        DOWNLOAD_DIR.glob(f"source_{download_id}.*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True
    )

    if matching_files:
        return matching_files[0]

    raise RuntimeError(
        "Download finished but the video file was not found.\n"
        + output
    )


# ============================================================
# 7. VIDEO DURATION
# ============================================================

def get_duration(video):

    output = run_command([
        find_executable("ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video)
    ])

    duration = float(output.strip())

    if duration <= 0:
        raise RuntimeError("Invalid video duration.")

    return duration


# ============================================================
# 8. AUTOMATIC VIRAL MOMENT SCORING
# ============================================================

def score_window(segments, start, end):

    text = " ".join(
        segment["text"] for segment in segments
    ).lower()

    words = re.findall(r"\w+", text, flags=re.UNICODE)

    if not words:
        return 0.0

    keyword_score = sum(
        weight
        for phrase, weight in KEYWORDS.items()
        if phrase in text
    )

    exclamations = text.count("!") * 0.8
    questions = text.count("?") * 0.35

    speech_density = min(
        len(words) / max(end - start, 1),
        4.0
    )

    return (
        keyword_score
        + exclamations
        + questions
        + speech_density * 1.5
        + min(len(words) / 35, 2.0)
    )


def choose_clips(segments, duration, clip_length, count):

    candidates = []

    if duration <= clip_length:
        windows = [(0.0, duration)]
    else:
        last_start = duration - clip_length
        step = max(8, clip_length // 4)

        starts = list(range(0, int(last_start) + 1, step))

        if not starts or starts[-1] != int(last_start):
            starts.append(int(last_start))

        windows = [
            (float(start), min(duration, float(start + clip_length)))
            for start in starts
        ]

    for start, end in windows:

        relevant = [
            segment
            for segment in segments
            if segment["end"] > start
            and segment["start"] < end
        ]

        if not relevant:
            continue

        score = score_window(relevant, start, end)

        candidates.append({
            "start": start,
            "end": end,
            "score": score
        })

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    selected = []

    for candidate in candidates:

        overlaps = any(
            candidate["end"] > item["start"]
            and candidate["start"] < item["end"]
            for item in selected
        )

        if not overlaps:
            selected.append(candidate)

        if len(selected) >= count:
            break

    return sorted(
        selected,
        key=lambda item: item["score"],
        reverse=True
    )


# ============================================================
# 9. SUBTITLE GENERATION
# ============================================================

def srt_time(seconds):

    milliseconds = int(round(seconds * 1000))

    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)

    return (
        f"{hours:02}:"
        f"{minutes:02}:"
        f"{seconds:02},"
        f"{milliseconds:03}"
    )


def write_srt(segments, start, end, output_path):

    lines = []
    index = 1

    for segment in segments:

        clip_start = max(
            float(segment["start"]),
            start
        )

        clip_end = min(
            float(segment["end"]),
            end
        )

        subtitle = segment["text"].strip()

        if clip_end <= clip_start or not subtitle:
            continue

        lines.extend([
            str(index),
            (
                f"{srt_time(clip_start - start)} --> "
                f"{srt_time(clip_end - start)}"
            ),
            subtitle,
            ""
        ])

        index += 1

    Path(output_path).write_text(
        "\n".join(lines),
        encoding="utf-8-sig"
    )


def escape_filter_path(path):

    value = str(Path(path).resolve())

    value = value.replace("\\", "/")
    value = value.replace(":", r"\:")
    value = value.replace("'", r"\'")

    return value


# ============================================================
# 10. VERTICAL VIDEO RENDERING
# ============================================================

def render_clip(
    video,
    clip,
    segments,
    index,
    resolution,
    burn_subtitles
):

    if resolution == "1080 × 1920 (Full HD)":
        width, height = 1080, 1920
    else:
        width, height = 720, 1280

    output_path = (
        OUTPUT_DIR / f"viral_clip_{index:02}.mp4"
    )

    subtitle_path = (
        OUTPUT_DIR / f"viral_clip_{index:02}.srt"
    )

    video_filter = (
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )

    subtitle_created = False

    if burn_subtitles:

        write_srt(
            segments,
            clip["start"],
            clip["end"],
            subtitle_path
        )

        if subtitle_path.exists() and subtitle_path.stat().st_size:

            escaped_path = escape_filter_path(subtitle_path)

            video_filter += (
                f",subtitles='{escaped_path}':"
                "force_style='FontName=Arial,"
                "FontSize=18,"
                "PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,"
                "BorderStyle=1,"
                "Outline=2,"
                "Shadow=1,"
                "Alignment=2,"
                "MarginV=90'"
            )

            subtitle_created = True

    args = [
        find_executable("ffmpeg"),
        "-y",
        "-ss",
        str(clip["start"]),
        "-i",
        str(video),
        "-t",
        str(clip["end"] - clip["start"]),
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path)
    ]

    run_command(args)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg did not create a valid MP4 file.")

    return (
        output_path,
        subtitle_path if subtitle_created else None
    )


# ============================================================
# 11. SIDEBAR SETTINGS
# ============================================================

with st.sidebar:

    st.header("⚙️ Video Settings")

    model_name = st.selectbox(
        "Whisper AI model",
        ["tiny", "base", "small"],
        index=0,
        help="Tiny is recommended for limited cloud resources."
    )

    clip_length = st.slider(
        "Clip duration (seconds)",
        min_value=30,
        max_value=60,
        value=40,
        step=5
    )

    clip_count = st.slider(
        "Number of Shorts",
        min_value=1,
        max_value=5,
        value=3
    )

    resolution = st.selectbox(
        "Video resolution",
        [
            "720 × 1280 (recommended)",
            "1080 × 1920 (Full HD)"
        ]
    )

    burn_subtitles = st.toggle(
        "Subtitles ON/OFF",
        value=True,
        help="ON: burn subtitles into video. OFF: clean video without subtitles."
    )

    st.divider()

    st.caption("ViralClips AI")
    st.caption("Automatic highlight detection")
    st.caption("Hindi and English speech transcription")


# ============================================================
# 12. MAIN INTERFACE
# ============================================================

st.subheader("🚀 Generate YouTube Shorts")

url = st.text_input(
    "YouTube video URL",
    placeholder="https://www.youtube.com/watch?v=..."
)

st.info(
    "Use completed videos that you own or have permission to edit. "
    "Live streams are not supported in this version. "
    "Public videos are recommended for the first test."
)

st.caption(
    "Note: The cloud server cannot access Chrome cookies "
    "from your personal Windows computer."
)

# ============================================================
# 13. PROCESSING
# ============================================================

if st.button(
    "🚀 Generate Shorts",
    type="primary",
    disabled=(
        not url.strip()
        or bool(missing_dependencies)
    ),
    use_container_width=True
):

    video_url = url.strip()

    if not re.match(
        r"^https?://",
        video_url,
        flags=re.IGNORECASE
    ):

        st.error("Please enter a valid HTTP or HTTPS video URL.")

    else:

        try:

            find_executable("ffmpeg")
            find_executable("ffprobe")

            if not YTDLP_AVAILABLE:
                raise RuntimeError("yt-dlp is not installed.")

            if not WHISPER_AVAILABLE:
                raise RuntimeError("faster-whisper is not installed.")

            with st.status(
                "Starting ViralClips AI...",
                expanded=True
            ) as status:

                # Download source video
                status.write("📥 Downloading YouTube video...")

                video = download_video(video_url)

                duration = get_duration(video)

                status.write(
                    f"Video downloaded successfully: "
                    f"{duration / 60:.1f} minutes"
                )

                # Load Whisper
                status.write(
                    f"🤖 Loading Whisper AI model: {model_name}"
                )

                from faster_whisper import WhisperModel

                model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=max(
                        1,
                        min(4, os.cpu_count() or 2)
                    )
                )

                # Transcription
                status.write("🎙️ Transcribing video audio...")

                segments_iterator, info = model.transcribe(
                    str(video),
                    beam_size=1,
                    vad_filter=True
                )

                segments = []

                for segment in segments_iterator:

                    segments.append({
                        "start": float(segment.start),
                        "end": float(segment.end),
                        "text": segment.text.strip()
                    })

                if not segments:
                    raise RuntimeError(
                        "No speech detected. Try a video with clear speech."
                    )

                status.write(
                    f"Transcription complete. "
                    f"Detected language: {info.language}"
                )

                # Select highlights
                status.write("🔥 Detecting exciting moments...")

                clips = choose_clips(
                    segments,
                    duration,
                    clip_length,
                    clip_count
                )

                if not clips:
                    raise RuntimeError(
                        "No suitable highlight moments were detected."
                    )

                # Render clips
                rendered = []

                for index, clip in enumerate(clips, start=1):

                    status.write(
                        f"🎬 Rendering Short {index}/{len(clips)}..."
                    )

                    output_path, subtitle_path = render_clip(
                        video,
                        clip,
                        segments,
                        index,
                        resolution,
                        burn_subtitles
                    )

                    rendered.append((
                        clip,
                        output_path,
                        subtitle_path
                    ))

                status.update(
                    label="All Shorts generated successfully!",
                    state="complete",
                    expanded=True
                )

            # Results
            st.success(
                f"🎉 Successfully generated {len(rendered)} Shorts!"
            )

            for clip, output_path, subtitle_path in rendered:

                st.divider()

                st.subheader(
                    f"Short: {output_path.name}"
                )

                st.write(
                    f"Source start: {srt_time(clip['start'])}"
                )

                st.write(
                    f"Source end: {srt_time(clip['end'])}"
                )

                st.write(
                    f"Highlight score: {clip['score']:.2f}"
                )

                st.video(str(output_path))

                st.download_button(
                    "⬇️ Download MP4",
                    data=output_path.read_bytes(),
                    file_name=output_path.name,
                    mime="video/mp4",
                    key=f"download_{output_path.name}",
                    use_container_width=True
                )

                if subtitle_path is not None:

                    st.download_button(
                        "⬇️ Download SRT subtitles",
                        data=subtitle_path.read_bytes(),
                        file_name=subtitle_path.name,
                        mime="application/x-subrip",
                        key=f"subtitle_{subtitle_path.name}"
                    )

        except subprocess.TimeoutExpired:

            st.error(
                "Video processing timed out. "
                "Try a shorter source video."
            )

        except Exception as error:

            st.error("Video processing failed.")

            st.code(str(error))

            st.caption(
                "Check the deployment logs for additional details. "
                "YouTube bot verification, unavailable videos, "
                "cloud memory limits, and unsupported video formats "
                "can also cause processing failures."
            )


# ============================================================
# 14. FOOTER
# ============================================================

st.divider()

st.caption(
    "ViralClips AI | YouTube-to-Shorts Generator"
)

st.caption(
    "Highlight selection uses transcript-based heuristic scoring. "
    "It does not guarantee viral performance. "
    "Whisper transcribes speech in its detected language; "
    "translation and face-tracking reframing are not included."
)
