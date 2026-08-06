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
# 2026.08.04  0.1.8, fixed #30 "How about numerical tags?"
# 2026.03.16  0.1.7, fixed #19 "Preserve notes with duplicate titles"
# 2026.02.10  0.1.6, fixed #16 "Wrong/Missing image extension"
# 2026.01.04  0.1.5, improved attachment handling and conversion robustness
#                    (#13 by quiettype), fixed some Pylance warnings
# 2025.08.18  0.1.3, fixed #9 "SyntaxWarning due to invalid escape sequences"
# 2025.05.23  0.1.0, 1st release
# 2024.10.08  0.0.1, 1st version

__version__ = "0.1.8"
__author__  = "AltoRetrato"

import os
import re
import json
import lzma
import pickle
import logging
import sqlite3
import mimetypes
import hashlib
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
TAG_PREFIX = "tag-"
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
    ("pdf_view",           "hybrid",            "Show PDFs as",                  "Choose how ALL PDF files will appear in the converted notes:\n - default: The same way as they appear in Evernote\n - title  : Show PDFs only as the title\n - preview: Preview of the first PDF page\n - hybrid : Preview if single PDF, title if consecutive PDFs"),
    ("first_line_empty",   False,               "Make first note line empty",    "If True, add an empty line at the beginning of the note.\nThis is a cosmetic hack to avoid Obsidian showing code when you open a note in editing view."),
    ("remove_green_link",  False,               "Remove color of green links",   "For a while, Evernote made internal links (links to other notes) green.\nI recommend removing them and using a CSS snippet in Obsidian instead\nif you want all internal links to be green."),
    ("escape_brackets",    False,               "Replace [] with () in links",   "Square brackets [] are special characters in Markdown.\nThey can appear the text portion of your links, but might look a bit odd in Obsidian.\nSet this to True to replace them with parentheses ()."),
    ("numeric_tag_prefix", TAG_PREFIX,          "Prefix for numeric tags",      f"Prefix added to Evernote numerical tags (which are invalid in Obsidian).\nIf set to an empty string the default prefix ({TAG_PREFIX}) will be used.\nE.g., a tag [2026] would be exported as [{TAG_PREFIX}2026]."),
    ("links_with_folders", True,                "Include folder path in links",  "Obsidian can have multiple notes with the same name in different folders.\nSet this to True to include the folder path in links. This helps avoid confusion when multiple notes share the same name.\nSet this to False to use only the note title in links. This keeps links simpler but may cause conflicts if note names are duplicated."),
    ("notebooks",          None,                "",                              "Notebooks to export"),
    ("global_resources",   True,                "Global _resources folder",      "If True, all attachments are stored in a single _resources folder at the vault root.\nIdentical files (same content) are deduplicated.\nThis makes it easier to reorganize notes without moving attachment folders.\nIf False, each notebook gets its own _resources subfolder."),
    ("calendar_event_mode", "custom_callout",   "Calendar event rendering mode", "Choose how Evernote calendar events are rendered:\n - custom_callout: nested Obsidian custom callout\n - remove       : remove calendar event blocks\n - raw          : keep raw/default conversion (debug only)\nIf using custom callouts, enable the snippet in Obsidian:\nSettings → Appearance → CSS snippets."),
    ("web_clip_mode",     "hybrid",             "Web clip rendering mode",        "Choose how web clips are rendered:\n - hybrid     : show iframe + archived clipped content in collapsed callout\n - iframe_only: only iframe (legacy behavior)\n - content_only: only archived clipped content in collapsed callout\nIf using custom web-clip callouts, enable the snippet in Obsidian:\nSettings → Appearance → CSS snippets."),
    ("web_clip_iframe_width_px", 750,           "Web clip iframe width (px)",     "Fixed width for web-clip iframes (pixels)."),
    ("web_clip_iframe_height_px", 600,          "Web clip iframe height (px)",    "Fixed height for web-clip iframes (pixels)."),
    ("web_clip_callout_type", "custom-web-clip","Web clip callout type",         "Callout type name used for web clip callout blocks."),
    ("web_clip_iframe_callout_title", "Web clip", "Iframe callout title",         "Callout title for the iframe (live site) callout. Expanded by default."),
    ("web_clip_callout_title", "Archived web clip", "Archived callout title",     "Callout title for the archived content callout."),
    ("web_clip_callout_collapsed", True,        "Collapse archived callout",      "If True, archived web clip callouts are collapsed by default."),
    ("manage_custom_callout_css", True,         "Manage custom callout CSS",      "If True, converter writes/updates managed callout CSS snippet in your vault.\nAfter export, enable the snippet in Obsidian:\nSettings → Appearance → CSS snippets."),
    ("custom_callout_css_path", ".obsidian/snippets/custom-callout.css", "Custom callout CSS path", "Path (relative to vault root) for managed custom callout CSS snippet.\nAfter export, enable this snippet in Obsidian:\nSettings → Appearance → CSS snippets."),
    ("bold_date_log_to_headings", False,        "Bold date log to headings",     "If True, bold date entries like **29 June 2024** at the start of a line\nare converted to ## DD MMM YYYY headings."),
    ("date_log_history_heading",  False,        "Auto-insert History heading",   "If True, a '# History' heading is inserted before the first date entry\nthat has no preceding section heading. Requires bold_date_log_to_headings."),
    ("normalize_header_dates",    False,        "Normalize dates in headings",  "If True, any date in a heading (e.g. ## February 17, 2026) is normalized\nto DD MMM YYYY (e.g. ## 17 Feb 2026)."),
    ("bold_as_heading",    False,               "Bold lines as headings",        "If True, in notes with no headings, standalone bold lines\n(e.g. <div><b>Section title</b></div>) are promoted to h2 headings."),
    ("hr_as_h1",           False,               "Text + hr line as heading",     "If True, a text line immediately followed by a horizontal rule\nis converted to a level 1 heading (the hr is removed)."),
    ("normalize_heading_levels", True,          "Normalize heading hierarchy",   "If True, heading level gaps are closed (e.g. h1 followed by h3\nbecomes h1 followed by h2). Headings with proper hierarchy are unaffected."),
    ("suppress_attachment_rename_warnings", True, "Suppress attachment rename warnings", "If True, warnings for attachment renames due to auto-fixes (e.g., leading slash, duplicate, extension inference, query string) are suppressed. Only ambiguous/unfixable cases will warn."),
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
            option_data[option]["options"] = ["default", "title", "preview", "hybrid"]
        elif option == "log_level":
            option_data[option]["type"]    = list
            option_data[option]["options"] = ["debug", "info", "warning", "error", "critical"]
        elif option == "calendar_event_mode":
            option_data[option]["type"]    = list
            option_data[option]["options"] = ["custom_callout", "remove", "raw"]
        elif option == "web_clip_mode":
            option_data[option]["type"]    = list
            option_data[option]["options"] = ["hybrid", "iframe_only", "content_only"]

cfg     = Config(default=default_cfg) # Global var. used by most functions

_option_groups = {
    "database": "General",
    "output_folder_md": "General",
    "output_folder_html": "General",
    "html_with_md_ext": "General",
    "log_file": "General",
    "log_level": "General",
    "overwrite": "General",
    "notebooks": "General",
    "export_trash": "Export",
    "export_empty_note": "Export",
    "export_empty_file": "Export",
    "max_path_len": "Export",
    "max_attach_MB": "Export",
    "check_emojis": "Validation",
    "check_tables": "Validation",
    "check_format": "Validation",
    "suppress_attachment_rename_warnings": "Validation",
    "remove_green_link": "Markdown",
    "escape_brackets": "Markdown",
    "links_with_folders": "Markdown",
    "pdf_view": "Markdown",
    "first_line_empty": "Markdown",
    "bold_date_log_to_headings": "Headings",
    "date_log_history_heading": "Headings",
    "normalize_header_dates": "Headings",
    "bold_as_heading": "Headings",
    "hr_as_h1": "Headings",
    "normalize_heading_levels": "Headings",
    "calendar_event_mode": "Calendar",
    "web_clip_mode": "Web clips",
    "web_clip_iframe_width_px": "Web clips",
    "web_clip_iframe_height_px": "Web clips",
    "web_clip_callout_type": "Web clips",
    "web_clip_iframe_callout_title": "Web clips",
    "web_clip_callout_title": "Web clips",
    "web_clip_callout_collapsed": "Web clips",
    "manage_custom_callout_css": "Callout CSS",
    "custom_callout_css_path": "Callout CSS",
    "global_resources": "Resources",
}

_group_order = {
    "General": 0,
    "Export": 1,
    "Validation": 2,
    "Markdown": 3,
    "Headings": 4,
    "Calendar": 5,
    "Web clips": 6,
    "Callout CSS": 7,
    "Resources": 8,
}

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

    # Clear the log file at the start of a new run
    try:
        with open(cfg["log_file"], "w", encoding="utf-8") as f:
            pass
    except Exception as e:
        print(f"Could not clear log file: {e}")

    # Create new file handler (append mode, but file is now empty)
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
    def _menu_label(opt):
        group = _option_groups.get(opt, "Other")
        value = cfg[opt] if opt in cfg else default_cfg[opt]
        return f"[{group}] {option_data[opt]['name']}: {value}"

    ordered_options = sorted(
        option_data.keys(),
        key=lambda o: (_group_order.get(_option_groups.get(o, "Other"), 999), option_data[o]["name"].lower()),
    )
    values = [(o, _menu_label(o)) for o in ordered_options]
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
        return False

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


invalid_chars = r'[\\*"/<>:|?#^]'

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


_invalid_char_replacements = str.maketrans({
    '\\': '⧵',   # U+29F5  REVERSE SOLIDUS OPERATOR
    '*':  '∗',   # U+2217  ASTERISK OPERATOR
    '"':  '＂',  # U+FF02  FULLWIDTH QUOTATION MARK
    '/':  '∕',   # U+2215  DIVISION SLASH
    '<':  '＜',  # U+FF1C  FULLWIDTH LESS-THAN SIGN
    '>':  '＞',  # U+FF1E  FULLWIDTH GREATER-THAN SIGN
    ':':  '꞉',   # U+A789  MODIFIER LETTER COLON
    '|':  '｜',  # U+FF5C  FULLWIDTH VERTICAL LINE
    '?':  '？',  # U+FF1F  FULLWIDTH QUESTION MARK
    '#':  '＃',  # U+FF03  FULLWIDTH NUMBER SIGN   (heading anchor in wikilinks)
    '^':  '＾',  # U+FF3E  FULLWIDTH CIRCUMFLEX     (block ref in wikilinks)
})

_unicode_spaces = re.compile(r'[\u00A0\u2007\u202F\u2060\uFEFF]+')

def safe_path(path):
    path = _unicode_spaces.sub(' ', path.strip())
    return path.translate(_invalid_char_replacements)


def truncate_filename(filename, max_length=200):
    """
    Truncate filename to max_length while preserving extension.
    If filename is too long, uses a hash to ensure uniqueness.
    Windows path limit is 260 chars, so we use 200 as a safe default.
    """
    if len(filename) <= max_length:
        return filename
    
    root, ext = os.path.splitext(filename)
    if len(ext) > 10:  # Unreasonably long extension, might be wrong split
        ext = ""
    
    # Use a short hash of the original filename to preserve uniqueness
    file_hash = hashlib.md5(filename.encode()).hexdigest()[:8]
    available_length = max_length - len(ext) - len(file_hash) - 1  # -1 for underscore
    
    if available_length < 10:
        # Filename + extension is still too long, use just hash + extension
        return f"{file_hash}{ext}"
    
    truncated_root = root[:available_length]
    return f"{truncated_root}_{file_hash}{ext}"


def truncate_full_path(full_path, max_path_length=None):
    """
    Ensure full path doesn't exceed Windows MAX_PATH (260 chars).
    If too long, truncates the filename component intelligently.
    Uses cfg["max_path_len"] if not provided.
    Logs a warning if extension is dropped or replaced.
    """
    if max_path_length is None:
        max_path_length = cfg.get("max_path_len", 255)
    if len(full_path) <= max_path_length:
        return full_path

    # Split into directory and filename
    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)

    # Calculate how much space we have for the filename
    available_for_filename = max_path_length - len(directory) - 1  # -1 for separator

    if available_for_filename < 20:
        # Directory path is too long, use just a hash as filename
        file_hash = hashlib.md5(full_path.encode()).hexdigest()[:12]
        root, ext = os.path.splitext(filename)
        if len(ext) > 10:
            log(logging.INFO, f"Extension too long, replaced with .bin for file: {filename}")
            ext = ".bin"  # fallback extension
        return posix_join(directory, f"{file_hash}{ext}")

    # Truncate the filename to fit
    # Check if extension will be dropped in truncate_filename
    root, ext = os.path.splitext(filename)
    if len(ext) > 10:
        log(logging.INFO, f"Extension too long, dropped for file: {filename}")
    truncated_fn = truncate_filename(filename, available_for_filename - 10)  # -10 safety margin
    return posix_join(directory, truncated_fn)


def evernote_tag_to_obsidian(tag):
    tag_name = tag.replace(" ", "-")
    if tag_name.isnumeric():
        tag_name = f"{cfg.get('numeric_tag_prefix', TAG_PREFIX)}{tag_name}"
    return tag_name


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

    for notebook in sorted(notebooks, key=lambda x: f"{x.get('stack') or ''}{x.get('name') or ''}".lower()):
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

    def issue(msg, warn_type=None):
        nonlocal total_issues
        # If suppress_attachment_rename_warnings is True, suppress certain auto-fix warnings
        suppress = cfg.get("suppress_attachment_rename_warnings", False)
        if suppress and warn_type in {"auto-rename", "leading-slash", "duplicate", "extension-infer", "query-string"}:
            return 0
        log(IMPORTANT, f" - {msg}")
        total_issues += 1
        return 1

    for notebook in sorted(notebooks, key=lambda x: f"{x.get('stack') or ''}{x.get('name') or ''}".lower()):
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
                if not cfg.get("suppress_fixable_warnings", False):
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
                    if not cfg.get("suppress_fixable_warnings", False):
                        note_has_issue = issue(f"[{note.title}] Unsupported formatting: {', '.join(issues)}")

            # Check for tags that need conversion for Obsidian.
            for tag in note.tagNames or []:
                converted_tag = evernote_tag_to_obsidian(tag)
                if converted_tag != tag:
                    note_has_issue = issue(f"[{note.title}] Invalid tag [{tag}]. Rename it in Evernote, or it will be exported as [{converted_tag}]")

            # Attachment tests
            for resource in note.resources or []:
                fn = resource.attributes.fileName
                if fn:
                    fn = fn.strip()
                    attachments.append(fn)
                    fn_safe = safe_path(fn)
                    fn_safe = truncate_filename(fn_safe)
                    if cfg.get("global_resources", True):
                        full_path = posix_join(self.output_folder, "_resources", fn_safe)
                    else:
                        full_path = posix_join(notebook_path, "_resources", fn_safe)
                    # Apply full path truncation to match what export will do
                    full_path = truncate_full_path(full_path)
                    full_paths.append(full_path)

                    # Check max. path length
                    if max_path_len and len(full_path) > max_path_len:
                        if not cfg.get("suppress_fixable_warnings", False):
                            note_has_issue = issue(f"[{note.title}] Exported attachment path will have {len(full_path)} characters: {full_path}")

                    # Check for invalid names in attachments
                    if (chars := is_invalid_obsidian_title(fn)):
                        if not cfg.get("suppress_fixable_warnings", False):
                            note_has_issue = issue(f"[{note.title}] Invalid chars [{chars}] in attachment name: {fn}")
                    if fn.endswith("."):
                        if not cfg.get("suppress_fixable_warnings", False):
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


    def convert(self, note, content, guid_to_path, path_to_guid, hash_to_paths, tasks, options, deleted_guid_to_title):
        raise NotImplementedError("Subclasses must implement this method")


    def export(self):
        option = confirm_conversion_dialog(self.confirm_title)
        if option is None:     return False
        if option == "Cancel": return True

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
                log(logging.WARNING, f"Error executing query for tasks for note {note_guid}: {e}")
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
        deleted_guid_to_title = {} # Best-effort fallback targets for links to deleted notes
        filenames_set    = set() # Keep track of filenames in lowercase
        content_hash_to_global_path = {} # For global_resources dedup: content hash -> path relative to output root
        notebook_data    = []
        notebooks        = get_notebooks_from_db(conn)
        sorted_notebooks = sorted(notebooks, key=lambda x: f"{x.get('stack') or ''}{x.get('name') or ''}".lower())

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
                is_active, raw_note = row_note
                if not is_active:
                    try:
                        deleted_note = pickle.loads(lzma.decompress(raw_note))
                        deleted_guid_to_title[deleted_note.guid] = deleted_note.title or ""
                    except Exception as e:
                        log(logging.DEBUG, f"Could not parse deleted note metadata for fallback links: {e}")
                note, note_content, tasks = get_note_notecontent(row_note)
                if not note: # skip deleted or empty notes, according to config.
                    continue

                # Create unique RELATIVE note path from notebook and note title
                safe_name     = safe_path(f"{note.title}{self.note_ext}")
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
                # Strip .md extension for internal note links
                if note_path_rel.lower().endswith('.md'):
                    guid_to_path_rel[note.guid] = note_path_rel[:-3]
                else:
                    guid_to_path_rel[note.guid] = note_path_rel
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
                    mime_ext  = mimetypes.guess_extension(resource.mime, strict=False) or ""  # "image/png" -> ".png"
                    root, ext = os.path.splitext(fn)
                    if root.strip() == "":
                        root = "unnamed"
                    if ext.strip() == "" and resource.mime != "application/octet-stream":
                        ext = mime_ext
                    fn = safe_path(f"{root}{ext}")
                    fn = truncate_filename(fn)  # Truncate to avoid Windows path length limits

                    attachment_folder_rel = "_resources"
                    content_hash = int.from_bytes(resource.data.bodyHash)

                    if cfg.get("global_resources", True):
                        # Global mode: single _resources at vault root with dedup
                        if content_hash in content_hash_to_global_path:
                            # Same content already stored — reuse the global path
                            unique_full_path_rel = content_hash_to_global_path[content_hash]
                        else:
                            # New content — compute path, ensure filename uniqueness
                            full_attachment_path_rel = posix_join(attachment_folder_rel, fn)
                            unique_full_path_rel = get_unique_filename(full_attachment_path_rel, filenames_set)
                            filenames_set.add(unique_full_path_rel.lower())
                            content_hash_to_global_path[content_hash] = unique_full_path_rel
                    else:
                        # Per-notebook mode: _resources inside each notebook folder
                        full_attachment_path_rel = posix_join(notebook_path_rel, attachment_folder_rel, fn)
                        unique_full_path_rel = get_unique_filename(full_attachment_path_rel, filenames_set)
                        filenames_set.add(unique_full_path_rel.lower())

                    attachment_path_rel = to_posix(os.path.relpath(unique_full_path_rel, notebook_path_rel)) # Path relative to note
                    attachment_path_abs = posix_join(self.output_folder, unique_full_path_rel)

                    fn = os.path.split(attachment_path_abs)[-1]
                    if resource.attributes.fileName and fn != resource.attributes.fileName:
                        suppress = cfg.get("suppress_attachment_rename_warnings", False)
                        if not suppress:
                            log(logging.INFO, f'  - Attachment renamed from "{resource.attributes.fileName}" to "{attachment_path_abs}" in {note_path_abs}')

                    path_to_guid[attachment_path_rel] = resource.guid
                    guid_to_path_rel[resource.guid]   = attachment_path_rel
                    guid_to_path_abs[resource.guid]   = attachment_path_abs
                    if content_hash not in hash_to_paths:
                        hash_to_paths[content_hash] = {}
                    hash_to_paths[content_hash][note.guid] = attachment_path_rel
                    # Some web clips use resource GUID in en-media hash instead of bodyHash.
                    try:
                        guid_hash = int(resource.guid.replace("-", ""), 16)
                        if guid_hash not in hash_to_paths:
                            hash_to_paths[guid_hash] = {}
                        hash_to_paths[guid_hash][note.guid] = attachment_path_rel
                    except ValueError:
                        pass

        # 2nd pass: export notes
        saved_attachments = set()  # Track saved attachment paths for dedup in global mode
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
                # Ensure full path doesn't exceed Windows MAX_PATH (260 chars)
                note_path_abs = truncate_full_path(note_path_abs)
                if len(note_path_abs) > cfg.get("max_path_len", 255):
                    log(logging.ERROR, f"  ERROR: Note path still too long after truncation: {note_path_abs}")
                if not cfg["overwrite"] and os.path.exists(note_path_abs):
                    log(logging.INFO, f"  - Skipping, already exists: {note_path_abs}")
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
                          due = epoch_to_local_time(task["dueDate"] // 1000, task.get("timeZone", "UTC"))
                          due = f" 📅 {due}"
                    else: due = ""
                    reminders = ""
                    for reminder in task["reminders"]:
                        bell = "🔔" if reminder.get("status") == "active" else "🔕"
                        rmd_due = epoch_to_local_time(reminder["reminderDate"] // 1000, reminder.get("timeZone", "UTC"))
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

                    # Always enforce full path truncation for attachments

                    orig_attachment_path_abs = guid_to_path_abs[resource.guid]
                    # Compute the full absolute path from the filesystem root
                    workspace_root = os.path.abspath(os.getcwd())
                    # If output_folder is relative, join with workspace root
                    if not os.path.isabs(orig_attachment_path_abs):
                        abs_attachment_path = os.path.abspath(os.path.join(workspace_root, orig_attachment_path_abs))
                    else:
                        abs_attachment_path = orig_attachment_path_abs

                    # Truncate based on the full absolute path
                    truncated_abs_attachment_path = truncate_full_path(abs_attachment_path)
                    # If still too long, fallback to hash-only filename
                    if len(truncated_abs_attachment_path) > cfg.get("max_path_len", 255):
                        directory = os.path.dirname(truncated_abs_attachment_path)
                        ext = os.path.splitext(truncated_abs_attachment_path)[1]
                        file_hash = hashlib.md5(truncated_abs_attachment_path.encode()).hexdigest()[:12]
                        truncated_abs_attachment_path = posix_join(directory, f"{file_hash}{ext}")
                        log(logging.WARNING, f"  WARNING: Attachment path fallback to hash-only: {truncated_abs_attachment_path}")

                    # Update the guid_to_path_abs so Markdown references use the truncated path (relative to output_folder)
                    # Compute the path relative to the output folder for Markdown
                    rel_truncated_path = os.path.relpath(truncated_abs_attachment_path, os.path.abspath(self.output_folder))
                    rel_truncated_path = to_posix(rel_truncated_path)
                    guid_to_path_abs[resource.guid] = truncated_abs_attachment_path
                    guid_to_path_rel[resource.guid] = rel_truncated_path

                    # Save attachment file (skip if already saved via dedup)
                    if truncated_abs_attachment_path in saved_attachments:
                        log(logging.DEBUG, f"    - Dedup skip: {truncated_abs_attachment_path}")
                    elif not cfg["overwrite"] and os.path.exists(truncated_abs_attachment_path):
                        log(logging.INFO, f"    - Skipping, already exists: {truncated_abs_attachment_path}")
                    else:
                        os.makedirs(os.path.dirname(truncated_abs_attachment_path), exist_ok=True)
                        try:
                            with open(truncated_abs_attachment_path, "wb") as fh:
                                fh.write(resource.data.body)
                            log(logging.INFO, f"    - ({len(resource.data.body):,} bytes) {truncated_abs_attachment_path}")
                        except Exception as e:
                            errors.append( log(logging.ERROR, f"  Error saving {truncated_abs_attachment_path}: **{e}**") )
                    saved_attachments.add(truncated_abs_attachment_path)

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
                            tag_name = evernote_tag_to_obsidian(tag)
                            md_properties.append(f" - {tag_name}")
                    md_properties.append("---\n")
                    md_properties = "\n".join(md_properties)

                    # Convert note body to HTML or Markdown
                    converted_content, conversion_issues = self.convert(
                        note, note_content, guid_to_path_rel, path_to_guid, hash_to_paths, task_groups, cfg, deleted_guid_to_title)

                    if conversion_issues:
                        max_level = max(level for level, _ in conversion_issues)
                        log(max_level, f'Issues converting "{note.title}" ({note_path_abs}):')
                        for level, issue in conversion_issues:
                            log(level, f"  - {issue}")

                    # Save note
                    # Ensure full path doesn't exceed Windows MAX_PATH (260 chars)
                    save_path_abs = note_path_abs  # Already truncated above
                    if len(save_path_abs) > cfg.get("max_path_len", 255):
                        log(logging.ERROR, f"  ERROR: Note save path still too long after truncation: {save_path_abs}")
                    try:
                        with open(save_path_abs, "w", encoding="utf-8") as fh:
                            if self.note_ext == ".md":
                                fh.write(md_properties)
                            if cfg["first_line_empty"]:
                                converted_content = "\n" + converted_content
                            fh.write(converted_content)
                    except Exception as e:
                        errors.append( log(logging.ERROR, f"  Error saving {save_path_abs}: **{e}**") )

        if errors:
            log(logging.ERROR, f"{len(errors):,} error(s) found.")
            for error in errors:
                log(logging.ERROR, error)

        conn.close()
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

    def export(self):
        restart_log()  # Clear log at the start of HTML export
        return super().export()


    def convert(self, note, content, guid_to_path, path_to_guid, hash_to_paths, tasks, options, deleted_guid_to_title):

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
                if deleted_guid_to_title.get(guid):
                    path = deleted_guid_to_title[guid]
                    log(logging.INFO, f"    - Link fallback for deleted GUID: {guid} ({path})")
                else:
                    path  = regex_match[0]
                    log(logging.ERROR, f"    - [ERROR] Path to GUID not found: {guid} ({path})")
            return f'"{path}"'

        processed_content = re.sub(r'<en-media ([^>]+)\s*/>', subs_en_media, content)
        processed_content = re.sub(r'"(?:evernote:///view/[^/]+/[^/]+/(.+?)/.+?|https://share.evernote.com/note/(.+?))"', subs_href, processed_content)
        return processed_content, errors


class Exporter_MD(Exporter):
    def __init__(self):
        super().__init__(
            format        = "Markdown",
            confirm_title = "Confirm conversion from Evernote to Obsidian Markdown?",
            output_folder = to_posix(cfg['output_folder_md']),
            note_ext      = ".md",
        )
        self.converter = EvernoteHTMLToMarkdownConverter(use_html=cfg["html_with_md_ext"])

    def export(self):
        restart_log()  # Clear log at the start of Markdown export
        self._ensure_custom_callout_css(cfg)
        return super().export()

    @staticmethod
    def _resolve_calendar_event_mode(options):
        """Resolve calendar event rendering mode with backward-compatible fallback."""
        mode = options.get("calendar_event_mode")
        if mode in {"custom_callout", "remove", "raw"}:
            return mode
        # Backward compatibility for legacy boolean option
        legacy = options.get("calendar_as_custom_callout")
        if isinstance(legacy, bool):
            return "custom_callout" if legacy else "remove"
        return "custom_callout"

    @staticmethod
    def _web_clip_iframe_html(options, source_url):
        """Build iframe HTML wrapped in an expanded-by-default collapsible callout."""
        width = options.get("web_clip_iframe_width_px", 750)
        height = options.get("web_clip_iframe_height_px", 600)
        try:
            width = max(100, int(width))
        except (TypeError, ValueError):
            width = 750
        try:
            height = max(100, int(height))
        except (TypeError, ValueError):
            height = 600
        iframe = f'<iframe src="{source_url}" height="{height}px" width="{width}px"></iframe>'
        callout_type = options.get("web_clip_callout_type", "custom-web-clip").strip() or "custom-web-clip"
        title = options.get("web_clip_iframe_callout_title", "Web clip").strip() or "Web clip"
        return f"> [!{callout_type}]+ {title}\n><br> {iframe}"

    def _ensure_custom_callout_css(self, options):
        """
        Ensure custom callout CSS exists for enabled converter-generated callouts.
        Keeps changes inside a managed block to avoid clobbering user CSS.
        """
        if not options.get("manage_custom_callout_css", True):
            return

        mode = self._resolve_web_clip_mode(options)
        needs_calendar = self._resolve_calendar_event_mode(options) == "custom_callout"
        needs_webclip = mode in {"hybrid", "content_only"}
        css_rel_path = options.get("custom_callout_css_path", ".obsidian/snippets/custom-callout.css")
        css_rel_path = to_posix(css_rel_path).lstrip("/")
        css_path = os.path.join(self.output_folder, css_rel_path)
        snippet_dir = os.path.dirname(css_path)

        start_marker = "/* evernote2obsidian-managed-start */"
        end_marker = "/* evernote2obsidian-managed-end */"

        existing = ""
        if os.path.exists(css_path):
            with open(css_path, "r", encoding="utf-8") as f:
                existing = f.read()

        pattern = re.compile(
            re.escape(start_marker) + r".*?" + re.escape(end_marker) + r"\n?",
            flags=re.DOTALL,
        )
        cleaned = re.sub(pattern, "", existing).rstrip()
        if not (needs_calendar or needs_webclip):
            # No feature needs the managed CSS; remove managed block and clean up.
            if cleaned.strip():
                if cleaned != existing:
                    with open(css_path, "w", encoding="utf-8") as f:
                        f.write(cleaned + "\n")
            elif os.path.exists(css_path):
                os.remove(css_path)
            return

        os.makedirs(snippet_dir, exist_ok=True)
        blocks = []
        if needs_calendar:
            blocks.append(
                '.callout[data-callout="custom-calendar-event"] {\n'
                "    --callout-color: 120, 82, 238;\n"
                "    --callout-icon: calendar-days;\n"
                "}"
            )
        if needs_webclip:
            web_clip_type = options.get("web_clip_callout_type", "custom-web-clip").strip() or "custom-web-clip"
            blocks.append(
                f'.callout[data-callout="{web_clip_type}"]' + " {\n"
                "    --callout-color: 59, 162, 186;\n"
                "    --callout-icon: globe;\n"
                "}"
            )
        managed_block = (
            f"{start_marker}\n"
            + "\n\n".join(blocks)
            + f"\n{end_marker}\n"
        )
        # Remove legacy unmanaged definitions for the same callouts to avoid duplicates.
        selectors = ["custom-calendar-event"]
        selectors.append(options.get("web_clip_callout_type", "custom-web-clip").strip() or "custom-web-clip")
        for selector in selectors:
            cleaned = re.sub(
                r'\.callout\[data-callout="' + re.escape(selector) + r'"\]\s*\{[^}]*\}\s*',
                "",
                cleaned,
                flags=re.DOTALL,
            ).rstrip()
        final_css = (cleaned + "\n\n" + managed_block).lstrip("\n") if cleaned else managed_block

        with open(css_path, "w", encoding="utf-8") as f:
            f.write(final_css)

    @staticmethod
    def _css_unescape(s):
        """Unescape a CSS string value (remove backslash escaping)."""
        result = []
        i = 0
        while i < len(s):
            if s[i] == '\\' and i + 1 < len(s):
                result.append(s[i+1])
                i += 2
            else:
                result.append(s[i])
                i += 1
        return ''.join(result)

    @staticmethod
    def _format_time(dt):
        """Format datetime time component (e.g., '10:00 AM' or '6:00 PM')."""
        time_str = dt.strftime('%I:%M %p')
        if time_str[0] == '0':
            time_str = time_str[1:]
        return time_str

    def _format_calendar_datetime(self, start_ms, end_ms, is_all_day=False):
        """Format start/end epoch-ms timestamps into a readable date & time string."""
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).astimezone(local_tz)
        end_dt   = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).astimezone(local_tz)

        if is_all_day:
            if start_dt.date() == end_dt.date() or (end_dt - start_dt).days <= 1:
                return start_dt.strftime('%a, %b %d, %Y') + ' (All day)'
            return f"{start_dt.strftime('%a, %b %d, %Y')} – {end_dt.strftime('%a, %b %d, %Y')} (All day)"

        start_date_str = start_dt.strftime('%a, %b %d, %Y')
        end_date_str   = end_dt.strftime('%a, %b %d, %Y')
        start_time = self._format_time(start_dt)
        end_time   = self._format_time(end_dt)

        if start_dt.date() == end_dt.date():
            return f"{start_date_str}, {start_time} – {end_time}"
        return f"{start_date_str}, {start_time} – {end_date_str}, {end_time}"

    @staticmethod
    def _html_description_to_text(html_desc):
        """Convert an HTML event description to plain text with paragraph breaks."""
        soup = BeautifulSoup(html_desc, 'html.parser')
        for sup in soup.find_all('sup'):
            sup.decompose()
        for p in soup.find_all('p'):
            if not p.get_text(strip=True):
                p.replace_with('\n')
            else:
                p.insert_after('\n\n')
        for br in soup.find_all('br'):
            br.replace_with('\n')
        for li in soup.find_all('li'):
            li.insert(0, '- ')
            li.insert_after('\n')
        text = soup.get_text().strip()
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        return text

    def _format_calendar_callout(self, event_data):
        """Build a nested Obsidian callout string from structured calendar event data."""
        summary    = event_data.get('summary', 'Calendar Event')
        start_ms   = event_data.get('start')
        end_ms     = event_data.get('end')
        description = event_data.get('description', '')
        links      = event_data.get('links', [])
        is_all_day = event_data.get('isAllDay', False)

        event_url = ''
        for link in links:
            if link.get('type') == 'WEB':
                event_url = link.get('uri', '')
                break

        date_time_str = ''
        if start_ms and end_ms:
            date_time_str = self._format_calendar_datetime(start_ms, end_ms, is_all_day)

        lines = [f'> [!custom-calendar-event] {summary}']

        dt_parts = []
        if date_time_str:
            dt_parts.append(f'**Date & Time:** {date_time_str}')
        if event_url:
            dt_parts.append(f'[Event link]({event_url})')
        if dt_parts:
            lines.append('> ' + ' | '.join(dt_parts) + ' ')

        if description:
            if '<p>' in description.lower() or '<br' in description.lower():
                description_text = self._html_description_to_text(description)
            else:
                description_text = description

            lines.append('> > [!example]- Click to show event description')
            for desc_line in description_text.split('\n'):
                stripped = desc_line.rstrip()
                if stripped:
                    lines.append(f'> > {stripped}')
                else:
                    lines.append('> >')

        return '\n'.join(lines) + '\n'

    def _extract_and_replace_calendar_events(self, html_content):
        """Find --en-calendarBlock divs in HTML, replace with placeholders, return event data."""
        soup = BeautifulSoup(html_content, 'html.parser')
        events = []

        for div in soup.find_all('div', style=True):
            style = div.get('style', '')
            if '--en-calendarBlock:true' not in style:
                continue

            idx = style.find('--en-calendarEvent:')
            if idx < 0:
                continue

            rest = style[idx + len('--en-calendarEvent:'):]
            q1 = rest.find('"')
            if q1 < 0:
                continue

            pos = q1 + 1
            while pos < len(rest):
                if rest[pos] == '"' and rest[pos - 1] != '\\':
                    break
                pos += 1
            css_str = rest[q1 + 1:pos]
            json_str = self._css_unescape(css_str)

            try:
                event_data = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            events.append(event_data)
            placeholder_tag = soup.new_tag('div')
            placeholder_tag.string = f'EVERNOTE_CALENDAR_PLACEHOLDER_{len(events) - 1}'
            div.replace_with(placeholder_tag)

        return str(soup), events

    @staticmethod
    def _remove_calendar_events(html_content):
        """Remove Evernote calendar block divs from HTML content."""
        soup = BeautifulSoup(html_content, 'html.parser')
        for div in list(soup.find_all('div', style=True)):
            style = div.get('style', '')
            if '--en-calendarBlock:true' in style:
                div.decompose()
        return str(soup)

    @staticmethod
    def _is_web_clip(note):
        """Check if a note is a pure Evernote web clip with no user-added content."""
        source_url = getattr(note.attributes, 'sourceURL', '') or ''
        if not source_url:
            return False
        if '--en-clipped-content' not in note.content:
            return False
        soup = BeautifulSoup(note.content, 'html.parser')
        en_note = soup.find('en-note')
        if not en_note:
            return True
        for child in en_note.children:
            if not hasattr(child, 'get'):
                if str(child).strip():
                    return False
                continue
            style = child.get('style', '')
            if '--en-clipped-content' in style or '--en-clipped-source' in style:
                continue
            if child.get_text(strip=True):
                return False
        return True

    @staticmethod
    def _replace_clipped_content_with_iframe(content, source_url):
        """Replace --en-clipped-content divs with an iframe, preserving other content."""
        placeholder = "EVERNOTE_WEBCLIP_IFRAME_PLACEHOLDER"
        soup = BeautifulSoup(content, 'html.parser')
        for div in list(soup.find_all('div')):
            style = div.get('style', '')
            if '--en-clipped-content' in style:
                wrapper = soup.new_tag('div')
                wrapper.string = placeholder
                div.replace_with(wrapper)
        return str(soup), placeholder

    @staticmethod
    def _resolve_web_clip_mode(options):
        """Resolve configured web clip mode with backward-compatible fallback."""
        mode = options.get("web_clip_mode")
        if mode in {"hybrid", "iframe_only", "content_only"}:
            return mode
        legacy_iframe = options.get("web_clip_as_iframe")
        if isinstance(legacy_iframe, bool):
            return "iframe_only" if legacy_iframe else "hybrid"
        return "hybrid"

    @staticmethod
    def _split_web_clip_content(content):
        """Split note HTML into (user_content, clipped_content) fragments."""
        soup = BeautifulSoup(f"<en-note>{content}</en-note>", 'html.parser')
        en_note = soup.find('en-note')
        if not en_note:
            return content, ""
        clipped_parts = []
        for child in list(en_note.children):
            if not hasattr(child, 'get'):
                continue
            style = child.get('style', '')
            if '--en-clipped-content' in style or '--en-clipped-source' in style:
                clipped_parts.append(str(child))
                child.extract()
        user_content = ''.join(str(child) for child in en_note.children).strip()
        clipped_content = ''.join(clipped_parts).strip()
        return user_content, clipped_content

    @staticmethod
    def _wrap_web_clip_callout(markdown_content, options):
        """Wrap markdown content in a configurable web-clip callout."""
        if not markdown_content.strip():
            return ""
        callout_type = options.get("web_clip_callout_type", "custom-web-clip").strip() or "custom-web-clip"
        title = options.get("web_clip_callout_title", "Archived web clip").strip() or "Archived web clip"
        collapsed = "-" if options.get("web_clip_callout_collapsed", True) else ""
        lines = [f"> [!{callout_type}]{collapsed} {title}"]
        for line in markdown_content.split('\n'):
            lines.append(f"> {line}" if line else ">")
        return '\n'.join(lines)

    @staticmethod
    def _join_blocks(blocks):
        """Join non-empty markdown blocks with blank lines."""
        clean = [block.strip('\n') for block in blocks if block and block.strip()]
        return '\n\n'.join(clean) + ('\n' if clean else '')

    def _convert_html_fragment_to_markdown(self, note, content, guid_to_path, hash_to_paths, tasks, options, deleted_guid_to_title):
        """Convert one HTML fragment to markdown with the standard post-processing pipeline."""
        note_specific_hash_to_path = {
            hash_val: paths.get(note.guid)
            for hash_val, paths in hash_to_paths.items() if note.guid in paths
        }
        options_with_context = dict(options)
        options_with_context["_deleted_guid_to_title"] = deleted_guid_to_title
        options_with_context["_is_web_clip_note"] = bool(
            getattr(note.attributes, "sourceURL", "")
            and "--en-clipped-content" in note.content
        )

        calendar_mode = self._resolve_calendar_event_mode(options)
        if calendar_mode == "custom_callout":
            formatted_content, calendar_events = self._extract_and_replace_calendar_events(content)
        elif calendar_mode == "remove":
            formatted_content, calendar_events = self._remove_calendar_events(content), []
        else:
            formatted_content, calendar_events = content, []

        markdown_content, warnings = self.converter.convert_html_to_markdown(
            formatted_content,
            md_properties = [],
            tasks = tasks,
            guid_to_path = guid_to_path,
            hash_to_path = note_specific_hash_to_path,
            options      = options_with_context)

        for idx, event_data in enumerate(calendar_events):
            placeholder = f'EVERNOTE_CALENDAR_PLACEHOLDER_{idx}'
            callout_md = self._format_calendar_callout(event_data)
            markdown_content = markdown_content.replace(placeholder, callout_md)

        markdown_content = self._convert_codeblocks_to_quotes(markdown_content)

        if options_with_context.get("hr_as_h1", False):
            markdown_content = self._promote_text_hr_to_h1(markdown_content)

        if options_with_context.get("bold_date_log_to_headings", False):
            add_history = options_with_context.get("date_log_history_heading", False)
            markdown_content = self._convert_bold_date_log_to_headings(markdown_content, add_history=add_history)

        if options_with_context.get("normalize_header_dates", False):
            markdown_content = self._normalize_dates_in_headings(markdown_content)

        return markdown_content, warnings

    def convert(self, note, content, guid_to_path, path_to_guid, hash_to_paths, tasks, options, deleted_guid_to_title):
        source_url = getattr(note.attributes, 'sourceURL', '') or ''
        is_clip = source_url and '--en-clipped-content' in content
        mode = self._resolve_web_clip_mode(options)

        if mode == "iframe_only":
            if self._is_web_clip(note):
                return self._web_clip_iframe_html(options, source_url), []
            if source_url and '--en-clipped-content' in content:
                content, placeholder = self._replace_clipped_content_with_iframe(content, source_url)
                markdown_content, warnings = self._convert_html_fragment_to_markdown(
                    note, content, guid_to_path, hash_to_paths, tasks, options, deleted_guid_to_title)
                iframe_html = self._web_clip_iframe_html(options, source_url)
                markdown_content = markdown_content.replace(placeholder, iframe_html)
                return markdown_content, warnings
            return self._convert_html_fragment_to_markdown(
                note, content, guid_to_path, hash_to_paths, tasks, options, deleted_guid_to_title)

        if not is_clip:
            return self._convert_html_fragment_to_markdown(
                note, content, guid_to_path, hash_to_paths, tasks, options, deleted_guid_to_title)

        # Hybrid/content-only modes: preserve archived clipped content as markdown.
        is_pure = self._is_web_clip(note)
        user_content, clipped_content = self._split_web_clip_content(content)
        archived_html = clipped_content or content
        archived_md, archived_warnings = self._convert_html_fragment_to_markdown(
            note, archived_html, guid_to_path, hash_to_paths, tasks, options, deleted_guid_to_title)
        archived_callout = self._wrap_web_clip_callout(archived_md, options)

        if is_pure:
            blocks = [archived_callout]
            if mode == "hybrid" and source_url:
                blocks.insert(0, self._web_clip_iframe_html(options, source_url))
            return self._join_blocks(blocks), archived_warnings

        user_md, user_warnings = self._convert_html_fragment_to_markdown(
            note, user_content, guid_to_path, hash_to_paths, tasks, options, deleted_guid_to_title)
        blocks = [user_md]
        if mode == "hybrid" and source_url:
            blocks.append(self._web_clip_iframe_html(options, source_url))
        blocks.append(archived_callout)
        return self._join_blocks(blocks), user_warnings + archived_warnings

    @staticmethod
    def _promote_text_hr_to_h1(markdown_content):
        """Convert 'single line text\\n___' to '# text' in markdown output."""
        return re.sub(
            r'^([^\n#>!\-\d|_].+)\n___\n?(?=\n|$)',
            r'# \1\n',
            markdown_content,
            flags=re.MULTILINE,
        )

    _codeblock_quote_languages = {'', 'plaintext'}

    @staticmethod
    def _convert_codeblocks_to_quotes(markdown_content):
        """Convert fenced code blocks without a real language to > [!quote] callouts."""
        convert_langs = Exporter_MD._codeblock_quote_languages
        lines = markdown_content.split('\n')
        result = []
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith('```'):
                lang = stripped[3:].strip()
                if lang in convert_langs:
                    block = []
                    i += 1
                    closed = False
                    while i < len(lines):
                        if lines[i].strip() == '```':
                            closed = True
                            i += 1
                            break
                        block.append(lines[i])
                        i += 1
                    if closed:
                        result.append('> [!quote] ')
                        for line in block:
                            s = line.rstrip()
                            result.append(f'> {s}' if s else '>')
                        result.append('')
                    else:
                        result.append(lines[i - len(block) - 1])
                        result.extend(block)
                else:
                    result.append(lines[i])
                    i += 1
                    while i < len(lines):
                        result.append(lines[i])
                        if lines[i].strip() == '```':
                            i += 1
                            break
                        i += 1
            else:
                result.append(lines[i])
                i += 1
        return '\n'.join(result)

    @staticmethod
    def _convert_bold_date_log_to_headings(markdown_content, add_history=False):
        """Convert lines starting with **date** or bare date to ## DD MMM YYYY headings."""
        from datetime import datetime

        def normalize_month(s):
            return re.sub(r'\bSept\b', 'Sep', s, flags=re.IGNORECASE)

        formats_with_year = (
            '%d %B %Y', '%d %b %Y',
            '%B %d, %Y', '%b %d, %Y', '%B %d %Y', '%b %d %Y',
            '%d/%m/%Y',
        )
        formats_no_year = (
            '%d %B', '%d %b',
            '%B %d', '%b %d',
        )

        def try_parse_date(text):
            text = normalize_month(text.strip())
            for fmt in formats_with_year:
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            return None

        def try_parse_date_no_year(text):
            text = normalize_month(text.strip())
            for fmt in formats_no_year:
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            return None

        _bare_date_dd = re.compile(r'^(\s*)(\d{1,2}\s+\w+\s+\d{4})\b(.*)$')
        _bare_date_md = re.compile(r'^(\s*)(\w+\s+\d{1,2},?\s+\d{4})\b(.*)$')
        _bare_date_numeric = re.compile(r'^(\s*)(\d{1,2}/\d{1,2}/\d{4})\b(.*)$')
        _bare_date_dd_noyear = re.compile(r'^(\s*)(\d{1,2}\s+\w+)\b(.*)$')

        def format_heading(dt, prefix, rest_stripped, level=2):
            hashes = '#' * level
            heading = f"{hashes} {dt.day} {dt.strftime('%b %Y')}"
            if rest_stripped:
                return f"{prefix}{heading}\n{prefix}{rest_stripped}"
            return f"{prefix}{heading}"

        def extract_date_and_rest(line):
            """Try to extract a date from a line. Returns (dt, prefix, rest) or None."""
            # Bold date: **29 June 2024** rest  or split bold **15 July** **2020** rest
            m = re.match(r'^(\s*)\*\*([^*]+)\*\*\s*(?:\*\*([^*]+)\*\*)?\s*(.*)$', line)
            if m:
                prefix = m.group(1)
                date_text = m.group(2) + (' ' + m.group(3) if m.group(3) else '')
                rest = m.group(4)
                dt = try_parse_date(date_text)
                if dt:
                    return dt, prefix, rest.strip()
                dt = try_parse_date_no_year(date_text)
                if dt:
                    return dt, prefix, rest.strip()

            # Bare date with year
            for pat in (_bare_date_dd, _bare_date_md, _bare_date_numeric):
                m = pat.match(line)
                if not m:
                    continue
                prefix, date_text, rest = m.group(1), m.group(2), m.group(3)
                dt = try_parse_date(date_text)
                if dt:
                    return dt, prefix, rest.strip()

            # Bare date without year: 26 Aug rest
            m = _bare_date_dd_noyear.match(line)
            if m and not line.lstrip().startswith('#'):
                prefix, date_text, rest = m.group(1), m.group(2), m.group(3)
                dt = try_parse_date_no_year(date_text)
                if dt:
                    return dt, prefix, rest.strip()

            return None

        _date_range_sep = re.compile(r'^[-–—]\s*\d|^to\s+\d', re.IGNORECASE)

        def is_date_range(rest):
            """Check if rest starts with a range separator followed by a date-like value."""
            return bool(_date_range_sep.match(rest))

        lines = markdown_content.split('\n')

        # First pass: collect years from all dated lines to build a lookup
        year_at_line = {}
        for i, line in enumerate(lines):
            result = extract_date_and_rest(line)
            if result and not is_date_range(result[2]) and result[0].year != 1900:
                year_at_line[i] = result[0].year

        def infer_year(line_idx):
            """Find the nearest line with a known year."""
            best_dist = float('inf')
            best_year = None
            for idx, year in year_at_line.items():
                dist = abs(idx - line_idx)
                if dist < best_dist:
                    best_dist = dist
                    best_year = year
            return best_year

        # Second pass: convert lines
        _heading_re = re.compile(r'^(#{1,6})\s')
        out = []
        current_section_level = 1
        for i, line in enumerate(lines):
            hm = _heading_re.match(line)
            if hm:
                heading_text = line[len(hm.group(0)):].strip()
                heading_is_date = try_parse_date(heading_text) is not None
                if not heading_is_date:
                    current_section_level = len(hm.group(1))

            result = extract_date_and_rest(line)
            if result and not is_date_range(result[2]):
                dt, prefix, rest = result
                if dt.year == 1900:
                    year = infer_year(i)
                    if year:
                        dt = dt.replace(year=year)
                    else:
                        out.append(line)
                        continue
                date_level = min(current_section_level + 1, 6)
                out.append(format_heading(dt, prefix, rest, level=date_level))
            else:
                out.append(line)

        if add_history:
            # Insert a "History" heading before the first date heading that
            # has no preceding non-date section heading.
            date_heading_re = re.compile(r'^#{1,6} \d{1,2} \w{3} \d{4}')
            any_heading_re  = re.compile(r'^#{1,6} ')
            first_date_idx = None
            has_prior_heading = False
            for idx, ln in enumerate(out):
                if any_heading_re.match(ln) and not date_heading_re.match(ln):
                    has_prior_heading = True
                elif date_heading_re.match(ln):
                    first_date_idx = idx
                    break
            if first_date_idx is not None and not has_prior_heading:
                date_hashes = out[first_date_idx].split(' ', 1)[0]
                history_level = max(len(date_hashes) - 1, 1)
                history_heading = f"{'#' * history_level} History"
                out.insert(first_date_idx, history_heading)

        return '\n'.join(out)

    @staticmethod
    def _normalize_dates_in_headings(markdown_content):
        """Normalize any date in a markdown heading to DD MMM YYYY format."""
        from datetime import datetime

        def normalize_month(s):
            return re.sub(r'\bSept\b', 'Sep', s, flags=re.IGNORECASE)

        formats = (
            '%d %B %Y', '%d %b %Y',
            '%B %d, %Y', '%b %d, %Y', '%B %d %Y', '%b %d %Y',
            '%Y-%m-%d',
            '%d/%m/%Y',
        )
        month_names = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*'
        date_patterns = [
            re.compile(r'(\d{4}-\d{2}-\d{2})'),
            re.compile(r'(\d{1,2}\s+' + month_names + r'\s+\d{4})', re.IGNORECASE),
            re.compile(r'(' + month_names + r'\s+\d{1,2},?\s+\d{4})', re.IGNORECASE),
            re.compile(r'(\d{1,2}/\d{1,2}/\d{4})'),
        ]

        def try_parse(s):
            s = normalize_month(s.strip())
            for fmt in formats:
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            return None

        def format_date(dt):
            return f"{dt.day} {dt.strftime('%b %Y')}"

        def replace_dates_in_heading(text):
            for pat in date_patterns:
                def repl(m):
                    dt = try_parse(m.group(1))
                    return format_date(dt) if dt else m.group(0)
                text = pat.sub(repl, text)
            return text

        def process_line(line):
            m = re.match(r'^(#{1,6})\s+(.*)$', line)
            if not m:
                return line
            prefix, rest = m.group(1), m.group(2)
            return f"{prefix} {replace_dates_in_heading(rest)}"

        return '\n'.join(process_line(line) for line in markdown_content.split('\n'))


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
