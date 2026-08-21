# E2E Test Suite Audit Report

**Date:** 2026-03-24
**Scope:** 93 spec files + 3 future/, ~28,500 lines, 117 components, 69 hooks, 39 API route files
**Method:** 50 parallel audit agents analyzing every file against source components

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total spec files | 96 (93 active + 3 future/) |
| Total tests (approx) | ~550+ |
| Average grade | **C** (2.1/4.0) |
| Files graded A- | 1 (snoozed-view-detail) |
| Files graded B+ or above | 4 |
| Files graded D or F | 18 |
| Critical issues found | ~120 |
| High issues found | ~160 |
| Tests that can never fail | ~80+ (silent-pass guards) |
| `waitForTimeout` calls | 123+ (anti-pattern) |
| WebSocket events tested in e2e | 0 of ~40 |
| Components with zero e2e coverage | ~30+ |

---

## TOP 10 SYSTEMIC ISSUES

### 1. Silent-Pass Guards (CRITICAL — ~80 tests affected)

The most pervasive problem. Tests wrap assertions in `if (await element.isVisible()) { ... }` or `if (count > 0) { ... }` with no else clause. When the element is absent (broken feature, wrong selector), the test passes with zero assertions.

**Files affected:** account-manager, label-library, learning-dashboard, my-style, snippet-library, smart-suggestions, dnd-mode, comprehensive-navigation, comprehensive-inbox, email-list, search, bulk-operations, sidebar, settings, shortcuts-help, regression-20agents, regression-lessons, visual-audit, and 15+ more.

**Fix:** Replace all `if (await el.isVisible()) { expect... }` with `await expect(el).toBeVisible()` as a hard prerequisite assertion.

### 2. Wrong/Nonexistent Selectors (CRITICAL — ~40 tests)

Tests reference CSS classes, data-testid values, or aria-labels that don't exist in the source component:

| Selector | Used in | Reality |
|----------|---------|---------|
| `data-testid="nav-calendar"` | 3 specs | Does not exist |
| `data-testid="sidebar-toggle"` | sidebar.spec | Does not exist |
| `data-testid="settings-overlay"` | settings.spec | Does not exist |
| `.label-library-item` | label-library.spec | Class is `.label-library-default-card` |
| `.login-oauth-btn` | login.spec | Class is `.login-oauth-card` |
| `.pin-active-btn` | pin-and-del-hover.spec | Does not exist |
| `.email-pinned-header` | pin-and-del-hover.spec | Does not exist |
| `.settings-close-btn` | comprehensive-settings.spec | Class is `.settings-close` |
| `.pdd-signature-preview` | signature-preview.spec | Does not exist |
| `.snippet-item` | snippet-library.spec | Class is `.snippet-card` |
| `.draft-send-btn` | priority-features.spec | Class is `.send-pill` |
| `data-testid="email-item"` (for rows) | delete-to-trash.spec | Not on rows, only container |

### 3. Mac-Only Keyboard Shortcuts (HIGH — ~25 tests)

Tests use `Meta+,`, `Meta+N`, `Meta+K`, `Meta+/` exclusively. The dev environment is Windows 11. `Meta` is the Windows key, not Ctrl. These shortcuts never fire in the Playwright browser on Windows/Linux CI.

**Files affected:** settings.spec, shortcuts.spec, shortcuts-help.spec, command-palette.spec, label-library.spec, learning-dashboard.spec, comprehensive-navigation.spec, visual-audit.spec, and 10+ more.

**Fix:** Use `Control+` instead of `Meta+` or detect platform with `process.platform`.

### 4. Zero WebSocket E2E Coverage (CRITICAL)

The backend emits ~40 Socket.IO event types. The frontend listens to all of them via `useWebSocketSync`. **Not a single WebSocket event is tested in any e2e spec.** The entire real-time pipeline (streaming drafts, email archival notifications, sync status, critique progress, learning events) has zero integration coverage.

### 5. Vacuous Assertions (CRITICAL — ~30 tests)

Tests with assertions that can never fail:
- `expect(count >= 0).toBeTruthy()` — always true
- `expect(typeof value).toBe('boolean')` — always true
- `expect(true).toBeTruthy()` — always true
- `expect(x || true).toBeTruthy()` — always true
- `try { assert } catch { /* swallow */ }` — always passes

**Worst offenders:** sent-email-detail.spec (9+ vacuous assertions), email-list.spec (5), comprehensive-inbox.spec (3), email-flow-integration.spec (8 via try/catch).

### 6. CSS Class Selectors Instead of data-testid (HIGH — ~500+ usages)

The vast majority of selectors use CSS classes (`.swipeable-email-item`, `.email-detail-title`, `.draft-item`, `.toast`, `.settings-sidebar-item`, etc.) which break on any CSS refactor. Key components missing `data-testid`:
- Email list rows (SwipeableEmailItem)
- Settings modal overlay and close button
- Calendar nav button
- Sidebar toggle
- All marketplace components
- All cleanup/spam/trash banner buttons
- ConfirmationDialog

### 7. French/English i18n Mismatch (HIGH — ~20 tests)

Tests hardcode French aria-labels (`"Fermer"`, `"Paramètres"`, `"Palette de commandes"`) but the component uses English or i18n keys that may resolve differently. Some tests do the opposite — check English strings when the app renders French.

**Key mismatches:**
- `aria-label="Paramètres"` vs actual `"Settings"` (accessibility.spec)
- `'Palette de commandes'` vs actual `'Command palette'` (command-palette.spec)
- Slash command names: French (`/confirmer`, `/decliner`) vs actual English (`/confirm`, `/decline`)
- `button:has-text("Répondre")` vs actual `"Reply"` (reply-process.spec)

### 8. `waitForTimeout` Anti-Pattern (HIGH — 123+ occurrences)

Hardcoded sleeps (`page.waitForTimeout(500)`, `waitForTimeout(1000)`, etc.) instead of proper Playwright waits. Makes tests simultaneously slow AND flaky.

**Fix:** Replace with `await expect(locator).toBeVisible()`, `page.waitForResponse()`, or `page.waitForFunction()`.

### 9. Mock/API Response Shape Mismatches (HIGH — ~15 specs)

Mock responses don't match actual backend response shapes:
- `my-style.spec`: mocks wrong endpoint (`/api/style` vs `/api/learning/stats`)
- `learning-dashboard.spec`: mock fields (`total_drafts`, `avg_score`) don't match hook model
- `folder-loading-perf.spec`: uses wrong port (5051 vs 5050)
- `snippet-library.spec`: mock uses `title`/`body` vs actual `name`/`content`
- `contextual-chips-100.spec`: tests chips in ReplyComposer which never renders them (only PendingDraftDetail does)
- Multiple specs: `/api/init` returns empty emails while `/api/emails` has data — race condition

### 10. `future/` Directory Should Be Deleted (LOW)

All 3 files in `future/` are fully superseded by production counterparts. They use broken glob patterns (`**/api/emails/*`) that Vite intercepts, wrong selectors, and have no `setupBaseMocks` integration. Grade: D average.

---

## FILE-BY-FILE GRADES

### Grade A (0 files)
None

### Grade B+ (4 files)
| File | Tests | Notes |
|------|-------|-------|
| cleanup-drafts.spec | 8 | Strong stateful mocks, real assertions |
| autoreply-toggle.spec | 7 | Correct flow, minor i18n issues |
| close-buttons.spec | 8 | CSS audit useful, but synthetic DOM tests |
| newsletter-unsubscribe.spec | 4 | Solid bulk-delete and optimistic UI |

### Grade B- (12 files)
archives-folder, archive-flow, cleanup-trash, thread-collapsing, signature-fixes, performance-audit, pin-and-del-hover, settings-parameters, email-rendering-1000, followup-reminder, regenerate-empty-draft, comprehensive-reply

### Grade C+ (13 files)
cleanup-noise, calendar-asap-create, comprehensive-connection, contextual-chips-100, perf-sections-calendar, folder-tabs, email-inline-images, deep-focus, priority-features, spam-folder, oauth-callback, reminder-sync, regression-optimization

### Grade C (15 files)
accessibility, calendar, comprehensive-navigation, email-list, comprehensive-calendar, comprehensive-compose, email-flow-integration, inbox-freshness, new-message, folder-loading-perf, sent-folder, bulk-delete, sidebar, reply-send, delete-to-trash

### Grade C- (8 files)
comprehensive-inbox, login, reply-process, support-panel, email-list (future/), comprehensive-settings, settings, search

### Grade D (15 files)
| File | Tests | Key Issue |
|------|-------|-----------|
| account-manager.spec | 5 | All tests wrapped in if-visible guards |
| label-library.spec | 4 | Wrong component opened, nonexistent selectors |
| learning-dashboard.spec | 4 | Wrong mock shape, Meta+, on Windows |
| my-style.spec | 3 | Wrong API mocked, wrong open mechanism |
| dnd-mode.spec | 3 | Wrong localStorage key, nonexistent classes |
| error-states.spec | 4 | Vacuous assertions, ErrorBoundary untested |
| comprehensive-performance.spec | 11 | All thresholds doubled vs descriptions |
| bulk-operations.spec | 4 | Hollow stubs, no real bulk assertions |
| send-flow.spec | 7 | Uses page.evaluate(fetch) not UI, SendConfirmationModal untested |
| search.spec | 9 | Wrong mock format, conditional skips |
| sent-email-detail.spec | 18 | 9+ vacuous assertions, wrong selectors |
| reply-composer.spec | 11 | Empty inbox mock, composer never opens |
| slash-commands.spec | 24 | All French command names wrong (English in source) |
| snippet-library.spec | 6 | Wrong field names, nonexistent selector |
| signature-preview.spec | 3 | 2/3 tests unconditionally skip |

### Grade F (1 file)
| File | Tests | Key Issue |
|------|-------|-----------|
| smart-suggestions.spec | 3 | All tests self-skip, wrong status casing |

### Grade D- (1 file)
| File | Tests | Key Issue |
|------|-------|-----------|
| send-flow.spec | 7 | Tests bypass entire React app with fetch() |

---

## COVERAGE GAPS

### Components With Zero E2E Coverage (~30+)

| Component | Importance | Lines |
|-----------|-----------|-------|
| DeepWorkOverlay | HIGH | 200+ |
| DeepWorkPanel | HIGH | 300+ |
| DeepFocusCelebration | MEDIUM | 200+ |
| GuidedTour | MEDIUM | ~150 |
| TrainingPage | HIGH | ~300 |
| MonthlyRecapPage | MEDIUM | ~250 |
| MilestoneToast | LOW | ~50 |
| FirstDraftCelebration | LOW | ~100 |
| RecapBanner | LOW | ~80 |
| BeforeAfterComparison | LOW | ~100 |
| AccountApprovalCard | HIGH | ~200 |
| StyleFeedback | LOW | ~100 |
| SubscriptionsModal | MEDIUM | ~150 |
| DraftVersionHistory | MEDIUM | ~200 |
| DraftComparisonView | LOW | ~150 |
| ContextReferencePanel | LOW | ~100 |
| ContextTransparencyPanel | LOW | ~100 |
| KnowledgeSuggestionToast | LOW | ~50 |
| LimitReachedBanner | HIGH | ~100 |
| ReferralPanel | LOW | ~100 |
| ShareSnippetDialog | MEDIUM | ~150 |
| SendConfirmationModal (e2e only) | HIGH | ~200 |
| AgentDetailedView | MEDIUM | ~200 |
| AgentPipeline | MEDIUM | ~150 |
| AIProgressBar | MEDIUM | ~100 |
| WorkflowStatusIndicator | LOW | ~100 |
| LLMSettings | MEDIUM | ~200 |
| LLMWizardStep | MEDIUM | ~150 |
| ModeSelectionStep | MEDIUM | ~100 |
| Wizard | HIGH | ~300 |

### Critical User Flows Not Tested End-to-End

1. **Email → AI Draft → Review → Send** — No test exercises the complete pipeline
2. **Onboarding flow** — Zero tests for the wizard/setup flow
3. **Deep Work mode** — Timer, overlay, bypass all untested
4. **WebSocket real-time updates** — Zero coverage
5. **Send Confirmation Modal** — 3-second countdown, skip preference untested in browser
6. **OAuth flow (click Google/Outlook button → redirect → callback)** — Button click untested
7. **Account switching** — Data isolation between accounts untested
8. **Logout → re-login** — Zero tests
9. **Token expiry mid-session** — Zero tests
10. **Draft streaming (chunks → completion)** — Zero tests

### API Endpoints With Zero E2E Mock Coverage

Key unmocked endpoints found across specs:
- `POST /api/emails/compose` (send new email)
- `POST /api/emails/:id/generate` (AI draft generation)
- WebSocket namespace `/daemon` events
- `GET /api/calendar/freebusy`
- `PATCH /api/settings` (most toggle verifications skip body check)
- `GET /api/newsletters`
- `POST /api/support`
- All onboarding endpoints (`/api/onboarding/*`)
- All marketplace subscription endpoints

---

## ANTI-PATTERN STATISTICS

| Anti-Pattern | Count | Severity |
|-------------|-------|----------|
| `if (isVisible) { assert }` silent guards | ~80 tests | CRITICAL |
| `expect(count >= 0).toBeTruthy()` tautologies | ~30 | CRITICAL |
| `try { assert } catch { }` swallowed failures | ~15 | CRITICAL |
| `page.waitForTimeout(N)` hardcoded sleeps | 123+ | HIGH |
| `Meta+` (Mac-only) keyboard shortcuts | ~25 tests | HIGH |
| CSS class selectors (no data-testid) | ~500+ usages | HIGH |
| French text assertions on English source | ~20 tests | HIGH |
| `.first()` on ambiguous multi-selectors | ~60 | MEDIUM |
| `waitForLoadState('domcontentloaded')` (no-op in SPA) | ~30 | MEDIUM |
| `page.evaluate(fetch(...))` bypassing UI | ~15 tests | HIGH |
| Missing dual-origin mock (127.0.0.1 vs localhost) | ~10 specs | HIGH |

---

## API ENDPOINT COVERAGE (Agent 34)

| Category | Endpoints | Mocked/Tested | Coverage |
|----------|-----------|---------------|----------|
| Core email flow | ~20 | ~18 | 90% |
| Pending drafts | ~8 | ~7 | 87% |
| Auth/OAuth | ~8 | ~6 | 75% |
| Calendar | ~25 | ~10 | 40% |
| Settings/Accounts | ~15 | ~4 | 27% |
| Labels | ~18 | ~3 | 17% |
| Learning/Analytics | ~20 | ~2 (prefix) | 10% |
| Snippets | ~12 | ~1 (prefix) | 8% |
| **Entire subsystems at 0%** | | | |
| Fine-tuning | 17 | 0 | 0% |
| Mobile | 17 | 0 | 0% |
| Onboarding | 7 | 0 | 0% |
| Discord/Telegram | 14 | 0 | 0% |
| Push notifications | 7 | 0 | 0% |
| Webhooks | 7 | 0 | 0% |
| Admin | 4 | 0 | 0% |
| Realtime edit | 6 | 0 | 0% |
| Contact map | 6 | 0 | 0% |

**~165 of ~230 endpoints have zero e2e coverage.** The catch-all mock (`route.fulfill({})`) masks this by returning `{}` instead of 404.

---

## MOCK RESPONSE SHAPE MISMATCHES (Agent 37)

| Endpoint | Real Shape | Mock Shape | Severity |
|----------|-----------|------------|----------|
| `POST /emails/:id/process` | `{ task_id, status: "processing" }` 202 | `{ draft_id, status: "created" }` 200 | CRITICAL |
| `GET /api/learning/all` | `{ categories: [...] }` | Flat object, no `categories` key | HIGH |
| `GET /api/drafts` | `{ total, limit, offset, drafts }` | `{ drafts, pending_count }` | HIGH |
| `GET /api/emails` | `count, offset, has_more, filter, source` | Missing `offset, filter, source` | HIGH |
| `GET /api/init` | Includes `spam_count` | Missing `spam_count` | MEDIUM |
| `GET /api/settings` | 40+ keys | Only 6 keys mocked | MEDIUM |

---

## DUPLICATE/OVERLAPPING TESTS (Agent 42)

### Files to delete (100% redundant)
- `settings.spec.ts` — fully covered by `comprehensive-settings.spec.ts`
- `future/email-detail.spec.ts` — superseded by `email-detail.spec.ts`
- `future/email-compose.spec.ts` — superseded by `email-compose.spec.ts` + `new-message.spec.ts`
- `future/email-list.spec.ts` — superseded by `email-list.spec.ts`

### Major overlap clusters (consolidation needed)
1. **Compose modal** — 4 files: `email-compose`, `comprehensive-compose`, `new-message`, `future/email-compose`
2. **Email detail** — 3 files: `email-detail`, `comprehensive-inbox`, `future/email-detail`
3. **Performance** — 4 files: `comprehensive-performance`, `performance-audit`, `folder-loading-perf`, `perf-sections-calendar`
4. **Settings** — 3 files: `settings`, `comprehensive-settings`, `settings-parameters`
5. **Spam cleanup** — 3 files: `spam-folder`, `spam-trash-restore`, `cleanup-spam`
6. **Reply composer** — 2 files: `reply-composer`, `comprehensive-reply` (80% identical)
7. **Shortcuts** — 3 files: `shortcuts`, `shortcuts-help`, `comprehensive-navigation`

### Cross-file duplications
- "Open compose with N key" tested in **7 files**
- "Open settings with Meta+," tested in **4 files**
- "Email detail closes with Escape" tested in **5 files**
- Folder navigation tested in **8 files**
- Folder load performance tested in **3 files** (~12 duplicate assertions)

---

## RESPONSIVE/VIEWPORT TESTING (Agent 48)

**Coverage: ZERO.** Only 1 of 99 spec files calls `setViewportSize` (visual-audit, for a screenshot with no assertions).

| Breakpoint | CSS Rules Exist | Tests |
|------------|----------------|-------|
| 1920px (large desktop) | Yes | 0 |
| 1280px (default) | All tests | All |
| 1024px (small desktop) | Grid column changes | 0 |
| 768px (tablet) | Single-column, sidebar overlay | 0 |
| 480px (mobile) | Compact layout | 0 |
| Touch (`pointer: coarse`) | Swipe styles | 0 |

The `SwipeableEmailItem` component has never been swipe-tested. All 500+ references use `.click()` only.

---

## ERROR HANDLING GAPS (Agent 45)

| Scenario | Coverage |
|----------|----------|
| Network 500/connection refused | GOOD |
| Empty states (no data) | GOOD |
| Backend down mid-session | GOOD |
| Malformed API data (null fields) | PARTIAL |
| Unicode/emoji in email fields | PARTIAL |
| Rate limiting (429) | **NONE** |
| Concurrent operations (double-click) | **MINIMAL** |
| Token expiry mid-session | **NONE** |
| Browser storage limits (quota exceeded) | **NONE** |
| RTL text rendering | **NONE** |
| Large payloads (5MB body, 50+ CC) | **NONE** |

---

## USER FLOW COMPLETENESS (Agent 44)

| Flow | Status |
|------|--------|
| Email → AI Draft → Review → Send | PARTIAL (segments only, not chained) |
| Compose → Recipients → Write → Send | WELL COVERED |
| Search → Find → Open → Reply | PARTIAL (chain broken) |
| Login → Connect Account → First Sync | PARTIAL (onboarding wizard untested) |
| Settings → Change → Verify Effect | WELL COVERED |
| Snooze → Wait → Reappear | WELL COVERED |
| Archive/Delete → Restore | WELL COVERED |
| Deep Focus → Process → Complete | WELL COVERED (no session recap) |
| Calendar → Create Event → Verify | PARTIAL (manual create untested) |
| Multi-Account → Switch → Verify Data | **NOT COVERED** |

---

## SECURITY TESTING GAPS

| Area | Status |
|------|--------|
| XSS injection in email body | NOT in CI (only in future/) |
| CSRF protection | Zero tests |
| Token expiry / 401 handling | Zero tests |
| Logout flow | Zero tests |
| OAuth state mismatch (CSRF) | Zero tests |
| Cross-account data isolation | Zero tests |
| Protected route without auth | Only `/` tested |

---

## RECOMMENDATIONS (Priority Order)

### P0 — Critical (Do First)

1. **Remove all silent-pass guards** — Convert `if (isVisible) { expect }` to `await expect(el).toBeVisible()` across ~80 tests
2. **Fix nonexistent selectors** — Add missing `data-testid` to ~15 components (Settings, Calendar nav, Sidebar toggle, etc.)
3. **Fix Mac-only shortcuts** — Replace `Meta+` with `Control+` (or platform-detect) in ~25 tests
4. **Delete `future/` directory** — 3 files fully superseded by production specs
5. **Fix slash-commands.spec** — Replace all French command names with actual English names

### P1 — High (Do Next)

6. **Create WebSocket mock utility** — Build a `simulateWsEvent(page, eventName, payload)` helper and write tests for top 5 events: `draft_complete`, `email_archived`, `new_email`, `sync_complete`, `auth:token_expired`
7. **Remove vacuous assertions** — Replace all `expect(x >= 0)`, `expect(typeof x === 'boolean')`, swallowed catches
8. **Replace `waitForTimeout` with proper waits** — 123 occurrences across all files
9. **Fix mock response shapes** — my-style, learning-dashboard, snippet-library, contextual-chips, folder-loading-perf
10. **Add SendConfirmationModal e2e test** — The send safety gate has zero browser-level coverage

### P2 — Medium (Improve Quality)

11. **Standardize selector strategy** — Prefer `data-testid` > `getByRole` > CSS class. Add testids to 15+ components
12. **Fix i18n mismatches** — Pin locale to `fr` in Playwright config or use locale-agnostic selectors
13. **Add missing user flow tests** — Email→Draft→Send pipeline, Onboarding, OAuth button click
14. **Consolidate duplicate helpers** — `mockBothFn` copied 4x in marketplace specs, `navigateToCalendar` duplicated, `openNewMessage` duplicated
15. **Write XSS test in active suite** — Move from `future/` to production and expand

### P3 — Low (Polish)

16. **Add error boundary test** — Trigger a real React error, verify "Une erreur est survenue" + reload button
17. **Add responsive/viewport tests** — Zero coverage for different screen sizes
18. **Add bundle size budget test** — Verify lazy loading works
19. **Add memory leak detection** — Use `performance.memory` or CDP heap metrics
20. **Clean up `TO-FIX.md`** — Update with current status of each item

---

## APPENDIX: Test Count Per File

<details>
<summary>Click to expand full list</summary>

| File | Tests | Grade |
|------|-------|-------|
| accessibility.spec | 10 | C |
| account-manager.spec | 5 | D |
| archive-flow.spec | 7 | B |
| archives-folder.spec | 14 | B- |
| auto-archive-after-send.spec | 2 | C |
| autoreply-toggle.spec | 7 | B+ |
| bulk-delete.spec | 3 | C |
| bulk-operations.spec | 4 | D |
| calendar-asap-create.spec | 1 | C+ |
| calendar-conference-link.spec | 4 | D |
| calendar.spec | 7 | C |
| cleanup-drafts.spec | 8 | B+ |
| cleanup-noise.spec | 15 | C+ |
| cleanup-spam.spec | 15 | B- |
| cleanup-trash.spec | 19 | B |
| close-buttons.spec | 8 | B+ |
| command-palette.spec | 9 | C+ |
| comprehensive-calendar.spec | 10 | D |
| comprehensive-compose.spec | 17 | C |
| comprehensive-connection.spec | 9 | C+ |
| comprehensive-inbox.spec | 15 | C- |
| comprehensive-navigation.spec | 18 | C |
| comprehensive-performance.spec | 11 | D |
| comprehensive-reply.spec | 19 | B- |
| comprehensive-settings.spec | 9 | D |
| contextual-chips-100.spec | 100 | C+ |
| contextual-chips.spec | 23 | C |
| deep-focus.spec | 20 | C+ |
| delete-to-trash.spec | 5 | B- |
| dnd-mode.spec | 3 | D |
| draft-list.spec | ~10 | C |
| email-compose.spec | ~15 | C |
| email-detail.spec | ~12 | C |
| email-flow-integration.spec | 11 | C |
| email-inline-images.spec | 6 | C+ |
| email-list.spec | 22 | B- |
| email-rendering-1000.spec | 18 | C+ |
| error-states.spec | 4 | D+ |
| folder-loading-perf.spec | 10 | C |
| folder-tabs.spec | 7 | C+ |
| followup-reminder.spec | 11 | B- |
| inbox-freshness.spec | 4 | C |
| label-library.spec | 4 | D |
| learning-dashboard.spec | 4 | D |
| login.spec | 7 | C- |
| marketplace-account.spec | 9 | C+ |
| marketplace-faq.spec | 12 | C |
| marketplace-refund.spec | 13 | C- |
| my-style.spec | 3 | D |
| new-message-signature.spec | 6 | C |
| new-message.spec | 18 | C+ |
| newsletter-unsubscribe.spec | 4 | B |
| oauth-callback.spec | 7 | C+ |
| pending-draft-detail.spec | 14 | C |
| perf-sections-calendar.spec | 8 | C |
| performance-audit.spec | 7 | B |
| pin-and-del-hover.spec | 20 | B- |
| priority-features.spec | 21 | C+ |
| refine-text.spec | 7 | D+ |
| regenerate-empty-draft.spec | 13 | B- |
| regression-20agents.spec | ~28 | C |
| regression-lessons.spec | 16 | C+ |
| regression-optimization.spec | 13 | B- |
| reminder-sync.spec | 5 | C+ |
| reply-composer.spec | 11 | D+ |
| reply-process.spec | 3 | C- |
| reply-send.spec | 10 | C+ |
| resilience.spec | 15 | B- |
| scroll-unified.spec | 4 | D |
| search-all-folders.spec | 20 | C+ |
| search.spec | 9 | D |
| send-flow.spec | 7 | D- |
| sent-email-detail.spec | 18 | D |
| sent-folder.spec | 12 | C+ |
| settings-parameters.spec | ~65 | B- |
| settings.spec | 8 | C- |
| shortcuts-help.spec | 6 | C |
| shortcuts.spec | 5 | C- |
| sidebar.spec | 10 | C |
| signature-fixes.spec | 11 | B- |
| signature-preview.spec | 3 | D |
| slash-commands.spec | 24 | D |
| smart-suggestions.spec | 3 | F |
| snippet-library.spec | 6 | D |
| snooze-badges.spec | 12 | B |
| snooze-rappel-e2e.spec | 5 | B- |
| snoozed-view-detail.spec | 6 | A- |
| spam-folder.spec | 13 | C+ |
| spam-trash-restore.spec | 10 | D |
| support-panel.spec | 9 | C- |
| thread-collapsing.spec | 6 | B- |
| trash-folder.spec | 12 | B |
| visual-audit.spec | 19 | C+ |
| future/email-detail.spec | 20 | D |
| future/email-compose.spec | 22 | D+ |
| future/email-list.spec | 23 | C- |

</details>

---

---

## SELECTOR STABILITY (Agent 38)

| Category | Count | % | Risk |
|----------|-------|---|------|
| CSS class selectors | 1,339 | 64% | RISKY |
| data-testid selectors | 336 | 16% | GOOD |
| Text selectors | 350 | 17% | MODERATE |
| Role/aria selectors | 52 | 2.5% | GOOD |
| Bare tag selectors | 12 | 0.6% | BAD |

**Quick win:** `.swipeable-email-item` is used 185 times across 31 files. The component already has `data-testid="email-item"` — replace all 185 references with zero production code changes.

**Worst file:** `settings-parameters.spec.ts` — 114 CSS class selectors, 15 `nth()` calls with no filter.

---

## TEST INFRASTRUCTURE (Agent 41)

| Area | Status |
|------|--------|
| Shared fixture (`setupBaseMocks`) | 91/93 specs use it — excellent |
| Page Object Model (`AppPage`) | Only 17/93 specs use it — low adoption |
| Dead code files | 3 helper files never imported (`index.ts`, `test-utils.ts`, `api-helper.ts`) |
| Browser coverage | Chromium only — no Firefox/Safari |
| CI parallelism | 1 worker, no sharding — slow |
| CI job dependencies | None — e2e runs even if typecheck fails |
| Playwright browser caching | Not cached in CI |

---

## OVERALL SCORECARD (Agent 50)

**Last run: 547 tests — 508 passed, 35 failed, 4 skipped (92.9% pass rate)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Test Quantity | 7/10 | 1,209 test cases, good breadth, 8 components uncovered |
| Test Quality | 5/10 | 99 waitForTimeout, 38 test.skip, vacuous assertions |
| Coverage | 6/10 | Good email flows, ~165 API endpoints untested |
| Infrastructure | 7/10 | Strong setupBaseMocks, weak POM adoption, dead helpers |
| Maintenance | 6/10 | 7 duplicate clusters, 42 fixme/skip, no doc comments |
| **Overall** | **6.2/10** | |

### Top 35 Failures in Last Run

| Spec | Failures | Root Cause |
|------|----------|------------|
| new-message.spec | 7 | Selectors broken |
| account-manager.spec | 5 | 30s timeout |
| comprehensive-reply.spec | 4 | Send button not rendered |
| reply-composer.spec | 3 | Mode chevron broken |
| search.spec | 3 | Search bar selectors |
| signature-preview.spec | 3 | `.pdd-signature-preview` nonexistent |
| comprehensive-compose.spec | 2 | Footer buttons not found |
| settings.spec | 2 | Active state mismatch |
| Others | 6 | Various selector/timing issues |

### TO-FIX.md Status

| Item | Status |
|------|--------|
| LoginPage data-testid | STILL OPEN |
| ErrorBoundary data-testid | STILL OPEN |
| MonthlyRecapPage data-testid | STILL OPEN |
| waitForTimeout anti-pattern | WORSENED (4 files → 99 occurrences) |
| Soft assertions | Changed to test.skip (still masks failures) |
| Auth mocks | FIXED |
| Sidebar toggle crash | PARTIALLY FIXED (skip instead of fixme) |
| SupportIntentCards unused | FIXED (removed) |
| PendingDraftDetail mock flow | STILL OPEN (3 test.fixme) |

---

*Generated by 50 parallel audit agents analyzing source code + test files*
