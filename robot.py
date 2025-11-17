from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import time
from typing import Dict, List, Mapping, Optional, Union

from playwright.sync_api import Browser, Frame, Locator, Page, Playwright, TimeoutError, sync_playwright

from config import PlaywrightSettings, settings

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
                return self._extract_table_rows(page)
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
        self._dismiss_stonly_widget(page)
        self._apply_status_filter(page)
        self._dismiss_stonly_widget(page)
        self._apply_date_filter(page)

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
        page.keyboard.press("Tab")  # first select
        page.wait_for_timeout(50)
        for _ in range(3):
            page.keyboard.press("ArrowDown")  # move to After
            page.wait_for_timeout(50)
        page.keyboard.press("Tab")  # first date input
        page.wait_for_timeout(50)
        page.keyboard.type(start_date)
        for _ in range(2):
            page.keyboard.press("Tab")  # move to second select
            page.wait_for_timeout(50)
        for _ in range(5):
            page.keyboard.press("ArrowDown")  # move to Before
            page.wait_for_timeout(50)
        page.keyboard.press("Tab")  # second date input
        page.wait_for_timeout(50)
        page.keyboard.type(end_date)

        self._click_filter_button(page, filter_menu)
        self._wait_for_grid_ready(page)

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
        for attempt in range(3):
            menu_button.click()
            page.wait_for_timeout(200)
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
                popup = page.locator("div.k-animation-container").filter(
                    has=page.locator(input_selector)
                )
                if popup.count():
                    popup.last.wait_for(state="visible", timeout=5_000)
                    return popup.last
            logger.warning("Filter menu attempt %d failed; retrying.", attempt + 1)
            page.wait_for_timeout(500)
        raise TimeoutError("Unable to activate Filter option after multiple attempts.")

    def _click_filter_button(self, page: Page, filter_menu: Locator) -> None:
        filter_button = filter_menu.locator(
            "button.k-button.k-primary", has_text=re.compile(r"\bFilter\b", re.I)
        ).first
        try:
            filter_button.click()
        except TimeoutError:
            logger.warning("Standard click on Filter button failed; retrying with force.")
            filter_button.click(force=True)
        page.wait_for_load_state("networkidle")

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

        self._dump_debug_snapshot(page)
        raise TimeoutError("Unable to locate the METRC packages grid.")

    def _dump_debug_snapshot(self, page: Page) -> None:
        try:
            path = Path(f"debug_grid_{int(time.time())}.html")
            path.write_text(page.content(), encoding="utf-8")
            logger.error("Saved debug snapshot to %s for troubleshooting.", path)
        except Exception:  # pragma: no cover - best effort debug
            logger.exception("Failed to write debug snapshot.")


def get_robot() -> MetrcRobot:
    return MetrcRobot(config=settings.playwright, date_range_days=settings.runtime.date_range_days)
