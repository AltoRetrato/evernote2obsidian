#!/usr/bin/env python3
"""
evernote-reconciliation.py

Reconciles note counts between the Evernote backup database and the
exported Obsidian Markdown and HTML output folders.

Reads config.json from the same directory as this script to locate:
  - database: path to the evernote-backup SQLite database
  - output_folder_md: path to the Markdown export folder
  - output_folder_html: path to the HTML export folder

Produces a table comparing note counts per notebook across all three
sources, highlighting any discrepancies.

"""

import json
import os
import re
import sys
import sqlite3


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    """Load config.json from the same directory as this script."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    if not os.path.exists(config_path):
        print(f"Error: config.json not found in {script_dir}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Database helpers (mirrors evernote2obsidian.py logic)
# ---------------------------------------------------------------------------

INVALID_CHARS = r'[\\*"/<>:|?]'


def safe_path(path):
    """Sanitize path component, matching evernote2obsidian.py behavior."""
    return re.sub(INVALID_CHARS, "_", path.strip())


def get_notebook_counts(conn, export_trash=False):
    """Get all notebooks with their active note counts in a single query."""
    if export_trash:
        query = """
            select n.guid, n.name, n.stack, count(notes.notebook_guid) as cnt
            from notebooks n
            left join notes on notes.notebook_guid = n.guid
            group by n.guid, n.name, n.stack
        """
    else:
        query = """
            select n.guid, n.name, n.stack, count(notes.notebook_guid) as cnt
            from notebooks n
            left join notes on notes.notebook_guid = n.guid and notes.is_active = 1
            group by n.guid, n.name, n.stack
        """
    return [
        {"guid": row[0], "name": row[1], "stack": row[2], "count": row[3]}
        for row in conn.execute(query)
    ]


def notebook_dir_name(stack, name):
    """Build the directory path for a notebook, matching evernote2obsidian.py."""
    stack = safe_path(re.sub(r"[\s\.]+$", "", (stack or "").strip()))
    name = safe_path(re.sub(r"[\s\.]+$", "", name.strip()))
    if stack:
        return os.path.join(stack, name)
    return name


# ---------------------------------------------------------------------------
# Filesystem counting
# ---------------------------------------------------------------------------

def count_files_in_dir(base_folder, notebook_rel_path, extension):
    """Count files with given extension in notebook directory, excluding _resources."""
    folder = os.path.join(base_folder, notebook_rel_path)
    if not os.path.isdir(folder):
        return None  # directory does not exist
    count = 0
    for entry in os.listdir(folder):
        if entry == "_resources":
            continue
        full = os.path.join(folder, entry)
        if os.path.isfile(full) and entry.lower().endswith(extension):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg = load_config()

    db_path = cfg.get("database", "en_backup.db")
    md_folder = cfg.get("output_folder_md", "md")
    html_folder = cfg.get("output_folder_html", "html")
    export_trash = cfg.get("export_trash", False)

    if not os.path.exists(db_path):
        print(f"Error: database not found at {db_path}")
        sys.exit(1)

    print(f"Database:    {db_path}")
    print(f"MD folder:   {md_folder}")
    print(f"HTML folder: {html_folder}")
    print()

    conn = sqlite3.connect(db_path)
    notebooks = get_notebook_counts(conn, export_trash)

    # Build rows
    rows = []
    for nb in sorted(notebooks, key=lambda x: f"{x['stack'] or ''}{x['name']}".lower()):
        stack = nb["stack"]
        name = nb["name"]
        display_name = f"{stack} / {name}" if stack else name
        rel_path = notebook_dir_name(stack, name)

        db_count = nb["count"]
        md_count = count_files_in_dir(md_folder, rel_path, ".md")
        html_count = count_files_in_dir(html_folder, rel_path, ".html")

        rows.append({
            "name": display_name,
            "db": db_count,
            "md": md_count,
            "md_delta": (md_count - db_count) if md_count is not None else None,
            "html": html_count,
            "html_delta": (html_count - db_count) if html_count is not None else None,
        })

    conn.close()

    # Column widths
    col_name_w = max(8, max((len(r["name"]) for r in rows), default=0))
    num_w = 10  # width for numeric columns

    def fmt_num(val):
        if val is None:
            return "-"
        return f"{val:,}"

    def fmt_delta(val):
        if val is None:
            return "-"
        if val == 0:
            return "0"
        return f"*{val:+,}*"

    # Print header
    header_line = (
        f"{'Notebook':<{col_name_w}}  "
        f"{'DB':>{num_w}}  "
        f"{'MD':>{num_w}}  "
        f"{'MD Delta':>{num_w}}  "
        f"{'HTML':>{num_w}}  "
        f"{'HTML Delta':>{num_w}}"
    )
    print(header_line)
    print("-" * len(header_line))

    # Print rows
    total_db = 0
    total_md = 0
    total_html = 0
    mismatches = 0

    for r in rows:
        md_delta_str = fmt_delta(r["md_delta"])
        html_delta_str = fmt_delta(r["html_delta"])

        has_issue = (
            (r["md_delta"] is not None and r["md_delta"] != 0)
            or (r["html_delta"] is not None and r["html_delta"] != 0)
        )
        if has_issue:
            mismatches += 1

        marker = " <<" if has_issue else ""

        line = (
            f"{r['name']:<{col_name_w}}  "
            f"{fmt_num(r['db']):>{num_w}}  "
            f"{fmt_num(r['md']):>{num_w}}  "
            f"{md_delta_str:>{num_w}}  "
            f"{fmt_num(r['html']):>{num_w}}  "
            f"{html_delta_str:>{num_w}}"
            f"{marker}"
        )
        print(line)

        total_db += r["db"]
        total_md += r["md"] if r["md"] is not None else 0
        total_html += r["html"] if r["html"] is not None else 0

    # Totals
    print("-" * len(header_line))
    total_md_delta = total_md - total_db
    total_html_delta = total_html - total_db
    line = (
        f"{'TOTAL':<{col_name_w}}  "
        f"{total_db:>{num_w},}  "
        f"{total_md:>{num_w},}  "
        f"{fmt_delta(total_md_delta):>{num_w}}  "
        f"{total_html:>{num_w},}  "
        f"{fmt_delta(total_html_delta):>{num_w}}"
    )
    print(line)
    print()

    if mismatches:
        print(f"  {mismatches} notebook(s) with mismatches (marked with <<)")
    else:
        print("  All notebook counts match.")
    print()


if __name__ == "__main__":
    main()
