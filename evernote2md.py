#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# evernote2md.py
# ==============
#
# Project: https://github.com/AltoRetrato/evernote2obsidian/
#
# This is an Evernote HTML to Markdown converter.
#
# 2026.02.20  0.1.7, fixed #17, "Crash on empty media nodes"
# 2026.01.05  0.1.6, fixed #15, "Text inside <p> tags from old notes turning into a single line"
# 2026.01.04  0.1.5, fixed some Pylance warnings
# 2025.08.21  0.1.4, fixed #8 "Crashes on notes with nested HTML tables"
# 2025.08.18  0.1.3, fixed #9 "SyntaxWarning due to invalid escape sequences"
# 2025.05.23  0.1.0, 1st release
# 2024.11.19  0.0.1, 1st version

__version__ = "0.1.7"
__author__  = "AltoRetrato"

import os
import re
from   bs4         import BeautifulSoup
from   typing      import List, Tuple, Dict
from   statistics  import mode
from   collections import Counter


# Set of block tags in Evernote / HTML (and maybe one or two extras that help with the logic of the code)
block_level_elements = {
    'address', 'article', 'aside', 'blockquote', 'canvas', 
    'dd', 'details', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 
    'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'li', 
    'main', 'nav', 'ol', 'p', 'pre', 'section', 'table',
    'tfoot', 'ul', 'video',
    # 'br', 'code', 'en-todo', 'form', 
}

class EvernoteHTMLToMarkdownConverter:
    def __init__(self, use_html=True):
        self.soup            = BeautifulSoup("", "html.parser")  # BeautifulSoup object (initialized later)
        self.use_html        = use_html # if True, use some HTML for things not supported by Obsidian Markdown
        self.url_pattern     = re.compile(r'\b(?:http|https|ftp)://\S+') # Regex pattern for URLs


    def convert_html_to_markdown(
            self,
            html_content: str,
            md_properties: List = [],
            tasks: Dict = {},
            guid_to_path: Dict = {},
            hash_to_path: Dict = {},
            options:      Dict = {},
            ) -> Tuple[str, List]:
        """ Convert HTML content to Markdown format. """

        self.tasks        = tasks        # dict. for tasks (provided by caller)
        self.guid_to_path = guid_to_path # dict. for links (provided by caller)
        self.hash_to_path = hash_to_path # dict. for attachments (provided by caller)
        self.options      = options      # dict. for options

        # Reset some variables
        self.list_stack    = []
        self.indent_level  = 0        # used in lists, list items
        self.number_indent = {}       # used in ordered lists
        self.warnings      = []       # list of warnings returned after conversion
        self.inside_pre    = False    # True if processing content that should not be escaped
        self.inside_table  = False    # True if processing a table

        # Parse HTML
        self.soup = BeautifulSoup(html_content, 'html.parser')

        # Remove script and style elements
        for element in self.soup(['script', 'style']):
            element.decompose()

        # Convert to markdown
        markdown = self._process_node(self.soup)

        # Add properties
        if md_properties:
            properties = ["---"] + md_properties + ["---\n"]
            markdown = '\n'.join(properties) + markdown

        # Return a short(er) list of warnings
        counter = Counter(self.warnings)
        sorted_warnings = sorted(
            counter.items(),
            key=lambda x: (-x[1], x[0]) # First by count (descending), then by name (ascending)
        )
        warnings = [
            f"{item} [{count}x]" if count > 1 else item
            for item, count in sorted_warnings
        ]

        return markdown, warnings

    def _process_node(self, node) -> str:
        """
        Process an HTML node and its children recursively.
        Args   : node: BeautifulSoup node
        Returns: str : Markdown representation of the node
        """
        if node.name is None:
            # Ignore stray "\n" outside tags (appears only in old notes?)
            if node.text == "\n":
                return ""
            return self._escape_text(node)

        def save_result(text):
            if text:
                result.append(text)

        result = []

        # Handle different HTML elements
        if node.name == 'div':
            save_result(self._process_div(node))
        elif node.name in ['p', 'span', 'font']:
            save_result(self._process_text_element(node))
        elif node.name in ['b', 'strong', 'i', 'em', 'u', 's', 'del', 'sup', 'sub', 'blockquote', 'code']:
            save_result(self._process_simple_tags(node))
        elif node.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            save_result(self._process_header(node))
        elif node.name in ['ul', 'ol']:
            save_result(self._process_list(node))
        elif node.name == 'li':
            save_result(self._process_list_item(node))
        elif node.name == 'table':
            save_result(self._process_table(node))
        elif node.name == 'a':
            save_result(self._process_link(node))
        elif node.name == 'img':
            save_result(self._process_image(node))
        elif node.name == 'br':
            save_result('\n')
        elif node.name == 'hr':
            save_result('___\n') # or '---', '* * *'
        elif node.name == 'en-todo':
            save_result(self._process_checkbox(node))
        elif node.name == 'en-media':
            save_result(self._process_media(node))
        else:
            # Process other elements recursively
            for child in node.children:
                save_result(self._process_node(child))

        return ''.join(result)

    def _newline_prefix(self, node) -> str:
        """Add a newline before the text if the node is a block-level element after a non-block-level element."""
        if (node.name in block_level_elements 
            and node.previous_sibling
            and node.previous_sibling.name
            and node.previous_sibling.name not in block_level_elements
        ):
            return "\n"
        return ""

    def _use_html(self, html: str) -> bool:
        """Helper function that checks if HTML should be used or not (and warns in each case)."""
        self.warnings.append(f"{'Added' if self.use_html else 'Removed'} unsupported HTML: {html}")
        return self.use_html

    def _process_div(self, node) -> str:
        """Process div elements, handling special cases like alignment."""
        style   = node.get('style', '')
        result  = self._process_node_children(node)

        # Table of contents
        if "--en-tableofcontents:true" in style:
            # Shouldn't be too hard to implement, but might just not be worth it
            # since Obsidian can show a note outline in the right side bar.
            self.warnings.append("Ignored Table of Contents (conversion not implemented)")
            result = '==Evernote Table of Contents removed during conversion! In Obsidian, use "Open linked view" > "Open outline" instead.=='
        # Code block
        elif "--en-codeblock:true" in style:
            language = (re.findall("--en-syntaxLanguage:(.+?);", style) or [""])[0]
            result = f"```{language}\n{result}```"
        # Tasks
        elif "--en-task-group:true" in style:
            id = re.findall("--en-id:([0-9a-f-]+);", style)[0]
            if self.tasks and id in self.tasks:
                  result = self.tasks[id]
            else: result = f"- [ ] ==Could not find task(s) ID {id} during conversion=="
        else:

            # Text alignment not supported in Markdown, but we can use some HTML...
            # (but it might not work very well in large tables)
            if not self.inside_table:
                if 'text-align:center' in style:
                    if self._use_html("text-align:center / <center>"):
                        result = f'<center>{result}</center>'
                elif 'text-align:right' in style:
                    if self._use_html("text-align:right / <span>"):
                        result = f'<span style="position:absolute;right: 0px;">{result}</span>\n'
                        # Obs: must end with \n, otherwise Obsidian will make a mess with the next lines...

            # Indentation
            #   There is no perfect solution, since Obsidian shows spaces or tab
            #   indentation correctly in editing mode but not in reading mode.
            #   Options:
            #   - " ", "\t": great in editing mode (even supports folding!), but don't work in reading mode.
            #   - Blockquote ">", but looks awful in both modes
            #   - "&nbsp;", even more awful in editing more
            #   - `  `, all spaces are condensed in reading mode (leaving just one, very small, indentation level)
            # Note 1: newer versions of Evernote use padding, older versions use margin.
            # Note 2: indented lines following a blank line are interpreted as code blocks.
            #         Workaround: use a bullet list (works even if you set it on just the 1s line!).
            padding_left = re.findall(r"(?:padding|margin)-left\s*:\s*(\d+)\s*px", style)
            if padding_left:
                indent = "    " * (int(padding_left[0])//40)
                result = f'{indent}{result}'
                # If list item has \n in the content, add indent
                result = result.replace("\n", f"\n{indent}")

        # An empty line in Evernote is a <div><br/></div>, which could create
        # a double line break in Markdown. So we strip any trailing new line.
        if result.endswith('\n'):
            result = result[:-1]

        prefix = self._newline_prefix(node) # FIX-ME: should add to other block elements too?
        return f'{prefix}{result}\n'

    def _process_text_element(self, node) -> str:
        """Process text-related elements with styling."""
        content = self._process_node_children(node)

        # <font color="#FF0000">...</font>
        # <font> is deprecated, but still found in old notes.
        if (color := node.get('color')):
            if self._use_html("font color"):
                return f'<span style="color:{color}">{content}</span>'

        if node.get('style'):
            style = node.get('style')

            for tag_name, test in ( 
                ("b", "font-weight: bold;"), 
                ("s", "line-through"), 
                ("i", "font-style: italic;") ):
                    if test in style:
                        new_tag = self.soup.new_tag(tag_name)
                        new_tag.string = node.text # "content" is already escaped, using it would double escape!
                        content = self._process_simple_tags(new_tag)

            if '--en-highlight:' in style:
                color = re.search(r'--en-highlight:(\w+)', style)
                if color:
                    if self._use_html("highlight / background-color") and color.group(1) != "yellow":
                        content = f'<span style="color: white; background-color: {color.group(1)}">{content}</span>'
                    else:
                        content = f'=={content}=='

            if ('color:rgb' in style
                and style != 'color:rgb(0, 0, 0);'):  # Ignore black text color, since it is the default
                    # For some time, Evernote added a green color to internal links.
                    # We can keep the link as green if the user wants to use HTML
                    # AND didn't ask to remove green links.
                    internal_link = node.parent and node.parent.name == 'a' and re.match(
                        "^(evernote:///|https://www.evernote.com/|https://share.evernote.com/note/).+",
                        node.parent.get("href", "")
                    )
                    if (   style == 'color:rgb(105, 170, 53);' # Green/yellowish color of internal links
                        or style == "color:rgb(24, 168, 65);--inversion-type-color:simple;" # Green color
                        and internal_link
                        and self.options.get("remove_green_link", True)):
                            pass # don't add color
                    elif self._use_html("text color / color:rgb"):
                        content = f'<span style="{style}">{content}</span>'

        if node.name == "p":
            content = content.strip()
            content = f'{content}\n\n'  # Ensure double new line after paragraphs

        return content

    def _process_simple_tags(self, node) -> str:
        """Convert a few HTML simple tags to Markdown or keep them as HTML if there is no equivalent."""
        content = self._process_node_children(node)
        if not content or content.isspace():
            return ""

        # If we are formatting an external link, format only the anchor text
        url, lf = None, None
        if node.next and node.next.name == "a" and not content.startswith("[["):
            if (parts := re.findall(r'^\[(.*?)\]\((.*?)\)(.*)$', content, flags=re.S) ):
                content, url, lf = parts[0]

        result  = content
        # Check if there are spaces inside the tag, e.g., "<b>bold </b>",
        # to add them after the markdown, e.g., "**bold** "
        space_begin = " " if content and content[ 0].isspace() else ""
        space_end   = " " if content and content[-1].isspace() else ""
        stripped_content = content.strip()
        if   node.name in ("b", "strong"):
            result = f'{space_begin}**{stripped_content}**{space_end}'
        elif node.name in ("i", "em"):
            result = f'{space_begin}_{stripped_content}_{space_end}'
        elif node.name in ("s", "del"):
            result = f'{space_begin}~~{stripped_content}~~{space_end}'
        elif node.name == "blockquote":
            result = f"> " + "\n> ".join(stripped_content.split("\n")) + "\n"
        elif node.name == "code":
            if "\n" in content:
                  result = f'```\n{content}\n```\n'
            else: result = f'`{content}`'
        elif node.name in ("u", "ins", "sup", "sub"):
            # In Obsidian, HTML tags don't mix with Markdown,
            # so "**_<u>B+I+U.</u>_**" == "<u>B+I+U.</u>".
            # This could be worked around in a final stage (?), but... is it worth the hassle?
            if self._use_html(node.name):
                result = f'<{node.name}>{space_begin}{stripped_content}{space_end}</{node.name}>'
        if url:
            result = f'[{result}]({url}){lf}'
        return result

    def _process_header(self, node) -> str:
        """Convert HTML headers to Markdown headers."""
        level = int(node.name[1])
        content = self._process_node_children(node)
        return f'{"#" * level} {content}\n'

    def _process_checkbox(self, node) -> str:
        """Convert Evernote to-do checkboxes to Markdown."""
        # In Evernote, you can have multiple checkboxes anywhere in a single line.
        # In Obsidian Markdown, only one, in the beginning of the line?
        # Should leave a space after the last bracket, otherwise it won't appear as a checkbox.
        checked = node.attrs.get("checked", "") == "true"
        marker = '- [x] ' if checked else '- [ ] '
        return marker

    def _process_list(self, node) -> str:
        """Process ordered and unordered lists."""
        self.list_stack.append(node.name)
        self.indent_level += 1
        if node.name == "ol":
            self.number_indent[self.indent_level] = 0

        result = ''
        # If there is a <ul> or <ol> inside a <li>, add a new line at the start
        if node.parent and node.parent.name == "li":
            result = "\n"
        for child in node.children:
            result += self._process_node(child)

        self.indent_level -= 1
        self.list_stack.pop()
        return result

    def _process_list_item(self, node) -> str:
        """Process list items with proper indentation."""
        indent  = '    ' * (self.indent_level - 1)
        content = self._process_node_children(node)
        content = content.strip()

        # If list item has \n in the content, add indent
        content = content.replace("\n", f"\n{indent}   ")

        if '--en-checked:' in node.get('style', ''):
            checked = '--en-checked:true' in node.get('style', '')
            marker = '[x]' if checked else '[ ]'
            return f'{indent}- {marker} {content}\n'
        elif self.list_stack and self.list_stack[-1] == 'ol':
            self.number_indent[self.indent_level] += 1
            level = self.number_indent[self.indent_level]
            return f'{indent}{level}. {content}\n'
        else:
            return f'{indent}- {content}\n'

    def _process_table(self, node) -> str:
        """Convert HTML table to Markdown table."""
        # We can't converted nested tables. In that case, just return the HTML.
        if node.find("table"):
            self.warnings.append("Nested tables are not supported, returning HTML")
            return str(node)

        # Convert HTML table to Markdown table.
        self.inside_table = True
        result     = []
        max_cols   = 0
        row_spans  = {}  # Keeps track of remaining row spans for each column
        LEFT       = "---"
        CENTER     = ":-:"
        RIGHT      = "--:"

        # Step 1: Count rows and maximum number of columns.
        # A row's effective width can exceed any single row's colspan-sum
        # when an earlier row's rowspan extends into it, so we simulate
        # cell placement (mirroring Step 3's logic) to track the true width.
        rows = node.find_all('tr')
        pending = {}  # col -> remaining rowspan count, simulation only
        for row in rows:
            cols = row.find_all(["th", "td"])
            if not cols:
                continue
            col_num = 0
            for cell in cols:
                while pending.get(col_num, 0) > 0:
                    pending[col_num] -= 1
                    col_num += 1
                col_span = int(cell.get("colspan", 1))
                row_span = int(cell.get("rowspan", 1))
                for _ in range(col_span):
                    if row_span > 1:
                        pending[col_num] = pending.get(col_num, 0) + (row_span - 1)
                    col_num += 1
            max_cols = max(max_cols, col_num)

        # Step 2: Initialize table grid and row_spans
        grid = [[{"align":LEFT,"content":""} for _ in range(max_cols)] for _ in range(len(rows))]
        row_spans = {i: 0 for i in range(max_cols)}  # Tracks active rowspans for each column

        def add_to_grid(col_num, row_num, cell_content, html_node):
            cell  = grid[row_num][col_num]
            child = next(html_node.children, None)
            if child and hasattr(child, "get"):
                style = child.get("style", "")
                if   "text-align:center" in style: cell["align"] = CENTER
                elif "text-align:right"  in style: cell["align"] = RIGHT
            cell["content"] = cell_content.replace("\n", "<br>")

        # Step 3: Fill the grid
        row_num = 0
        for row in rows:
            cols = row.find_all(["th", "td"])
            if cols:
                col_num = 0  # Column number of the current cell
                for cell in cols:
                    # Move past any active rowspans from previous rows
                    while row_spans[col_num] > 0:
                        row_spans[col_num] -= 1
                        col_num += 1
                    # Get cell content
                    cell_content = self._process_node_children(cell).rstrip("\n")
                    add_to_grid(col_num, row_num, cell_content, cell)
                    # Skip empty cells (with current alignment) if there is a colspan or rowspan
                    col_span = int(cell.get("colspan", "1"))
                    row_span = int(cell.get("rowspan", "1"))
                    for x in range(col_span):
                        if row_span > 1:
                            row_spans[col_num] += row_span -1
                        col_num += 1
                # Adjust row_spans at the end of a row, if needed
                for x in range(col_num, max_cols):
                    row_spans[x] -= 1

            row_num += 1

        # Step 4: Create Markdown table from grid
        for grid_row in grid:
            row_content = [cell["content"] for cell in grid_row]
            result.append(f"| {' | '.join(row_content)} |")

        # Step 5: Add separators / column alignments
        if result:
            # Use the most common ("mode") alignment of each column as separator
            separators = [mode([grid[r][c]["align"] for r in range(len(grid))]) for c in range(max_cols)]
            result.insert(1, f"| {' | '.join(separators)} |")

        self.inside_table = False
        return "\n" + "\n".join(result) + "\n"

    def _process_link(self, node) -> str:
        """Convert HTML links to Markdown links."""
        content = self._process_node_children(node)
        href    = node.get('href', '')
        # https://help.obsidian.md/syntax#Escape+blank+spaces+in+links
        # (even though spaces in Evernote links are already escaped with %20)
        if " " in href:
            href = f"<{href}>"

        # Check if the note has preview enabled
        # Linked note - title
        #   <div style="--en-richlink:true; --en-href:[...]; --en-title:[...]; --en-viewAs:evernote-minimal;--en-requiredFeatures:[...]">
        #   <a href="[...]" rev="en_rl_small">A linked note</a></div>
        # Linked note - preview
        #   <div style="--en-richlink:true; --en-href:[...]; --en-title:[...]; --en-viewAs:evernote-note-snippet-preview;[...]">
        #   <a href="[...]" rev="en_rl_small">A linked note</a></div>
        preview = "!" if "evernote-note-snippet-preview" in node.parent.get("style","") else ""
        escape  = "\\" if self.inside_table else ""

        style = None
        if (match := re.search(r'<span style="(.*?)">(.*?)</span>', content)):
            style   = match.group(1)
            content = match.group(2)

        # Replace square brackets with parentheses if configuration says so.
        if self.options.get("escape_brackets", False):
            # At this point, brackets were already escaped, so remove slashes, too
            content = content.replace(r"\[", "(").replace(r"\]", ")")

        # Check for internal links and web note links
        if    (guid := re.match("evernote:///view/[^/]+/[^/]+/([0-9a-f-]+)/", href)) \
           or (guid := re.match("https://www.evernote.com/[^/]+/[^/]+/[^/]+/[^/]+/([0-9a-f-]+)", href)) \
           or (guid := re.match("https://share.evernote.com/note/(.+)", href)):
            if not (path := self.guid_to_path.get(guid[1])):
                path = content
                self.warnings.append(f"Path to link GUID not found: {guid[1]} ({content})")
            # Escaping links can get ugly pretty quickly...
            # At this point, square brackets were already escaped,
            # but they don't need to be for internal links, so we remove them...
            content = content.replace(r"\[", "[").replace(r"\]", "]")
            if style:
                  return f'<span style="{style}">{preview}[[{path}{escape}|{content}]]</span>'
            else: return f'{preview}[[{path}{escape}|{content}]]'

        # Return external link
        if style:
              return f'[<span style="{style}">{content}</span>]({href})'
        else: return f'[{content}]({href})'

    def _process_image(self, node) -> str:
        """Convert HTML images to Markdown image syntax."""
        # Evernote images are not in <img> tags, but in <en-media> tags.
        # See _process_media()
        src = node.get('src', '')
        if not src:
            return ""
        alt   = node.get('alt',   '')
        title = node.get('title', '') 
        if src.startswith("data:image"):
            # Base64 images are exported with <img> tag
            self.warnings.append(f"Added base64 image")
            alt_   = f' alt="{alt}"'     if alt   else ""
            title_ = f' title="{title}"' if title else ""
            return f'<img src="{src}"{alt_}{title_} />'
        if src.startswith('/'):
            src = f'./_resources{src}'
        return f'![{title or alt}]({src})'

    def _process_media(self, node) -> str:
        """Convert Evernote media to Obsidian Markdown."""
        result = ""
        type_  = node.get("type",  "")
        style  = node.get("style", "")
        hash_hex = node.get("hash", "")
        if not hash_hex:
            # Seems like Evernote Web Clips (sometimes? always?) ends with these "empty" media notes:
            # <br/><en-media hash="" type="" /><br/><en-media hash="" type="text/html" />
            # See https://github.com/AltoRetrato/evernote2obsidian/issues/17
            self.warnings.append(f"Media node without hash: {node}")
            return ""
        hash_int = int(hash_hex, 16)
        if not (file_path := self.hash_to_path.get(hash_int)):
            file_path = hash_hex
            self.warnings.append(f"Path to media hash not found: {hash_hex}")
            # TO-DO: this happened on a few (4?) notes where the media hash
            # in <resource> and <en-media> where different (Evernote bug?).
            # It could be interesting to list <resource>
            # hashes that were never referenced (orphans?)...
        file_name = os.path.split(file_path)[-1]
        escape    = "\\" if self.inside_table else ""
        preview   = "" if "--en-viewAs:attachment" in style else "!"
        result    = f"[[{file_path}{escape}|{file_name}]]"
        if type_.startswith("audio/") or type_.startswith("video/"):
            result = f"!{result}\n"
        elif type_ == "application/pdf":
            # Evernote can show PDF files in 3 different ways: attachment, pdf-pageByPage, pdf-full
            # Obsidian can show PDF files in 2 different ways: with or without preview

            # TBH, I'm a bit stumped about entries like this:
            # <en-media height="autopx" hash="..." type="application/pdf" />
            # Most of the time, the "autopx" makes the PDF appear as an attachment,
            # but sometimes it is a preview. It might depend on a number of factors,
            # such as the size of the PDF, the Evernote window size, and the context
            # in which the PDF is inserted (e.g., in a table cell).
            # In my notes, it was much better to consider the PDF in these cases
            # as an attachment, so we disable the preview.
            if not style and "autopx" in node.get("height", ""):
                preview = ""
            pdf_view    = self.options.get("pdf_view", "default")
            pdf_preview = {"default": preview, "title": "", "preview": "!"}.get(pdf_view, preview)
            result  = f"{pdf_preview}{result}\n"
        elif type_.startswith("image/"):
            width = node.get("width","")
            # Image alignment and full width are not supported in Markdown,
            # but we can use HTML:
            if ("--en-imageAlignment:center" in style and
                self._use_html("image alignment (center)")):
                    if width:
                          result = f'<div style="text-align: center;"><img src="{file_path}" width="{width}"></div>\n'
                    else: result = f'<div style="text-align: center;"><img src="{file_path}"></div>\n'
                    # Inline CSS also works, but has odd spacing in editing view and none in reading view.
                    # <img src="..." style="display: block; margin-left: auto; margin-right: auto;">
            elif ("--en-imageAlignment:right" in style and
                  self._use_html("image alignment (right)")):
                    if width:
                          result = f'<div style="text-align: right;"><img src="{file_path}" width="{width}"></div>\n'
                    else: result = f'<div style="text-align: right;"><img src="{file_path}"></div>\n'
                    # <img src="..." style="display: block; margin-left: auto; margin-right: 0;">
            elif ("--en-imageAlignment:fullWidth" in style and
                  self._use_html("image alignment (right)")):
                    result = f'<img src="{file_path}" style="width: 100%;">\n'
            else:
                # If next node is a <div>, <p> or <br>, add a new line, otherwise add a space
                nl = "\n" if node.next_sibling and node.next_sibling.name in block_level_elements else " "
                if width:
                    try:
                        width_val = int(float(width.strip("px")))
                        result = f'{preview}[[{file_path}\\|{width_val}]]{nl}'
                    except ValueError:
                        # Width is not a valid number (e.g., "auto"), so don't specify it
                        result = f'{preview}{result}{nl}'
                else:
                    result = f'{preview}{result}{nl}'
        else:
            pass
            #self.warnings.append(f"Unsupported media type: {type_}")
        return result

    def _process_node_children(self, node) -> str:
        """Process all children of a node."""
        style = node.get('style', '')
        entered_codeblock = "--en-codeblock:true"  in style
        if entered_codeblock:
            self.inside_pre = True
        result = ''.join(self._process_node(child) for child in node.children)
        if entered_codeblock:
            self.inside_pre = False
        return result

    def escape_non_url(self, part):
        if self.url_pattern.match(part):
            return part  # Don't escape URLs

        # Escape all instances of [ ] ` * $
        part = re.sub(r"([\[\]`*\$])", r"\\\1", part)

        # Escape all _ preceeded by nothing or a space and followed by a non-space character
        part = re.sub(r"(^|\s)([_]+)(?=\S)", lambda m: m.group(1) + "\\" + "\\".join(m.group(2)), part)

        # Escape instances of * _ when they are followed by a non-space character
        # Works in editing mode, but not always in reading mode (e.g., "1 * 2 * 3")
        # text = re.sub(r"([*_^]+)(\S)", lambda m: "\\" + "\\".join(m.group(1)) + m.group(2), text)

        # Escape "%%"
        part = part.replace("%%", "%\\%")

        # Escape possible HTML tags that appear as text
        part = re.sub(r"<(?=[^>]+>)", r"\\<", part)

        # Escape single # preceded by nothing or spaces, and followed by a non-space character
        part = re.sub(r'(^|\s)(#)(?=\S)(?!#)', r'\1\\\2', part)

        # Escape single ^ preceded by nothing or spaces, and followed by a non-space character
        part = re.sub(r'(^|\s)(\^)(?=\S)', r'\1\\\2', part)

        # Escape sequences of two or more = ~ followed by a non-space character
        part = re.sub(r"([=~]{2,})(?=\S)", lambda m: "\\" + "\\".join(m.group(1)), part)

        # Escape sequences of three or more - *
        #text = re.sub("([-*]{3,})", lambda m: "\\" + "\\".join(m.group(1)), text)

        # Escape - + = > # | when they appear at the start of a line (even if preceeded by spaces)
        part = re.sub(r"(?m)^(\s*)([\-+=>#|])", r"\1\\\2", part)

        # Escape ordered / numbered lists (e.g.: 1. ... => 1\. ...)
        part = re.sub(r"(?m)^(\s*\d+)(\.\s+)", r"\1\\\2", part)

        # If not escaping $ above / previously, these two regexes
        # give a better result when using only editing view.
        # # Escape single dollar signs pair to avoid inline math
        # part = re.sub(r"\$(?!\s)([^$]+)(?<!\s)\$", r"\$\1$", part)
        # # Escape sequences of two or more $
        # part = re.sub(r"([$]{2,})", lambda m: "\\" + "\\".join(m.group(1)), part)

        if self.inside_table:
            part = part.replace("|", r"\|")

        return part

    def _escape_text(self, node) -> str:
        """Escape text content of a node, excluding URLs."""
        text = node.string or ''
        if not text:
            return ''

        # Do not escape text from <pre>, <code> or <a> tags
        if self.inside_pre: # or (node.parent and node.parent.name == "a"):
            return text

        # Split the text into parts, separating URLs and other text
        parts = re.split(f'({self.url_pattern.pattern})', text)

        # Escape non-URL parts and reconstruct the text
        escaped_text = ''.join(self.escape_non_url(part) for part in parts)

        return escaped_text
