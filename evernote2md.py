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

import logging
import os
import re
from   bs4         import BeautifulSoup
from   typing      import List, Tuple, Dict
from   statistics  import mode, StatisticsError
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
            md_properties: List  = None,
            tasks: Dict         = None,
            guid_to_path: Dict  = None,
            hash_to_path: Dict  = None,
            options:      Dict  = None,
            ) -> Tuple[str, List]:
        """ Convert HTML content to Markdown format. """

        if md_properties is None: md_properties = []
        if tasks is None:         tasks = {}
        if guid_to_path is None:  guid_to_path = {}
        if hash_to_path is None:  hash_to_path = {}
        if options is None:       options = {}

        self.tasks        = tasks        # dict. for tasks (provided by caller)
        self.guid_to_path = guid_to_path # dict. for links (provided by caller)
        self.hash_to_path = hash_to_path # dict. for attachments (provided by caller)
        self.options      = options      # dict. for options

        # Reset some variables
        self.list_stack    = []
        self.indent_level  = 0        # used in lists, list items
        self.number_indent = {}       # used in ordered lists
        self.warnings      = []       # list of (level, message) tuples returned after conversion
        self.inside_pre    = False    # True if processing content that should not be escaped
        self.inside_table  = False    # True if processing a table

        # Parse HTML
        self.soup = BeautifulSoup(html_content, 'html.parser')

        # Remove script and style elements
        for element in self.soup(['script', 'style']):
            element.decompose()

        if self.options.get("hr_as_h1", False):
            self._promote_hr_to_h1()

        if self.options.get("normalize_heading_levels", True):
            self._normalize_heading_levels()

        if self.options.get("bold_as_heading", False):
            self._promote_bold_to_heading()

        # Convert to markdown
        markdown = self._process_node(self.soup)

        # Add properties
        if md_properties:
            properties = ["---"] + md_properties + ["---\n"]
            markdown = '\n'.join(properties) + markdown

        # Return a short(er) list of (level, message) warnings
        counter = Counter(self.warnings)
        sorted_warnings = sorted(
            counter.items(),
            key=lambda x: (-x[1], x[0][1]) # First by count (descending), then by message (ascending)
        )
        warnings = [
            (level, f"{msg} [{count}x]") if count > 1 else (level, msg)
            for (level, msg), count in sorted_warnings
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
        self.warnings.append((logging.INFO, f"{'Added' if self.use_html else 'Removed'} unsupported HTML: {html}"))
        return self.use_html

    def _process_div(self, node) -> str:
        """Process div elements, handling special cases like alignment."""
        style   = node.get('style', '')
        result  = self._process_node_children(node)

        # Table of contents
        if "--en-tableofcontents:true" in style:
            # Shouldn't be too hard to implement, but might just not be worth it
            # since Obsidian can show a note outline in the right side bar.
            self.warnings.append((logging.INFO, "Ignored Table of Contents (conversion not implemented)"))
            return ""
        # Code block
        elif "--en-codeblock:true" in style:
            language = (re.findall("--en-syntaxLanguage:(.+?);", style) or [""])[0]
            result = f"```{language}\n{result}```"
        # Tasks
        elif "--en-task-group:true" in style:
            ids = re.findall("--en-id:([0-9a-f-]+);", style)
            task_id = ids[0] if ids else None
            if self.tasks and task_id and task_id in self.tasks:
                  result = self.tasks[task_id]
            else: return ""  # Empty task group (no tasks in database) — skip
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
                indent = "  " * (int(padding_left[0])//40)
                result = f'{indent}{result}'
                # If list item has \n in the content, add indent
                result = result.replace("\n", f"\n{indent}")

            # Collapse leading non-breaking / regular spaces to max 3 to avoid
            # accidental code blocks (4+ spaces after a blank line = code).
            stripped = result.lstrip(' \xa0')
            leading = len(result) - len(stripped)
            if leading >= 4:
                indent = "  " * (leading // 5 or 1)
                result = indent + stripped

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
                    if (internal_link
                        and self.options.get("remove_green_link", True)
                        and style in ('color:rgb(105, 170, 53);',
                                      'color:rgb(24, 168, 65);--inversion-type-color:simple;')):
                            pass  # green internal-link color — strip it
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
        nxt = node.find_next_sibling()
        if nxt and nxt.name == "a" and not content.startswith("[["):
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
            quoted_lines = ['> [!quote] ']
            for line in stripped_content.split('\n'):
                s = line.rstrip()
                quoted_lines.append(f'> {s}' if s else '>')
            result = '\n'.join(quoted_lines) + '\n\n'
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
        stripped = content.strip().replace("**", "")
        if not stripped:
            return ""
        return f'{"#" * level} {stripped}\n'

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
        has_direct_items = any(
            child.name == "li" for child in node.children if hasattr(child, "name")
        )
        if has_direct_items:
            self.list_stack.append(node.name)
            self.indent_level += 1
            if node.name == "ol":
                self.number_indent[self.indent_level] = int(node.get("start", 1)) - 1

        result = ''
        # If there is a <ul> or <ol> inside a <li>, add a new line at the start
        if node.parent and node.parent.name == "li":
            result = "\n"
        for child in node.children:
            result += self._process_node(child)

        if has_direct_items:
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
            level = logging.INFO if self._is_web_clip_note() else logging.WARNING
            self.warnings.append((level, "Nested tables are not supported, returning HTML"))
            return str(node)

        # Convert HTML table to Markdown table.
        self.inside_table = True
        result     = []
        max_cols   = 0
        row_spans  = {}  # Keeps track of remaining row spans for each column
        LEFT       = "---"
        CENTER     = ":-:"
        RIGHT      = "--:"

        # Step 1: Count rows and maximum number of columns
        rows = node.find_all('tr')
        for row in rows:
            cols = row.find_all(["th", "td"])
            current_cols = sum(int(cell.get("colspan", 1)) for cell in cols)
            max_cols = max(max_cols, current_cols)

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
                    if row_spans[x] > 0:
                        row_spans[x] -= 1

            row_num += 1

        # Step 4: Create Markdown table from grid
        for grid_row in grid:
            row_content = [cell["content"] for cell in grid_row]
            result.append(f"| {' | '.join(row_content)} |")

        # Step 5: Add separators / column alignments
        if result:
            def _safe_mode(values, default=LEFT):
                try:
                    return mode(values)
                except StatisticsError:
                    return default
            separators = [_safe_mode([grid[r][c]["align"] for r in range(len(grid))]) for c in range(max_cols)]
            result.insert(1, f"| {' | '.join(separators)} |")

        self.inside_table = False
        return "\n" + "\n".join(result) + "\n"

    _unicode_spaces = re.compile(r'[\u00A0\u2007\u202F\u2060\uFEFF]+')

    def _is_web_clip_note(self) -> bool:
        """Return True when converting content from a web clip note."""
        return bool(self.options.get("_is_web_clip_note", False))

    def _process_link(self, node) -> str:
        """Convert HTML links to Markdown links."""
        content = self._unicode_spaces.sub(' ', self._process_node_children(node))
        href    = node.get('href', '')
        # Prevent accidental Obsidian ==highlight== parsing inside link labels.
        content = content.replace("==", r"\=\=")
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
        preview = ""
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
                deleted_guid_to_title = self.options.get("_deleted_guid_to_title", {})
                if deleted_guid_to_title.get(guid[1]):
                    path = deleted_guid_to_title[guid[1]]
                    path = self._unicode_spaces.sub(' ', path).strip()
                    path = path.replace('|', ' - ').replace('[', '(').replace(']', ')')
                    self.warnings.append((logging.INFO, f"Path to link GUID not found in active export, using deleted note title: {guid[1]} ({path})"))
                else:
                    path = content
                    self.warnings.append((logging.WARNING, f"Path to link GUID not found: {guid[1]} ({content})"))
            # Remove .md extension from path for internal links
            path_without_ext = path[:-3] if path.lower().endswith('.md') else path
            # Escaping links can get ugly pretty quickly...
            # At this point, square brackets were already escaped,
            # but they don't need to be for internal links, so we remove them...
            content = content.replace(r"\[", "[").replace(r"\]", "]")
            if style:
                  return f'<span style="{style}">{preview}[[{path_without_ext}{escape}]]</span>'
            else: return f'{preview}[[{path_without_ext}{escape}]]'

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
            self.warnings.append((logging.INFO, "Added base64 image"))
            alt_   = f' alt="{alt}"'     if alt   else ""
            title_ = f' title="{title}"' if title else ""
            return f'<img src="{src}"{alt_}{title_} />'
        if src.startswith('/'):
            src = f'./_resources{src}'
        return f'![{title or alt}]({src})'

    def _promote_hr_to_h1(self):
        """Replace <div>text</div><hr/> with <h1>text</h1> in the parsed soup."""
        for hr in list(self.soup.find_all('hr')):
            prev = hr.find_previous_sibling()
            if not prev or prev.name != 'div':
                continue
            text = prev.get_text(strip=True)
            if not text or prev.find(['div', 'table', 'ul', 'ol', 'en-media', 'img']):
                continue
            nxt = hr.find_next_sibling()
            h1 = self.soup.new_tag('h1')
            h1.string = text
            prev.replace_with(h1)
            hr.decompose()
            if nxt and nxt.name and not nxt.get_text(strip=True):
                nxt.decompose()

    @staticmethod
    def _is_bold_element(tag):
        """Check if a tag is visually bold (<b>, <strong>, or font-weight:bold span)."""
        if not hasattr(tag, 'name'):
            return False
        if tag.name in ('b', 'strong'):
            return True
        if tag.name == 'span':
            style = tag.get('style', '')
            if 'font-weight' in style and ('bold' in style or '700' in style):
                return True
        return False

    def _promote_bold_to_heading(self):
        """In notes with no headings, convert bold-only divs to heading tags."""
        if self.soup.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            return
        for div in list(self.soup.find_all('div')):
            children = [c for c in div.children if str(c).strip()]
            if len(children) != 1:
                continue
            child = children[0]
            if not self._is_bold_element(child):
                continue
            text = child.get_text(strip=True)
            if not text or len(text) > 80:
                continue
            h1 = self.soup.new_tag('h1')
            h1.string = text
            div.replace_with(h1)

    def _normalize_heading_levels(self):
        """Close gaps in heading hierarchy (e.g. h1→h3 becomes h1→h2)."""
        headings = self.soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if not headings:
            return
        prev_orig = 0
        prev_new  = 0
        level_map = {}
        for h in headings:
            orig = int(h.name[1])
            if orig < prev_orig:
                level_map = {k: v for k, v in level_map.items() if k <= orig}
            if orig in level_map:
                new = level_map[orig]
            elif orig > prev_new + 1:
                new = prev_new + 1
                level_map[orig] = new
            else:
                new = orig
            prev_orig = orig
            prev_new  = new
            if new != orig:
                h.name = f'h{new}'

    @staticmethod
    def _has_adjacent_pdf(node) -> bool:
        """Check if the previous or next sibling is also a PDF en-media tag."""
        for sibling in (node.previous_sibling, node.next_sibling):
            if (sibling and sibling.name == "en-media"
                    and "application/pdf" in sibling.get("type", "")):
                return True
        return False

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
            self.warnings.append((logging.WARNING, f"Media node without hash: {node}"))
            return ""
        # Handle UUID format hashes (with hyphens) by removing them
        hash_hex_clean = hash_hex.replace("-", "")
        try:
            hash_int = int(hash_hex_clean, 16)
        except ValueError:
            hash_int = None
        if hash_int is not None and (file_path := self.hash_to_path.get(hash_int)):
            pass
        else:
            file_path = hash_hex
            level = logging.INFO if self._is_web_clip_note() else logging.WARNING
            self.warnings.append((level, f"Path to media hash not found: {hash_hex}"))
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
            pdf_view    = self.options.get("pdf_view", "hybrid")
            if pdf_view == "hybrid":
                pdf_preview = "" if self._has_adjacent_pdf(node) else preview
            else:
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
                  self._use_html("image alignment (fullWidth)")):
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
        elif type_ == "application/octet-stream":
            _IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp', '.tiff', '.tif', '.ico'}
            ext = os.path.splitext(file_name)[1].lower()
            if ext in _IMAGE_EXTS:
                nl = "\n" if node.next_sibling and node.next_sibling.name in block_level_elements else " "
                result = f'{preview}{result}{nl}'
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

        # Escape - + = > # | when they appear at the start of a line (even if preceeded by spaces)
        part = re.sub(r"(?m)^(\s*)([\-+=>#|])", r"\1\\\2", part)

        # Escape ordered / numbered lists (e.g.: 1. ... => 1\. ...)
        part = re.sub(r"(?m)^(\s*\d+)(\.\s+)", r"\1\\\2", part)

        if self.inside_table:
            part = part.replace("|", r"\|")

        return part

    def _escape_text(self, node) -> str:
        """Escape text content of a node, excluding URLs."""
        text = node.string or ''
        if not text:
            return ''

        # Do not escape text from <pre>, <code> or <a> tags
        if self.inside_pre:
            return text

        # Split the text into parts, separating URLs and other text
        parts = re.split(f'({self.url_pattern.pattern})', text)

        # Escape non-URL parts and reconstruct the text
        escaped_text = ''.join(self.escape_non_url(part) for part in parts)

        return escaped_text
