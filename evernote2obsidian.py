#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# evernote-backup2obsidian.py
# ===========================
#
# Project: https://github.com/AltoRetrato/evernote2obsidian/
#
# This program converts an Evernote backup created with evernote-backup
# (https://github.com/vzhd1701/evernote-backup) to Obsidian Markdown (or HTML).
#
# 2026.02.10  0.1.6, fixed #16 "Wrong/Missing image extension"
# 2026.01.04  0.1.5, improved attachment handling and conversion robustness
#                    (#13 by quiettype), fixed some Pylance warnings
# 2025.08.18  0.1.3, fixed #9 "SyntaxWarning due to invalid escape sequences"
# 2025.05.23  0.1.0, 1st release
# 2024.10.08  0.0.1, 1st version

__version__ = "0.1.6"
__author__  = "AltoRetrato"

import os
import re
import json
import lzma
import hashlib
import pickle
import logging
import sqlite3
import mimetypes
from   bs4         import BeautifulSoup
from   bs4.element import Tag
from   typing      import Sequence, TypeVar, cast
from   datetime    import datetime, timezone
from   zoneinfo    import ZoneInfo
from   posixpath   import join as posix_join, normpath as posix_normpath, abspath as posix_abspath
from   evernote2md import EvernoteHTMLToMarkdownConverter
try:
    from prompt_toolkit.shortcuts import radiolist_dialog, input_dialog, button_dialog
    from prompt_toolkit.shortcuts.dialogs import  _return_none, _create_app
    from prompt_toolkit.application import Application
    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.formatted_text import AnyFormattedText
    from prompt_toolkit.styles import BaseStyle
    from prompt_toolkit.layout.containers import HSplit
    from prompt_toolkit.widgets import Button, CheckboxList, Dialog, Label
except ImportError as e:
    missing_module = str(e).split()[-1].strip("'")
    print(e)
    print(f"Error importing module {missing_module} - if not installed, install it with:")
    print(f"pip install {missing_module}")
    exit()


class Config(dict):

    file_name = "config.json"

    def __init__(self, default=None, file_name=None):
        """Initialize the Config object and load settings."""
        super().__init__()
        # Set default values if provided
        if default is not None:
            self.update(default)

        if file_name is not None:
            self.file_name = file_name

        # Load configuration from the JSON file
        self.load()

    def load(self):
        """Load configuration from a JSON file into the dictionary."""
        try:
            with open(self.file_name, "r", encoding="utf-8") as f:
                self.update(json.load(f))
        except FileNotFoundError:
            pass
            #print(f"Configuration file '{self.config_file_name}' not found. Using default values.")
        except json.JSONDecodeError:
            print(f"Error decoding JSON from the file '{self.file_name}'. Using default values.")

    def save(self):
        """Save the dictionary to a JSON file."""
        try:
            with open(self.file_name, "w", encoding="utf-8") as f:
                json.dump(self, f, indent=2, sort_keys=True)
        except IOError as e:
            print(f"Error writing to the file '{self.file_name}': {e}")


# Configuration options & default values
max_name_len = 29
default_cfg  = {}
option_data  = {}
for option, value, name, help in (
    ("database",           "en_backup.db",      "Database path",                 "Location of your 'evernote-backup' database,\ncreated with 'evernote-backup init-db'."),
    ("output_folder_md",   "md",                "Vault/Markdown output folder",  "Folder where Markdown and attachment files will be exported to."),
    ("output_folder_html", "html",              "HTML output folder",            "Folder where HTML and attachment files will be exported to."),
    ("html_with_md_ext",   False,               "Use HTML in .md files",         'If True:\n - Notes exported as HTML will have .md extension, .html otherwise.\n - Notes exported as Markdown will include some formatting in HTML.\nHTML in .md can be awful to edit and break Markdown formatting, but might be worth testing. It all depends on how you format your notes, and how much some HTML formatting (e.g., text color) is important for you to keep.'),
    ("log_file",           "conversion.log",    "Log file",                      "File name for log. Leave empty to skip logging."),
    ("log_level",          "warning",           "Log verbosity",                 "Choose log verbosity level:\n  debug    = most verbose\n  critical = least verbose" ),
    ("overwrite",          True,                "Overwrite existing files",      "Overwrite existing files in the output folder?"),
    ("export_trash",       False,               "Export Trash notebook",         "Set this to True to export deleted notes."),
    ("export_empty_note",  False,               "Export empty notes",            "Set this to True to export notes with empty content."),
    ("export_empty_file",  False,               "Export empty attachments",      "Set this to True to export attachments with 0 bytes."),
    ("max_path_len",       256,                 "Max. path length (0=no limit)", "Warn if total absolute path length > this value.\nSet to 0 for no limit."),
    ("max_attach_MB",      5,                   "Warn attachment size (in MB)",  "List attachments above this size in MB.\nSet to 0 to skip this check."),
    ("check_emojis",       True,                "Warn if file name has emoji",   "Warn if files to be exported have emojis,\nwhich is unsupported in Dropbox and other programs."),
    ("check_tables",       True,                "Warn if table has merged cell", "Warn if tables have merged cells,\nwhich is unsupported in Obsidian Markdown by default."),
    ("check_format",       True,                "Warn of unsupported format",    "Warn if notes have formatting unsupported by Markdown,\nsuch as font size and color, underline, etc."),
    ("pdf_view",           "default",           "Show PDFs as",                  "Choose how ALL PDF files will appear in the converted notes:\n - default: The same way as they appear in Evernote\n - title  : Show PDFs only as the title\n - preview: Preview of the first PDF page"),
    ("first_line_empty",   False,               "Make first note line empty",    "If True, add an empty line at the beginning of the note.\nThis is a cosmetic hack to avoid Obsidian showing code when you open a note in editing view."),
    ("remove_green_link",  False,               "Remove color of green links",   "For a while, Evernote made internal links (links to other notes) green.\nI recommend removing them and using a CSS snippet in Obsidian instead\nif you want all internal links to be green."),
    ("escape_brackets",    False,               "Replace [] with () in links",   "Square brackets [] are special characters in Markdown.\nThey can appear the text portion of your links, but might look a bit odd in Obsidian.\nSet this to True to replace them with parentheses ()."),
    ("links_with_folders", True,                "Include folder path in links",  "Obsidian can have multiple notes with the same name in different folders.\nSet this to True to include the folder path in links. This helps avoid confusion when multiple notes share the same name.\nSet this to False to use only the note title in links. This keeps links simpler but may cause conflicts if note names are duplicated."),
    ("notebooks",          None,                "",                              "Notebooks to export"),
):
    default_cfg[option] = value
    if name:
        option_data[option] = {
            "name": name,
            "type": type(value),
            "help": help,
            "menu_name": f"{name}{'.'*(max_name_len -len(name))}",
        }
        if option == "pdf_view":
            option_data[option]["type"]    = list
            option_data[option]["options"] = ["default", "title", "preview"]
        elif option == "log_level":
            option_data[option]["type"]    = list
            option_data[option]["options"] = ["debug", "info", "warning", "error", "critical"]

cfg     = Config(default=default_cfg) # Global var. used by most functions

# Logging
IMPORTANT = logging.CRITICAL +10
logging.addLevelName(IMPORTANT, "IMPORTANT")

def important(self, message, *args, **kwargs):
    if self.isEnabledFor(IMPORTANT):
        self._log(IMPORTANT, message, args, **kwargs)

setattr(logging.Logger, "important", important)  # Add to Logger class

_logger = logging.getLogger("custom_logger")
_log_handler = None # To track and remove file handler when needed


def restart_log(just_close=False):
    # Should be called whenever log file name or log level changes
    global _log_handler, _log_level

    # Remove old handler if any
    if _log_handler:
        _logger.removeHandler(_log_handler)
        _log_handler.close()
        _log_handler = None

    if just_close or not cfg.get("log_file"):
        return

    # Set log level
    log_level = {
        "debug"   : logging.DEBUG,
        "info"    : logging.INFO,
        "warning" : logging.WARNING,
        "error"   : logging.ERROR,
        "critical": logging.CRITICAL
    }.get(cfg["log_level"], logging.WARNING)

    # Create new file handler
    _log_handler = logging.FileHandler(cfg["log_file"], mode='a', encoding='utf-8')
    _log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S'))
    _logger.addHandler(_log_handler)
    _logger.setLevel(log_level)


def log(level, msg):
    # Log to console always
    print(msg)
    # Log to file (if log file exists and depending on log level)
    if cfg.get("log_file"):
        if _log_handler is None:
            restart_log()
        _logger.log(level, msg)
    # Return the message for "chaining"
    return msg


def cfg_menu():
    """Show current configuration and allow user to change it."""

    global cfg
    values = [(o, f"{option_data[o]['menu_name']}: {cfg[o] if o in cfg else default_cfg[o]}") for o in option_data]
    option = radiolist_dialog(
        title  = "Configuration",
        text   = "Select an item then <Change> to modify it, or <Back> to return:",
        ok_text     = "Change",
        cancel_text = "Back",
        values      = values,
    ).run()
    if option is None:
        return True

    name  = option_data[option]["name"]
    otype = option_data[option]["type"]
    help  = option_data[option]["help"]
    title = f"Change '{name}'"
    text  = f"{help}\n\nEnter new value for '{name}':"
    new_value = None
    if otype in [str, int, float]:
        new_value = input_dialog(
            title = title,
            text  = text,
            default = str(cfg[option] or "")).run()
    elif otype is bool or otype is list:
        if otype is list:
              _values = [ (v, v) for v in option_data[option]["options"]]
        else: _values = [ (True, "True"), (False, "False")]
        new_value = radiolist_dialog(
            title = title, 
            text  = text, 
            values  = _values,
            default = cfg[option] ).run()

    if new_value is not None:
        if   otype is int:   cfg[option] = int  (new_value)
        elif otype is float: cfg[option] = float(new_value)
        else:                cfg[option] = new_value
        cfg.save()
        if option == "log_file":
            restart_log()

    return cfg_menu()


def open_db(db_path):
    log(IMPORTANT, f"Reading database {db_path}")

    if not os.path.exists(db_path):
        log(logging.CRITICAL, f"""
Database file {db_path} not found. Set the correct database path
in the configuration, or sync Evernote data with:
    evernote-backup init-db --oauth
    evernote-backup sync""")
        return False

    try:
        conn = sqlite3.connect(db_path)
    except Exception as e:
        log(logging.CRITICAL, f"Could not open database {db_path}")
        log(logging.CRITICAL, f"Exception: {e}")
        return

    return conn


def has_emoji(s):
    # Regular expression pattern for emojis, excluding Japanese Unicode ranges
    # Might be incomplete and/or plain wrong...
    emoji_pattern = re.compile(
        r"[\U0001F600-\U0001F64F]"  # emoticons
        r"|[\U0001F300-\U0001F5FF]"  # symbols & pictographs
        r"|[\U0001F680-\U0001F6FF]"  # transport & map symbols
        r"|[\U0001F700-\U0001F77F]"  # alchemical symbols
        r"|[\U0001F780-\U0001F7FF]"  # Geometric shapes extended
        r"|[\U0001F800-\U0001F8FF]"  # Supplemental Arrows-C
        r"|[\U0001F900-\U0001F9FF]"  # Supplemental Symbols and Pictographs
        r"|[\U0001FA00-\U0001FA6F]"  # Chess Symbols
        r"|[\U0001FA70-\U0001FAFF]"  # Symbols and Pictographs Extended-A
        r"|[\U00002702-\U000027B0]"  # Dingbats
       #"|[\U000024C2-\U0001F251]"  # Enclosed characters # Conflicts with Japanese / Kanji
        r"|[\U0001F1E6-\U0001F1FF]"  # Flags (iOS)
        r"|[\U00002500-\U00002BEF]"  # Geometric Shapes
        , flags=re.UNICODE)

    return bool(emoji_pattern.search(s))


invalid_chars = r'[\\*"/<>:|?]'

def is_invalid_obsidian_title(title):
    """ Return False if title is valid, otherwise return invalid chars. """
    invalid_matches = re.findall(invalid_chars, title)
    if cfg.get("check_emojis") and has_emoji(title):
        invalid_matches.append("emoji")
    if not invalid_matches:
        return False
    return f"{' '.join(invalid_matches)}"


def repeated_strings(str_list, msg):
    # Dictionary to store the occurrence count of each string
    string_counts = {}

    # Count occurrences of each string (case-insensitive and stripped of whitespace)
    for s in str_list:
        if s:
            normalized_str = s.lower().strip()
            string_counts[normalized_str] = string_counts.get(normalized_str, 0) + 1

    # Filter strings that have more than one occurrence and sort them by count (descending)
    duplicates = {
        string: count for string, count in sorted(
            string_counts.items(), key=lambda item: item[1], reverse=True
        ) if count > 1
    }

    # Report duplicates if any
    if duplicates:
        log(IMPORTANT, msg)
        for string, count in duplicates.items():
            log(IMPORTANT, f"  {count:3}: {string}")

    # Return the number of duplicated strings found
    return len(duplicates)


def get_notebooks_from_db(conn):
    return [dict(zip(["guid", "name", "stack"], row))
            for row in conn.execute("select guid, name, stack from notebooks")]


def get_notes_from_notebook(conn, notebook_guid):
    return conn.execute(
            "select is_active, raw_note from notes where notebook_guid=? "
            "order by title COLLATE NOCASE",
            (notebook_guid, )
    )

_T = TypeVar("_T")


def custom_checkboxlist_dialog(
    title: AnyFormattedText = "",
    text: AnyFormattedText = "",
    ok_text: str = "Ok",
    cancel_text: str = "Cancel",
    values: Sequence[tuple[_T, AnyFormattedText]] | None = None,
    default_values: Sequence[_T] | None = None,
    style: BaseStyle | None = None,
) -> Application[list[_T]]:
    """
    Display a simple list of element the user can choose multiple values amongst.

    Several elements can be selected at a time using Arrow keys and Enter.
    The focus can be moved between the list and the buttons with tab.
    """
    if values is None:
        values = []

    def ok_handler() -> None:
        get_app().exit(result=cb_list.current_values)

    cb_list = CheckboxList(values=values, default_values=default_values)

    def set_all_cb_list(cb_list, all_marked):
        if all_marked:
              cb_list.current_values = [key for key, value in values]
        else: cb_list.current_values = []

    dialog = Dialog(
        title=title,
        body=HSplit(
            [Label(text=text, dont_extend_height=True), cb_list],
            padding=1,
        ),
        buttons=[
            Button(text="All",  handler=lambda: set_all_cb_list(cb_list, True )),
            Button(text="None", handler=lambda: set_all_cb_list(cb_list, False)),
            Button(text=ok_text, handler=ok_handler),
            Button(text=cancel_text, handler=_return_none),
        ],
        with_background=True,
    )

    return _create_app(dialog, style)


def sel_nb_menu():
    """Allows user to select any/all from a list of notebooks in the DB."""

    if not (conn := open_db(cfg['database'])):
        return False

    notebooks = get_notebooks_from_db(conn)

    cur = conn.execute("select COUNT(*) from notes where is_active=1")
    num_active = int(cur.fetchone()[0])

    cur = conn.execute("select COUNT(*) from notes where is_active=0")
    num_deleted = int(cur.fetchone()[0])

    guids_notebooks = {}

    for notebook in sorted(
            notebooks, 
            key = lambda x: f"{x['stack' or '']}{x['name']}".lower() ):
        cur = conn.execute(
                "select COUNT(*) from notes where notebook_guid=? and is_active=1",
                (notebook["guid"],) )
        num_notes = int(cur.fetchone()[0])
        stack     = notebook["stack"] or ""
        if stack: stack = f"{stack} / "
        guids_notebooks[notebook["guid"]] = f"{stack}{notebook['name']} ({num_notes:,})"

    conn.close()

    selection = custom_checkboxlist_dialog(
        title  = "Select notebooks to export",
        text   = f"DB has {len(notebooks):,} notebooks, {num_active:,} active notes, {num_deleted:,} del. notes\n" \
                  "Select notebooks to export:",
        ok_text= "Save sel.",
        values = [(key, value) for key, value in guids_notebooks.items()],
        default_values = cfg["notebooks"]
    ).run()

    if selection is not None:
        cfg["notebooks"] = selection
        cfg.save()
        pass

    return True


def safe_path(path):
    # TO-DO: add in config. a custom character, translation map or regex?
    return re.sub(invalid_chars, "_", path.strip())


def truncate_filename(filename, max_bytes=255):
    """Truncate a filename to fit within the filesystem's max byte limit.
    Preserves the extension and appends a short hash for uniqueness when truncating."""
    encoded = filename.encode("utf-8")
    if len(encoded) <= max_bytes:
        return filename

    # Split into stem and extension
    if '.' in filename:
        stem, ext = filename.rsplit('.', 1)
        ext = '.' + ext
    else:
        stem = filename
        ext = ''

    # Create a short hash from the original full filename for uniqueness
    hash_suffix = hashlib.md5(filename.encode("utf-8")).hexdigest()[:8]
    suffix = f"_{hash_suffix}{ext}"
    suffix_bytes = len(suffix.encode("utf-8"))

    # Truncate stem to fit: max_bytes - suffix length
    max_stem_bytes = max_bytes - suffix_bytes
    stem_encoded = stem.encode("utf-8")
    if len(stem_encoded) > max_stem_bytes:
        # Truncate at UTF-8 character boundary
        truncated = stem_encoded[:max_stem_bytes].decode("utf-8", errors="ignore")
        return truncated + suffix

    return stem + suffix


def safe_join(*paths):
    # Apply safe_path() to each argument and then join them
    safe_paths = [safe_path(path) for path in paths if path]
    return posix_join(*safe_paths)


def to_posix(path):
    return path.replace('\\', '/')


def list_db():
    """List all notes in the DB."""

    if not (conn := open_db(cfg['database'])):
        return False

    notebooks = get_notebooks_from_db(conn)

    log(IMPORTANT, "Listing notes in selected notebooks.")

    for notebook in sorted(notebooks, key=lambda x: f"{x['stack' or '']}{x['name']}".lower() ):
        # Process only selected notebooks
        if cfg["notebooks"] and notebook["guid"] not in cfg["notebooks"]:
            continue

        stack_name    = (notebook["stack"] or "").strip()
        notebook_name = notebook["name"].strip()

        # Get number of notes in notebook
        cur = conn.execute(
                "select COUNT(*) from notes where notebook_guid=? and is_active=1",
                (notebook["guid"],) )
        num_notes = int(cur.fetchone()[0])
        prefix    = stack_name or ""
        if prefix: prefix = f"{prefix} / "
        log(IMPORTANT, f"{prefix}{notebook_name} ({num_notes:,} notes)")

        cur = conn.execute(
                "select is_active, raw_note from notes where notebook_guid=? "
                "order by title COLLATE NOCASE",
                (notebook["guid"], ) )

        for row_note in cur:
            is_active, raw_note = row_note

            # Skip processing deleted notes according to config.
            if not (is_active or cfg["export_trash"]):
                continue

            # Insert Rick and Morty reference...
            note = pickle.loads(lzma.decompress(raw_note))
            log(IMPORTANT, f" - {note.title}")

    conn.close()
    input("\n[ENTER] to continue.")
    return True


def scan_db():
    """Scan the DB and list possible issues before conversion."""

    if not (conn := open_db(cfg['database'])):
        return False

    notebooks = get_notebooks_from_db(conn)

    log(IMPORTANT, "Looking for issues in selected notebooks.")

    note_titles  = []
    attachments  = []
    full_paths   = []
    attachments_size = 0
    total_issues = 0
    notes_with_issues = 0
    max_path_len  = cfg["max_path_len"]
    max_attach_MB = cfg["max_attach_MB"] * 1024 * 1024

    def issue(msg):
        nonlocal total_issues
        log(IMPORTANT, f" - {msg}")
        total_issues += 1
        return 1

    for notebook in sorted(notebooks, key=lambda x: f"{x['stack' or '']}{x['name']}".lower() ):
        # Process only selected notebooks
        if cfg["notebooks"] and notebook["guid"] not in cfg["notebooks"]:
            continue

        # Folder names can't end with a space, so remove them
        stack_name    = (notebook["stack"] or "").strip()
        notebook_name = notebook["name"].strip()
        output_folder = to_posix(cfg["output_folder_md"])
        notebook_path = posix_join(output_folder, safe_join(stack_name, notebook_name))

        # Get number of notes in notebook
        cur = conn.execute(
                "select COUNT(*) from notes where notebook_guid=? and is_active=1",
                (notebook["guid"],) )
        num_notes = int(cur.fetchone()[0])
        prefix    = stack_name or ""
        if prefix: prefix = f"{prefix} / "
        log(IMPORTANT, f"{prefix}{notebook_name} ({num_notes:,} notes)")

        # Check for invalid names in stacks, notebooks
        if (chars := is_invalid_obsidian_title(stack_name)):
            issue(f"Invalid chars [{chars}] in stack name: {stack_name}")
        if (chars := is_invalid_obsidian_title(notebook_name)):
            issue(f"Invalid chars [{chars}] in notebook name: {notebook_name}")
        if stack_name.endswith("."):
            issue(f"Folder name from stack cannot end with a dot: {stack_name}")
        if notebook_name.endswith("."):
            issue(f"Folder name from notebook cannot end with a dot: {notebook_name}")
        if stack_name.startswith("."):
            issue(f"Folder name from stack starting with a dot will be hidden: {stack_name}")
        if notebook_name.startswith("."):
            issue(f"Folder name from notebook starting with a dot will be hidden: {notebook_name}")

        # Check each note in the notebook for issues
        cur = conn.execute(
                "select is_active, raw_note from notes where notebook_guid=? "
                "order by title COLLATE NOCASE",
                (notebook["guid"], ) )

        for row_note in cur:
            is_active, raw_note = row_note

            # Skip processing deleted notes according to config.
            if not (is_active or cfg["export_trash"]):
                continue

            # Insert Rick and Morty reference...
            note = pickle.loads(lzma.decompress(raw_note))

            note_has_issue = 0
            re_note_content = re.search("<en-note[^>]*?>(.+?)</en-note>", note.content, re.DOTALL)
            note_content = re_note_content[1] if re_note_content else ""
            note_titles.append(note.title)

            # Check for invalid names in note titles
            if (chars := is_invalid_obsidian_title(note.title)):
                note_has_issue = issue(f"[{note.title}] Invalid chars [{chars}] in note title")
            # Don't check if title ends with period, since file will end with ".md"
            if note.title.startswith("."):
                note_has_issue = issue(f"[{note.title}] Note title starting with a dot will be hidden")

            # Check if note content is empty
            if not cfg["export_empty_note"]:
                if not note_content.replace("<div><br/></div>", ""):
                    note_has_issue = issue(f"[{note.title}] Empty note")

            # Check if there are tables with "colspan" or "rowspan" > 1
            if cfg["check_tables"]:
                num_span = re.findall(r'(?:col|row)span="(\d+)"', note_content)
                if any(n != "1" for n in num_span):
                    note_has_issue = issue(f"[{note.title}] Merged cell in a table")

            # Check if there is "HTML Content" in the note. That is any HTML
            # content not editable in Evernote (but there is no list of that
            # content, AFAIK, so this is probably only a very small sample).
            # Can produce some false positives.
            if re.findall(r'style="[^"]*(flex:|box-shadow:|float:\s*(?:left|right)|position:\s*(?:absolute|fixed|sticky))', note_content):
                note_has_issue = issue(f'[{note.title}] "HTML Content" block in note')

            # Another unsupported HTML content is nested tables
            soup = BeautifulSoup(note_content, "html.parser")
            tables = cast(Sequence[Tag], soup.find_all("table"))
            if any(table.find("table") for table in tables):
                note_has_issue = issue(f"[{note.title}] Nested tables in note")

            # Check for formatting not supported in Markdown
            if cfg["check_format"]:
                unsupported = {
                    "table of contents" : "--en-tableofcontents:true",
                    "underline"         : "<u>",
                    "superscript"       : "<sup>",
                    "subscript"         : "<sub>",
                    "highlight (red)"   : "--en-highlight:red",
                    "highlight (green)" : "--en-highlight:green",
                    "highlight (blue)"  : "--en-highlight:blue",
                    "highlight (purple)": "--en-highlight:purple",
                    "highlight (orange)": "--en-highlight:orange",
                    "font type"         : "--en-fontfamily:",
                    "font size"         : "font-size:",
                    "font color"        : ('"color:', 'font color='),
                   #"HTML content": Any "uneditable" HTML in Evernote, such as
                   # nested tables, appears in an "HTML content" box.
                }
                # TO-DO: add this somehow in the configuration ?
                ignore_regex = set((
                    r'color\s*:\s*rgb\s*\(\s*24\s*,\s*168\s*,\s*65\s*', # green color for internal links
                    r"color\s*:\s*rgb\s*\(\s*105\s*,\s*170\s*,\s*53",   # green color for internal links
                    r"color\s*:\s*#69aa35",                             # green color for internal links
                    r"color\s*:\s*rgb\(\s*71,\s*18\s*,\s*100",          # white / blueish color?
                    r"border-color\s*:\s*#ccc",                         # border color of table cells
                ))
                filtered_note_content = note_content
                for regex in ignore_regex:
                    filtered_note_content = re.sub(regex, "", filtered_note_content)
                issues = []
                for issue_name, issue_tests in unsupported.items():
                    for test in issue_tests if isinstance(issue_tests, tuple) else (issue_tests,):
                        if test in filtered_note_content:
                            issues.append(issue_name)
                if issues:
                    note_has_issue = issue(f"[{note.title}] Unsupported formatting: {', '.join(issues)}")

            # Attachment tests
            for resource in note.resources or []:
                fn = resource.attributes.fileName
                if fn:
                    fn = fn.strip()
                    attachments.append(fn)
                    # Save full path of attachments for later tests
                    # TO-DO: create single function to create this path; let user set another value in cfg instead of "_resources"
                    full_path = posix_join(notebook_path, "_resources", safe_path(fn))
                    full_paths.append(full_path)

                    # Check max. path length
                    if max_path_len and len(full_path) > max_path_len:
                        note_has_issue = issue(f"[{note.title}] Exported attachment path will have {len(full_path)} characters: {full_path}")

                    # Check for invalid names in attachments
                    if (chars := is_invalid_obsidian_title(fn)):
                        note_has_issue = issue(f"[{note.title}] Invalid chars [{chars}] in attachment name: {fn}")
                    if fn.endswith("."):
                        note_has_issue = issue(f"[{note.title}] Invalid chars in attachment name: {fn}")

                    # Check for 0 bytes attachments
                    # assert resource.data.size == len(resource.data.body)
                    attachments_size += resource.data.size
                    if not cfg["export_empty_file"] and resource.data.size == 0:
                        note_has_issue = issue(f"[{note.title}] Empty (0 bytes) attachment: {fn}")

                    if max_attach_MB and resource.data.size > max_attach_MB:
                        note_has_issue = issue(f"[{note.title}] Resource size: {resource.data.size / (1024*1024):.2f} MB - {fn}")

            notes_with_issues += note_has_issue

    # Check for repeated note titles
    total_issues += repeated_strings(note_titles, "Repeated note titles:")

    # Check for repeated attachment file names
    total_issues += repeated_strings(attachments, "Repeated attachment file names:")

    if total_issues:
        log(IMPORTANT, f"{total_issues:,} issues found in {notes_with_issues} notes.")

    conn.close()
    input("\n[ENTER] to continue.")
    return True


def confirm_conversion_dialog(title="Confirm conversion?"):
    return button_dialog(
        title = title,
        text  = """Did you check for issues already? If so, proceed; otherwise, better cancel and check.
Did you select the notebooks you want to convert? (No selection = export all!)
To avoid broken links, select and export all notebooks at the same time.
Some issues can be fixed manually in Evernote, or automatically during conversion (but not all).
Review the configuration menu for options affecting automatic fixes.
Quit and resync (evernote-backup sync) if you changed data in Evernote since last sync.
I recommend closing Obsidian before starting conversion to avoid issues.
Be sure to enable logging and check it after conversion.""",
        buttons=[
            ("Convert", True    ),
            ("Cancel",  "Cancel"),
            ("Quit",    None    ),
        ],
    ).run()


def get_unique_filename(filename, existing_files):
    if '.' in filename:
        name, extension = filename.rsplit('.', 1)
        extension = '.' + extension  # Keep the '.' in the extension
    else:
        name = filename
        extension = ''

    unique_filename = filename
    counter = 1
    while unique_filename.lower() in existing_files:
        unique_filename = f"{name}({counter}){extension}"
        counter += 1

    # Truncate the filename component if it exceeds the filesystem limit
    parts = unique_filename.rsplit("/", 1)
    if len(parts) == 2:
        unique_filename = parts[0] + "/" + truncate_filename(parts[1])
    else:
        unique_filename = truncate_filename(unique_filename)

    return unique_filename


class Exporter:
    def __init__(self, 
                 format,
                 confirm_title,
                 output_folder,
                 note_ext,
                 ):
        self.format        = format
        self.output_folder = to_posix(output_folder)
        self.confirm_title = confirm_title
        self.note_ext      = note_ext


    def convert(self, note, content, guid_to_path, path_to_guid, hash_to_paths, tasks, options):
        raise NotImplementedError("Subclasses must implement this method")


    def export(self):
        option = confirm_conversion_dialog(self.confirm_title)
        if option is None:     return False
        if option == "Cancel": return True

        export_start = datetime.now()

        if not (conn := open_db(cfg['database'])):
            return False

        def get_tasks_for_note_id(note_guid):
            tasks = {}
            # Get tasks for this note
            try:
                cursor = conn.execute(
                    "select guid, raw_task from tasks where note_guid=?",
                    (note_guid, ) )
            except sqlite3.OperationalError as e:
                log(logging.DEBUG, f"Tasks table not found in the database. Skipping task processing for note {note_guid}.")
                return tasks
            except Exception as e:
                log(logging.WARN, f"Error executing query for tasks for note {note_guid}: {e}")
                return tasks
            for task_guid, raw_task in cursor:
                try:
                    task = json.loads(lzma.decompress(raw_task).decode("utf-8"))
                    # Get reminders for this task
                    for reminder_guid, raw_reminder in conn.execute(
                        "select guid, raw_reminder from reminders where task_guid=?",
                        (task_guid,) ):
                        try:
                            reminder = json.loads(lzma.decompress(raw_reminder).decode("utf-8"))
                            task["reminders"].append(reminder)
                        except Exception as e:
                            log(logging.CRITICAL, f"Error reading reminder for task {task_guid}): {e}")
                    tasks[task_guid] = task
                except Exception as e:
                    log(logging.CRITICAL, f"Error reading task {task_guid} (for note {note_guid}): {e}")
            return tasks

        def get_note_notecontent(row_note):
            note, note_content, tasks = False, False, {}
            is_active, raw_note = row_note
            # Skip processing deleted notes according to config.
            if is_active or cfg["export_trash"]:
                # Insert Rick and Morty reference... 🥒
                note = pickle.loads(lzma.decompress(raw_note))
                re_note_content = re.search("<en-note[^>]*?>(.+?)</en-note>", note.content, re.DOTALL)
                note_content = re_note_content[1] if re_note_content else ""
                # Check if note content is empty
                if not cfg["export_empty_note"]:
                    if not note_content.replace("<div><br/></div>", ""):
                        return False, False, tasks
                # Check if there are tasks & reminders in the db for this note
                tasks = get_tasks_for_note_id(note.guid)

            return note, note_content, tasks

        # Log configuration used for this conversion
        log(IMPORTANT, f"Configuration used for this conversion:")
        for option in sorted(cfg.keys()):
            if option != "notebooks":
                log(IMPORTANT, f"  {option}: {cfg[option]}")

        # 1st pass: get all note / attachment titles and IDs to make correct links later.
        log(IMPORTANT, f"Reading notebooks and notes from {cfg['database']}. This might take a while...")
        errors           = []
        guid_to_path_rel = {} # Keep track of Evernote internal links to notes and files (relative path, used in links in the notes)
        guid_to_path_abs = {} # Keep track of Evernote internal links to notes and files (absolute path, used internally during conversion)
        path_to_guid     = {} # Keep track of Evernote internal links to notes and files
        hash_to_paths    = {} # Keep track of Evernote hashes to attachments
        filenames_set    = set() # Keep track of filenames in lowercase
        notebook_data    = []
        notebooks        = get_notebooks_from_db(conn)
        sorted_notebooks = sorted(notebooks, key=lambda x: f"{x['stack' or '']}{x['name']}".lower() )

        for notebook in sorted_notebooks:
            # If we process only selected notebooks, processing time can be 
            # shortened, but links to notes in other notebooks won't be found.
            if cfg["notebooks"] and notebook["guid"] not in cfg["notebooks"]:
                continue

            # Folder names can't end with a space or dot, so remove them
            stack_name        = (notebook["stack"] or "").strip()
            notebook_name     = notebook["name"].strip()
            stack_name        = safe_path(re.sub(r"[\s\.]+$", "", stack_name))
            notebook_name     = safe_path(re.sub(r"[\s\.]+$", "", notebook_name))
            notebook_path_rel = posix_join(stack_name, notebook_name)
            notebook_path_abs = posix_join(self.output_folder, notebook_path_rel)
            notebook_data.append({
                "guid"    : notebook["guid"],
                "path_rel": notebook_path_rel,
                "path_abs": notebook_path_abs,
            })

            # Get notes in the current notebook
            for row_note in get_notes_from_notebook(conn, notebook["guid"]):
                note, note_content, tasks = get_note_notecontent(row_note)
                if not note: # skip deleted or empty notes, according to config.
                    continue

                # Create unique RELATIVE note path from notebook and note title
                safe_name     = truncate_filename(safe_path(f"{note.title}{self.note_ext}"))
                if cfg["links_with_folders"]:
                    candidate     = posix_join(notebook_path_rel, safe_name)
                    note_path_rel = get_unique_filename(candidate, filenames_set)
                    safe_name     = note_path_rel.rsplit("/", 1)[-1]
                else:
                    note_path_rel = get_unique_filename(safe_name, filenames_set)
                    safe_name     = note_path_rel
                note_path_abs = posix_join(notebook_path_abs, safe_name)
                filenames_set.add(note_path_rel.lower())
                path_to_guid    [note_path_rel] = note.guid
                guid_to_path_rel[note.guid]     = note_path_rel
                guid_to_path_abs[note.guid]     = note_path_abs

                # Create unique RELATIVE attachment path from notebook attachment name
                for resource in note.resources or []:
                    if not cfg["export_empty_file"] and resource.data.size == 0:
                        continue

                    # In theory, we should preserve the original file name.
                    # Unfortunately, some files have no name, invalid name, or repeated names,
                    # and there can be issues in Obsidian displaying files with wrong extension.
                    # So, be sure attachment has a file name with correct extension.
                    fn        = resource.attributes.fileName or "unnamed"
                    mime_ext  = mimetypes.guess_extension(resource.mime, strict=False) # "image/png" -> ".png"
                    root, ext = os.path.splitext(fn)
                    if root.strip() == "":
                        root = "unnamed"
                    if ext.strip() == "" and resource.mime != "application/octet-stream":
                        ext = mime_ext
                    fn = truncate_filename(safe_path(f"{root}{ext}"))

                    # TO-DO:
                    # - Allow user to select folder for attachments (one per notebook / one per note ?)
                    #   - In case of HTML files, use "correct" format ([html file without ext]_files) ?
                    # - We're also not checking if there are links to each/all attachment in the note content. But should we?
                    attachment_folder_rel = "_resources"
                    # Create a unique full relative path for the attachment
                    full_attachment_path_rel = posix_join(notebook_path_rel, attachment_folder_rel, fn)
                    unique_full_path_rel     = get_unique_filename(full_attachment_path_rel, filenames_set)
                    attachment_path_rel      = to_posix(os.path.relpath(unique_full_path_rel, notebook_path_rel)) # Path relative to note
                    attachment_path_abs      = posix_join(self.output_folder, unique_full_path_rel)

                    fn = os.path.split(attachment_path_abs)[-1]
                    if resource.attributes.fileName and fn != resource.attributes.fileName:
                        log(logging.WARNING, f'  - Attachment renamed from "{resource.attributes.fileName}" to "{attachment_path_abs}" in {note_path_abs}')

                    # Obsidian seems to support relative paths in HTML tags now. But it previously didn't. See:
                    # https://forum.obsidian.md/t/support-img-and-video-tag-with-src-relative-path-format/18647/47
                    # if self.format == "HTML" and self.note_ext == ".md":
                    #     # Use RELATIVE paths in attachment_path if converting to Markdown or to HTML files
                    #     # Use ABSOLUTE paths in attachment_path if converting to .md files in HTML format
                    #     attachment_path_rel = attachment_path_abs
                    filenames_set.add(unique_full_path_rel.lower())
                    path_to_guid[attachment_path_rel] = resource.guid
                    guid_to_path_rel[resource.guid]   = attachment_path_rel
                    guid_to_path_abs[resource.guid]   = attachment_path_abs
                    hash = int.from_bytes(resource.data.bodyHash) # Better int than .hex().zfill(32) ?
                    # Store all paths for a given hash, keyed by the note's GUID
                    if hash not in hash_to_paths:
                        hash_to_paths[hash] = {}
                    hash_to_paths[hash][note.guid] = attachment_path_rel

        # 2nd pass: export notes
        log(IMPORTANT, f"Exporting from {cfg['database']} to {self.format} into {self.output_folder}")

        for nb_data in notebook_data:
            notebook_guid     = nb_data["guid"]
            notebook_path_rel = nb_data["path_rel"]
            notebook_path_abs = nb_data["path_abs"]

            # Get number of notes in notebook
            cur = conn.execute(
                    "select COUNT(*) from notes where notebook_guid=? and is_active=1",
                    (notebook_guid,) )
            num_notes = int(cur.fetchone()[0])
            log(IMPORTANT, f"{num_notes:5,} notes - {notebook_path_abs}")

            os.makedirs(notebook_path_abs, exist_ok=True)

            # Get notes in the current notebook
            for row_note in get_notes_from_notebook(conn, notebook_guid):
                note, note_content, tasks = get_note_notecontent(row_note)
                if not note: # skip deleted or empty notes, according to config.
                    continue

                note_path_abs = guid_to_path_abs[note.guid]

                if not cfg["overwrite"] and os.path.exists(note_path_abs):
                    log(logging.WARNING, f"  - Skipping, already exists: {note_path_abs}")
                    save_note = False
                else:
                    log(logging.INFO, f"  - {note_path_abs}")
                    save_note = True

                # Convert "single tasks" into "task groups"
                def epoch_to_local_time(epoch, tz):
                    dt_utc   = datetime.fromtimestamp(epoch, tz=timezone.utc)
                    dt_local = dt_utc.astimezone(ZoneInfo(tz))
                    return dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')

                task_groups = {}
                for id, task in tasks.items():
                    group_id  = task["taskGroupNoteLevelID"]
                    label     = task["label"]
                    if "dueDate" in task:
                          due = epoch_to_local_time(task["dueDate"] // 1000, task["timeZone"])
                          due = f" 📅 {due}"
                    else: due = ""
                    reminders = ""
                    for reminder in task["reminders"]:
                        bell = "🔔" if reminder.get("status") == "active" else "🔕"
                        rmd_due = epoch_to_local_time(reminder["reminderDate"] // 1000, reminder["timeZone"])
                        reminders += f" {bell} {rmd_due}"
                    flag      = "🚩" if task.get("flag") else ""
                    completed = "x" if task.get("status") == "completed" else " "
                    # Still missing: task priority: 🐢 low, ⚠️ medium, 🔥 high (where and how is it stored?)
                    task_txt  = f"- [{completed}] {flag} {label}{due}{reminders}\n"
                    task_groups[group_id] = task_groups.get(group_id, "") + task_txt

                # Process attachments
                for resource in note.resources or []:
                    if not cfg["export_empty_file"] and resource.data.size == 0:
                        continue

                    attachment_path_abs = guid_to_path_abs[resource.guid]

                    # Save attachment file
                    os.makedirs(os.path.dirname(attachment_path_abs), exist_ok=True)
                    if not cfg["overwrite"] and os.path.exists(attachment_path_abs):
                        log(logging.WARNING, f"    - Skipping, already exists: {attachment_path_abs}")
                    else:
                        try:
                            with open(attachment_path_abs, "wb") as fh:
                                fh.write(resource.data.body)
                            log(logging.INFO, f"    - ({len(resource.data.body):,} bytes) {attachment_path_abs}")
                        except Exception as e:
                            errors.append( log(logging.ERROR, f"  Error saving {attachment_path_abs}: **{e}**") )

                if save_note:
                    # Prepare note properties
                    md_properties = ["---"]
                    if note.created:
                        time_ = datetime.fromtimestamp(note.created//1000).strftime('%Y-%m-%d %H:%M:%S')
                        md_properties.append(f"Created at: {time_}")
                    if note.updated:
                        time_ = datetime.fromtimestamp(note.updated//1000).strftime('%Y-%m-%d %H:%M:%S')
                        md_properties.append(f"Last updated at: {time_}")
                    if note.attributes.sourceURL: md_properties.append(f"Source URL: {note.attributes.sourceURL}")
                    if note.attributes.author:    md_properties.append(f"Author: {note.attributes.author}")
                    # if note.attributes.subjectDate:       md_properties.append(f"subjectDate: {note.attributes.subjectDate}")
                    # if note.attributes.latitude:          md_properties.append(f"latitude: {note.attributes.latitude}")
                    # if note.attributes.longitude:         md_properties.append(f"longitude: {note.attributes.longitude}")
                    # if note.attributes.altitude:          md_properties.append(f"altitude: {note.attributes.altitude}")
                    # if note.attributes.source:            md_properties.append(f"source: {note.attributes.source}")
                    # if note.attributes.sourceApplication: md_properties.append(f"sourceApplication: {note.attributes.sourceApplication}")
                    # if note.attributes.shareDate:         md_properties.append(f"shareDate: {note.attributes.shareDate}")
                    # if note.attributes.reminderOrder:     md_properties.append(f"reminderOrder: {note.attributes.reminderOrder}")
                    # if note.attributes.reminderDoneTime:  md_properties.append(f"reminderDoneTime: {note.attributes.reminderDoneTime}")
                    # if note.attributes.reminderTime:      md_properties.append(f"reminderTime: {note.attributes.reminderTime}")
                    # if note.attributes.placeName:         md_properties.append(f"placeName: {note.attributes.placeName}")
                    # if note.attributes.contentClass:      md_properties.append(f"contentClass: {note.attributes.contentClass}")
                    # if note.attributes.applicationData:   md_properties.append(f"applicationData: {note.attributes.applicationData}")
                    # if note.attributes.lastEditedBy:      md_properties.append(f"lastEditedBy: {note.attributes.lastEditedBy}")
                    # if note.attributes.classifications:   md_properties.append(f"classifications: {note.attributes.classifications}")
                    # if note.attributes.creatorId:         md_properties.append(f"creatorId: {note.attributes.creatorId}")
                    # if note.attributes.lastEditorId:      md_properties.append(f"lastEditorId: {note.attributes.lastEditorId}")
                    if note.tagNames:
                        md_properties.append("tags:")
                        for tag in note.tagNames:
                            tag_name = tag.replace(" ", "-")
                            md_properties.append(f" - {tag_name}")
                    md_properties.append("---\n")
                    md_properties = "\n".join(md_properties)

                    # Convert note body to HTML or Markdown
                    converted_content, conversion_issues = self.convert(
                        note, note_content, guid_to_path_rel, path_to_guid, hash_to_paths, task_groups, cfg)

                    if conversion_issues:
                        log(logging.WARNING, f'Issues converting "{note.title}" ({note_path_abs}):')
                        for issue in conversion_issues:
                            log(logging.WARNING, f"  - {issue}")

                    # Save note
                    try:
                        with open(note_path_abs, "w", encoding="utf-8") as fh:
                            if self.note_ext == ".md":
                                fh.write(md_properties)
                            if cfg["first_line_empty"]:
                                converted_content = "\n" + converted_content
                            fh.write(converted_content)
                    except Exception as e:
                        errors.append( log(logging.ERROR, f"  Error saving {note_path_abs}: **{e}**") )

        if errors:
            log(logging.ERROR, f"{len(errors):,} error(s) found.")
            for error in errors:
                log(logging.ERROR, error)

        conn.close()

        export_end = datetime.now()
        duration = export_end - export_start
        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        log(IMPORTANT, f"  Start:    {export_start.strftime('%Y-%m-%d %H:%M:%S')}")
        log(IMPORTANT, f"  End:      {export_end.strftime('%Y-%m-%d %H:%M:%S')}")
        log(IMPORTANT, f"  Duration: {hours:02d}:{minutes:02d}:{seconds:02d}")

        input("\n[ENTER] to continue.")
        return True


class Exporter_HTML(Exporter):
    def __init__(self):
        super().__init__(
            format        = "HTML",
            confirm_title = "Confirm conversion from Evernote to HTML?",
            output_folder = to_posix(cfg['output_folder_html']),
            note_ext      = ".md" if cfg["html_with_md_ext"] else ".html",
        )


    def convert(self, note, content, guid_to_path, path_to_guid, hash_to_paths, tasks, options):

        errors = []

        def subs_en_media(regex_match) -> str:
            en_media = regex_match[1]
            result = en_media
            type_  = re.findall('type="([^"]+)"', en_media)[0]
            hash_hex = re.findall('hash="([^"]+)"', en_media)[0]
            hash_int = int(hash_hex, 16)

            # Find the correct path for this attachment in this specific note
            note_hash_paths = hash_to_paths.get(hash_int, {})
            path = note_hash_paths.get(note.guid)

            if not path:
                # Fallback to any available path if the specific one isn't found
                path = next(iter(note_hash_paths.values()), None)
                if path is None:
                    log(logging.ERROR, f"    - [ERROR] Path to media hash not found: {hash_hex}")
                    path = hash_hex # Use the hex string as a fallback path

            if type_.startswith("image"):
                    width  = (re.findall(' width="[^"]+"',  en_media) or [""])[0]
                    height = (re.findall(' height="[^"]+"', en_media) or [""])[0]
                    result = f'<img src="{path}"{width}{height} />'
            elif self.note_ext == ".md":
                # Obsidian doesn't support most of the HTML tags below,
                # so just create the simplest link
                result = f'<a href="{path}">{path}</a>'
            else: 
                if type_.startswith("video"):
                    result = f'<video controls><source src="{path}" type="{type_}"></video>'
                elif type_.startswith("audio"):
                    result = f'<audio controls><source src="{path}" type="{type_}"></audio>'
                elif type_ == "application/pdf":
                    if "--en-viewAs:attachment" in en_media:
                        result = f'<a href="{path}">{path}</a>'
                    else:
                        result = f'<iframe src="{path}" width="100%" height="500px"></iframe>'
                else:
                    result = f'<a href="{path}">{path}</a>'
            return result

        def subs_href(regex_match) -> str:
            guid = regex_match[1] or regex_match[2]
            # <guid>#<guid> -> Links to items inside notes?
            guid = guid.split("#")[0]
            if not (path := guid_to_path.get(guid)):
                path  = regex_match[0]
                log(logging.ERROR, f"    - [ERROR] Path to GUID not found: {guid} ({path})")
            return f'"{path}"'

        content = re.sub(r'<en-media ([^>]+)\s*/>', subs_en_media, content)
        content = re.sub(r'"(?:evernote:///view/[^/]+/[^/]+/(.+?)/.+?|https://share.evernote.com/note/(.+?))"', subs_href, content)
        return content, errors


class Exporter_MD(Exporter):
    def __init__(self):
        super().__init__(
            format        = "Markdown",
            confirm_title = "Confirm conversion from Evernote to Obsidian Markdown?",
            output_folder = to_posix(cfg['output_folder_md']),
            note_ext      = ".md",
        )
        self.converter = EvernoteHTMLToMarkdownConverter(use_html=cfg["html_with_md_ext"])


    def convert(self, note, content, guid_to_path, path_to_guid, hash_to_paths, tasks, options):
        # Create a simple {hash: path} dictionary for the current note for the converter
        note_specific_hash_to_path = {
            hash_val: paths.get(note.guid)
            for hash_val, paths in hash_to_paths.items() if note.guid in paths
        }
        markdown_content, warnings = self.converter.convert_html_to_markdown(
            content, 
            md_properties = [], # actually processed by parent of this
            tasks = tasks,
            guid_to_path = guid_to_path,
            hash_to_path = note_specific_hash_to_path,
            options      = options)

        # if warnings:
        #     for warning in warnings:
        #         log(logging.WARNING, f"   - {warning}")

        return markdown_content, warnings


def export_html():
    html_exporter = Exporter_HTML()
    return html_exporter.export()


def export_md():
    markdown_exporter = Exporter_MD()
    return markdown_exporter.export()


def read_vault(vault_folder):
    md_data   = {} # K: full path for .md files,            V: note content
    abs_paths = {} # K: full path for non-.md files,        V: { "links": 0 }
    all_paths = {} # K: full & partial paths for all files, V: count of files with this K path
    for root, dirs, files in os.walk(vault_folder):
        root = to_posix(root).lower()
        for file in files:
            file = file.lower()
            full_path = posix_join(root, file)
            if file.endswith(".md"):
                try:
                    with open(full_path, 'r', encoding='utf-8') as md_file:
                        md_data[full_path] = md_file.read()
                except Exception as e:
                    log(logging.CRITICAL, f"scan_vault(): error reading {full_path}: {e}")
            else:
                abs_paths[full_path] = { "links": 0 }
            # Split full_path into parts and combine them for all possible partial paths
            parts = full_path.split("/")
            for i in range(len(parts)):
                partial_path = "/".join(parts[i:]) 
                all_paths[partial_path] = all_paths.get(partial_path, 0) + 1

    return md_data, abs_paths, all_paths


def scan_vault():
    # Read all vault .md files into memory. Not a bright idea if your vault 
    # is really large, but is only 12 MB in 3k notes in mine, so...
    vault_path = cfg["output_folder_md"]
    log(IMPORTANT, f"Looking for issues in the vault at {vault_path}")

    md_files, abs_paths, all_paths = read_vault(vault_path)

    stats = {
        "Scanned notes": len(md_files),
        "Empty notes": 0,
        "External links": 0,
        "Internal links": 0,
        "Internal links not found": 0,
        "Non-Markdown files": len(abs_paths),
       #"Unlinked files": 0, # should rework the code to count this
        "File name conflicts": 0,
    }

    note_titles = set([os.path.split(x)[-1][:-3].lower() for x in md_files])

    for md_path, md_data in md_files.items():
        # Show "empty" notes
        if re.match(r"^\s*$", md_data):
            log(IMPORTANT, f" - Empty note ({len(md_data)} bytes): {md_path}")
            stats["Empty notes"] += 1

        # Count ext. & int. links, internal links not found, linked files
        clean_md_data  = re.sub(r'```.*?```', '', md_data, flags=re.S)     # Remove code blocks (multiline)
        clean_md_data  = re.sub(r'`[^`]*`', '', clean_md_data, flags=re.S) # Remove inline code (single line)
        external_links = re.findall(r"\[[^\]]+?\]\((.+?)\)", clean_md_data, flags=re.S)
        stats["External links"] += len(external_links)
        internal_links = re.findall(r"(?<!\\)\[\[([^\]]+?)\]\]", clean_md_data, flags=re.S)
        note_parent_path = os.path.split(md_path)[0]
        for link in internal_links:
            stats["Internal links"] += 1
            link = posix_normpath(link.split("|")[0]).lower()
            if link.endswith("\\"):
                link = link[:-1]
            if link not in note_titles:
                full_path = posix_abspath(posix_join(note_parent_path, link))
                if not os.path.exists(full_path):
                    # Obsidian can find a relative or partial file name anywhere in the vault.
                    # If there is just one matching path or file name for a link, that's OK.
                    # Otherwise, alert that there might be a conflict.
                    count = all_paths.get(link, 0)
                    if count > 1:
                        log(IMPORTANT, f" - File name conflict: {link} can refer to {count} files")
                        stats["File name conflicts"] += 1
                    elif count < 1:
                        log(IMPORTANT, f" - Internal link '{link}' not found in {md_path}")
                        stats["Internal links not found"] += 1
                else:
                    if full_path in abs_paths:
                        abs_paths[full_path]["links"] += 1

    #stats["Unlinked files"] = sum((files_data[x]["links"] == 0 for x in files_data))

    log(IMPORTANT, "Results")
    for k, v in stats.items():
        log(IMPORTANT, f"  {k:24}: {v:9,}")

    input("\n[ENTER] to continue.")
    return True


def main_menu():
    option = radiolist_dialog(
        title  = f"Evernote2Obsidian Markdown converter v.{__version__}",
        text   = "Use mouse/keyboard (TAB/arrows/PgUp/PgDn: navigate; ENTER/SPACE: select):",
        ok_text     = "Run sel.",
        cancel_text = "Quit",
        values = [
            (cfg_menu,      "Configuration"),
            (sel_nb_menu,   "Select Evernote notebooks to process"),
            (list_db,       "List notes in selected notebooks"),
            (scan_db,       "Scan selected notebooks for issues (so you can fix them before exporting)"),
            (export_html,   "Export selected notebooks as HTML and attachments"),
            (export_md,     "Export selected notebooks as Obsidian Markdown and attachments"),
            (scan_vault,    "Scan Obsidian Vault for issues"),
        ],
    ).run()

    if callable(option):
        return option()

    return False


def main():
    while main_menu():
        pass


if __name__ == '__main__':
    main()
    restart_log(just_close=True)
