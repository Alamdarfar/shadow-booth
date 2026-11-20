"""Fetch Leo English Podcast episodes and turn their transcripts into shadowing lessons.

Usage:
    .venv\\Scripts\\python.exe fetch_lessons.py            # fetch every episode not fetched yet
    .venv\\Scripts\\python.exe fetch_lessons.py --limit 20 # only the 20 newest
    .venv\\Scripts\\python.exe fetch_lessons.py --refresh  # re-fetch lessons already on disk

Writes lessons/index.json (episode list) and lessons/<videoId>.json (timed sentences).
Safe to re-run: episodes already on disk are skipped, so it picks up where it stopped.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi

CHANNEL = "https://www.youtube.com/@Leo-EnglishPodcast/videos"
ROOT = Path(__file__).parent
OUT = ROOT / "lessons"
YTDLP = ROOT / ".venv" / "Scripts" / "yt-dlp.exe"
MAX_WORDS = 20
BLOCKED = ("IpBlocked", "RequestBlocked", "TooManyRequests")


def list_videos(limit=None):
    cmd = [str(YTDLP), "--flat-playlist", "--print", "%(id)s\t%(title)s\t%(duration)s", CHANNEL]
    if limit:
        cmd[1:1] = ["--playlist-end", str(limit)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    vids = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0]:
            dur = int(float(parts[2])) if parts[2] not in ("NA", "None", "") else None
            vids.append({"id": parts[0], "title": parts[1], "duration": dur})
    return vids


def level_from_title(title):
    m = re.search(r"\b([ABC][12])\s*[-–]\s*([ABC][12])\b", title)
    if m:
        return f"{m.group(1)}–{m.group(2)}"
    m = re.search(r"\b([ABC][12])\b", title)
    return m.group(1) if m else ""


def short_title(title):
    """Pick the most specific part of 'English Podcast | Topic | Tagline' titles."""
    parts = [p.strip() for p in title.split("|") if p.strip()]
    generic = re.compile(r"english podcast|learn(ing)? english|english conversation|conversation practice|"
                         r"speaking practice|listening practice|easy english|daily life english", re.I)
    specific = [p for p in parts if not generic.search(p)]
    return (specific or parts or [title])[0]


def build_sentences(snippets):
    """Spread each caption line's time across its words, then regroup the words into sentences."""
    words = []  # (word, time, new_turn)
    for i, s in enumerate(snippets):
        text = s.text.replace("\n", " ").strip()
        if not text or re.fullmatch(r"\[.*?\]", text):
            continue
        nxt = snippets[i + 1].start if i + 1 < len(snippets) else s.start + s.duration
        end = max(min(nxt, s.start + s.duration), s.start + 0.3)
        toks = text.split()
        turn = False
        clean = []
        for t in toks:
            if t.startswith(">>"):
                turn = True
                t = t[2:]
                if not t:
                    continue
            if re.fullmatch(r"\[.*?\]", t):
                continue
            clean.append((t, turn))
            turn = False
        for k, (t, tn) in enumerate(clean):
            words.append((t, s.start + (end - s.start) * k / max(len(clean), 1), tn))

    sentences, cur = [], []

    def flush(end_time):
        if cur:
            sentences.append({"t": " ".join(w for w, _, _ in cur), "s": round(cur[0][1], 2), "e": round(end_time, 2),
                              "turn": cur[0][2]})
            cur.clear()

    for idx, (w, t, turn) in enumerate(words):
        if turn and cur:
            flush(t)
        cur.append((w, t, turn))
        next_t = words[idx + 1][1] if idx + 1 < len(words) else t + 0.6
        if re.search(r"[.!?][\"')\]]*$", w) or (len(cur) >= MAX_WORDS and w.endswith(",")) or len(cur) >= MAX_WORDS + 8:
            flush(next_t)
    if words:
        flush(words[-1][1] + 0.8)

    # merge very short fragments ("Okay.") into the next sentence when it is close in time
    merged = []
    for s in sentences:
        if merged and not s["turn"] and len(merged[-1]["t"].split()) < 3 and s["s"] - merged[-1]["e"] < 1.0 \
                and len(merged[-1]["t"].split()) + len(s["t"].split()) <= MAX_WORDS + 4:
            merged[-1] = {**merged[-1], "t": merged[-1]["t"] + " " + s["t"], "e": s["e"]}
        else:
            merged.append(s)
    # "n" marks a new speaker's turn so the app can show who is talking changed
    return [{"t": s["t"], "s": s["s"], "e": s["e"], **({"n": 1} if s["turn"] else {})}
            for s in merged if len(s["t"].split()) >= 2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the N newest episodes")
    ap.add_argument("--refresh", action="store_true", help="re-fetch episodes already on disk")
    ap.add_argument("--delay", type=float, default=4, help="seconds between transcript requests")
    ap.add_argument("--wait", type=float, default=20, help="minutes to wait when YouTube limits requests")
    ap.add_argument("--max-waits", type=int, default=6, help="how many times to wait and retry before stopping")
    args = ap.parse_args()
    blocks = 0

    OUT.mkdir(exist_ok=True)
    print("Listing channel videos…", flush=True)
    videos = list_videos(args.limit)
    print(f"Found {len(videos)} videos", flush=True)

    api = YouTubeTranscriptApi()
    index_path = OUT / "index.json"
    old = {v["id"]: v for v in json.loads(index_path.read_text("utf-8"))} if index_path.exists() else {}
    index, fetched, skipped, failed = [], 0, 0, []

    def save_index():
        # keep channel order (newest first); include older entries no longer in this listing
        ids = {v["id"] for v in index}
        rest = [v for k, v in old.items() if k not in ids]
        index_path.write_text(json.dumps(index + rest, ensure_ascii=False, indent=1), "utf-8")

    for n, v in enumerate(videos, 1):
        path = OUT / f"{v['id']}.json"
        entry = {"id": v["id"], "title": v["title"], "short": short_title(v["title"]),
                 "level": level_from_title(v["title"]), "duration": v["duration"]}
        if path.exists() and not args.refresh:
            entry["count"] = len(json.loads(path.read_text("utf-8"))["sentences"])
            index.append(entry)
            skipped += 1
            continue
        try:
            tr = None
            while tr is None:
                try:
                    tr = api.fetch(v["id"], languages=["en", "en-US", "en-GB"])
                except Exception as e:  # noqa: BLE001
                    if type(e).__name__ in BLOCKED and blocks < args.max_waits:
                        blocks += 1
                        save_index()
                        print(f"YouTube is limiting requests. Waiting {args.wait} min before retrying "
                              f"({blocks}/{args.max_waits})…", flush=True)
                        time.sleep(args.wait * 60)
                        api = YouTubeTranscriptApi()
                    else:
                        raise
            sents = build_sentences(list(tr))
            if len(sents) < 3:
                raise ValueError("transcript too short")
            path.write_text(json.dumps({**entry, "sentences": sents}, ensure_ascii=False), "utf-8")
            entry["count"] = len(sents)
            index.append(entry)
            fetched += 1
            print(f"[{n}/{len(videos)}] {len(sents):4d} sentences  {entry['short'][:60]}", flush=True)
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            failed.append((v["id"], name))
            print(f"[{n}/{len(videos)}] skipped ({name})  {entry['short'][:60]}", flush=True)
            if name in BLOCKED:
                print("YouTube is limiting requests from this network. Stopping; re-run later to continue.", flush=True)
                break
        if n % 10 == 0:
            save_index()
        time.sleep(args.delay)

    save_index()
    print(f"\nDone. {fetched} fetched, {skipped} already on disk, {len(failed)} skipped.")
    print(f"Lessons in index: {len(json.loads(index_path.read_text('utf-8')))}")


if __name__ == "__main__":
    sys.exit(main())
