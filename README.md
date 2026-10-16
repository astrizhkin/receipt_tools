# Receipt Tools

Receipt OCR pipeline + minimal Android capture app.

Take a photo of a cash-register receipt on the phone → the pipeline resizes it,
runs Qwen VL OCR (whole document as Markdown), converts the Markdown to
structured JSON with a text LLM (arithmetic-validated), and stores the
receipt + line items + discounts in Postgres. Every step's input/output is
saved for debug.

## Layout

```
receipt_tools/
├── app/                 Flutter app source (mounted into the builder container)
├── pipeline/            LangGraph pipeline + FastAPI (own Docker image)
│   ├── src/phunter/     package: api, graph, steps/, llm, artifacts, db, schemas
│   ├── config/pipeline.yaml
│   └── tests/           offline tests (httpx.MockTransport) — `docker build --target test`
├── docker/flutter-builder/   Dockerfile: Flutter SDK + Android SDK build container
├── db/init/             postgres schema (applied on first start)
├── artifacts/           per-call folders (runtime output, bind-mounted)
├── demo/                scaffold_app.sh, build_apk.sh, send_photo.sh, run_demo.sh
└── docker-compose.yaml  postgres + pipeline
```

Source and artifacts are separate: code lives in `app/` + `pipeline/`,
all runtime output lands in `artifacts/<run_id>/`.

## Auth (device id + PAT)

On app launch the phone calls `POST /check_account {device_id, pat|null}`;
the server returns the account's PAT (issuing a new one for unknown
device+pat), and the app stores it in `flutter_secure_storage`. Every other
endpoint requires matching `X-PAT` + `X-Device-Id` headers (401 otherwise).
Known-device lookups always return the stored PAT — deliberate demo-stage
security debt.

## Pipeline (async)

`POST /photo_input` (auth, multipart `file`) → **202** `{request_id, status:"queued"}`;
a single-threaded background worker claims queued requests FIFO and runs the
graph, updating `requests.status/stage/status_at` at every step. The app polls
`GET /requests/{id}` every 5 s. Endpoints: `GET /requests`, `GET /requests/{id}`,
`GET /receipts/{id}` (all authed). `receipts.request_id` links the result.

Per-call folder `artifacts/<run_id>/`:

```
original.jpg
journal.log                  ts | run | node | event | json
run_meta.json
steps/01_resize/             input.md, output.json, resized.jpg
steps/02_ocr/                input.md, output.json, raw.txt, llm/NNN_*_{input.md,output.txt}
steps/03_structure/          same shape
steps/04_persist/            output.json (receipt_id)
```

Steps (LangGraph linear chain):
1. **resize** — integer scale factor `k` so `(w//k)*(h//k) <= 3 MP`
2. **ocr** — Qwen VL endpoint (host/model via `PH_VL_*` in `.env`), plain
   Markdown of the whole receipt
3. **structure** — text LLM (via `PH_TEXT_*` in `.env`) → receipt JSON (store,
   date, items[], totals, discounts), pydantic-validated + arithmetic-checked
   via the validate_json tool with retry-feedback
4. **persist** — `receipts` + `receipt_items` in Postgres

## Run

```bash
cp .env.example .env                  # fill in DB creds + LLM endpoints (gitignored)
docker compose up -d --build          # postgres + pipeline on :8000, web on :8090
./demo/run_demo.sh                    # bootstraps an account, sends all sample photos, polls
./demo/curl_auth.sh                   # reference: get PAT/DEV by hand
PAT=... DEV=... ./demo/send_photo.sh <file.jpg>   # single photo + poll
```

## Web app

`./demo/build_web.sh` compiles the Flutter app for the browser into
`app/build/web`; the `web` compose service (nginx, port **8090**) serves it and
proxies the API same-origin at `/api/` → pipeline:8000 (no CORS, no cert
prompts). On web the button is "Upload a photo" (browser file picker) and the
device id falls back to a stored random id (no ANDROID_ID in browsers).

Tests: `docker build --target test -t ph-test pipeline && docker run --rm ph-test`

> Note: this workspace is itself a container; `/workspace` == `/home/andy/Projects/claude-workspace`
> on the docker daemon host. Bind mounts in `.env` (`PH_HOST_DIR`) must use the host path.

## Android app

One button: **Take a photo** → camera → multipart upload to the pipeline URL
(editable in the app; set it to the host's LAN IP reachable from the phone).

```bash
./demo/scaffold_app.sh    # one-time: flutter create inside the builder container
./demo/build_apk.sh       # APK -> app/build/app/outputs/flutter-apk/app-release.apk
```

The builder container mounts `app/` at `/src` and caches gradle/pub in named
volumes (`ph_gradle_cache`, `ph_pub_cache`).

## Config

`pipeline/config/pipeline.yaml` holds tuning only (prompts, token limits,
resize, timeouts). Endpoints, models and the DB DSN are deployment config:
set them in `.env` (copy `.env.example`) — `PH_VL_BASE_URL`, `PH_VL_MODEL`,
`PH_TEXT_BASE_URL`, `PH_TEXT_MODEL`, `PH_DB_*`, `PH_DB_DSN`,
`PH_ARTIFACTS_DIR`. The pipeline refuses to start without them.

## License

Apache License 2.0 — see [LICENSE](LICENSE). Free to use, modify and deploy;
redistributions must keep the LICENSE, the copyright notice and the
[NOTICE](NOTICE) file.

Source: https://github.com/astrizhkin/receipt_tools
