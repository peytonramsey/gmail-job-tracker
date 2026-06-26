from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

STATUS_COLORS: dict[str, str] = {
    "Offer":       "bold green",
    "Interview":   "bold yellow",
    "Assessment":  "bold cyan",
    "Rejected":    "red",
    "Applied":     "white",
    "Other":       "dim",
}

FILTERS = ["All", "Applied", "Interview", "Assessment", "Offer", "Rejected"]


def _cell(value, default="—"):
    """Read a Series cell for display, coercing NaN/None to a default.
    (`value or default` is unsafe: NaN is truthy, so it would render as 'nan'.)
    """
    return default if pd.isna(value) else value


def _is_true(value) -> bool:
    """Coerce a CSV-loaded boolean cell to bool. Handles real bools, the
    strings 'True'/'False' (object dtype when NaN is present), and NaN itself —
    bool('False') is True, so a plain bool() cast is wrong here.
    """
    return str(value).strip().lower() == "true"


class JobTrackerApp(App):

    TITLE = "Job Search Tracker"

    CSS = """
    #stats {
        background: $boost;
        color: $text-muted;
        padding: 0 2;
        height: 1;
    }
    #filters {
        height: 3;
        padding: 0 1;
    }
    #filters Button {
        margin: 0 1;
        min-width: 14;
    }
    #filters Button.-active-filter {
        background: $accent;
        color: $text;
    }
    #search {
        margin: 0 1 0 1;
    }
    #table {
        border: solid $accent;
    }
    #detail {
        height: 10;
        background: $boost;
        padding: 0 2;
        border-top: solid $accent;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("/", "focus_search", "Search"),
        Binding("escape", "clear_search", "Clear"),
        Binding("1", "set_filter('All')",        "All",        show=False),
        Binding("2", "set_filter('Applied')",    "Applied",    show=False),
        Binding("3", "set_filter('Interview')",  "Interview",  show=False),
        Binding("4", "set_filter('Assessment')", "Assessment", show=False),
        Binding("5", "set_filter('Offer')",      "Offer",      show=False),
        Binding("6", "set_filter('Rejected')",   "Rejected",   show=False),
    ]

    active_filter: reactive[str] = reactive("All", init=False)
    search_query:  reactive[str] = reactive("",    init=False)

    def __init__(self) -> None:
        super().__init__()
        self._df: pd.DataFrame = pd.DataFrame()

    # ── compose ──────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="stats")
        yield Horizontal(
            *[Button(f"{i+1}: {fl}", id=f"btn_{fl.lower()}") for i, fl in enumerate(FILTERS)],
            id="filters",
        )
        yield Input(placeholder="/ to search by company or title…", id="search")
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Static("Select a row to see details", id="detail")
        yield Footer()

    # ── startup ───────────────────────────────────────────────────────────────
    def on_mount(self) -> None:
        csv_path = Path("job_tracker.csv")
        if not csv_path.exists():
            self.query_one("#stats", Static).update(
                "[bold red]job_tracker.csv not found — run the pipeline first[/]"
            )
            return

        df = pd.read_csv(csv_path)
        # utc=True guarantees a tz-aware column, so tz_convert(None) can't raise
        # on tz-naive input (matches how extract.py parses Date).
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce", utc=True).dt.tz_convert(None)
        df = df.sort_values("Date", ascending=False).reset_index(drop=True)
        self._df = df

        self._update_stats()
        self._refresh_table()
        self._mark_active_button("All")

    # ── stats bar ─────────────────────────────────────────────────────────────
    def _update_stats(self) -> None:
        df = self._df
        total      = len(df)
        interviews = (df["Status"] == "Interview").sum()
        offers     = (df["Status"] == "Offer").sum()
        rejected   = (df["Status"] == "Rejected").sum()
        pending    = (df["Status"] == "Applied").sum()
        any_resp   = df["Status"].isin(["Interview", "Offer", "Rejected"]).sum()
        rate       = f"{any_resp / total:.1%}" if total else "0.0%"

        self.query_one("#stats", Static).update(
            f"Total: [bold]{total}[/]  "
            f"Interviews: [bold yellow]{interviews}[/]  "
            f"Offers: [bold green]{offers}[/]  "
            f"Rejected: [bold red]{rejected}[/]  "
            f"Pending: [bold]{pending}[/]  "
            f"Response rate: [bold cyan]{rate}[/]"
        )

    # ── table ─────────────────────────────────────────────────────────────────
    def _refresh_table(self) -> None:
        if self._df.empty:
            return

        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "Company", "Job Title", "Status", "Date", "Days Since")

        df = self._df
        if self.active_filter != "All":
            df = df[df["Status"] == self.active_filter]
        if self.search_query:
            q = self.search_query.lower()
            mask = (
                df.get("Company", pd.Series(dtype=str)).fillna("").str.lower().str.contains(q, regex=False) |
                df.get("JobTitle", pd.Series(dtype=str)).fillna("").str.lower().str.contains(q, regex=False)
            )
            df = df[mask]

        today = pd.Timestamp.now()
        for display_n, (idx, row) in enumerate(df.iterrows(), start=1):
            status  = str(_cell(row.get("Status"), ""))
            color   = STATUS_COLORS.get(status, "white")
            date_v  = row["Date"]
            date_s  = date_v.strftime("%b %d %Y") if pd.notna(date_v) else "—"
            days_s  = f"{int((today - date_v).days)}d" if pd.notna(date_v) else "—"
            company = str(_cell(row.get("Company")))[:32]
            title   = str(_cell(row.get("JobTitle")))[:42]

            table.add_row(
                Text(str(display_n), style="dim"),
                Text(company, style=color),
                Text(title,   style=color),
                Text(status,  style=color),
                Text(date_s,  style="dim"),
                Text(days_s,  style="dim"),
                key=str(idx),
            )

        count = len(df)
        s = "" if count == 1 else "s"
        search_tag = f" matching '{self.search_query}'" if self.search_query else ""
        self.sub_title = f"{count} application{s} ({self.active_filter}){search_tag}"

    # ── detail pane ───────────────────────────────────────────────────────────
    def _show_detail(self, row_key: str) -> None:
        try:
            row = self._df.loc[int(row_key)]
        except (KeyError, ValueError):
            return

        subject    = str(_cell(row.get("Subject")))
        method     = str(_cell(row.get("ExtractionMethod")))
        confidence = row.get("Confidence")
        conf_s     = f"{confidence:.2f}" if pd.notna(confidence) else "—"
        needs_rev  = _is_true(row.get("NeedsReview", False))
        rev_tag    = "  [bold red]⚠ needs review[/]" if needs_rev else ""

        raw = str(_cell(row.get("EvidenceSnippets"), ""))
        try:
            snippets = json.loads(raw) if raw else []
            evidence = "  |  ".join(f'"{s}"' for s in snippets[:3])
        except (json.JSONDecodeError, TypeError):
            evidence = raw[:150]

        raw_history = str(_cell(row.get("EmailHistory"), ""))
        try:
            history = json.loads(raw_history) if raw_history else []
        except (json.JSONDecodeError, TypeError):
            history = []
        if history:
            hist_lines = [f"  {h['date']}  {h['status']:<12} {h['subject'][:60]}" for h in history[-5:]]
            history_block = "\n".join(hist_lines)
        else:
            history_block = "  -"

        self.query_one("#detail", Static).update(
            f"[bold]Subject:[/] {subject}\n"
            f"[bold]Method:[/] {method}   [bold]Confidence:[/] {conf_s}{rev_tag}\n"
            f"[bold]Evidence:[/] {evidence or '-'}\n"
            f"[bold]Email history[/] ({len(history)}):\n{history_block}"
        )

    # ── event handlers ────────────────────────────────────────────────────────
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value is not None:
            self._show_detail(str(event.row_key.value))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search_query = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("btn_"):
            slug = btn_id[4:]
            label = next((fl for fl in FILTERS if fl.lower() == slug), "All")
            self.active_filter = label
            self._mark_active_button(label)

    # ── reactive watchers ─────────────────────────────────────────────────────
    def watch_active_filter(self) -> None:
        if not self._df.empty:
            self._refresh_table()

    def watch_search_query(self) -> None:
        if not self._df.empty:
            self._refresh_table()

    # ── helpers ───────────────────────────────────────────────────────────────
    def _mark_active_button(self, label: str) -> None:
        for fl in FILTERS:
            btn = self.query_one(f"#btn_{fl.lower()}", Button)
            if fl == label:
                btn.add_class("-active-filter")
            else:
                btn.remove_class("-active-filter")

    # ── actions ───────────────────────────────────────────────────────────────
    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        self.query_one("#search", Input).value = ""
        self.query_one("#table", DataTable).focus()

    def action_set_filter(self, label: str) -> None:
        self.active_filter = label
        self._mark_active_button(label)


if __name__ == "__main__":
    JobTrackerApp().run()
