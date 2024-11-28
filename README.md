# evernote2obsidian
This project aims to transfer your Evernote data to Obsidian with maximum fidelity, while alerting you to any issues encountered during conversion.

**HTML** (used by Evernote) and **Markdown** (`.md`, used by Obsidian) lack feature parity, making such conversion potentially lossy. Many "HTML to Markdown" and "Evernote to Obsidian" converters are already available, all of them (including this one) having their own limitations.

The main files in this project are:
- **`evernote-backup2obsidian.py`**: converts Evernote notebooks (from a database created by [evernote-backup](https://github.com/vzhd1701/evernote-backup/)) to Obsidian Markdown, and check an Obsidian vault for issues. This is what most users want to use.
- `evernote2md.py`: a standalone module for converting HTML (vanilla or with Evernote-specific formatting) to Markdown. This one is used mostly by programmers.
- `test_enex_conversion.py`: a script to convert HTML from an `.enex` file to Markdown using different Python modules, to assist in comparing the quality of the outputs. It also works as an example on how to use `evernote2md.py`. Used mostly by programmers.
- `[Evernote formatting test note.enex](/media/Evernote formatting test note.enex)`: a sample Evernote export file with many Evernote features to help evaluate the output of the programs above and compare it to other tools.


## Features  
  - **Improved quality of conversion:** this project was created because I could not find another one that can preserve as much of the original Evernote data when converted to Obsidian as I wanted. See more details in the [comparison section](#comparison-with-other-tools-and-limitations) below.
  - **Text User Interface (TUI):** with menus, mouse support, and many user-configurable options.
  - **Log of Issues:** helps you addressing issues either before or after conversion.
  - **Output formats:** export your notes (and their attachments) as HTML or Markdown.
  - **Detection of issues:** you can see issues before or after conversion, and even look for issues in an Obsidian vault converted from Evernote by another program.

![Screenshot of the main screen of evernote-backup2obsidian.py](/media/evernote-backup2obsidian.png)

## Comparison with Other Tools and Limitations
The [Obsidian Importer Plugin](https://github.com/obsidianmd/obsidian-importer/) might be good enough for you, if:
- You have just a few notes and/or don't mind manually checking them all after conversion to find and fix conversion issues.
- Your notes are mainly in plain text, without features such as links for other notes, text colors and highlighting, image resizing, etc.
- You don't care about some loss of formatting (and a small risk of losing some information) in your notes, and you prefer the convenience of using a plugin that already comes installed with Obsidian.

On the other hand, you might want an alternative if:
- You want to preserve as much data and formatting during conversion as possible.
- Your notes use many Evernote / HTML features.
- Even if some features can't be converted, you want to have a log of all notes and issues so you can manually check them (after or even before conversion).

#### Other HTML to Markdown Python modules ([html2markdown](https://github.com/dlon/html2markdown), [html2text](https://github.com/Alir3z4/html2text/), [markdownify](https://github.com/matthewwithanm/python-markdownify), ...)
It is somewhat unfair to compare this project, which understands the special formatting Evernote uses, with generic HTML to Markdown converters. Yet, even for "plain" HTML, some features are better supported by `evernote2md.py`, such as converting tables with merged cells, escaping of special Markdown characters, and more.

#### Obsidian Importer Plugin, YARLE
The [Obsidian Importer Plugin](https://github.com/obsidianmd/obsidian-importer/) and [YARLE](https://github.com/akosbalasko/yarle/) are popular tools for migrating data from Evernote to Obsidian. They do a good job, and YARLE have advanced and powerful features. Unfortunately, they not always preserve internal links and complex formatting:
  - They convert Evernote data from `.enex` files, but those files are missing note link information, so they can only "guess" how to link to a note. If the title of a note or the title of the link was changed (by the user or during conversion), or if there is more than one note with the same title, the link in the Markdown file can be wrong.
  - Some note contents are not properly converted, such as (but not limited to): correct color highlighting other than yellow, superscript / subscript, font color, text alignment, image size, tables (merged, cells, column alignment), some spaces in `code` spans are removed, some Markup tags are not correctly escaped, ...
  - File names for attachments are truncated to 50 characters.

### Limitations of evernote2obsidian
- **Platform:** Currently tested only on Windows 11, but should support Linux, Mac, and any other OS that can run Python.
- **Tasks OR Links:** `evernote2obsidian` requires backing up your Evernote data with [evernote-backup](https://github.com/vzhd1701/evernote-backup/) to correctly convert note links, as it collects all necessary information via Evernote API. Unfortunately, it still doesn't support Evernote "tasks" (see [this issue](https://github.com/vzhd1701/evernote-backup/issues/39)). Tasks could be converted from `.enex` files, but those files lack information required to properly convert note links. As I don't use tasks in Evernote, I chose to support links over tasks.
- Some unsupported features in Markdown (such as superscript, subscript, font colors, etc.) are not converted by Obsidian Importer and YARLE. However, these features are supported in Obsidian through simple HTML tags. Although evernote2obsidian can optionally use these HTML tags, Obsidian's support for them can be inconsistent depending on the "viewing mode."<br/>For example, in "reading" mode, Obsidian supports mixing Markdown and HTML tags, such as creating superscript text in italics with `_<sup>superscript</sup>_`. However, in "editing" mode, the text will only appear as <sup>superscript</sup> (not italicized). A workaround is to use additional HTML tags. For instance, `<i><sup>superscript</sup></i>` produces <i><sup>superscript in italics</sup></i> in both reading and editing modes.<br/>This is something the program could handle but does not currently implement, as the aim is to retain as much Markdown as possible in your notes.

---

## Installation  
1. Install `evernote-backup` to create a local backup of all your Evernote data:
```
pip install evernote-backup
```

2. Create a folder for `evernote2obsidian` and install the following dependencies:  
```
md evernote2obsidian
cd evernote2obsidian
pip install prompt_toolkit  
```

3. Download [evernote-backup2obsidian.py](evernote-backup2obsidian.py) and [evernote2md.py](evernote2md.py) into the `evernote2obsidian` folder you just created.

## Usage

1. If, like me, you have thousand of notes in Evernote, first review and delete any unnecessary notes or notebooks.

2. Use `evernote-backup` to create a local backup up of all your Evernote data. It uses the Evernote API to access your data. If you want to, you can [get your own API keys](https://dev.evernote.com/) (see [scramble.py](scramble.py) for more details).
```
evernote-backup init-db --oauth
evernote-backup sync
```

The initial sync may take a while depending on the size of your data. The next syncs should be faster, as they only download changes. If you authorized the app to access your data for a limited time (e.g., one day) and want to sync again, run `evernote-backup reauth --oauth`.

3. Run `evernote2obsidian.py`, then:

![Screenshot of the main screen of evernote-backup2obsidian.py](/media/evernote-backup2obsidian.png)
- Run **Configuration** to set up input and output paths and conversion options.
- Run **Scan Evernote database for issues** to see issues before conversion. Then check the log and manually fix any issue you want in the notes while they are still on Evernote (such as simplifying or removing formatting). At least try to rename repeated note titles so note links work correctly. When you are done, sync your data again (`evernote-backup sync`).
- Run **Select Evernote notebooks to export**. Select just one or a few if you want to do a quick test.
- Run **Export notes as Obsidian Markdown and attachments** when you are ready. Check the results in Obsidian.
- Optionally, you can run **Export notes as HTML and attachments** to keep the original HTML data. This should preserve basically almost _all_ of your data (except for "tasks", as explained before). It can be used as another backup option, but editing your notes in Obsidian would become very cumbersome (specially tables), since you will be editing everything in HTML.
- **Scan Obsidian Vault for issues** can help you find some issues in your vault when you use this or other migration tools.

## Acknowledgments
[evernote-backup](https://github.com/vzhd1701/evernote-backup/): Great tool for creating a local backup of all of your Evernote data.

[prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit): Used for building the TUI.
