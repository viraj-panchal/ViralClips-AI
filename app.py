import os
import re
import subprocess
import textwrap
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = APP_DIR / "downloads"
OUTPUT_DIR = APP_DIR / "output"
TEMP_DIR = APP_DIR / "temp"
for folder in (DOWNLOAD_DIR, OUTPUT_DIR, TEMP_DIR):
    folder.mkdir(exist_ok=True)

st.set_page_config(page_title="ViralClips AI", page_icon="🎬", layout="wide")
st.title("🎬 ViralClips AI")
st.caption("Local YouTube-to-Shorts generator • Whisper transcription • FFmpeg rendering")

KEYWORDS = {
    "hyped": 3.0, "crazy": 2.5, "wow": 2.2, "omg": 2.5, "no way": 3.0,
    "let's go": 2.5, "lets go": 2.5, "insane": 2.8, "unbelievable": 2.8,
    "what": 0.6, "why": 0.5, "bro": 0.7, "wait": 1.0, "never": 1.0,
    "finally": 1.2, "secret": 1.2, "amazing": 1.5, "worst": 1.2,
    "best": 1.0, "fail": 1.5, "win": 1.0, "won": 1.0, "lost": 1.0,
    "help": 0.6, "seriously": 0.8, "really": 0.5, "oh my god": 2.5,
    "अरे": 1.0, "वाह": 2.0, "क्या": 0.5, "नहीं": 0.5, "भाई": 0.8,
    "जबरदस्त": 2.0, "कमाल": 2.0, "शानदार": 1.8
}

def run_command(args):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown command error")[-5000:]
        raise RuntimeError(detail)
    return result.stdout

def find_executable(name):
    from shutil import which
    path = which(name)
    if not path:
        raise RuntimeError(f"{name} was not found on PATH. Install it and reopen PowerShell.")
    return path

def download_video(url, use_chrome_cookies):
    output_template = str(DOWNLOAD_DIR / "source.%(ext)s")
    args = [
        "python", "-m", "yt_dlp",
        "--no-playlist",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--print", "after_move:filepath",
    ]
    if use_chrome_cookies:
        args += ["--cookies-from-browser", "chrome"]
    args += [url]
    output = run_command(args)
    possible = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(possible):
        candidate = Path(line)
        if candidate.exists() and candidate.is_file():
            return candidate
    files = sorted(DOWNLOAD_DIR.glob("source.*"), key=lambda x: x.stat().st_mtime, reverse=True)
    if files:
        return files[0]
    raise RuntimeError("yt-dlp finished but the downloaded video file could not be located.\n" + output)

def get_duration(video):
    out = run_command([
        find_executable("ffprobe"), "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video)
    ])
    return float(out.strip())

def score_window(window_segments, start, end):
    text = " ".join(s["text"] for s in window_segments).lower()
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    if not words:
        return 0.0
    keyword_score = sum(weight for phrase, weight in KEYWORDS.items() if phrase in text)
    exclamations = text.count("!") * 0.8
    questions = text.count("?") * 0.35
    speech_density = min(len(words) / max(end - start, 1), 4.0)
    # A transparent heuristic score, not a prediction of actual virality.
    return keyword_score + exclamations + questions + speech_density * 1.5 + min(len(words) / 35, 2.0)

def choose_clips(segments, duration, clip_len, count):
    candidates = []
    step = max(8, clip_len // 4)
    last_start = max(0, int(duration - clip_len))
    for start in range(0, last_start + 1, step):
        end = min(duration, start + clip_len)
        relevant = [s for s in segments if s["end"] > start and s["start"] < end]
        score = score_window(relevant, start, end)
        if relevant:
            candidates.append({"start": float(start), "end": float(end), "score": score})
    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected = []
    for candidate in candidates:
        if all(candidate["end"] <= item["start"] or candidate["start"] >= item["end"] for item in selected):
            selected.append(candidate)
            if len(selected) >= count:
                break
    return sorted(selected, key=lambda x: x["score"], reverse=True)

def srt_time(seconds):
    ms = int(round(seconds * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"

def write_srt(segments, start, end, path):
    lines = []
    idx = 1
    for seg in segments:
        a = max(float(seg["start"]), start)
        b = min(float(seg["end"]), end)
        text = seg["text"].strip()
        if b <= a or not text:
            continue
        lines.extend([str(idx), f"{srt_time(a-start)} --> {srt_time(b-start)}", text, ""])
        idx += 1
    Path(path).write_text("\n".join(lines), encoding="utf-8-sig")

def ffmpeg_filter_path(path):
    # Escape a Windows path for FFmpeg filter arguments.
    value = str(path.resolve()).replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return value

def render_clip(video, clip, segments, index, resolution, burn_subtitles):
    width, height = (1080, 1920) if resolution == "1080 × 1920 (Full HD)" else (720, 1280)
    out = OUTPUT_DIR / f"viral_clip_{index:02}.mp4"
    srt = OUTPUT_DIR / f"viral_clip_{index:02}.srt"
    write_srt(segments, clip["start"], clip["end"], srt)
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if burn_subtitles and srt.stat().st_size:
        vf += f",subtitles='{ffmpeg_filter_path(srt)}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=90'"
    args = [
        find_executable("ffmpeg"), "-y", "-ss", str(clip["start"]), "-i", str(video),
        "-t", str(clip["end"] - clip["start"]), "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)
    ]
    run_command(args)
    return out, srt

with st.sidebar:
    st.header("Settings")
    model_name = st.selectbox("Whisper model (CPU)", ["tiny", "base", "small"], index=0,
                              help="tiny is recommended for 8 GB RAM. Larger models are slower.")
    clip_len = st.slider("Clip duration (seconds)", 30, 60, 40, 5)
    clip_count = st.slider("Number of clips", 1, 5, 3)
    resolution = st.selectbox("Vertical output", ["720 × 1280 (recommended)", "1080 × 1920 (Full HD)"])
    burn_subtitles = st.checkbox("Burn subtitles into video", value=True)
    use_cookies = st.checkbox("Use Chrome cookies (if YouTube asks you to sign in)", value=False)

url = st.text_input("YouTube video URL", placeholder="https://www.youtube.com/watch?v=...")
st.info("This first version processes completed videos/VODs, not a live stream while it is broadcasting. Use videos you own or have permission to edit.")

if st.button("🚀 Generate Shorts", type="primary", disabled=not url.strip()):
    try:
        find_executable("ffmpeg")
        find_executable("ffprobe")
        status = st.status("Starting video processing…", expanded=True)
        status.write("Downloading source video with yt-dlp…")
        video = download_video(url.strip(), use_cookies)
        duration = get_duration(video)
        status.write(f"Downloaded: {video.name} ({duration/60:.1f} minutes)")
        status.write(f"Loading Whisper '{model_name}' on CPU…")
        from faster_whisper import WhisperModel
        model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=max(1, (os.cpu_count() or 4) - 1))
        status.write("Transcribing audio. This may take several minutes…")
        segments_iter, info = model.transcribe(str(video), beam_size=1, vad_filter=True)
        segments = []
        for seg in segments_iter:
            segments.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()})
        if not segments:
            raise RuntimeError("No speech was detected. Try another video with clear speech.")
        status.write(f"Transcription complete. Detected language: {info.language} (confidence {info.language_probability:.2f})")
        status.write("Scoring candidate moments and selecting non-overlapping clips…")
        clips = choose_clips(segments, duration, clip_len, clip_count)
        if not clips:
            raise RuntimeError("Could not find suitable speech segments in this video.")
        rendered = []
        for i, clip in enumerate(clips, start=1):
            status.write(f"Rendering clip {i}/{len(clips)}…")
            out, srt = render_clip(video, clip, segments, i, resolution, burn_subtitles)
            rendered.append((clip, out, srt))
        status.update(label="Your Shorts are ready!", state="complete", expanded=True)
        st.success(f"Created {len(rendered)} clip(s) in: {OUTPUT_DIR}")
        for clip, out, srt in rendered:
            st.markdown(f"**Clip score:** {clip['score']:.2f} · **Source time:** {srt_time(clip['start'])} – {srt_time(clip['end'])}")
            st.video(str(out))
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(f"Download MP4 — {out.name}", data=out.read_bytes(), file_name=out.name, mime="video/mp4", key=f"mp4_{out.name}")
            with c2:
                st.download_button(f"Download subtitles — {srt.name}", data=srt.read_bytes(), file_name=srt.name, mime="application/x-subrip", key=f"srt_{srt.name}")
    except Exception as exc:
        st.error("Processing failed.")
        st.code(str(exc))
        st.caption("If the error mentions YouTube bot verification, enable 'Use Chrome cookies' and try again. If it mentions FFmpeg, check that ffmpeg and ffprobe are available in PATH.")

st.divider()
st.caption("ViralClips AI local prototype • Highlight ranking is a heuristic based on transcript signals and speech density. It does not guarantee viral performance. Transcription is in the detected spoken language; translation is not included in this version.")
