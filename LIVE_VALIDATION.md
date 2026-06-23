# Live Validation — run at the SCADA workstation

The migration so far (Phases 0/1, P2.2, P2.3-emit, P6.1/P6.1b, discovery) is
**additive / behavior-neutral** and backed by 133 offline tests. But the live
capture + Modbus path can't be tested offline. This checklist validates the real
run. Do **Phase A first** — it confirms nothing regressed before we change anything
further.

---

## Phase A — Confirm current code still runs a suite correctly

> Goal: prove the additive changes (registry dispatch, event emission, schema
> versioning) didn't change real behavior.

1. **Launch the app**
   ```
   python baru.py
   ```
   ✅ Expect: the window opens normally (same as before).

2. **Run a small real suite** — pick 2–5 IO points, draw zones as usual, run.

3. **Watch for these — all should behave exactly as before our changes:**
   - [ ] Each point **triggers** the alarm (Modbus write happens)
   - [ ] Alarm panel **verifies** (OCR + colour) → PASS/FAIL as expected
   - [ ] Point **resets / normalizes**
   - [ ] Screenshots saved under `test_logs/<suite>/loop_0001/...`
   - [ ] **`Suite_Report.html` generates** at the suite root
   - [ ] **Excel workbook generates**
   - [ ] Rerun-on-failure (if enabled) still works
   - [ ] Recording (if enabled) still starts/stops per card

4. **If anything is wrong / different:** capture the console log + the failing
   point, and tell Claude. To revert instantly to pre-change state:
   ```
   git stash                 # or: git checkout -- baru.py iscs_workflow.py iscs_assets.py
   ```

✅ **If Phase A passes, the whole additive migration is validated live.** Commit it
as a known-good checkpoint, then proceed to Phase B.

---

## Phase B — Run-required changes (one at a time, each validated by a real run)

Each item below is: **Claude writes it → you run a suite → you confirm → commit.**
Order is chosen so the smallest, safest cutover proves the pattern first.

1. **B1 — Auto-run discovery + port `DELAY` to a plugin.** ✅ CODE DONE — validate now.
   `plugins/utilities/delay.py` is a real `DelayCapability`; `baru._load_plugins()` discovers it at
   startup and it overrides the legacy `delay` adapter by key.
   **Validate at the rig:**
   - [ ] Launch `python baru.py`. Console shows: `INFO: loaded plugin(s) from plugins/utilities: ['delay']`
   - [ ] Add/keep a flow with a **Delay** step (e.g. `delay_sec = 3`), run a suite.
   - [ ] The delay still waits the configured time, and **Stop** still interrupts it mid-wait.
   - [ ] Suite completes + report generates exactly as before.
   - If anything is off: `git checkout -- baru.py` and delete `plugins/utilities/delay.py` to revert
     (the legacy `_exec_delay` path resumes automatically), then tell Claude.

2. **B2 — Report as an event subscriber (P2.3 cutover).** ✅ CODE DONE — validate now.
   `SuiteRunner` now emits `SuiteCompleted`; `ReportManager.on_suite_completed` (subscribed at startup)
   generates the report. A safety net falls back to the direct call if no subscriber handled it.
   **Validate at the rig:**
   - [ ] At launch, console shows: `INFO: report subsystem subscribed to SuiteCompleted.`
   - [ ] Run a suite. At the end the UI log still shows
         `✅ Consolidated Suite Report generated successfully inside: <suite>`
   - [ ] **`Suite_Report.html` and the Excel workbook are present** in the suite folder, content as before
   - [ ] Exactly **one** report is generated (not two — the safety net must not double-fire)
   - If the report is missing or doubled: `git checkout -- baru.py iscs_reports.py iscs_core/events.py`
     to revert, and tell Claude.

3. **B3 — Recorder as an event subscriber (P2.3 cutover).** ✅ CODE DONE — validate now.
   Recorder start/stop is driven by `CardStarted`/`CardCompleted`; handlers set `_active_rec` so
   per-point overlay updates still work. Falls back to inline start/stop if unhandled.
   **Validate at the rig — enable Recording on a card, then run:**
   - [ ] An **MP4 records per card** (one file per card/loop, as before)
   - [ ] The burned-in **overlay still updates per point** (timestamp + point identifier change)
   - [ ] Recording **stops cleanly** at card end (file is playable, not truncated)
   - [ ] Exactly **one** recording per card (not doubled)
   - [ ] Multi-card / looped suite: each card records correctly (no leaked/stale recorder)
   - If anything is off: `git checkout -- baru.py iscs_core/events.py` to revert, then tell Claude.

4. **B4 — DI container wiring (P2.1).**
   Resolve `ProtocolManager` / verifier / runner through `iscs_core.Container`.
   *Validate:* suite still connects Modbus + runs.

5. **B5 — Port the verification capabilities (Phase 3 / P3.2).**
   Move `_exec_verify_*` into `plugins/verifications/` one at a time. Orchestration moves to the
   capability; OCR/colour stays in `ISCSVerifier` behind a `VerificationBackend`.
   - [x] **verify_alarm_panel** — CODE DONE, validate now. **Validate at the rig:**
     - [ ] At launch, console shows `INFO: loaded plugin(s) from plugins/verifications: ['verify_alarm_panel']`
     - [ ] Run a suite — the alarm-panel verify produces the **same PASS/FAIL** as before per point
     - [ ] Failure screenshots + per-check details still appear in `Suite_Report.html` (unchanged)
     - [ ] Severity/colour/datetime sub-checks behave as before
     - Revert if off: delete `plugins/verifications/verify_alarm_panel.py` → legacy path resumes.
   - [x] **verify_normalize** — CODE DONE, validate now: run a suite and confirm the **normalize/reset
         check** still PASS/FAILs the same, and the report's **Normalize column** still populates
         (step names are re-tagged alarm_panel/→normalize/). Revert: delete
         `plugins/verifications/verify_normalize.py`.
   - [x] **alarm_list / event_list / equipment_page / alarm_panel_custom / custom** — CODE DONE.
         Validate on a suite that exercises those zones/nav (and a custom-asset step if you use one):
         each list/equipment/custom check should PASS/FAIL the same and populate its report column
         (alarm_list/event_list "trigger/" tags, "equipment/" prefix, custom-asset Expected/Actual card).
         Revert any one by deleting its file in `plugins/verifications/`.

6. **B6 — Port input/navigation/screenshot actions (Phase 3 / P3.1).** ✅ CODE DONE — validate now.
   `plugins/actions/` (click, right_click, hotkey, type_text, navigate_home/alarm_list/event_list/
   equipment_page) + `plugins/utilities/screenshot.py`. **trigger_alarm/reset_alarm stay legacy.**
   - [ ] At launch, console lists `plugins/actions: ['example_action', 'input', 'navigate']`
   - [ ] A flow using **Navigate to Alarm/Event List** or **Equipment Page** still navigates correctly
   - [ ] **Screenshot** step still saves an image; **Click/Hotkey/Type** steps behave as before
   - [ ] Trigger/Reset (still legacy) unaffected — alarms still fire/clear
   - Revert any one by deleting its file in `plugins/actions/` (or `plugins/utilities/screenshot.py`).

7. **B7 — Arbitrary plugin step types (P6.3 enum decoupling).** ✅ CODE DONE — validate now.
   `Procedure` no longer needs a `ProcedureType` enum entry; plugin keys become a `_DynamicProcType`.
   The `example_action` plugin is now `addable=True` to demonstrate it.
   **Validate at the rig:**
   - [ ] Open a card's Flow editor (⚡) → **"Example No-Op"** now appears in the Step Type dropdown
   - [ ] Add it (set a `message`), **save** the card, reopen the editor → the step is still there
   - [ ] Run the suite → it executes (log shows `example_noop ran (message=...)`), step PASSes
   - [ ] **Existing flows still load and run** exactly as before (regression check)
   - To hide the demo from the palette later: set `addable=False` in `plugins/actions/example_action.py`
     (or delete the file). Real new step types: drop a plugin with `addable=True` — no enum edit needed.

8. **B8 — Report template UI picker (Phase 5).** ✅ CODE DONE — validate now.
   A **📊 button** in the Suite panel (next to 💾/📂) opens a "Generate Report As…" dialog.
   **Validate at the rig:**
   - [ ] Run a suite (so `suite_results.json` is written in the suite folder)
   - [ ] Click **📊** → dialog lists Management / Engineering / Audit / Results JSON
   - [ ] Pick one → **Generate & Open** → the report is written in the suite folder and opens
   - [ ] Try each template; the legacy `Suite_Report.html` is still produced as before (unchanged)
   - [ ] With no run yet, 📊 lets you browse for a `suite_results.json` (or says to run a suite first)

> After each B-step: run a suite, confirm the checklist item, and commit. If a step
> misbehaves, revert that step (`git checkout -- <files>`) and report — nothing else
> is affected because they're done one at a time.
