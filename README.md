# evernote2obsidian - Advanced Evernote to Obsidian Migration Tool

Convert your Evernote data to Obsidian as best as possible (better than the default Obsidian Importer plugin).

**HTML** (the note format in Evernote) and **Markdown** (`.md`, used by Obsidian) lack feature parity, making such conversion potentially lossy. Many things you can do in Evernote are not possible with Markdown, e.g., changing the color of links. Many "HTML to Markdown" and "Evernote to Obsidian" converters already exist - all of them (including this one) with their own limitations.

## Features
- **Text-based user interface** with menus, partial mouse support, and many user-configurable options.
- **List all your notes in Evernote.**
- **Scan notes for potential conversion issues**, so you can "fix" them in Evernote before exporting - or just let the program deal with the issues automatically.
- **Export notes as HTML or Markdown**, including attachments.
- **Improved conversion quality:** this project was created because I could not find any other that preserves as much of the original Evernote data when converted to Obsidian as I wanted. More details below.
- **Scan your Obsidian vault** for potential issues, such as broken links.

![Screenshot of the main screen of evernote2obsidian.py](/extra/evernote2obsidian_0.1.0.png)

## Comparison with Other Tools and Limitations
In [A Comparison of Evernote to Obsidian Conversion Tools](comparison.md) you can see how `evernote2obsidian` compares with YARLE.

The official [Obsidian Importer Plugin](https://github.com/obsidianmd/obsidian-importer/) might be good enough for you, if:
- You have just a few notes and/or don't mind manually checking them all after conversion to find and fix conversion issues.
- Your notes are mainly in plain text, without features such as links for other notes, text colors and highlighting, images, tables with merged cells, etc.
- You don't care about some loss of formatting (and a small risk of losing some information) in your notes, and you prefer the convenience of using a plugin that already comes installed with Obsidian.

On the other hand, you might want an alternative if:
- You want to preserve as much data and formatting during conversion as possible.
- Your notes use many Evernote / HTML features.
- Even if some features can't be converted, you want to have a log of all notes and issues so you can manually check them (after or even before conversion).

#### Other HTML to Markdown Python modules ([html2markdown](https://github.com/dlon/html2markdown), [html2text](https://github.com/Alir3z4/html2text/), [markdownify](https://github.com/matthewwithanm/python-markdownify), ...)
It is somewhat unfair to compare this project, which understands the special formatting Evernote uses, with generic HTML to Markdown converters. But even for "plain" HTML, this project (more precisely, the `evernote2md.py` module) is better than most to convert tables with merged cells, escape special Markdown characters, and more.

#### Obsidian Importer Plugin, YARLE
The [Obsidian Importer Plugin](https://github.com/obsidianmd/obsidian-importer/) and [YARLE](https://github.com/akosbalasko/yarle/) are popular tools for migrating data from Evernote to Obsidian. They do a good job, and YARLE has advanced and powerful features. Unfortunately, they do not always preserve internal links and complex formatting:
- They convert Evernote data from `.enex` files, but those files are missing note link information, so they can only "guess" how to link to a note. If the title of a note or the title of the link was changed (by the user or during conversion), or if there is more than one note with the same title, the link in the Markdown file can be wrong.
- Some note contents are not properly converted, such as (but not limited to): correct color highlighting (other than yellow), superscript / subscript, font color, text alignment, image size, tables (merged, cells, column alignment), some spaces in `code` spans are removed, some Markup tags are not correctly escaped, ...
- File names for attachments are truncated to 50 characters.

### Limitations of evernote2obsidian
- **Platform:** Currently tested only on Windows 11 and Python 3.11.1, but should support Linux, Mac, and any other OS that can run Python.
- **Dependencies:** `evernote2obsidian` requires you to install and back up your Evernote data with [evernote-backup](https://github.com/vzhd1701/evernote-backup/).
- As of this writing, [evernote-backup does not sync shared notes ("Shared with Me")](https://github.com/vzhd1701/evernote-backup/issues/138). The current suggested workaround is to manually copy each shared note into a local notebook in Evernote before syncing.
- Some unsupported features in Markdown (such as superscript, subscript, font colors, etc.) are supported in Obsidian through simple HTML tags. Although `evernote2obsidian` can optionally embed these HTML tags, Obsidian's support for them can vary depending on the "viewing mode."<br/>For example, in "reading" mode, Obsidian supports mixing some Markdown and HTML tags, such as superscript in italics with `_<sup>superscript</sup>_`. However, in "editing" mode, it appears as <sup>superscript in italics</sup> only (not italicized). A workaround is to use additional HTML tags. For instance, `<i><sup>superscript</sup></i>` produces <i><sup>superscript in italics</sup></i> in both reading and editing modes.<br/>This is something the program could handle but does not currently implement, as one of the aims is to retain as much Markdown as possible in your notes.
- Currently, Obsidian does not support "indentation" in reading mode, even though it works fine in editing mode ([it is considered a "feature"](https://help.obsidian.md/Editing+and+formatting/Basic+formatting+syntax#Paragraphs)). Workarounds, such as using quotes (`>`), non-breaking spaces (`&nbsp;`), or [callouts](https://help.obsidian.md/Editing+and+formatting/Callouts), can be used instead, but the best workaround is likely best left for the user to decide on a case-by-case basis.
- "Table of Contents" blocks are not converted, use "Open linked view > Open outline" in Obsidian instead.
- Conversion to Markdown was much more tested than to HTML. Tasks are not exported to HTML, only to Markdown.
- The option to "Scan Obsidian Vault for issues" is not complete or precise, but can still be useful.
- For now, I mostly tested the conversion of my own notes (since 2010!) to Markdown. Notes that are older, using different styles, resources, etc. might have conversion issues I haven't seen yet. If you find a problem that you want to be fixed, please open an issue with a sample .enex file (with any personal data scrubbed from it), or even better, fix the issue and open a pull request! 😉
- **Error checking:** I'm running the program directly from an IDE so I can easily see and correct issues when I find them, and that is why the code doesn't try to catch all possible error conditions.


## Installation

The main files in this project are:
- **`evernote2obsidian.py`**: converts Evernote notebooks (from a database created by [evernote-backup](https://github.com/vzhd1701/evernote-backup/)) to Obsidian Markdown, and checks an Obsidian vault for issues. This is what most users want to use.
- `evernote2md.py`: a standalone module for converting HTML (vanilla or with Evernote-specific formatting) to Markdown. Required by `evernote2obsidian.py`, but can be used in other programs.
- [Evernote to Obsidian Conversion Test Note.enex](</extra/Evernote to Obsidian Conversion Test Note.enex>): an Evernote note to help test the conversion quality and compare the result with other programs.

**How to install**:

1. Be sure to have Python 3.9 or newer installed on your system.

2. Install `evernote-backup` (to create a local backup of all your Evernote data) and the `prompt_toolkit` module. Using the Command Prompt:
```
pip install evernote-backup prompt_toolkit
```

3. Create a new folder and download [evernote2obsidian.py](evernote2obsidian.py) and [evernote2md.py](evernote2md.py) into the folder you just created.


## Usage

Before converting any important data, make sure to **properly back it up**.
Do not use a destination folder that already contains data, as existing files may be **overwritten or lost**.
This software is provided "as is" without any warranties. Use it at your own risk. **The author assumes no responsibility for data loss or other damages.**

1. If, like me, you have thousands of notes in Evernote, first review and delete any unnecessary notes or notebooks on Evernote.

2. Use `evernote-backup` to create a local backup of all your Evernote data.
```
evernote-backup init-db --oauth
evernote-backup sync
```

Add parameter `--api-data <key>:<secret>` if you want to use your own Evernote API key.

It uses the Evernote API to access your data. If you want to, you can optionally [get your own Evernote API key](https://dev.evernote.com/) and add `--api key:secret` to the command line arguments.

Use `evernote-backup sync --include-tasks --token <YOUR_TOKEN_HERE>` if you want to [sync tasks and reminders](https://github.com/vzhd1701/evernote-backup?tab=readme-ov-file#tasks). Check the link for more information.

The initial sync may take a while depending on the size of your data. The next syncs should be faster, as they only download changes. If you authorized the app to access your data for a limited time (e.g., one day) and want to sync again after that period, reauthorize with `evernote-backup reauth --oauth`.

3. Run `evernote2obsidian.py`, then:

![Screenshot of the main screen of evernote2obsidian.py](/extra/evernote2obsidian_0.1.0.png)
- Run **Configuration** to set up input and output paths and conversion options.
- Run **Select Evernote notebooks to process**. You can select one or a few if you want to do a quick test. When doing a final export, it is better to select all notebooks, otherwise you can end up with broken links between notes.
- Run **List notes in selected notebooks** if you want exactly that: a list of notebooks and note titles.
- Run **Scan selected notebooks for issues** to see issues before conversion. Check the log and manually fix in Evernote any issue you want (such as simplifying or removing formatting, manually reformatting "HTML Content" sections, or converting them to PDF). Rename repeated note titles so note links work correctly. When you are done, sync your data again (`evernote-backup sync`).
- Run **Export selected notebooks as Obsidian Markdown** when you are ready. Check the results in Obsidian.
- Optionally, you can run **Export selected notebooks as HTML** to keep the original HTML data. This should preserve essentially _all_ of your data (except for "tasks" and "table of contents", as explained before). It can be used as another backup option, or can be used directly in Obsidian, but editing your notes in that format would become very cumbersome (especially tables), since you will be editing everything in HTML.
- **Scan Obsidian Vault for issues** can help you find some issues in your vault when you use this or other migration tools.

## Acknowledgments
[evernote-backup](https://github.com/vzhd1701/evernote-backup/): An awesome tool for creating a local backup of all of your Evernote data.

[prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit): Used for building the TUI.
