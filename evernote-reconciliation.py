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

    # Split into matched and mismatched
    # All three counts (db, md, html) must be equal to reconcile
    def has_mismatch(r):
        return r["md"] != r["db"] or r["html"] != r["db"]

    matched = [r for r in rows if not has_mismatch(r)]
    mismatched = [r for r in rows if has_mismatch(r)]

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

    def print_header():
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
        return header_line

    def print_row(r):
        return (
            f"{r['name']:<{col_name_w}}  "
            f"{fmt_num(r['db']):>{num_w}}  "
            f"{fmt_num(r['md']):>{num_w}}  "
            f"{fmt_delta(r['md_delta']):>{num_w}}  "
            f"{fmt_num(r['html']):>{num_w}}  "
            f"{fmt_delta(r['html_delta']):>{num_w}}"
        )

    def subtotal(section_rows, label):
        s_db = sum(r["db"] for r in section_rows)
        s_md = sum(r["md"] for r in section_rows if r["md"] is not None)
        s_html = sum(r["html"] for r in section_rows if r["html"] is not None)
        return (
            f"{label:<{col_name_w}}  "
            f"{s_db:>{num_w},}  "
            f"{s_md:>{num_w},}  "
            f"{fmt_delta(s_md - s_db):>{num_w}}  "
            f"{s_html:>{num_w},}  "
            f"{fmt_delta(s_html - s_db):>{num_w}}"
        )

    # Reconciled notebooks
    print(f"RECONCILED ({len(matched)} notebooks)")
    header_line = print_header()
    for r in matched:
        print(print_row(r))
    print("-" * len(header_line))
    print(subtotal(matched, "Subtotal"))
    print()

    # Mismatched notebooks
    if mismatched:
        print(f"MISMATCHED ({len(mismatched)} notebooks)")
        print_header()
        for r in mismatched:
            print(print_row(r))
        print("-" * len(header_line))
        print(subtotal(mismatched, "Subtotal"))
        print()

    # Grand total
    total_db = sum(r["db"] for r in rows)
    total_md = sum(r["md"] for r in rows if r["md"] is not None)
    total_html = sum(r["html"] for r in rows if r["html"] is not None)
    print("=" * len(header_line))
    total_line = (
        f"{'GRAND TOTAL':<{col_name_w}}  "
        f"{total_db:>{num_w},}  "
        f"{total_md:>{num_w},}  "
        f"{fmt_delta(total_md - total_db):>{num_w}}  "
        f"{total_html:>{num_w},}  "
        f"{fmt_delta(total_html - total_db):>{num_w}}"
    )
    print(total_line)
    print()

    if mismatched:
        print(f"  {len(mismatched)} notebook(s) with mismatches.")
    else:
        print("  All notebook counts match.")
    print()


if __name__ == "__main__":
    main()
