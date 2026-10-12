"""Verify a rendered reel, splice in re-rendered sections, shrink it to a size limit, make a frame sheet.

  python finish.py out/reel.mp4                          verify: frames, duration, decode, loudness + frame sheet
  python finish.py out/reel.mp4 --splice out/segment-60-75.mp4 [--splice ...]
                                                         replace those seconds with the re-rendered segments
  python finish.py out/reel.mp4 --target-mb 29           two-pass encode that fits under 29 MB (e.g. a 30 MB upload limit)

Writes <name>-final.mp4 next to the input when splicing or shrinking, and <name>-sheet.jpg.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()


def ff(*args, check=True):
    r = subprocess.run([FF, "-hide_banner", *map(str, args)], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit("ffmpeg failed:\n" + r.stderr[-2000:])
    return r


def probe(path):
    """Frame count, duration, fps, size, audio presence and decode errors of a video."""
    path = Path(path)
    frames, secs = imageio_ffmpeg.count_frames_and_secs(str(path))
    head = ff("-i", path, check=False).stderr
    fps = float(re.search(r"(\d+(?:\.\d+)?) fps", head).group(1)) if re.search(r"(\d+(?:\.\d+)?) fps", head) else 30.0
    size = re.search(r"Video: .*?(\d{3,5})x(\d{3,5})", head)
    errors = ff("-v", "error", "-i", path, "-f", "null", "-", check=False).stderr.strip()
    return {"frames": frames, "duration": secs, "fps": fps, "size": f"{size.group(1)}x{size.group(2)}" if size else "?",
            "audio": "Audio:" in head, "decode_errors": errors[:500], "mb": path.stat().st_size / 2 ** 20}


def loudness(path):
    out = ff("-i", path, "-af", "volumedetect", "-vn", "-f", "null", "-", check=False).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", out)
    p = re.search(r"max_volume: (-?[\d.]+) dB", out)
    return (float(m.group(1)) if m else None, float(p.group(1)) if p else None)


def sheet(path, info, out):
    n = 12
    ff("-v", "error", "-y", "-i", path, "-vf", f"fps={n}/{max(info['duration'], 0.1):.3f},scale=270:-2,tile=6x2", "-frames:v", "1", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--splice", action="append", default=[], help="segment-<t0>-<t1>.mp4 from render.cjs --range")
    ap.add_argument("--target-mb", type=float, help="shrink to fit under this many MiB")
    ap.add_argument("--audio-kbps", type=int, default=160)
    a = ap.parse_args()
    src = Path(a.video)
    info = probe(src)
    print(json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in info.items()}, indent=1))
    if info["decode_errors"]:
        print("WARNING: decode errors (see above)")
    if info["audio"]:
        mean, peak = loudness(src)
        print(f"loudness: mean {mean} dB, peak {peak} dB" + ("   <- quiet" if mean is not None and mean < -24 else ""))
    fps = info["fps"]
    final = src.with_name(src.stem + "-final.mp4")
    if a.splice or a.target_mb:
        inputs, graph, parts, cursor = ["-i", str(src)], [], [], 0
        segs = []
        for k, s in enumerate(a.splice, start=1):
            m = re.search(r"segment-([\d.]+)-([\d.]+)\.mp4$", s)
            if not m:
                sys.exit(f"--splice expects render.cjs's segment-<t0>-<t1>.mp4 naming: {s}")
            segs.append((round(float(m.group(1)) * fps), round(float(m.group(2)) * fps), k, s))
        segs.sort()
        n_main = len(segs) + 1
        graph.append(f"[0:v]split={n_main}" + "".join(f"[m{i}]" for i in range(n_main)))
        for i, (f0, f1, k, s) in enumerate(segs):
            inputs += ["-i", s]
            graph.append(f"[m{i}]trim=start_frame={cursor}:end_frame={f0},setpts=PTS-STARTPTS[a{i}]")
            graph.append(f"[{k}:v]setpts=PTS-STARTPTS[s{i}]")
            parts += [f"[a{i}]", f"[s{i}]"]
            cursor = f1
        graph.append(f"[m{len(segs)}]trim=start_frame={cursor},setpts=PTS-STARTPTS[z]")
        parts.append("[z]")
        graph.append("".join(parts) + f"concat=n={len(parts)}:v=1:a=0[v]")
        fg = ";".join(graph)
        audio = ["-map", "0:a", "-c:a", "aac", "-b:a", f"{a.audio_kbps}k"] if info["audio"] else ["-an"]
        # -r on every pass: concat output is otherwise tagged 25 fps (and two-pass would fail on the mismatch)
        if a.target_mb:
            kbps = int((a.target_mb * 8 * 1024 * 1024 / info["duration"] / 1000 - (a.audio_kbps if info["audio"] else 0)) * 0.96)
            print(f"two-pass at {kbps} kb/s video to fit {a.target_mb} MB")
            log = str(src.with_name("ffpass"))
            ff("-y", *inputs, "-filter_complex", fg, "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-tune", "film",
               "-b:v", f"{kbps}k", "-r", fps, "-pass", "1", "-passlogfile", log, "-an", "-f", "mp4", "-y",
               "NUL" if sys.platform == "win32" else "/dev/null")
            ff("-y", *inputs, "-filter_complex", fg, "-map", "[v]", *audio, "-c:v", "libx264", "-preset", "slow", "-tune", "film",
               "-b:v", f"{kbps}k", "-maxrate", f"{kbps * 2}k", "-bufsize", f"{kbps * 4}k", "-r", fps, "-pass", "2", "-passlogfile", log,
               "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart", final)
            for f in src.parent.glob("ffpass*"):
                f.unlink()
        else:
            ff("-y", *inputs, "-filter_complex", fg, "-map", "[v]", *audio, "-c:v", "libx264", "-preset", "slow", "-crf", "17",
               "-r", fps, "-pix_fmt", "yuv420p", "-movflags", "+faststart", final)
        out = probe(final)
        print(f"wrote {final}: {out['frames']} frames (source {info['frames']}), {out['duration']:.2f} s, {out['mb']:.2f} MB")
        if out["frames"] != info["frames"]:
            print("WARNING: frame count changed; check the splice ranges")
        target = final
    else:
        target = src
    sh = target.with_name(target.stem + "-sheet.jpg")
    sheet(target, probe(target), sh)
    print("frame sheet:", sh)


if __name__ == "__main__":
    main()
