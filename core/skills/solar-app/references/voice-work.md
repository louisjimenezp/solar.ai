# Solar App: one conversation-to-work path

`/app` is the user interface. `/` redirects there. Conversations, activity,
artifact previews, status and logs are views within it. `/dashboard` is fleet
administration only; scoped chat is removed and `/api/chat` returns HTTP 410.
The macOS menu bar Voice item records locally, sends the transcript to the
conversation API, and speaks the reply in a HUD. Solar and Dashboard open those
URLs in an app window. There is no automatic paste, separate work page or model picker.

## Runtime and storage

- `app_conversations.py`: SQLite conversations, messages, child run links and cancellation requests.
- `host_server.py`: in-process reconciliation loop. Pending message intents become tasks
  through `voice_work.py`, exclusively in the configured canonical `solar-async-tasks`
  root (`sun/runtime/async-tasks` by default): `drafts` -> `queued`.
- `solar-system` owns the canonical worker when its `async-tasks` feature is enabled.
  Otherwise Host uses the existing `ensure_async_tasks.sh` fallback entrypoint;
  it does not implement another worker or queue.
- `execute_active.py` and `managed_process.py` own execution. `task_cancel.py`
  owns durable cancellation. SQLite cancellation requests are propagated by reconciliation;
  `cancelled` is reported only after the canonical runtime acknowledges stopping.
- Reconciliation projects status, input/output and bounded logs into SQLite.
  `app_artifacts.py` observes files and maintains SQLite snapshots/change events;
  list endpoints query those records, not filesystem directories. A selected file
  is read only for preview, with path and type restrictions.
- Results remain `output.md` in the existing run directory. The parent conversation
  receives one durable completion message and the right panel exposes the artifact.

The API lives in `app_http.py`; UI assets are `app.html`, `app.js`, `app.css`.
Migration 003 adds conversation records. Migration 004 is retained solely because
it was applied during the discarded prototype; 005 removes its model settings and
private task-root column and adds canonical SQLite projections. Do not renumber
applied migrations. No old prototype files are executed or migrated into a second queue.

## Solar and authority

Enable `SOLAR_VOICE_OS_ENABLED=1` only for the accepted matching runtime.
Talk (typed or spoken) enters `POST /api/app/conversations/<id>/messages`.
That door calls solar-router with `channel=app` and `mode=auto`, the same
contract as n8n. There is no private conductor and no `SOLAR_VOICE_CONDUCTOR_*`.
Mac STT/TTS stay local; Solar answers the text.

Explicit local preparation still gets an immediate companion acknowledgement
without a second approval; `tick()` publishes that intent into `solar-async-tasks`.
If the router itself returns `async_draft_created`, the App links that `task_id`
into the conversation expediente. The original message is the authority.
External effects are not queued and require formal approval.

## API and verification

- POST `/api/app/conversations`, then POST `/api/app/conversations/<id>/messages`.
- GET `/api/app/conversations/<id>?workspace=<path>` and `/api/app/threads/<id>`.
- POST `/api/app/runs/<id>/cancel`; reads and mutations pin the expected workspace.
- `/app?conversation=<id>` opens the parent; `/app?thread=<id>` opens a work result.
- Local dictation uses `app_audio.py` and the existing `voice_core.transcribe`.

Run the app, async-tasks and router suites under `core/tests/skills/`.
`test_host_chat_e2e.sh` exercises the canonical HTTP contract in a temporary Host.
Physical microphone quality and real router latency require separate acceptance;
fixture tests are not evidence of a deployed, accepted voice experience.
