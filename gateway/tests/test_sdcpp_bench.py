"""tools/sdcpp_bench.py against a fake sd-cli script (no GPU, no real sd-cli). Run: python tests/test_sdcpp_bench.py"""
import os, sys, traceback
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(D, "tools"))
import sdcpp_bench as sb

def test_selftest_with_fake_exe():
    assert sb.selftest() == 0                      # success, non-zero exit, kill under --min-free-mb, timeout, no RAM source, missing exe, JSON lines, ltx_bench keys

def test_ram_probe_never_raises():
    av, tot = sb.available_mb(); assert (av is None) == (tot is None) or tot is None or av is not None

def test_bad_flag_map():
    try: sb.parse_flag_map(["nope=--x"]); raise AssertionError("accepted")
    except sb.BenchError: pass

if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    sys.exit(1 if fails else 0)
