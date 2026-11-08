# AgriVision on Vercel

Browser webcam frontend + Python/Flask/OpenCV backend for **AgriVision: Produce
Ripeness & Defect Grader**.

The visitor opens the site, allows camera access (or uploads a photo), and
presses **Grade this produce**. The browser sends the image to
`POST /api/grade`, and the Python function returns the grade, measurements, and
an annotated image.

Everything here is free-plan compatible. No Hugging Face Space is required.

## What the app returns

- **Grade A / Grade B / Reject**
- Ripeness: Ripe, Turning / mixed, or Unripe
- Color purity percentage
- Dark-surface defect percentage
- Diameter in pixels and approximate millimetres
- An annotated image with the detected outline, diameter line, and grade panel

The analysis logic is the same OpenCV code used by the desktop grader in
`agrivision_grader.py`.

## Project structure

```text
agrivision-vercel/
├── app.py                 # Flask entrypoint and /api/grade endpoint
├── agrivision_grader.py   # Shared OpenCV analysis and annotation
├── requirements.txt       # Flask, NumPy, headless OpenCV
├── .python-version        # 3.12
├── templates/
│   └── index.html         # Page markup
├── public/
│   ├── styles.css         # Page styles (served by the Vercel CDN)
│   └── app.js             # Camera, upload, and API client logic
├── .gitignore
└── .vercelignore
```

## Run locally

From PowerShell:

```powershell
cd "C:\Users\devik\OneDrive\Desktop\mediapipe-project\agrivision-vercel"
..\venv\Scripts\python.exe -m pip install -r requirements.txt
..\venv\Scripts\python.exe -u app.py
```

Open:

```text
http://127.0.0.1:5000
```

Camera access works on `localhost` / `127.0.0.1` and on HTTPS. It does not work
on a plain HTTP LAN address, so use **Upload** there.

Quick API check:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
```

Expected:

```json
{"service": "agrivision", "status": "ok"}
```

## Deploy to Vercel

### Option 1: Vercel CLI (fastest, no GitHub push needed)

Requirements: Node.js/npm (already installed) and a free Vercel account.

1. Open PowerShell in the app folder:

   ```powershell
   cd "C:\Users\devik\OneDrive\Desktop\mediapipe-project\agrivision-vercel"
   ```

2. Log in. This opens your browser:

   ```powershell
   npx vercel login
   ```

   The first `npx` command may ask to install the Vercel CLI; answer `y`.

3. Start the first deployment:

   ```powershell
   npx vercel
   ```

   Answer the prompts like this:

   | Prompt | Answer |
   | --- | --- |
   | Set up and deploy? | `Y` |
   | Which scope? | your personal account |
   | Link to existing project? | `N` to create a new project |
   | Project name | `agrivision` (or another available name) |
   | Directory containing your code | `./` |
   | Want to modify these settings? | `N` |

   To reuse the old `agrivision-seven-dun.vercel.app` address, answer **Yes**
   to “Link to existing project?” and select `agrivision-seven-dun` instead.

4. Deploy the production version:

   ```powershell
   npx vercel --prod
   ```

5. Copy the **Production** URL printed by the CLI. It will look like:

   ```text
   https://agrivision-<something>.vercel.app
   ```

   or, if the project name is available:

   ```text
   https://agrivision.vercel.app
   ```

Share that Production URL. Preview deployment URLs should not be shared as the
main link because they can require Vercel authentication.

To redeploy after changing files, run `npx vercel --prod` again.

### Option 2: GitHub import

The current `SHN-MEDIAPIPE` repository does not contain this web app yet. Either
create a new repository for this folder, or commit this folder into the existing
repository as a subdirectory.

If you push this folder into `SHN-MEDIAPIPE/agrivision-vercel`:

```powershell
cd "C:\path\to\SHN-MEDIAPIPE"
git add agrivision-vercel
git commit -m "Add AgriVision Vercel web app"
git push
```

Then:

1. Open <https://vercel.com/new>.
2. Import the `SHN-MEDIAPIPE` repository.
3. Set **Root Directory** to `agrivision-vercel`.
4. Leave **Framework Preset** as **Flask** (Vercel detects it automatically).
5. Leave the build and output settings empty.
6. Click **Deploy**.

If you create a separate repository containing only the contents of this
folder, leave Root Directory at `./` instead.

The resulting URL has the same format:

```text
https://<project-name>.vercel.app
```

## How the deployment works

- Vercel detects the Flask `app` object in `app.py` at the project root.
- The whole Flask app runs as one Python Vercel Function.
- `public/` is served as static files by the Vercel CDN.
- `templates/` is bundled with the Python function so `render_template()` works.
- No environment variables or database are needed.
- Vercel’s free Hobby plan is sufficient for a demo/student project.

## API contract

### `GET /`

Returns the single-page frontend.

### `GET /api/health`

```json
{"status": "ok", "service": "agrivision"}
```

### `POST /api/grade`

Multipart form upload with one field:

```text
image = <JPG / PNG / WebP file>
```

Successful response:

```json
{
  "detected": true,
  "grade": "Grade A",
  "grade_key": "a",
  "reason": "Ripe, uniform color, clean surface",
  "diameter_px": 360,
  "diameter_mm": 90.0,
  "color_purity_pct": 100.0,
  "defect_pct": 0.4,
  "ripeness": "Ripe",
  "ripe_pct": 100.0,
  "image": "data:image/jpeg;base64,..."
}
```

If no produce is found, the response is still HTTP 200 with:

```json
{
  "detected": false,
  "grade": "No produce",
  "grade_key": "none",
  "reason": "No fruit or vegetable was detected. ...",
  "image": "data:image/jpeg;base64,..."
}
```

Errors return HTTP 400 (missing/empty/invalid image), 413 (too large), or 500
(analysis failure) with an `error` message.

## Upload limits

- Vercel Functions accept at most **4.5 MB** per request and response.
- The frontend re-encodes photos to a maximum side of **1600 px** JPEG and
  caps the upload at **4 MB** before sending.
- The Flask endpoint also accepts up to 10 MB locally and downscales analysis
  input to a maximum side of **1280 px**.
- Captured webcam frames and uploaded photos are processed in memory; the app
  does not save them.

## Troubleshooting

### The URL shows `404: NOT_FOUND`

The project has no production deployment, or the wrong root directory was
deployed. Confirm that `app.py` is at the deployment root, then run:

```powershell
npx vercel --prod
```

Use the exact URL printed under **Production** in the CLI output. The old
`agrivision-seven-dun.vercel.app` address stays 404 until that project is linked
and redeployed.

### Build fails while installing OpenCV

Check the Vercel build logs. Confirm these files are present at the project
root:

- `requirements.txt`
- `.python-version` containing `3.12`
- `app.py`
- `agrivision_grader.py`

Do not upload `venv/` or `__pycache__/`; `.vercelignore` excludes them.

### `413 FUNCTION_PAYLOAD_TOO_LARGE`

The request exceeded Vercel’s 4.5 MB body limit. The browser normally compresses
photos automatically. If it still happens, use a smaller image.

### Camera does not start

- Allow camera permission in the browser.
- Use HTTPS (the Vercel URL) or `http://127.0.0.1:5000` locally.
- Close other apps that may be using the camera.
- Use **Upload** as a fallback.

### First analysis is slow

The first request after inactivity starts a new Python function and imports
OpenCV. Later requests are much faster. The page sends a health request on load
to warm the function up.

## Tuning the grader

Edit the constants at the top of `agrivision_grader.py`:

- HSV color ranges for ripe/unripe produce
- `MIN_ITEM_AREA`
- `DARK_V_MAX`, `DEFECT_EDGE_MARGIN`, `MIN_DEFECT_AREA`
- `MM_PER_PIXEL`
- Grade A / Grade B thresholds

Then redeploy with:

```powershell
npx vercel --prod
```
