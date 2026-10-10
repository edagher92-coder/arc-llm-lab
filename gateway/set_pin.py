"""Reads the new PIN from stdin and stores a salted PBKDF2-SHA256 hash in approval-pin.json next to this file."""
import hashlib, json, os, sys
pin = sys.stdin.readline().strip()
if len(pin) < 6:
    sys.exit("PIN too short")
salt = os.urandom(16); n = 310000
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "approval-pin.json")
json.dump({"salt": salt.hex(), "iterations": n, "hash": hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, n).hex()}, open(out, "w"))
print("saved")
