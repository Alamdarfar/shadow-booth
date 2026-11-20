# Shadow Booth

Personal shadowing practice with Leo English Podcast episodes. Each episode's YouTube transcript is split into timed sentences; the app plays one sentence from the real video, you repeat it, and Chrome's speech recognition scores which words you got.

## Run the app

Double-click `start.bat`, or:

```
.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1
```

then open http://localhost:8765 in **Google Chrome** (speech scoring needs Chrome or Edge; allow the microphone when asked).

## Get new episodes

```
.venv\Scripts\python.exe fetch_lessons.py
```

- Lists every video on the channel and downloads transcripts for episodes not on disk yet (`lessons/`).
- If YouTube limits requests, it waits 20 minutes and retries (up to 6 times), then stops. Re-run any time; it resumes where it left off.
- Options: `--limit 20` (newest 20 only), `--refresh` (re-download), `--delay 4`, `--wait 20`, `--max-waits 6`.

## Files

- `index.html` – the app (library + practice booth)
- `fetch_lessons.py` – downloader / sentence splitter
- `lessons/index.json` – episode list; `lessons/<videoId>.json` – timed sentences
- Scores are saved in the browser (localStorage), per episode.
