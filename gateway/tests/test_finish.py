"""Finishing: size recommendation, target sizes, the ffmpeg upscale job, and the video input type. Run: python -m pytest -q tests/test_finish.py"""
import os, sys, time
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video
import test_video as tv


def raises(fn, *a, **k):
    try: fn(*a, **k)
    except video.VideoError as e: return str(e)
    raise AssertionError("no VideoError")


def test_target_sizes_snap_to_standard_ratios():
    assert [video.target_size(704, 384, t) for t in ("1080p", "2k", "4k")] == [(1920, 1080), (2560, 1440), (3840, 2160)]
    assert video.target_size(384, 704, "1080p") == (1080, 1920) and video.target_size(512, 512, "4k") == (2160, 2160)
    assert video.target_size(1000, 400, "1080p") == (2700, 1080)                       # 2.5:1 is not near a standard ratio: kept
    assert "target must be" in raises(video.target_size, 704, 384, "8k")


def test_recommend_never_exceeds_budget_target_or_loses_length():
    for sec in (1, 3, 10, 15, 30):
        for t in ("1080p", "2k", "4k"):
            p = video.recommend_plan(sec, t, 16 / 9.0, 80000000)
            assert p["gen_w"] * p["gen_h"] * p["frames"] <= 80000000 and p["gen_w"] % 64 == 0 and p["gen_h"] % 64 == 0 and (p["frames"] - 1) % 8 == 0
            assert min(p["gen_w"], p["gen_h"]) <= {"1080p": 1080, "2k": 1440, "4k": 2160}[t] and p["out_h"] == {"1080p": 1080, "2k": 1440, "4k": 2160}[t]
            assert p["frames"] >= sec * 24 - 8                                           # no length limit: the SIZE shrinks instead
    assert video.recommend_plan(10, "1080p")["factor"] > 2 and "no new detail" in video.recommend_plan(10, "4k")["note"]
    short = video.recommend_plan(3, "1080p"); assert short["gen_w"] >= 1280 and short["factor"] < 1.6     # a short clip is generated large
    assert "target must be" in raises(video.recommend_plan, 5, "bad")


def _done_job(rig, name="clip.mp4"):
    jid = "abcd1234"; d = os.path.join(rig.q.out_dir, jid); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name); open(p, "wb").write(b"x")
    with rig.q.lock:
        rig.q.jobs.append(dict(id=jid, workflow="w", params={"width": 704, "height": 384}, files={}, state="done", created=time.time(), files_out=[p]))
    return jid, p


def _wait_finish(rig, jid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        f = (rig.q.get(jid) or {}).get("finish") or {}
        if f.get("state") in ("done", "error"): return f
        time.sleep(0.05)
    raise AssertionError("finish stuck")


def test_finish_runs_ffmpeg_and_adds_the_clip():
    rig = tv.Rig(); seen = []
    def run_cmd(cmd, timeout=600):
        seen.append(cmd); open(cmd[-1], "wb").write(b"out"); return 0, ""
    rig.q.env.run_cmd = run_cmd
    jid, p = _done_job(rig)
    rig.q.finish(jid, p, "1080p", 1920, 1080)
    f = _wait_finish(rig, jid)
    assert f["state"] == "done" and f["name"] == "clip_1080p.mp4", f
    cmd = seen[0]; vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1920:1080" in vf and "crop=1920:1080" in vf and cmd[cmd.index("-c:a") + 1] == "copy" and "-nostdin" in cmd
    j = rig.q.get(jid); assert [os.path.basename(x) for x in j["files_out"]] == ["clip.mp4", "clip_1080p.mp4"]
    assert not os.path.exists(os.path.join(os.path.dirname(p), "clip_1080p.mp4.tmp.mp4"))


def test_finish_failure_is_recorded_and_leaves_no_partial():
    rig = tv.Rig()
    def run_cmd(cmd, timeout=600):
        open(cmd[-1], "wb").write(b"half"); return 1, "Conversion failed!"
    rig.q.env.run_cmd = run_cmd
    jid, p = _done_job(rig)
    rig.q.finish(jid, p, "2k", 2560, 1440)
    f = _wait_finish(rig, jid)
    assert f["state"] == "error" and "ffmpeg exit 1" in f["note"]
    assert len(rig.q.get(jid)["files_out"]) == 1 and not [n for n in os.listdir(os.path.dirname(p)) if "tmp" in n]


def test_finish_missing_ffmpeg_message_and_guards():
    rig = tv.Rig()
    def run_cmd(cmd, timeout=600): raise FileNotFoundError("ffmpeg")
    rig.q.env.run_cmd = run_cmd
    jid, p = _done_job(rig)
    assert "target must be" in raises(rig.q.finish, jid, p, "8k", 100, 100)
    assert "bad output size" in raises(rig.q.finish, jid, p, "4k", 3841, 2160)
    assert "finished job" in raises(rig.q.finish, "00000000", p, "4k", 3840, 2160)
    rig.q.finish(jid, p, "4k", 3840, 2160)
    assert "ffmpeg was not found" in _wait_finish(rig, jid)["note"]


def test_video_input_type_is_validated_against_the_shared_folders():
    rig = tv.Rig()
    wf = {"meta": {"params": {"video": {"type": "video", "required": True}, "seconds": {"type": "float", "default": 1.7, "min": 1, "max": 4}}}, "prompt": {}}
    vals, files = video.resolve_params(wf, {"video": "C:\\x\\a.mp4"}, rig.q.cfg)
    assert files == {"video": "C:\\x\\a.mp4"} and "video" not in vals
    ok = os.path.join(rig.img_root, "a.mp4"); open(ok, "wb").write(b"x")
    assert rig.q._check_video(ok) == os.path.realpath(ok)
    assert "outside the shared folders" in raises(rig.q._check_video, os.path.join(rig.t, "b.mp4"))
    bad = os.path.join(rig.img_root, "a.exe"); open(bad, "wb").write(b"x")
    assert "mp4, webm or mov" in raises(rig.q._check_video, bad)


def test_finish_target_runs_after_the_render():
    rig = tv.Rig(); seen = []
    def run_cmd(cmd, timeout=600):
        if "-vf" in cmd: seen.append(cmd)
        open(cmd[-1], "wb").write(b"out"); return 0, ""
    rig.q.env.run_cmd = run_cmd
    assert "finish must be" in raises(rig.q.submit, "t2v", {"prompt": "a fox"}, finish_target="8k")
    jid, pos, est = rig.q.submit("t2v", {"prompt": "a fox"}, finish_target="2K")
    j = rig.wait(jid, ("done", "failed"))
    assert j["state"] == "done" and j["finish_target"] == "2k", j
    f = _wait_finish(rig, jid)
    assert f["state"] == "done" and f["target"] == "2k" and len(rig.q.get(jid)["files_out"]) == 2, f
