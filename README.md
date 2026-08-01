# Instagram Saved Posts Downloader

A reliable, resumable tool to download **all media** (photos, carousels, and videos/reels) from your Instagram **Saved** collection.

---

## Why this project exists

I live in Iran.  
In times of heightened tension or war, internet access can be severely restricted or completely cut off.  

Instagram Saved posts often contain important personal memories, educational content, news archives, tutorials, and reference material. Once the connection is gone, that data becomes inaccessible.

This tool was created so that anyone in a similar situation can **download their entire Saved collection offline** before access becomes limited or impossible.

The goal is simple:

> Make a local backup of everything you have carefully saved on Instagram, so you still own the data even if the platform or the internet becomes unavailable.

---

## Features

- Downloads **images**, **carousels** (multi-image posts), and **videos/reels**
- Works with your personal Saved collection (requires login)
- Fully **resumable** – can be stopped and restarted at any time
- Skips already downloaded posts automatically
- Handles deleted / private / restricted posts gracefully
- Uses a real browser session (Playwright) for maximum reliability
- No dependency on yt-dlp for Instagram (which is currently broken)
- Clean progress bar and detailed logging
- Completeness report at the end of each run

---

## How it works

1. Launches a persistent Chromium browser (via Playwright).
2. You log in to Instagram once (session is saved in `browser_data/`).
3. Scans your entire Saved collection and caches the list of shortcodes in `all_posts.json`.
4. For each remaining post:
   - Opens the post page
   - Extracts high-resolution image URLs and video sources from the DOM
   - Navigates carousels using keyboard arrow keys
   - Downloads every media file into the `downloads/` folder
5. Marks successfully downloaded posts in `downloaded.json`
6. At the end, prints a clear archive status report

The tool is intentionally conservative and resilient. Individual broken posts will not stop the whole process.

---

## Requirements

- Linux (tested on Debian/Ubuntu-based systems)
- Python 3.10 or newer
- A working Instagram account

### System packages (Debian / Ubuntu / similar)

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
```

---

## Installation

```bash
# 1. Clone or download this repository
cd ~/Projects
# (or wherever you keep the project)

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install Python dependencies
pip install --upgrade pip
pip install playwright requests tqdm

# 4. Install the browser that Playwright needs
playwright install chromium
```

---

## Usage

### First run

```bash
source venv/bin/activate
python ig_saved_downloader.py
```

- A Chromium window will open.
- If you are not logged in, the script will ask you to log in manually and then press `ENTER` in the terminal.
- The script will scan your Saved posts (this can take a few minutes on the first run).
- It will then start downloading.

### Subsequent runs

Just run the same command again:

```bash
python ig_saved_downloader.py
```

The tool will automatically:
- Skip posts already marked as downloaded
- Continue from where it left off
- Skip posts that previously failed (if you created `unavailable.json`)

---

## File structure after running

```
InstaSaveSync2/
├── ig_saved_downloader.py      # Main script
├── browser_data/               # Persistent browser profile (login session)
├── downloads/                  # All downloaded media files
├── all_posts.json              # Complete list of shortcodes found in Saved
├── downloaded.json             # Shortcodes that were successfully downloaded
├── unavailable.json            # (optional) Shortcodes that are permanently gone
├── cookies.txt                 # Exported cookies (for potential future use)
└── README.md
```

### Naming of downloaded files

- Single image/video: `SHORTCODE.jpg` or `SHORTCODE.mp4`
- Carousel: `SHORTCODE_1.jpg`, `SHORTCODE_2.jpg`, ...

---

## Checking completeness

After a run finishes, the script prints a status report.  
You can also check manually at any time:

```bash
python -c '
import json
from pathlib import Path

all_posts = set(json.load(open("all_posts.json")))
downloaded = set(json.load(open("downloaded.json")))
remaining = sorted(all_posts - downloaded)

print(f"Total known posts     : {len(all_posts)}")
print(f"Marked as downloaded  : {len(downloaded)}")
print(f"Remaining             : {len(remaining)}")
print(f"Files on disk         : {len(list(Path(\"downloads\").glob(\"*\")))}")
'
```

---

## Handling permanently unavailable posts

Many old saved posts get deleted by their authors or become private.  
These will show errors such as `ERR_HTTP_RESPONSE_CODE_FAILURE` or “No media found”.

You can mark them as unavailable so the script never tries them again:

```bash
python -c '
import json
all_posts = set(json.load(open("all_posts.json")))
downloaded = set(json.load(open("downloaded.json")))
unavailable = sorted(all_posts - downloaded)
with open("unavailable.json", "w") as f:
    json.dump(unavailable, f, indent=2)
print(f"Marked {len(unavailable)} posts as unavailable.")
'
```

Then add this line in the script (already supported in the latest version) so future runs ignore them.

---

## Important notes & limitations

- The tool uses a real browser. Keep the Chromium window open while it runs.
- Instagram may rate-limit or temporarily block aggressive automation. The script includes polite delays, but if you encounter many consecutive failures, wait a few hours and try again.
- Very old posts are frequently deleted by their original authors — this is normal.
- Stories and Highlights are **not** supported (only Saved posts).
- The quality of downloaded media depends on what Instagram serves in the browser (usually the highest available resolution).

---

## Privacy & Security

- All processing happens **locally** on your machine.
- Your login session is stored only in the local `browser_data/` folder.
- No data is sent to any third-party server.
- You are responsible for complying with Instagram’s Terms of Service and for only downloading content you have the right to keep.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Browser opens but stays on login page | Log in manually, then press Enter in the terminal |
| “Session expired” | Delete the `browser_data/` folder and log in again |
| Many consecutive “No media found” | Those posts are most likely deleted or private |
| Script crashes on one post | The latest version catches the error and continues |
| Slow downloads | Normal – Instagram serves media slowly and the script is polite |

---

## License

This project is released for personal backup and archival purposes.  
Use it responsibly and only on content you are allowed to download.

---

**Stay safe. Keep your data.**
