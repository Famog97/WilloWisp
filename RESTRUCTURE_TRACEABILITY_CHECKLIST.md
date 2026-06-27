# WilloWisp — Method-by-Method Traceability Checklist

**Companion to:** [`RESTRUCTURE_MIGRATION.md`](RESTRUCTURE_MIGRATION.md) ·
**Destination map:** [`RESTRUCTURE_DESIGN.md`](RESTRUCTURE_DESIGN.md) §1.0b
**Date:** 2026-06-25

> Every significant class, method, and helper in the six legacy files, mapped to its **exact
> physical destination** in the Hexagonal tree (§1.0b). Check items off `[x]` as each unit is
> extracted and moved. Sizes are line counts (AST). Trivial 1–2-line accessors are bundled.
>
> **Per-method gate:** the unit is moved behind a shim, the relevant characterization/unit test
> stays green, and the core import-ban (B9) holds. **Tk-bound UI methods carry NO business
> logic** after the move — they call `WilloWispCoreAPI`.

**Destination roots:** `core/{ports,domain,services}` · `core/api.py` ·
`adapters/driven/{persistence,perception,protocol,input,recorder}` ·
`adapters/driving/{cli,ui_tkinter}` · `plugins/`.

**Legacy-file fates:** all six are **retired in M6** once empty (shims removed).

**Tracking protocol:** tick a function box here **first** (the moment its logic is relocated),
then — only once every box in a migration phase is `[x]` — tick that phase in
[`RESTRUCTURE_MIGRATION.md`](RESTRUCTURE_MIGRATION.md).

> **Status (2026-06-26): all boxes unticked — correct.** **M0 is complete** but moved **no
> code** (it is the safety net: characterization goldens, CI guards, empty skeleton, the B2
> baseline). Per-function relocation — and therefore the first ticks below — **begins at M1**
> (first up: `BaseProtocol` → `core/ports/protocol.py`).

---

## 1. `baru.py` (7,663 L) → split across core + adapters; **retired M6**

### 1.1 Module-level helpers
- [ ] `_load_plugins` (42) → `core/api.py` (composition / discovery wiring)
- [ ] `_wire_subscribers` (10) → `core/api.py` (event-subscriber wiring)
- [ ] `_load_template` (9) / `_save_template` (12) → `adapters/driven/persistence/` (template store)
- [ ] `initialize_tesseract` (6) → `adapters/driven/perception/tesseract_ocr.py`
- [x] `save_config` (7) → `core/services/config.py` (`ConfigProvider`) — **M2.2 DONE** (baru shim; `SEVERITY_MATRIX`/`APP_CONFIG` now backed by `core.services.config`; `SeverityColorClassifier` added for M2.4)
- [ ] `init_test_run_log` (17) → `core/services/run_coordinator.py` (`EvidencePathManager`)
- [ ] `_normalize` (3) → `core/services/report_service.py`
- [x] `_ocr_canon` (11) / `_ocr_contains` (20) / `_ocr_fuzzy_contains` (27) → `core/services/text_match.py` (`TextMatcher`) — **M2.4 DONE** (baru shim; tested by `test_ocr_match`)
- [ ] `_find_state_table_cols` (20) / `_extract_states` (17) → `core/services/import_service.py` (IO-list parsing) · [x] `_get_state_indices` (19) / `_get_expected_for_value` (20) / `build_expected` (29) → **M3.4 relocated** to `core/services/expected_state.py` (pure; imports `SEVERITY_MATRIX`; baru re-exports as shims). Cuts the engine's last `baru` import — `_run_point` now pulls expected-state + `FailureEvidenceCollector` from `core`, so `ProcedureRunner` is `baru`-free.
- [ ] `db_session` (13) / `_metadata_get_db` (47) / `_migrate_columns` (12) / `_metadata_file_hash` (9) → `adapters/driven/persistence/metadata_store.py`
- [ ] `_metadata_save_profile` (46) / `_metadata_list_profiles` (10) / `_metadata_load_profile` (27) / `_metadata_delete_profile` (8) → `adapters/driven/persistence/metadata_store.py`
- [ ] `detect_header_row` (23) / `auto_map_columns` (17) → `core/services/import_service.py`
- [ ] `ocr_analyze_image` (2) / `ocr_preprocess` (2) / `ocr_run` (2) → `adapters/driven/perception/tesseract_ocr.py`
- [ ] `detect_monitors` (13) / `get_physical_monitor_rects` (11) / `match_physical_rect` (3) → `adapters/driven/perception/local_grab.py` (screen-info)
- [ ] `generate_points` (18) → `core/services/run_coordinator.py` (grid/sequence point generation)
- [ ] `zone_has_points` (5) → `core/domain/zone.py`

### 1.2 Protocol layer
- [x] `BaseProtocol` (all 6 methods) → `core/ports/protocol.py` — **M1.4 DONE** (promoted to `ProtocolPort`; `baru` re-exports `BaseProtocol` via shim; `ModbusProtocol` still subclasses it)
- [x] `ModbusProtocol.__init__` / `_start_server_thread` / `_run_server` / `stop` / `_on_packet` / `_on_connect` / `_get_slave` / `_write_coil_or_reg` / `trigger_alarm` / `reset_alarm` → `adapters/driven/protocol/modbus.py` — **M3.4 relocated** (verbatim; pymodbus guarded; `baru` re-exports as shim)
- [x] `ProtocolManager.__init__` / `register_protocol` / `get_protocol` / `stop_all` → `adapters/driven/protocol/manager.py` — **M3.4 relocated** (imports `ModbusProtocol`; `baru` re-exports as shim)

### 1.3 Domain models
- [x] `VerifyResult.__init__` / `to_dict` → `core/domain/results.py` — **M2.1 DONE** (baru shim)
- [x] `Monitor.__init__` / `label` → `core/domain/scenario.py` — **M2.1 DONE** (baru shim)
- [x] `Scenario.__init__` / `to_dict` / `from_dict` → `core/domain/scenario.py` — **M2.1 DONE** (baru shim; `WORKFLOW_AVAILABLE` guard dropped — `ProcedureFlow` is always core-available)
- [x] `SuiteCard.__init__` / `from_card_cfg` / `from_direct` → `core/domain/scenario.py` — **M2.1 DONE** (baru shim)
- [x] `Zone` (`__init__`, `width/height/cx/cy/contains`, `to_dict`, `from_dict`) → `core/domain/zone.py` — **M2.1 DONE** (pure geometry, R-HEX-3; baru shim)

### 1.4 Verification (`ISCSVerifier`) → decompose (perception vs decision vs evidence)
> **M2.4 ✅ (relocation-first):** the **whole `ISCSVerifier` class is relocated** to
> `core/services/verifier.py` (rewired off baru globals: PIL via local import, OCR via
> `iscs_OCR`, text-match via `core.services.text_match`, severity via `core.services.config`;
> `UPGRADES_AVAILABLE` → anchor/sampler-presence). `baru` re-exports it as a shim;
> `test_characterization_verify` (now patching the new module) + GUI smoke pass. The fine
> perception/decision/evidence split (the sub-units below) is a deferred refinement.
- [x] `__init__` (9) → `core/services/verifier.py` — **M2.4 relocated**
- [~] `_get_color_name` (6) → `core/services/verifier.py` (`SeverityColorClassifier`)  — **relocated** (split deferred)
- [~] `_get_zone_bbox` (14) → `core/services/verifier.py` (`ZoneResolver`)  — **relocated** (split deferred)
- [~] `verify` (23) → **keep/kill** (legacy single-shot; superseded by policies) → delete after caller check  — **relocated** (split deferred)
- [~] `_grab_zone` (12) → **split** `adapters/driven/perception/local_grab.py` (grab) + `core/services/evidence_collector.py` (save)  — **relocated** (split deferred)
- [~] `_analyze_image` (2) / `_preprocess_for_ocr` (2) / `_ocr_image` (4) → `adapters/driven/perception/tesseract_ocr.py` (`OcrReader`/`OcrPreprocessor`)  — **relocated** (split deferred)
- [~] `_color_present` (28) → `core/services/verifier.py` (`ColorSampler`/`ColorComparator`)  — **relocated** (split deferred)
- [~] `_blink_color_present` (21) → `core/services/verifier.py` (`BlinkAnalyzer`)  — **relocated** (split deferred)
- [~] `verify_alarm_panel` (256) → **decompose** into `core/services/verifier.py`: `StatePoller` + `FrameSampleCoordinator` + `TimestampExtractor`/`ClockSyncEvaluator` + `AlarmPanel/NormalizationVerificationPolicy` + `EvidenceScreenshotWriter` (gated by M0.1)  — **relocated** (split deferred)
- [~] `verify_list` (59) → `core/services/verifier.py` (`ListVerificationPolicy`)  — **relocated** (split deferred)

### 1.5 Evidence
- [~] `FailureEvidenceCollector.collect` (220) → `core/services/evidence_collector.py` — **M2.6 relocated** (whole class moved verbatim, rewired off baru PIL globals; baru shim; per-artifact-collector split deferred)

### 1.6 Run engines (→ one canonical path; legacy collapses, removed M6)
- [ ] `SuiteRunner.__init__` / `_emit` / `stop` / `_sleep` / pause/resume/is_paused → `core/services/run_coordinator.py` (`SuiteExecutionThread` + `RunControl`)
- [ ] `SuiteRunner._on_event_card_started` / `_on_event_card_completed` → `core/services/run_coordinator.py` (`RecorderCoordinator`)
- [ ] `SuiteRunner._take_screenshot` (30) → **split** `adapters/driven/perception/local_grab.py` + `core/services/run_coordinator.py` (`EvidencePathManager`)
- [ ] `SuiteRunner.run` (167) → **decompose** `core/services/run_coordinator.py` (`SuiteExecutionThread`/`SuiteScheduler`/`PointRunCoordinator`) — gated by M0.1
- [ ] `SuiteRunner._run_scenario` (160) → collapse into the canonical scheduler (B2)
- [ ] `SuiteRunner._collect_failed_point_ids` (17) → `core/services/run_coordinator.py` (`RerunController`)
- [ ] `SuiteRunner._run_scenario_legacy_iscs` (232) → **REMOVE in M6** after B2 equivalence
- [ ] `ISCS_Engine.*` (run 318 + 10 helpers) → collapse into `core/services/run_coordinator.py`; **REMOVE legacy copy in M6** (B2)
- [ ] `ClickEngine.*` (run 63 + 6 helpers) → `core/services/run_coordinator.py` (grid/sequence run mode)

### 1.7 UI (Tkinter) → `adapters/driving/ui_tkinter/`; **no business logic after move**
- [ ] `App.__init__` / `_set_taskbar_icon` / `_build_ui` (136) / `_on_resize` / `_shake_window` / `destroy` → `adapters/driving/ui_tkinter/app_shell.py`
- [ ] `App` help/preview: `_build_help_content` / `_init_help_panel` / `_open_preview` / `_close_preview` / `_toggle_preview` / `_open_ocr_monitor` → `adapters/driving/ui_tkinter/views/diagnostics_view.py`
- [ ] `App` hotkeys: `_register_hotkeys` / `_unregister_hotkeys` / `_hk_run` / `_hk_stop` / `_hk_space` → `adapters/driving/ui_tkinter/views/hotkey_adapter.py` (driving)
- [ ] `App` import: `_load_excel` / `_excel_load_failed` / `_excel_file_loaded` (116) / `_open_metadata_browser` / `_load_profile_from_metadata` / `_notify_profile_listeners` → `adapters/driving/ui_tkinter/views/import_view.py` (logic → `core/services/import_service.py`)
- [ ] `App` monitors/zones: `_refresh_monitors` / `_on_screen_selected` / `_find_monitor_by_info` / `_capture_monitor_thumbnail` / `_draw_minimap` / `_open_overlay` / `_overlay_done` / `_save_zones` / `_load_zones` / `_update_overlay_btn` → `adapters/driving/ui_tkinter/views/` (zone/monitor views; data via facade)
- [ ] `App` mode/run: `_set_mode` / `_update_mode_buttons` / `_on_mode_change` / `_run_test` / `_stop_test` / `_test_finished` / `_toggle_pause` / `_toggle_suite` / `set_execution_state` (45) / `_cb_progress` / `_cb_paused` / `_cb_done` / `_on_auto_paused` → `adapters/driving/ui_tkinter/views/run_controls.py` (**intent-forward to facade only**; `ExecutionStateView`)
- [ ] `App._settings_dialog` (124) → `adapters/driving/ui_tkinter/views/settings_view.py` (read/write via `core/services/config.py`)
- [ ] `App._clear_workspace` (12) → calls `core/services/workspace.py` (`WorkspaceSession.reset`)
- [ ] `App._sync_open_card_config` (12) → `adapters/driving/ui_tkinter/views/card_config_view.py`
- [ ] `App._log` (7) → `adapters/driving/ui_tkinter/views/log_sink.py`
- [ ] `App` stats: `_refresh` / `_refresh_stats_only` / `_update_stats` → `adapters/driving/ui_tkinter/views/stats_view.py`
- [ ] `SuitePanel` view/controls (`__init__`/`_build`/`_build_card`/`_rebuild_cards`/`_select_scenario`/`_move`/`_remove`/`_rename_scenario`/`_clear_all`/scroll) → `adapters/driving/ui_tkinter/views/suite_panel.py`
- [ ] `SuitePanel` persistence (`_json_safe`/`_save_suite`/`_load_suite`) → `adapters/driven/persistence/suite_store.py`
- [ ] `SuitePanel` run/record/report (`_run_suite`/`_run_flow`/`_cb_*`/`_finish`/`_on_rerun_toggle`/`_toggle_recording`/`_start_recorder_for_card`/`_stop_recorder`/`_open_rec_settings`/`_open_report_picker`/`_open_flow_dialog`/`_edit_card_cfg`/`_add_current`/`_ask_name`) → `adapters/driving/ui_tkinter/views/suite_panel.py` (**facade calls only**)
- [ ] Overlays/dialogs → `adapters/driving/ui_tkinter/components/`:
      `CrosshairOverlay` · `HudOverlay` · `ConfirmDialog` · `OcrOverlay` · `IdentifyOverlay` ·
      `Tooltip` · `CoordinatePickOverlay` · `Toast` · `ScreenSelectorPanel` · `RecordingSettingsDialog`
- [ ] `OcrMonitorPanel` (13 methods) → `adapters/driving/ui_tkinter/views/ocr_monitor_view.py` (OCR via core perception)
- [ ] `OverlayWindow` (32 methods) → **split (R-HEX-3)**: drawing/interaction/toolbar (`_build_canvas`/`_draw_zone`/`_on_press`/`_on_drag`/`_on_release`/`_on_right_click`/`_hit_zone`/`_build_toolbar`/`_show_zone_type`/etc.) → `adapters/driving/ui_tkinter/components/zone_overlay.py`; `_canvas_to_abs`/`_abs_to_canvas` → `CanvasViewport` (adapter); zone ops + undo (`_save_zone_type`/`_delete_zone`/`_undo`/`_push_undo`/`_check_zone_size`/`_change_zone_type`) → `core/domain/zone.py` (`ZoneLayout`/`ZoneEditSession`); `_link_zone_to_anchor` → `core/services/` (anchor)
- [ ] `HelpInspectorPanel` / `MetadataBrowserDialog` / `SuiteCardConfigDialog` / `SheetSelectorDialog` / `ColumnMapperDialog` → `adapters/driving/ui_tkinter/views/` (data via facade; SQLite via metadata_store)

---

## 2. `iscs_workflow.py` (4,841 L) → split across core + UI; **retired M6**

### 2.1 Module-level helpers
- [x] `_resolve_proc_type` (8) → `core/domain/flow.py` — **M2.1 DONE** (workflow shim) · [ ] `_category_for` (8) / `_noop_log` (2) → (stay engine-side / flow.py later)
- [x] `register_flow_migrator` (3) / `_migrate_flow_dict` (25) + `FLOW_SCHEMA_VERSION`/`_FLOW_MIGRATORS` → `core/domain/flow.py` — **M2.1 DONE** (workflow shim) · [ ] `registry_step_coverage` (17) → `core/services/engine.py` (stays engine-side)
- [x] `_next_io_id` (4) / `_next_step_id` (4) → `core/domain/flow.py` — **M2.1 DONE** (workflow shim)
- [x] `auto_register_procedures` (205) → `core/services/import_service.py` — **M3.3 relocated** (workflow shim; gated by `test_workflow_autoregister` + golden). Decompose into `DefaultFlowBuilder` + per-step `*Rule`s (FR-21) deferred.
- [ ] `_dynamic_catalogue` (29) → `core/api.py` (capability catalogue for `list_step_types`)
- [ ] `_detect_monitors` (26) / `_monitor_index_for_point` (8) → `adapters/driven/perception/local_grab.py`
- [ ] `capture_region_overlay` (89) → `adapters/driving/ui_tkinter/components/region_capture.py`
- [ ] `open_procedure_flow_dialog` (3) → `adapters/driving/ui_tkinter/views/flow_editor.py`
- [ ] `build_runner_from_scenario` (40) → `core/services/run_coordinator.py`

### 2.2 Flow data model & enums
- [x] `ProcedureCategory` / `ProcedureStatus` / `ProcedureType` / `_DynamicProcType` → `core/domain/flow.py` — **M2.1 DONE** (workflow shim)
- [x] `Procedure.to_dict` / `from_dict` → `core/domain/flow.py` — **M2.1 DONE** (workflow shim)
- [x] `ProcedureResult` (`passed`/`failed`/`summary_line`) → `core/domain/results.py` — **M2.1 DONE** (workflow shim)
- [x] `ExecutionTrace` (`overall`/`total_duration_ms`/`_find`/`_status_prefix`/`flat_records`/`_collect_custom_checks`/`format_trace_log`) → `core/domain/results.py` — **M2.1 DONE** (workflow shim)
- [x] `IOGroup` (7 methods) → `core/domain/flow.py` — **M2.1 DONE** (workflow shim)
- [x] `ProcedureFlow` (21 methods) → `core/domain/flow.py` — **M2.1 DONE** (workflow shim)
- [ ] `ExecContext` / `_StandaloneCtx` → `core/services/run_coordinator.py` (per-point state, owned by `PointRunCoordinator`)

### 2.3 Engine (`ProcedureRunner`) → **M3.1 RELOCATED** to `core/services/engine.py` (whole class + capability bridge + `ExecContext`/`_StandaloneCtx`, behind `iscs_workflow` shims). Engine now imports **headlessly** — no tkinter/pyautogui (`tests/test_engine_headless.py`). God-method **decomposition deferred** (relocation-first); the `FlowRunCoordinator`/`PointExecutor`/`StepLifecycle` split below is the future quality pass.
- [x] `__init__` / `_emit` / `_sleep` / `_check_pause` → `core/services/engine.py` (relocated; decompose → `FlowRunCoordinator` + `RunControl` deferred)
- [x] `run_scenario` (88) / `run_standalone` (44) → `core/services/engine.py` (relocated; → `FlowRunCoordinator` deferred)
- [x] `_run_point` (112) → `core/services/engine.py` (relocated; **decompose** → `PointExecutor` deferred, gated by M0.1)
- [x] `_execute_procedure` (89) → `core/services/engine.py` (relocated; **split** → `StepLifecycle` + `StepDispatcher` deferred)
- [x] `_make_skip_result` (11) → `core/services/engine.py` (relocated; → `PointExecutor` deferred)
- [x] `_exec_trigger_alarm`/`_exec_reset_alarm`/`_exec_navigate_*`/`_exec_verify_*`/`_exec_delay`/`_exec_screenshot`/`_exec_click`/`_exec_right_click`/`_exec_hotkey`/`_exec_type_text` (the 19 `_exec_*`) → **M3.4 extracted** to `adapters/driven/input/legacy_executors.py` (NOT core — they carry `pyautogui`; quarantined as the R-EXT-1 safety net). Rebound `self`→`runner`; `LegacyCapabilityAdapter` + the dispatcher fallback resolve them there. This removes the only `pyautogui` from the engine, unblocking the `ProcedureRunner`→`core/services/engine.py` move (still pending the `baru` tendrils: `_get_state_indices`/`build_expected`).

### 2.4 UI dialogs → `adapters/driving/ui_tkinter/`
- [ ] `RegionPickerFrame` (10) → `adapters/driving/ui_tkinter/components/region_picker.py`
- [ ] `AddStepDialog` (10) → `adapters/driving/ui_tkinter/views/flow_editor.py`; **`_rebuild_params` (70) → `adapters/driving/ui_tkinter/renderer.py` (`SchemaFormRenderer`, R-EXT-1)**; `_pick_xy`/`_draw_bbox` → `components/`
- [ ] `ProcedureFlowDialog` (33) → `adapters/driving/ui_tkinter/views/flow_editor.py`; tree edits operate on a core `FlowEditModel` via facade; `_save_step_as_check_card`/`_open_assets`/`_open_check_gallery` → `views/check_authoring.py`
- [ ] `VerifyCustomWizard` (18) → `adapters/driving/ui_tkinter/views/verify_custom_wizard.py`
- [ ] `BindingEditorDialog` (5) / `AssetManagerDialog` (10) / `CheckGalleryDialog` (12) / `_TemplatePickerDialog` / `_AssetPickerDialog` → `adapters/driving/ui_tkinter/views/asset_views.py` (data via facade `assets()`)

---

## 3. `iscs_reports.py` (1,635 L) → `core/services/report_service.py` + `plugins/report_widgets/`; **retired M6**

> **M2.5 status:** the whole module is **relocated** to `core/services/report_service.py`
> (verbatim, `iscs_reports` shim). The internal **decomposition** of `normalize_results` and
> `_write_html_report` (the rewrites below) is a deferred refinement (M2.5 cont).
- [x] `_size_label` (10) → `core/services/report_service.py` — **M2.5 relocated**
- [~] `ReportManager.normalize_results` (213) → `core/services/report_service.py` — **relocated**; decomposition into `ResultNormalizer`/`ShapeRouter`/mappers deferred (contract golden-gated)
- [x] `ReportManager.generate_reports` (23) / `on_suite_completed` (31) → `core/services/report_service.py` — **M2.5 relocated** (EventBus subscriber)
- [x] `ReportManager._scan_evidence_files` (35) / `_build_file_entry` (14) / `_inject_evidence_manifest` (3) → `core/services/report_service.py` — **M2.5 relocated**
- [~] `ReportManager._write_html_report` (1,128) → `core/services/report_service.py` — **relocated**; decompose (B6) into `LegacyReportComposer` + `plugins/report_widgets/` deferred (golden-HTML-gated, M0.1)
- [x] `ReportManager._write_excel_report` (134) → `core/services/report_service.py` — **M2.5 relocated**

---

## 4. `iscs_assets.py` (1,133 L) → core/domain + persistence + plugins; **retired M6**

> **M2.3 ✅ (relocation-first):** the asset **entities** are in `core/domain/assets.py` (§4.2),
> and the rest of the module — `AssetManager` (§4.3), the module-level helpers (§4.1), and the
> binding executor/resolvers (§4.4) — is **relocated verbatim** to
> `adapters/driven/persistence/asset_store.py`; `iscs_assets` is a shim re-exporting the full
> surface (incl. `_BINDING_RESOLVERS`/`_APP_DIR`). The fine-grained split (per-entity repos ·
> `IdSequencer` · `ImageFileStore` · `BindingResolutionService` · resolvers→`plugins/`) is a
> deferred refinement. All §4.1/§4.3/§4.4 boxes below = **relocated** (split pending).

### 4.1 Module-level
- [ ] `set_app_dir` (4) / `_get_app_dir` (5) / `_now_iso` (3) → `adapters/driven/persistence/json_repos.py`
- [ ] `register_asset_migrator` (3) / `_migrate_assets_dict` (20) → `adapters/driven/persistence/json_repos.py` (`AssetPersistence`)
- [ ] `register_binding_resolver` (11) / `get_binding_resolver` (8) / `list_binding_resolvers` (3) → `core/ports/` (resolver registry; R-EXT-4)
- [ ] `get_manager` (3) → `core/api.py` (`assets()` accessor)

### 4.2 Entity value objects → `core/domain/assets.py`
- [x] `TextAsset` / `ImageAsset` / `Region` / `FlowTemplate` (to_dict/from_dict/matches/props) → `core/domain/assets.py` — **M2.3 DONE** (iscs_assets shim)
- [x] `BindingType` / `StepBinding` (to_dict/from_dict/text/image/hybrid) → `core/domain/assets.py` — **M2.3 DONE** (iscs_assets shim)

### 4.3 `AssetManager` → split into repositories / persistence / services
- [ ] `instance` (7) / `reset` (4) / `__init__` (12) / `__repr__` / `stats` (7) → `adapters/driven/persistence/json_repos.py` (`AssetLibrary` facade)
- [ ] `_json_path` (2) / `images_dir` (4) / `_load` (57) / `save` (19) → `adapters/driven/persistence/json_repos.py` (`AssetPersistence`)
- [ ] `_bump_counter` (7) / `_next_id` (3) → `adapters/driven/persistence/json_repos.py` (`IdSequencer`)
- [ ] text CRUD (`create_text_asset`/`update_text_asset`/`delete_text_asset`/`get_text_asset`/`list_text_assets`) → `adapters/driven/persistence/json_repos.py` (`TextAssetRepository`)
- [ ] image CRUD (`create_image_asset`/`create_image_asset_from_bytes`/`update_image_asset`/`delete_image_asset`/`get_image_asset`/`list_image_assets`) → **split** `adapters/driven/persistence/json_repos.py` (metadata) + `adapters/driven/persistence/image_store.py` (bytes); `get_image_path` → `image_store.py`
- [ ] region CRUD (`create_region`/`update_region`/`delete_region`/`get_region`/`list_regions`) → `adapters/driven/persistence/json_repos.py` (`RegionRepository`)
- [ ] template CRUD (`create_flow_template`/`update_flow_template`/`delete_flow_template`/`get_flow_template`/`list_flow_templates`) → `adapters/driven/persistence/json_repos.py` (`FlowTemplateRepository`)
- [ ] `search` (20) → `adapters/driven/persistence/json_repos.py` (`AssetSearch`)
- [ ] `resolve_binding` (47) → `core/services/verifier.py` (`BindingResolutionService`)

### 4.4 Binding execution & resolvers
- [ ] `BindingExecutor.__init__` / `execute` (40) / `_capture_region` (12) → `core/services/verifier.py` (binding execution; capture via `ScreenCapturePort`)
- [ ] `BindingResolver` (base) → `core/ports/` (resolver interface)
- [ ] `TextBindingResolver` / `ImageBindingResolver` / `HybridBindingResolver` (`resolve`) → `plugins/binding_resolvers/` (R-EXT-4 — already registered)

---

## 5. `iscs_OCR.py` (170 L) → `adapters/driven/perception/tesseract_ocr.py`; **retired M6**

- [ ] `initialize` (28) → `adapters/driven/perception/tesseract_ocr.py` (`OcrPort` init; **fixed `shutil.which`**)
- [ ] `analyze_image` (42) → `adapters/driven/perception/tesseract_ocr.py` (`OcrPreprocessor` analysis)
- [ ] `preprocess` (21) → `adapters/driven/perception/tesseract_ocr.py` (`OcrPreprocessor`)
- [ ] `run` (17) / `run_digits` (22) → `adapters/driven/perception/tesseract_ocr.py` (`OcrReader`)

---

## 6. `iscs_recorder.py` (479 L) → `adapters/driven/recorder/recorder.py`; **retired M6**

- [ ] `_sanitise` (3) / `_estimate_size_gb` (9) / `check_disk_space` (11) / `_get_font` (13) / `pre_flight_check` (35) → `adapters/driven/recorder/recorder.py`
- [ ] `RecorderSettings.to_dict` / `from_dict` → `adapters/driven/recorder/recorder.py`
- [ ] `Recorder` (`__init__`/`start`/`stop`/`update_point`/`is_running`/`_loop`/`_output_size`/`_open_new_segment`/`_close_writer`/`_segment_path`/`_screen_size`/`_grab_frame`/`_composite_overlay`) → `adapters/driven/recorder/recorder.py` (driven adapter; screen access via `ScreenCapturePort`)

---

## Completion summary (fill in as you go)

| Legacy file | Units | Moved | Remaining | Retired? |
|---|---:|---:|---:|:--:|
| `baru.py` | ~150 methods / 30 classes | BaseProtocol(M1.4); Zone/Monitor/Scenario/SuiteCard/VerifyResult(M2.1); config+severity(M2.2); text-match(M2.4); **ISCSVerifier**(M2.4); → core |  | [ ] |
| `iscs_workflow.py` | ~120 methods / 20 classes | flow model: enums + `_DynamicProcType`/`_resolve_proc_type` + `Procedure`/`IOGroup`/`ProcedureFlow`/`ProcedureResult`/`ExecutionTrace` + counters/schema (M2.1) |  | [ ] |
| `iscs_reports.py` | 8 methods | whole module relocated to core/services/report_service.py (M2.5); iscs_reports is a shim |  | [ ] |
| `iscs_assets.py` | ~60 methods / 11 classes | entities → core/domain/assets.py; rest (AssetManager/helpers/binding executor+resolvers) relocated to adapters/driven/persistence/asset_store.py; iscs_assets is a shim (M2.3) |  | [ ] |
| `iscs_OCR.py` | 5 functions | 0 |  | [ ] |
| `iscs_recorder.py` | ~18 methods / 2 classes | 0 |  | [ ] |

**Done when:** every box above is `[x]`, all six legacy files are deleted (M6.3), and the core
import-ban + acyclic checks pass on the whole tree (M6.4).
