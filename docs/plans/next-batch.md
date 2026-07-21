# WorkshopOS — Next Feature Batch (planned 2026-07-17)

Combined plan for the 6 remaining post-billing roadmap items (User Manual/Documentation excluded — that's written after these features exist, not planned alongside them). Each section is self-contained and can be executed independently, in this order, one at a time — building all 6 in parallel would risk the same contract-mismatch problems this session's reconciliation passes have repeatedly caught (multiple features touching `ToolsPage.tsx`, `types.ts`, `api.ts`, and a new dashboard simultaneously). Two of the six (Checkout Tracking, Maintenance Reminders) share one new Dashboard page — introduced by Checkout Tracking, extended by Maintenance Reminders — so build those two in that order.

Research for all 6 was done directly against the real codebase (file:line references below) before writing this plan, same discipline as every other milestone this session.

---

## 1. Tool Photos

### Context
Attach a photo to a Tool so you can visually confirm what's in a bin at a glance, not just rely on the printed label.

### Backend changes
- New `Tool.photo_path: str | None` column (new Alembic migration, next number after whatever's latest at execution time).
- Storage convention matches every other generated/uploaded file in this app exactly: `Path(settings.generated_files_dir) / org_id / "tools" / tool_id / f"photo{ext}"` (mirrors `InsertDesign`'s `{generated_files_dir}/{org_id}/{entity_id}/...` pattern from `workers/tasks.py`).
- `POST /organizations/{id}/tools/{tool_id}/photo` — multipart upload. Accept `.jpg/.jpeg/.png/.webp/.gif` by extension (don't trust Content-Type — same reasoning as the existing STL upload endpoint in `insert_designs.py`). Read fully into memory (no chunked write needed — photos are far smaller than the STL endpoint's 25MB use case), cap at **10MB**. On upload, delete any existing photo file first (replace semantics, one photo per tool), write the new one, set `photo_path`.
- `DELETE /organizations/{id}/tools/{tool_id}/photo` — remove file + clear `photo_path`.
- `GET /organizations/{id}/tools/{tool_id}/photo` — `FileResponse`, `media_type` via stdlib `mimetypes.guess_type(photo_path)`, 404 if `photo_path` is unset or the file is missing on disk (same pattern as `get_insert_design_file`).
- `ToolRead` gains `has_photo: bool` — attached as a plain instance attribute (`tool.has_photo = tool.photo_path is not None`) in the same "query/derive separately, attach as instance attribute" convention already used for `location` (`_attach_locations` in `routers/tools.py`) — **not** the raw `photo_path`, so the filesystem layout never leaks to the client.

### Frontend changes
- `frontend/src/lib/api.ts`: `uploadToolPhoto(toolId, file)` (multipart, mirrors `uploadInsertDesign`), `deleteToolPhoto(toolId)`, `fetchToolPhoto(toolId): Promise<Blob>` (authenticated blob fetch, mirrors `fetchInsertDesignFile`).
- `frontend/src/lib/types.ts`: `Tool.has_photo: boolean`.
- `frontend/src/pages/tools/ToolsPage.tsx`: new "Photo" column. If `has_photo`, a small thumbnail — fetched lazily via `useQuery({queryKey: ["tool-photo", tool.id, tool.updated_at], queryFn: () => fetchToolPhoto(tool.id)})` (keying on `updated_at` naturally busts the cache on replace, since replacing a photo updates the row's timestamp) rendered as an `<img src={URL.createObjectURL(blob)}>`. If no photo, a small camera-icon button. Either way, clicking opens a hidden `<input type="file" accept="image/*">` that immediately uploads on selection (no separate dialog — one-click, matching this feature's low ceremony). A small trash icon next to an existing thumbnail calls `deleteToolPhoto`.

### Scope limits
- No server-side resizing/compression/thumbnailing — store as-is, let the browser handle display sizing via CSS. No new image-processing dependency (Pillow) needed for this specific feature.
- No content-based image validation beyond extension — matches this app's established STL-upload precedent (trust the extension, not a deep content sniff).
- One photo per tool, not a gallery.

### Verification
1. Backend tests: upload replaces an existing photo (old file actually removed from disk, not orphaned), delete clears both the column and the file, wrong extension rejected, oversized file rejected (413), `GET .../photo` 404s when none exists, tenant isolation (org A can't fetch org B's tool photo).
2. Live curl pass: upload a real JPEG, confirm `has_photo: true` on the tool, download it back and diff bytes, delete it, confirm 404 afterward.
3. Browser pass: upload via the Tools table, confirm the thumbnail renders, replace it and confirm the old one is gone (no stale cache), delete it and confirm the camera icon returns.

---

## 2. QR Code on Labels

### Context
Embed a scannable QR code into a generated physical label that deep-links to the tool's info page, for mobile lookup while in the workshop. ("Barcode" in the roadmap title resolved to QR specifically — denser, easier to scan reliably at small printed size, and the geometry pipeline supports it equally well.)

Two real prerequisites, confirmed via research, that this feature must build, not just the QR geometry itself:
- **`Design` (the label entity) has no link to `Tool` at all today** — it's a free-form `text` string with no relationship to any Tool/Drawer/Shop row beyond an optional `shop_id`. A QR code needs something stable to link to, so a label must optionally be tied to a specific `Tool`.
- **No `/tools/:id` detail route or page exists** — confirmed via `App.tsx`'s route tree (`tools` is a flat leaf, unlike `label-designer`/`inserts` which do have `:id` detail children). The QR's target URL needs somewhere to actually resolve.

### Backend changes
- New `Design.tool_id: uuid.UUID | None` (FK to `tools.id`, nullable — existing unlinked labels keep working exactly as today; new migration).
- `DesignCreate` gains optional `tool_id`; `create_design` validates it the same way `_validate_drawer`/`_validate_insert_design` validate other cross-entity FKs in `tools.py` (tool must belong to the same org).
- `geometry/pyproject.toml`: add `qrcode` (matrix-only usage — `QRCode.get_matrix()` returns a grid of booleans directly, no `[pil]`/Pillow extra needed, confirmed via research this avoids a second image library alongside Tool Photos' needs).
- `geometry/src/workshop_geometry/label_engine.py`: new `_qr_geometry(url: str) -> Polygon` — get the QR matrix, turn each dark cell into a Shapely `box()`, `unary_union` them (same "2D polygon, then extrude" pipeline the existing text rendering already uses — confirmed this is a straightforward extension of `_text_geometry`/`_extrude`, not a new geometry primitive). Fixed physical size (~15×15mm) with a low/medium error-correction level chosen to keep the module count printable at that size. `generate_label()` calls this only when the `Design` has a `tool_id`, producing a third extruded body (`qr_body`) via the existing `_extrude()` helper, exported as a third STL (`qr.stl`) alongside the existing `outline.stl`/`text.stl` — same multi-body-for-multi-color-print convention already established, not a new export shape.
- The QR payload URL is `f"{settings.app_public_url}/tools/{tool_id}"` — reuses the `app_public_url` setting added in the billing milestone (Stripe redirect URLs), no new setting needed.
- New minimal `GET /organizations/{id}/tools/{tool_id}` consumer on the frontend (the endpoint **already exists** — `get_tool`, confirmed unchanged — this is purely new frontend surface, zero new backend route for the detail page itself).

### Frontend changes
- `frontend/src/App.tsx`: new `{ path: "tools/:toolId", element: <ToolDetail /> }` route.
- New `frontend/src/pages/tools/ToolDetail.tsx` — minimal read-only view (name/category/manufacturer/sku/notes/quantity/location breadcrumb from `tool.location`, photo if `has_photo` from the Tool Photos milestone) — this is the page the QR code's URL resolves to once scanned and logged in.
- `frontend/src/pages/label-designer/DesignsList.tsx`: create form gains an optional "Link to tool" `<Select>` (same pattern as `ToolsPage.tsx`'s existing drawer/insert selects), populated via `toolsApi.list()`.
- `frontend/src/pages/label-designer/DesignDetail.tsx`: a third "Download QR STL" button alongside the existing outline/text downloads, shown only when `design.tool_id` is set, reusing the exact `fetchDesignFile`/`triggerBlobDownload` pattern already there for the other two bodies.

### Scope limits
- QR only, no 1D barcode support.
- The QR's target page requires being logged in as a member of the org — no public/unauthenticated tool view is being built. Scanning while logged out shows the login wall, which is expected/acceptable for this app's homelab/small-team audience, not a gap to fix here.
- No change to unlinked labels' existing behavior — `qr.stl` is only produced when a label is explicitly linked to a tool.

### Verification
1. Backend/geometry tests: a linked `Design` produces 3 STL bodies (outline/text/qr), an unlinked one still produces exactly 2 (regression check — existing behavior unchanged), the QR body's bounding box matches the fixed ~15mm target size, and (using a QR-decoding library only in the test, e.g. `pyzbar` or by re-deriving the matrix and comparing) the extruded QR's module pattern actually decodes back to the expected URL — not just "some geometry was produced."
2. Live curl pass: create a tool, create a label linked to it, generate, download `qr.stl`, confirm via an independent QR decode that scanning it (in a real phone camera or a decode library) resolves to `{app_public_url}/tools/{tool_id}`.
3. Browser pass: navigate to the new `/tools/:id` route directly, confirm it renders the right tool's info; create a linked label end-to-end through the UI and confirm the QR download button appears only when linked.

---

## 3. Tool Checkout / Loan Tracking

### Context
Track who has a tool checked out and when it's due back — relevant for shared workshops/makerspaces. No real multi-user support exists yet (Member invites is still unbuilt — every org has exactly one real user account today), so "checked out to" is a **free-text field**, not a link to a User account.

This introduces the app's first dashboard page (confirmed via research: `/` just redirects to `/shops`, no dashboard/home route or nav item exists anywhere) — Maintenance Reminders (next section) extends this same dashboard rather than building a second one.

### Backend changes
- New `Tool` columns: `checked_out_to: str | None`, `checked_out_at: datetime | None`, `checkout_due_at: datetime | None` (new migration).
- Two dedicated endpoints rather than raw PATCH, to keep the three fields atomically consistent (PATCH could otherwise set `checked_out_at` without `checked_out_to`, an invalid state the schema itself can't express):
  - `POST /organizations/{id}/tools/{tool_id}/checkout` `{checked_out_to: str, checkout_due_at: datetime | None}` — 422 if `checked_out_to` is blank or the tool is already checked out.
  - `POST /organizations/{id}/tools/{tool_id}/return` — clears all three fields. 422 if not currently checked out.
- `ToolRead` gains `checked_out_to`/`checked_out_at`/`checkout_due_at` directly (real columns, no derivation needed — unlike `location`/`has_photo`).
- New `GET /organizations/{id}/dashboard` — first cross-entity aggregation endpoint in this app (confirmed via research: every existing list endpoint is strictly single-entity-type). Returns `{overdue_checkouts: ToolRead[], active_checkouts: ToolRead[]}` for this milestone (Maintenance Reminders adds a third key to the same response).

### Frontend changes
- `frontend/src/lib/types.ts`/`api.ts`: new fields on `Tool`, `checkoutTool(toolId, payload)`/`returnTool(toolId)`, `dashboardApi.get()`.
- `frontend/src/pages/tools/ToolsPage.tsx`: a compact "Status" column — a `Badge` (component already exists, `components/ui/badge.tsx`, unused in this file today) showing "Checked out to X" (`variant="outline"`, or `variant="destructive"` if past `checkout_due_at`) with an inline "Return" button, or a "Check out" button opening a small `FormDialog` (who + optional due date) when not checked out.
- New `frontend/src/pages/Dashboard.tsx` + `App.tsx` route (`/` now renders this instead of redirecting straight to `/shops`; add a "Dashboard" entry to `Sidebar.tsx`'s nav). Two always-visible lists — **styled and behaviorally modeled on `DrawerDetail.tsx`'s existing Unplaced-list idiom**: always rendered even when empty (explicit "Nothing overdue" state, not conditionally hidden — this app has an established, explicitly-commented anti-silent-failure convention here, confirmed via research at `DrawerDetail.tsx:504-524`), destructive-tinted styling for the overdue list.

### Scope limits
- No link to real User accounts — free-text borrower name only, consistent with "Member invites" being a separate, still-unbuilt roadmap item.
- No reservation/queue system (can't "reserve" a tool that's currently out) — just checked-out-or-not.
- No email/push reminders for due dates — surfaced only via the in-app dashboard, not proactively notified (that's closer to the separate Job Failure Notifications feature's territory, and even that one is in-app-only per its own scope limits below).

### Verification
1. Backend tests: checkout sets all 3 fields, checking out an already-checked-out tool 422s, return clears all 3, returning a not-checked-out tool 422s, dashboard correctly buckets overdue (`checkout_due_at < now`) vs active (checked out, not yet due or no due date set).
2. Live curl pass: full checkout → verify dashboard shows it under active → set a past due date → verify it moves to overdue → return → verify dashboard is empty again.
3. Browser pass: check out a tool via the Tools table, confirm the Dashboard reflects it immediately, confirm the overdue-styling kicks in for a past-due item, return it and confirm both surfaces clear.

---

## 4. Maintenance Reminders

### Context
Periodic reminders for tool maintenance (sharpening, calibration, battery replacement). Extends the Dashboard introduced by Checkout Tracking — build after that feature, not before.

### Backend changes
- New `Tool` columns: `maintenance_interval_days: int | None`, `last_maintained_at: datetime | None` (new migration). A single interval/last-done pair per tool (not a separate `ToolMaintenanceReminder` table for multiple reminder types) — kept simple; if a tool genuinely needs several independent reminder types later, that's a natural additive migration, not something to speculatively build now.
- `POST /organizations/{id}/tools/{tool_id}/maintenance/mark-done` — sets `last_maintained_at = now()`. Setting/changing `maintenance_interval_days` itself is a plain field, updatable via the existing PATCH endpoint (no atomicity concern here, unlike checkout).
- `GET /organizations/{id}/dashboard` (extended, not duplicated) gains a third key: `maintenance_due: ToolRead[]` — computed as `maintenance_interval_days IS NOT NULL AND (last_maintained_at IS NULL OR last_maintained_at + interval < now())`.

### Frontend changes
- `frontend/src/lib/types.ts`/`api.ts`: new fields, `markMaintenanceDone(toolId)`.
- Tool create/edit form (`ToolsPage.tsx`): optional "Maintenance interval (days)" number input.
- `Dashboard.tsx`: third always-visible list, "Maintenance due," same styling convention as the checkout lists, each row with a "Mark done" button.
- `ToolsPage.tsx`'s Status column: if a tool has both an overdue checkout and maintenance due, show whichever is more urgent (overdue checkout first) rather than stacking multiple badges — keeps the table compact; the Dashboard is the place to see the full breakdown.

### Scope limits
- No proactive notification (email/push) when maintenance comes due — surfaced only on the Dashboard, matching Checkout Tracking's same scope limit.
- No maintenance history log (who did it, what was done) — just a single last-done timestamp. A history table is a natural future extension if ever needed, not built now.

### Verification
1. Backend tests: a tool with no interval never appears in `maintenance_due`; one with an interval and no `last_maintained_at` appears immediately; one maintained recently doesn't; one maintained long enough ago does; marking done clears it from the list and updates the timestamp.
2. Live curl pass: set an interval, confirm dashboard shows it due (no prior maintenance), mark done, confirm it drops off, then verify it reappears once you fast-forward past the interval (test via directly setting `last_maintained_at` far in the past through a follow-up PATCH-equivalent, since there's no time-travel in a live check).
3. Browser pass: set an interval on a tool via the edit form, confirm it shows up on the Dashboard, mark it done from there, confirm it disappears.

---

## 5. Data Export / Backup

### Context
Export an organization's full data as a backup, independent of Docker volume backups — especially important for self-hosted deployments where the operator may not otherwise have a reliable off-box backup story.

### Backend changes
- New `GET /organizations/{id}/export` — builds a ZIP (stdlib `zipfile`, confirmed greenfield — no existing archive-bundling precedent anywhere in this app) containing:
  - `data.json`: every org-scoped row from every model (Shops, Toolboxes, Drawers, DrawerProfiles, Tools, all 5 profile types, Designs, InsertDesigns, DrawerLayouts+InsertPlacements), each serialized via its existing `*Read` Pydantic schema — reusing schemas that already exist, not inventing a new export-specific shape.
  - `files/`: every generated STL, walked via the same `{generated_files_dir}/{org_id}/{entity_id}/...` convention confirmed identical across `Design` (`outline_stl_path`/`text_stl_path`), `InsertDesign` (`stl_path`, both generated and uploaded sources), and `DrawerLayout` (`layout_json["plates"][i].stl_path`, which — unlike the other two — requires parsing the JSONB blob rather than querying a column, since plates aren't their own DB rows).
  - Missing files on disk are skipped gracefully (not a hard failure for the whole export) — matches this app's established defensive `.is_file()`-check-before-serving pattern used everywhere else files are served.
- Build to a `tempfile.NamedTemporaryFile`, return via `FileResponse` with a `BackgroundTasks`-scheduled cleanup delete after the response is sent (standard FastAPI pattern for "generate then stream then clean up").
- **No scheduling** — confirmed no cron/periodic-task mechanism exists anywhere in this app (Dramatiq here is on-demand only). This is a manual, click-to-export action; a self-hoster wanting scheduled backups can script `curl` against this endpoint plus their own system cron — worth saying so explicitly in the eventual user manual, not something this app needs to build internally.
- Synchronous, not a Dramatiq job — this is a rare, operator-initiated action, not a hot path, and realistic org sizes (dozens to low-hundreds of small STL files) don't warrant background-job complexity for this.

### Frontend changes
- `frontend/src/pages/settings/SettingsPage.tsx`: an "Export organization data" button, authenticated blob fetch (`responseType: "blob"`, same pattern as every other file download in this app) + `triggerBlobDownload`.

### Scope limits
- No import/restore path — export only. Restore-from-backup is a much bigger feature (conflict resolution, ID collisions across environments) and wasn't requested; flagged here explicitly so it isn't assumed to exist.
- No incremental/differential export — always a full snapshot.

### Verification
1. Backend test: export a real org with a few tools/designs/inserts, unzip the result, confirm `data.json` round-trips the expected row counts and confirms at least one real STL file is present and matches the on-disk original's bytes.
2. Live curl pass: real org with real generated bins/labels, download the export, unzip, spot-check a few files.
3. Browser pass: click Export in Settings, confirm a real zip downloads and opens.

---

## 6. Background Job Failure Notifications

### Context
Surface a visible notification when a background job (bin generation, plate STL export, label generation) fails, instead of requiring a manual status check on that specific record's page.

### Backend changes
- New `GET /organizations/{id}/failed-jobs` — the second cross-entity aggregation endpoint in this app (after the Dashboard). Confirmed via research that failure detection **cannot** be uniform across all job types: `Design` and `InsertDesign` both have a real `status` column (`WHERE status = 'failed'`, trivial query), but `generate_plate_stl` failures live inside `DrawerLayout.layout_json["plates"][i].status`, not a column — `DrawerLayout.status` itself has no `'failed'` value at all. The endpoint unions: a simple query each for failed `Design`/`InsertDesign` rows, plus an app-side walk of `DrawerLayout` rows checking each plate entry's `status`. Returns `[{kind: "label"|"insert"|"plate", id, name, error_message, failed_at}]`.

### Frontend changes
- `frontend/src/lib/jobFailures.ts` — copy of the `billing.ts` pub/sub shape exactly (confirmed via research this pattern has zero coupling to axios/HTTP status codes, it's a plain listener-`Set`, fully reusable for a poll-detected trigger instead of an interceptor-detected one): `onJobFailureDetected`/`handleJobFailureDetected`.
- A poll (mounted in `AppShell.tsx`, `setInterval` every 30s hitting `GET .../failed-jobs`), diffing returned IDs against a locally-tracked set of already-notified failures (in-memory, e.g. a `useRef<Set<string>>` — not persisted server-side) so the same failure doesn't re-toast on every poll tick.
- New `<JobFailureToast />`, mounted in `AppShell.tsx` alongside `<UpgradeDialog />`/`<CommandPalette />`, subscribing via `onJobFailureDetected`.

### Scope limits
- No persisted notification/read-state table — a dismissed toast is just gone until the next poll surfaces a genuinely new failure; there's no "notification inbox" to revisit later. If that turns out to be wanted, it's a real additive feature (a table, read/unread state), not built speculatively now.
- Client-side polling only — confirmed no server-side scheduler exists in this app to push failures proactively; 30s is a reasonable default poll interval, not something requiring server infrastructure.
- Covers the three generation-pipeline job types (label/bin/plate) — not a generic "any error in the app" notification system.

### Verification
1. Backend test: a failed `Design`, a failed `InsertDesign`, and a `DrawerLayout` with one failed plate among several all show up correctly in `/failed-jobs`; a layout with zero failed plates contributes nothing; tenant isolation (org A never sees org B's failures).
2. Live curl pass: deliberately trigger a real failure (e.g. an insert design generation with a magnet hole depth that violates `BinParameters.validate()`), confirm it appears in `/failed-jobs` with the real error message.
3. Browser pass: trigger a real failure, confirm the toast appears within one poll interval, confirm it doesn't re-appear on subsequent polls once already shown.
