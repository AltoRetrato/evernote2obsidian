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



Usage:
  python evernote-reconciliation.py        Show reconciliation table
  python evernote-reconciliation.py --nb   Drill into a mismatched notebook
"""

import argparse
import json
import os
import re
import sys
import sqlite3
from collections import Counter


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
# Filesystem helpers
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


def list_files_in_dir(base_folder, notebook_rel_path, extension):
    """List filenames (without extension) in a notebook directory, excluding _resources."""
    folder = os.path.join(base_folder, notebook_rel_path)
    if not os.path.isdir(folder):
        return []
    names = []
    for entry in os.listdir(folder):
        if entry == "_resources":
            continue
        full = os.path.join(folder, entry)
        if os.path.isfile(full) and entry.lower().endswith(extension):
            names.append(entry[:-(len(extension))])
    return names


def get_db_note_titles(conn, notebook_guid, export_trash=False):
    """Get note titles from the database for a notebook."""
    if export_trash:
        cursor = conn.execute(
            "select title from notes where notebook_guid=? order by title COLLATE NOCASE",
            (notebook_guid,),
        )
    else:
        cursor = conn.execute(
            "select title from notes where notebook_guid=? and is_active=1 "
            "order by title COLLATE NOCASE",
            (notebook_guid,),
        )
    return [row[0] for row in cursor]


def db_title_to_filename(title):
    """Convert a DB note title to the filename stem that evernote2obsidian would produce."""
    return safe_path(title)


# Regex to strip dedup suffixes like (1), (2) and truncation hashes like _abcd1234
_DEDUP_SUFFIX = re.compile(r"\(\d+\)$")
_TRUNC_HASH = re.compile(r"_[0-9a-f]{8}$")
NORMALIZE_LEN = 55


def normalize_title(name):
    """Normalize a filename stem for fuzzy matching.

    Strips dedup suffixes (1), truncation hashes _abcd1234, then
    takes the first NORMALIZE_LEN characters for prefix matching.
    """
    name = _DEDUP_SUFFIX.sub("", name)
    name = _TRUNC_HASH.sub("", name)
    return name[:NORMALIZE_LEN]


# ---------------------------------------------------------------------------
# Shared: build notebook rows
# ---------------------------------------------------------------------------

def build_rows(cfg):
    """Open the DB, count notes per notebook, return (rows, notebooks_by_name) tuple."""
    db_path = cfg.get("database", "en_backup.db")
    md_folder = cfg.get("output_folder_md", "md")
    html_folder = cfg.get("output_folder_html", "html")
    export_trash = cfg.get("export_trash", False)

    if not os.path.exists(db_path):
        print(f"Error: database not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    notebooks = get_notebook_counts(conn, export_trash)
    conn.close()

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
            "guid": nb["guid"],
            "stack": stack,
            "nb_name": name,
            "rel_path": rel_path,
            "db": db_count,
            "md": md_count,
            "md_delta": (md_count - db_count) if md_count is not None else None,
            "html": html_count,
            "html_delta": (html_count - db_count) if html_count is not None else None,
        })

    return rows


def has_mismatch(r):
    """All three counts (db, md, html) must be equal to reconcile."""
    return r["md"] != r["db"] or r["html"] != r["db"]


# ---------------------------------------------------------------------------
# Table display
# ---------------------------------------------------------------------------

def show_table(cfg, rows):
    """Print the reconciliation table."""
    print(f"Database:    {cfg.get('database', 'en_backup.db')}")
    print(f"MD folder:   {cfg.get('output_folder_md', 'md')}")
    print(f"HTML folder: {cfg.get('output_folder_html', 'html')}")
    print()

    matched = [r for r in rows if not has_mismatch(r)]
    mismatched = [r for r in rows if has_mismatch(r)]

    col_name_w = max(8, max((len(r["name"]) for r in rows), default=0))
    num_w = 10

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

    def fmt_row(r):
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
        print(fmt_row(r))
    print("-" * len(header_line))
    print(subtotal(matched, "Subtotal"))
    print()

    # Mismatched notebooks
    if mismatched:
        print(f"MISMATCHED ({len(mismatched)} notebooks)")
        print_header()
        for r in mismatched:
            print(fmt_row(r))
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


# ---------------------------------------------------------------------------
# Notebook drill-down: find missing notes between two sources
# ---------------------------------------------------------------------------

def pick_from_list(prompt, options):
    """Display a numbered list and let the user pick one."""
    print(prompt)
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    print()
    while True:
        try:
            choice = input("Enter number (or q to quit): ").strip()
            if choice.lower() == "q":
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return idx
        except (ValueError, EOFError):
            pass
        print(f"  Please enter a number between 1 and {len(options)}.")


def notebook_drilldown(cfg, rows):
    """Interactive drill-down into a mismatched notebook to find missing notes."""
    mismatched = [r for r in rows if has_mismatch(r)]

    if not mismatched:
        print("All notebooks are reconciled. Nothing to drill into.")
        return

    # Step 1: pick a notebook
    nb_names = [f"{r['name']}  (DB:{r['db']}  MD:{r['md']}  HTML:{r['html']})" for r in mismatched]
    idx = pick_from_list("Select an unreconciled notebook:", nb_names)
    if idx is None:
        return
    nb = mismatched[idx]
    print()

    # Step 2: pick two sources to compare
    sources = []
    if nb["db"] > 0:
        sources.append("DB")
    if nb["md"] is not None:
        sources.append("MD")
    if nb["html"] is not None:
        sources.append("HTML")

    if len(sources) < 2:
        print("Need at least two available sources to compare.")
        return

    pairs = []
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            pairs.append((sources[i], sources[j]))

    pair_labels = [f"{a} vs {b}" for a, b in pairs]
    pidx = pick_from_list("Select two sources to compare:", pair_labels)
    if pidx is None:
        return
    source_a, source_b = pairs[pidx]
    print()

    # Step 3: get note titles from each source
    db_path = cfg.get("database", "en_backup.db")
    md_folder = cfg.get("output_folder_md", "md")
    html_folder = cfg.get("output_folder_html", "html")
    export_trash = cfg.get("export_trash", False)

    def get_titles(source):
        if source == "DB":
            conn = sqlite3.connect(db_path)
            titles = get_db_note_titles(conn, nb["guid"], export_trash)
            conn.close()
            return [db_title_to_filename(t) for t in titles]
        elif source == "MD":
            return list_files_in_dir(md_folder, nb["rel_path"], ".md")
        elif source == "HTML":
            return list_files_in_dir(html_folder, nb["rel_path"], ".html")
        return []

    raw_a = get_titles(source_a)
    raw_b = get_titles(source_b)

    # Normalize titles for comparison (strips dedup suffixes, truncation hashes, prefix match)
    norm_a = Counter(normalize_title(t) for t in raw_a)
    norm_b = Counter(normalize_title(t) for t in raw_b)

    only_in_a_counter = norm_a - norm_b
    only_in_b_counter = norm_b - norm_a

    def expand_counter(ctr):
        result = []
        for title in sorted(ctr, key=str.lower):
            count = ctr[title]
            if count == 1:
                result.append(title)
            else:
                result.append(f"{title}  (x{count})")
        return result

    only_in_a = expand_counter(only_in_a_counter)
    only_in_b = expand_counter(only_in_b_counter)
    total_only_a = sum(only_in_a_counter.values())
    total_only_b = sum(only_in_b_counter.values())

    print(f"Notebook: {nb['name']}")
    print(f"Comparing: {source_a} ({len(raw_a)} notes) vs {source_b} ({len(raw_b)} notes)")
    print(f"(matching on first {NORMALIZE_LEN} chars, ignoring dedup/truncation suffixes)")
    print()

    if only_in_a:
        print(f"In {source_a} but not in {source_b} ({total_only_a}):")
        for title in only_in_a:
            print(f"  - {title}")
        print()

    if only_in_b:
        print(f"In {source_b} but not in {source_a} ({total_only_b}):")
        for title in only_in_b:
            print(f"  - {title}")
        print()

    if not only_in_a and not only_in_b:
        print("  No differences found.")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def print_usage():
    print("evernote-reconciliation.py")
    print()
    print("Reconcile note counts between Evernote backup DB and export folders.")
    print("Reads config.json from the script directory for paths.")
    print()
    print("Usage:")
    print("  python evernote-reconciliation.py --all   Full reconciliation table")
    print("  python evernote-reconciliation.py --nb    Drill into a mismatched notebook")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile note counts between Evernote backup and export folders.",
        add_help=False,
    )
    parser.add_argument("--all", action="store_true", help="Show full reconciliation table")
    parser.add_argument("--nb", action="store_true", help="Drill into a mismatched notebook")
    parser.add_argument("-h", "--help", action="store_true", help="Show usage")
    args = parser.parse_args()

    if not args.all and not args.nb:
        print_usage()
        return

    cfg = load_config()
    rows = build_rows(cfg)

    if args.nb:
        notebook_drilldown(cfg, rows)
    else:
        show_table(cfg, rows)


if __name__ == "__main__":
    main()
