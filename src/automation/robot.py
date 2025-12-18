from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
import re
import time
from typing import Dict, List, Mapping, Optional, Union

from playwright.sync_api import Browser, Frame, Locator, Page, Playwright, TimeoutError, sync_playwright

from src.config import PlaywrightSettings, settings

logger = logging.getLogger(__name__)


Scope = Union[Page, Frame]


class MetrcRobot:
    """Encapsulates the Playwright automation that extracts table rows from METRC."""

    COLUMN_MAP: Mapping[str, str] = {
        "Tag": "Label",
        "Src H's": "SourceHarvestNames",
        "Src Pkg's": "SourcePackageLabels",
        "Src Pj's": "SourceProcessingJobNames",
        "Location": "LocationName",
        "Sublocation": "SublocationName",
        "Item": "Item.Name",
        "Category": "Item.ProductCategoryName",
        "Item Strain": "Item.StrainName",
        "Quantity": "Quantity",
        "UoM": "UnitOfMeasureAbbreviation",
        "P.B. No.": "ProductionBatchNumber",
        "LT Status": "LabTestingStateName",
        "A.H.": "IsOnHold",
        "Date": "PackagedDate",
        "Rcv'd": "ReceivedDateTime",
        "L.T.E.": "LabTestResultExpirationDateTime",
    }

    FILTER_TERM = "pro"

    def __init__(self, config: PlaywrightSettings, date_range_days: int = 30) -> None:
        self.config = config
        self._grid_scope: Optional[Scope] = None
        self.date_range_days = max(1, date_range_days)
        self.max_tag_filter_retries = 3

    def fetch_table_rows(self) -> List[Dict[str, str]]:
        """Main entrypoint for the robot."""
        self._grid_scope = None
        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright)
            page = browser.new_page()
            try:
                self._open_base_url(page)
                self._login_if_needed(page)
                self._navigate_to_packages(page)
                self._dismiss_stonly_widget(page)
                self._apply_filters(page)
                rows = self._extract_table_rows(page)
                filtered = self._filter_rows_by_date(rows)
                logger.info(
                    "Date validation (last %d days): kept %d of %d rows",
                    self.date_range_days,
                    len(filtered),
                    len(rows),
                )
                if len(filtered) < len(rows):
                    logger.warning("Discarded %d rows outside date range.", len(rows) - len(filtered))
                filtered_testing = [
                    row for row in filtered if (row.get("LT Status") or "").strip() == "TestingInProgress"
                ]
                logger.info(
                    "TestingInProgress filter: kept %d of %d rows after date check.",
                    len(filtered_testing),
                    len(filtered),
                )
                return filtered_testing
            finally:
                browser.close()

    def _launch_browser(self, playwright: Playwright) -> Browser:
        logger.info("Launching Chromium (headless=%s)", self.config.headless)
        return playwright.chromium.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
        )

    def _open_base_url(self, page: Page) -> None:
        logger.debug("Opening %s", self.config.base_url)
        page.goto(self.config.base_url, wait_until="domcontentloaded")

    def _login_if_needed(self, page: Page) -> None:
        login_button = page.locator("button.metrc-btn.metrc-btn-confirm", has_text=re.compile(r"\bLog in\b", re.I))
        if login_button.count() == 0:
            logger.info("Session already authenticated, skipping login.")
            return

        logger.info("Logging into METRC portal.")
        username_field = self._first_existing_locator(
            page,
            [
                "input[name='userName']",
                "input[name='username']",
                "input#UserName",
                "input[id='username']",
                "input[type='text']",
            ],
        )
        password_field = self._first_existing_locator(
            page,
            [
                "input[name='password']",
                "input#Password",
                "input[id='password']",
                "input[type='password']",
            ],
        )
        if username_field is None or password_field is None:
            raise RuntimeError("Unable to locate username/password fields on login page.")

        username_field.fill(self.config.username, timeout=5_000)
        password_field.fill(self.config.password, timeout=5_000)

        with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
            login_button.first.click()

        page.wait_for_load_state("networkidle", timeout=30_000)
        logger.info("Login completed.")
        page.goto(self.config.base_url, wait_until="domcontentloaded")

    def _navigate_to_packages(self, page: Page) -> None:
        try:
            page.wait_for_url("**/packages*", timeout=20_000)
        except TimeoutError:
            logger.warning("URL didn't update to packages explicitly; continuing with manual waits.")

        tab_selector = "li[data-grid-selector='#active-grid'] span.k-link"
        try:
            page.wait_for_selector(tab_selector, timeout=20_000)
            active_tab = page.locator(tab_selector).first
            parent_li = active_tab.locator("xpath=ancestor::li[1]")
            if "k-state-active" not in (parent_li.get_attribute("class") or ""):
                active_tab.click()
        except TimeoutError:
            logger.info("Active tab not found; proceeding without explicit click.")

        self._wait_for_grid_ready(page)

    def _apply_filters(self, page: Page) -> None:
        self._dismiss_csv_templates_popup(page)
        self._dismiss_stonly_widget(page)
        self._dismiss_system_alerts(page)
        self._apply_status_filter(page)
        self._dismiss_stonly_widget(page)
        # Date filtering is now handled internally on extracted rows.

    def _apply_status_filter(self, page: Page) -> None:
        logger.info("Applying Lab Test Status filter (term '%s').", self.FILTER_TERM)
        scope = self._ensure_grid_scope(page)
        column_header = scope.locator(
            "#active-grid thead.k-grid-header th[data-field='LabTestingStateName']"
        ).first
        column_header.wait_for(state="visible", timeout=10_000)

        filter_menu = self._open_filter_popup(
            page,
            column_header,
            input_selector="input[title='Filter Criteria']",
            tab_presses=2,
            allow_keyboard=True,
        )
        filter_input = filter_menu.locator("input[title='Filter Criteria']").first
        filter_input.scroll_into_view_if_needed()
        filter_input.fill(self.FILTER_TERM)
        self._click_filter_button(page, filter_menu)
        self._wait_for_grid_ready(page)
        self._log_row_count(page, context="after status filter")

    def _apply_date_filter(self, page: Page) -> None:
        logger.info(
            "Applying Date filter for the last %d days (UTC).",
            self.date_range_days,
        )
        scope = self._ensure_grid_scope(page)
        column_header = scope.locator(
            "#active-grid thead.k-grid-header th[data-field='PackagedDate']"
        ).first
        column_header.wait_for(state="visible", timeout=10_000)

        filter_menu = self._open_filter_popup(
            page,
            column_header,
            input_selector="input[data-role='datepicker']",
            tab_presses=0,
            allow_keyboard=True,
        )

        start_date, end_date = self._get_date_range_strings()
        self._set_date_filter_values(filter_menu, start_date, end_date)

        self._click_filter_button(page, filter_menu)
        self._wait_for_grid_ready(page)
        self._log_row_count(page, context="after date filter")

    def _open_filter_popup(
        self,
        page: Page,
        column_header: Locator,
        *,
        input_selector: str,
        tab_presses: int,
        allow_keyboard: bool,
    ) -> Locator:
        menu_button = column_header.locator("a.k-header-column-menu").first
        for attempt in range(6):
            self._dismiss_csv_templates_popup(page)
            self._dismiss_csv_templates_popup(page)
            self._dismiss_stonly_widget(page)
            self._dismiss_system_alerts(page)
            try:
                menu_button.scroll_into_view_if_needed(timeout=2_000)
            except Exception:
                logger.debug("Scroll into view failed for column menu; continuing.")
            try:
                menu_button.click(timeout=2_000, force=True)
            except Exception:
                logger.warning("Standard click on column menu failed; retrying with JS.")
                handle = menu_button.element_handle()
                if handle is not None:
                    page.evaluate("el => el.click()", handle)
            page.wait_for_timeout(400)
            activated = False
            if allow_keyboard:
                activated = self._select_filter_via_keyboard(
                    page,
                    target_selector=f"div.k-animation-container {input_selector}",
                    tab_presses=tab_presses,
                )
            if not activated:
                activated = self._click_filter_option_via_js(page)
            if activated:
                popup_container = page.locator("div.k-animation-container:visible")
                popup = popup_container.filter(has=page.locator(input_selector))
                if popup.count():
                    target = popup.first
                    target.wait_for(state="visible", timeout=5_000)
                    return target
            page.wait_for_timeout(700)
        raise TimeoutError("Unable to activate Filter option after multiple attempts.")

    def _click_filter_button(self, page: Page, filter_menu: Locator) -> None:
        filter_button = filter_menu.locator(
            "button.k-button.k-primary:visible", has_text=re.compile(r"\bFilter\b", re.I)
        ).first
        try:
            filter_button.wait_for(state="visible", timeout=5_000)
            filter_button.click()
        except TimeoutError:
            logger.warning("Standard click on Filter button failed; retrying with JS.")
            popup_handle = filter_menu.element_handle(timeout=5_000)
            if popup_handle is None:
                raise
            page.evaluate(
                """
                popup => {
                    const btn = popup.querySelector('button.k-button.k-primary');
                    if (btn) { btn.click(); }
                }
                """,
                popup_handle,
            )
        self._wait_for_network_idle(page)

    def _set_date_filter_values(self, filter_menu: Locator, start_date: str, end_date: str) -> None:
        # Prefer selecting operators (>=, <=) via the dropdowns if present.
        operators = filter_menu.locator("select[data-role='dropdownlist']")
        if operators.count() >= 2:
            self._select_dropdown_option(operators.nth(0), ["gte", "after", "greater"])
            self._select_dropdown_option(operators.nth(1), ["lte", "before", "less"])

        date_inputs = filter_menu.locator("input[data-role='datepicker']")
        if date_inputs.count() < 2:
            raise TimeoutError("Date inputs not found inside filter menu.")

        start_input = date_inputs.nth(0)
        end_input = date_inputs.nth(1)
        start_input.scroll_into_view_if_needed()
        logger.debug("Setting start date to %s", start_date)
        start_input.fill(start_date)
        end_input.scroll_into_view_if_needed()
        logger.debug("Setting end date to %s", end_date)
        end_input.fill(end_date)
        logger.info(
            "Date inputs filled: start=%s, end=%s",
            start_input.input_value(),
            end_input.input_value(),
        )

    def _select_dropdown_option(self, select_locator: Locator, candidates: List[str]) -> None:
        # First try the value attribute; then fallback to matching by label text via evaluation.
        for candidate in candidates:
            try:
                select_locator.select_option(value=candidate, timeout=2_000)
                return
            except Exception:
                continue
        handle = select_locator.element_handle()
        if handle is None:
            return
        handle.evaluate(
            """
            (select, labels) => {
                const lower = labels.map(l => l.toLowerCase());
                const opts = Array.from(select.options);
                const match = opts.find(opt => {
                    const text = (opt.label || opt.textContent || '').toLowerCase();
                    return lower.some(label => text.includes(label));
                });
                if (match) {
                    select.value = match.value;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
            """,
            candidates,
        )

    def _wait_for_network_idle(self, page: Page, timeout_ms: int = 30_000) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except TimeoutError:
            logger.warning("Network idle not reached within %d ms; continuing.", timeout_ms)

    def _filter_rows_by_date(self, rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Keep only rows whose 'Date' is within [today - date_range_days, today] inclusive."""
        if not rows:
            return rows
        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=self.date_range_days)
        kept: List[Dict[str, str]] = []
        for row in rows:
            raw_date = row.get("Date")
            parsed = self._parse_row_date(raw_date)
            if parsed is None:
                logger.debug("Skipping row with unparsable Date: %s", raw_date)
                continue
            if start_date <= parsed <= today:
                kept.append(row)
            else:
                logger.debug("Dropping row with Date %s outside range %s - %s", parsed, start_date, today)
        return kept

    def _parse_row_date(self, value: object) -> Optional[datetime.date]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.split()[0]  # drop time if present
        try:
            return datetime.strptime(text, "%m/%d/%Y").date()
        except ValueError:
            return None

    # --- Secondary routine: verify and update statuses by Tag ---

    def verify_status_by_tag(self, records: List[Mapping[str, object]]) -> List[Dict[str, object]]:
        """
        For each record, apply a Tag equals filter, fetch LT Status, and return results.
        """
        if not records:
            return []

        outcomes: List[Dict[str, object]] = []
        self._grid_scope = None
        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright)
            page = browser.new_page()
            try:
                self._open_base_url(page)
                self._login_if_needed(page)
                self._navigate_to_packages(page)
                self._dismiss_csv_templates_popup(page)
                self._dismiss_stonly_widget(page)
                for record in records:
                    metrc_id = (record.get("Tag") or "").strip()
                    current_status = (record.get("LT Status") or "").strip()
                    if not metrc_id:
                        logger.warning("Skipping record with empty Tag.")
                        continue
                    outcome = self._verify_single_tag(page, metrc_id, current_status)
                    outcomes.append(outcome)
                return outcomes
            finally:
                browser.close()

    def _verify_single_tag(self, page: Page, metrc_id: str, current_status: str) -> Dict[str, object]:
        for attempt in range(1, self.max_tag_filter_retries + 1):
            self._apply_tag_filter(page, metrc_id)
            scope = self._ensure_grid_scope(page)
            rows = scope.locator("#active-grid table tbody tr[role='row']")
            count = rows.count()
            logger.info("Tag %s attempt %d: row count %d", metrc_id, attempt, count)
            if count == 1:
                lt_status = self._get_cell_text(rows.nth(0), self.COLUMN_MAP["LT Status"])
                lt_status = lt_status.strip()
                return {
                    "metrc_id": metrc_id,
                    "current_status": current_status,
                    "fetched_status": lt_status,
                    "changed": lt_status != current_status,
                    "attempts": attempt,
                    "success": True,
                }
            if count > 1:
                lt_status = self._get_cell_text(rows.nth(0), self.COLUMN_MAP["LT Status"]).strip()
                return {
                    "metrc_id": metrc_id,
                    "current_status": current_status,
                    "fetched_status": lt_status,
                    "changed": lt_status != current_status,
                    "attempts": attempt,
                    "success": True,
                    "note": f"Multiple rows ({count}), used first.",
                }
        logger.error("Tag %s: no rows after %d attempts.", metrc_id, self.max_tag_filter_retries)
        return {
            "metrc_id": metrc_id,
            "current_status": current_status,
            "fetched_status": None,
            "changed": False,
            "attempts": self.max_tag_filter_retries,
            "success": False,
        }

    def _apply_tag_filter(self, page: Page, metrc_id: str) -> None:
        logger.info("Applying Tag equals filter for %s", metrc_id)
        self._dismiss_csv_templates_popup(page)
        self._dismiss_stonly_widget(page)
        scope = self._ensure_grid_scope(page)
        column_header = scope.locator(
            "#active-grid thead.k-grid-header th[data-field='Label']"
        ).first
        column_header.wait_for(state="visible", timeout=10_000)

        filter_menu = self._open_filter_popup(
            page,
            column_header,
            input_selector="input[type='text']",
            tab_presses=0,
            allow_keyboard=True,
        )

        operators = filter_menu.locator("select[data-role='dropdownlist']")
        if operators.count() >= 1:
            self._select_dropdown_option(operators.nth(0), ["eq", "equals", "equal", "is equal to"])

        input_box = filter_menu.locator("input[type='text']").first
        filled = False
        try:
            input_box.scroll_into_view_if_needed(timeout=2_000)
            try:
                input_box.fill("", timeout=1_000)
            except Exception:
                pass
            input_box.fill(metrc_id, timeout=3_000)
            filled = True
        except Exception:
            logger.warning("Standard fill failed for tag filter input; retrying with JS.")
            handle = input_box.element_handle()
            if handle is not None:
                handle.evaluate(
                    "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', {bubbles:true})); }",
                    metrc_id,
                )
                filled = True
        if not filled:
            raise TimeoutError("Unable to set Tag filter input.")

        self._click_filter_button(page, filter_menu)
        self._wait_for_grid_ready(page)

    def _log_row_count(
        self,
        page: Page,
        *,
        context: str,
    ) -> None:
        try:
            scope = self._ensure_grid_scope(page)
            grid_rows = scope.locator("#active-grid table tbody tr[role='row']")
            row_count = grid_rows.count()
            logger.info("Row count %s: %d", context, row_count)
        except Exception:
            logger.exception("Failed to log row count for context '%s'", context)

    def _get_date_range_strings(self) -> tuple[str, str]:
        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=self.date_range_days)
        fmt = "%m/%d/%Y"
        return start_date.strftime(fmt), today.strftime(fmt)

    def _extract_table_rows(self, page: Page) -> List[Dict[str, str]]:
        logger.info("Extracting table rows after filter.")
        scope = self._ensure_grid_scope(page)
        grid_rows = scope.locator("#active-grid table tbody tr[role='row']")
        row_count = grid_rows.count()
        logger.info("Found %d rows.", row_count)

        extracted: List[Dict[str, str]] = []
        for index in range(row_count):
            row = grid_rows.nth(index)
            row_data: Dict[str, str] = {}
            for label, data_field in self.COLUMN_MAP.items():
                value = self._get_cell_text(row, data_field)
                row_data[label] = value
            extracted.append(row_data)

        return extracted

    def _first_existing_locator(self, page: Page, selectors: List[str]) -> Locator | None:
        for selector in selectors:
            locator = page.locator(selector).first
            if locator.count() > 0:
                try:
                    locator.wait_for(state="visible", timeout=5_000)
                except TimeoutError:
                    continue
                return locator
        return None

    def _first_visible_locator(
        self,
        locators: List[Locator],
        timeout: int = 5_000,
    ) -> Locator | None:
        for locator in locators:
            candidate = locator.first
            try:
                candidate.wait_for(state="visible", timeout=timeout)
                return candidate
            except TimeoutError:
                continue
        return None

    def _get_cell_text(self, row: Locator, data_field: str) -> str:
        cell = row.locator(f"td[data-field='{data_field}']").first
        if cell.count() == 0:
            return ""
        text = cell.inner_text(timeout=5_000)
        return " ".join(text.split())

    def _select_filter_via_keyboard(
        self,
        page: Page,
        *,
        target_selector: str,
        tab_presses: int,
    ) -> bool:
        try:
            for _ in range(3):
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(100)
            page.keyboard.press("Enter")
            page.wait_for_timeout(200)
            for _ in range(tab_presses):
                page.keyboard.press("Tab")
                page.wait_for_timeout(50)
            page.wait_for_selector(target_selector, timeout=5_000)
            return True
        except TimeoutError:
            logger.warning("Keyboard navigation to Filter failed; falling back to mouse interaction.")
            return False

    def _click_filter_option_via_js(self, page: Page) -> bool:
        menu_container = page.locator("div.k-animation-container").filter(
            has=page.locator("span.k-link", has_text=re.compile(r"\bFilter\b", re.I))
        )
        if menu_container.count() == 0:
            return False
        try:
            menu_container.last.wait_for(state="visible", timeout=3_000)
        except TimeoutError:
            return False

        filter_span = menu_container.last.locator(
            "li.k-item span.k-link", has_text=re.compile(r"\bFilter\b", re.I)
        ).first
        if filter_span.count() == 0:
            return False

        handle = filter_span.element_handle()
        if handle is None:
            return False
        page.evaluate("el => el.click()", handle)
        page.wait_for_timeout(200)
        return True

    def _dismiss_stonly_widget(self, page: Page) -> None:
        widget = page.locator("iframe[title='interactive guide'], .stn-wdgt")
        if widget.count() == 0:
            return
        page.add_style_tag(content=".stn-wdgt { display: none !important; }")

    def _dismiss_csv_templates_popup(self, page: Page) -> None:
        """
        Close the new CSV Templates modal that blocks the grid (button text 'Got It').
        """
        candidate_buttons: List[Locator] = [
            page.get_by_role("button", name=re.compile(r"\bGot\s*It\b", re.I)),
            page.locator("div.Button__StyledButtonInterior-sc-3ecdced5-4", has_text=re.compile(r"\bGot\s*It\b", re.I)),
            page.locator("button", has_text=re.compile(r"\bGot\s*It\b", re.I)),
        ]
        button = self._first_visible_locator(candidate_buttons, timeout=3_000)
        if button is None:
            return
        try:
            button.click(timeout=2_000)
            logger.info("Dismissed CSV Templates modal (Got It).")
        except Exception:
            logger.warning("Standard click failed on CSV Templates modal; retrying with JS.")
            handle = button.element_handle()
            if handle is not None:
                page.evaluate("el => el.click()", handle)

    def _dismiss_system_alerts(self, page: Page) -> None:
        """
        Dismiss yellow/red system alerts that block the UI.
        Selectors based on 'data-donotshow-cookiename' attributes.
        """
        # 1. MetrcHideNotificationAlert (Yellow)
        # 2. MetrcPackagesHideOnHoldNotice (Red)
        alert_close_buttons = page.locator("span[data-dismiss='alert'][data-donotshow-cookiename]")
        count = alert_close_buttons.count()
        if count > 0:
            logger.info("Found %d system alert(s) to dismiss.", count)
            # Iterate in reverse or just click all visible
            for i in range(count):
                btn = alert_close_buttons.nth(i)
                if btn.is_visible():
                    try:
                        btn.click(timeout=2000)
                        logger.info("Clicked system alert dismiss button.")
                        page.wait_for_timeout(500)  # wait for animation
                    except Exception:
                        logger.warning("Failed to dismiss a system alert.")

    def _wait_for_grid_ready(self, page: Page) -> None:
        scope = self._ensure_grid_scope(page)
        panel = scope.locator("#packages_tabstrip-1")
        try:
            panel.wait_for(state="visible", timeout=20_000)
        except TimeoutError:
            logger.warning("Active panel did not become visible; continuing.")

        table_body = scope.locator("#active-grid table tbody")
        table_body.wait_for(state="visible", timeout=20_000)
        try:
            scope.wait_for_selector("#active-grid table tbody tr", timeout=20_000)
        except TimeoutError:
            logger.warning("Table has no rows after waiting.")
        self._wait_for_loading_overlay(scope)

    def _wait_for_loading_overlay(self, scope: Scope) -> None:
        overlays = scope.locator("div.k-loading-mask")
        end_time = time.time() + 15
        while time.time() < end_time:
            if overlays.count() == 0:
                return
            visible = any(overlays.nth(i).is_visible() for i in range(overlays.count()))
            if not visible:
                return
            time.sleep(0.25)

    def _ensure_grid_scope(self, page: Page) -> Scope:
        if self._grid_scope is not None:
            return self._grid_scope

        deadline = time.time() + 30
        while time.time() < deadline:
            scopes: List[Scope] = [page, *page.frames]
            for scope in scopes:
                locator = scope.locator("#active-grid")
                try:
                    if locator.count() > 0:
                        self._grid_scope = scope
                        logger.debug(
                            "Resolved grid scope to %s",
                            "frame" if isinstance(scope, Frame) else "page",
                        )
                        return scope
                except TimeoutError:
                    continue
            time.sleep(0.5)

        raise TimeoutError("Unable to locate the METRC packages grid.")


def get_robot() -> MetrcRobot:
    return MetrcRobot(config=settings.playwright, date_range_days=settings.runtime.date_range_days)
