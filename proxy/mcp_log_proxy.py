"""A stdio logging proxy for MCP: sits between an MCP client and an MCP server and writes every
JSON-RPC line, both ways, with a timestamp, to a JSONL file. It forwards bytes unchanged.

    python3 mcp_log_proxy.py --log transcript.jsonl [--png-dir DIR] -- solidcraft-cli mcp --allow-path /lab/out

Each log line: {"t": ISO-8601 UTC, "seq": n, "dir": "client->server" | "server->client" | "server-stderr" | "proxy", "msg": ...}
Only the LOG is shortened: base64 image data in a reply is replaced by its size and SHA-256 and
the PNG is written to --png-dir (the client still receives the full image).
"""

import argparse
import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys
import threading

lock = threading.Lock()
seq = 0
shots = 0


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def shorten_images(msg, png_dir):
    global shots
    content = (msg.get("result") or {}).get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return msg
    msg = json.loads(json.dumps(msg))
    for c in msg["result"]["content"]:
        if c.get("type") == "image" and isinstance(c.get("data"), str):
            raw = base64.b64decode(c["data"])
            shots += 1
            name = f"claude-shot-{shots:02d}.png"
            if png_dir:
                with open(os.path.join(png_dir, name), "wb") as f:
                    f.write(raw)
            c["data"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "saved_as": name}
    return msg


def log(fh, direction, line, png_dir=None):
    global seq
    text = line.decode("utf-8", errors="replace").rstrip("\r\n")
    try:
        msg = json.loads(text)
        if direction == "server->client":
            msg = shorten_images(msg, png_dir)
    except json.JSONDecodeError:
        msg = text
    with lock:
        seq += 1
        fh.write(json.dumps({"t": now(), "seq": seq, "dir": direction, "msg": msg}, ensure_ascii=False) + "\n")
        fh.flush()


def pump(src, dst, fh, direction, png_dir=None):
    for line in iter(src.readline, b""):
        log(fh, direction, line, png_dir)
        if dst is not None:
            dst.write(line)
            dst.flush()
    if dst is not None and direction == "client->server":
        dst.close()  # client closed stdin: pass the EOF on


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--png-dir")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    fh = open(a.log, "a", encoding="utf-8")
    log(fh, "proxy", json.dumps({"start": cmd}).encode())
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    threads = [
        threading.Thread(target=pump, args=(sys.stdin.buffer, child.stdin, fh, "client->server"), daemon=True),
        threading.Thread(target=pump, args=(child.stdout, sys.stdout.buffer, fh, "server->client", a.png_dir)),
        threading.Thread(target=pump, args=(child.stderr, None, fh, "server-stderr")),
    ]
    for t in threads:
        t.start()
    rc = child.wait()
    for t in threads[1:]:
        t.join()
    log(fh, "proxy", json.dumps({"exit": rc}).encode())
    return rc


if __name__ == "__main__":
    sys.exit(main())
