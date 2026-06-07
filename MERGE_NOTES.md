# Tickety — Backend Merge Notes

One unified Flask backend serving both the **React web app** and the
**Flutter mobile app**. Built by merging the two forked backends.

## How the merge was done
The two backends were a clean fork of a common base: 12 source files were
byte-identical, and every shared feature exposed the **same route surface**.
Divergence was almost entirely *disjoint feature additions*, so this is a
union merge, not a rewrite.

## Per-area decisions
- **models.py** — union: kept the web schema (Notification, Service.notifications,
  Ticket.printed) and added the mobile `SwapRequest` model. Added a `called_at`
  column + `Ticket.actual_wait_minutes()` (see "fixes" below).
- **queues.py** — union of both controllers in one class:
  web `issue_ticket` + mobile `get_tickets_for_user`, `get_ticket`,
  `check_called`, `preview_queue`. The fragile positional `_get_deps()` tuple
  was replaced with a named `_QueueDeps` container (see "fixes").
- **counter.py / team.py / analytics.py** — kept the web versions; they are
  supersets (notifications, real wait-time analytics, cleaner team handling).
- **auth.py** — kept web version + added mobile `change_password` /
  `delete_account`.
- **repositories** — `ticket_repository` kept the web version (its
  position logic is correct, see "fixes") + added mobile
  `find_by_customer_identifier`; `user_repository` gained `find_by_id` + `delete`.
- **schedule_service.py** — kept the web version (timezone-safe helpers).
- **app.py** — web factory + registered the mobile `swap_bp`. 10 blueprints total.
- **requirements.txt** — rebuilt from real imports (12 packages) instead of the
  mobile backend's ~50-package freeze (torch/opencv/whisper/pygame/etc. unused).

## Bugs found and fixed during the merge
1. **Ticket status lifecycle.** The mobile `join_queue` force-set new tickets to
   `active`, which made them invisible to the shared counter's *waiting* list
   (active but position > 0 → neither "serving" nor "waiting"). The shared
   counter logic, and the mobile app's own display code, reveal the intended
   design: **store `pending`, display `active`**. New tickets are now created
   `pending`; `get_ticket`/`get_tickets_for_user` translate `pending → "active"`
   for the end-user view only. (This also restored the mobile backend's narrowed
   `next_position`/`reindex_positions`, which had been limited to `active` and
   would have collapsed all positions to 0.)
2. **`user_repo` mis-binding.** The mobile `get_tickets_for_user`/`get_ticket`
   unpacked a `QueueRepository` into a `user_repo` slot and called
   `user_repo.find_by_id(...)` — looking up a *queue* by user id. Fixed by the
   named-dependency container, which binds `user_repo` to `UserRepository`.
3. **Dead/broken rolling-average code.** The web `compute_rolling_avg_duration`
   referenced a non-existent `Ticket.called_at` column and
   `actual_wait_minutes()` method. Added both to the model and now stamp
   `called_at` when an agent calls a ticket (in `call_next` and on promotion in
   `terminate`). Estimation behaviour is unchanged — the method is now correct and
   available to enable when wanted.

## Note on JWT
The mobile backend's `.env` carried `JWT_*` keys, but the unified auth uses the
OTP + session-payload flow (no JWT). Those keys were intentionally **not** carried
over to avoid dead, misleading config.

## Frontends
No code changes required. Point both clients' API base URL at this one backend:
- React: its API base env var → this server's `/api`.
- Flutter: its base URL → this server's `/api`.

## Run locally
    cp .env.example .env        # then fill in DATABASE_URL + BREVO keys
    pip install -r requirements.txt
    python app.py               # dev server on :5000
    # or production:  gunicorn -w 4 wsgi:app
