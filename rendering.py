# rendering.py
# --- Official Module ---
import flask
import html
import re
import markdown
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit
import sqlite3
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename
from pygments.util import ClassNotFound

# --- Personal Module ---
import config
from table import _split_table_cells, table


_UNSAFE_SOURCE_ELEMENT_PATTERN = re.compile(
    r'<\s*(script|style|iframe|object|applet)\b[^>]*>.*?'
    r'</\s*\1\s*>'
    r'|<\s*(?:embed|base|meta|link)\b[^>]*?/?>',
    re.IGNORECASE | re.DOTALL
)
_TABLE_CELL_METADATA_PATTERN = re.compile(
    r'<(?:tablealign|tablebgcolor|tablecolor|tablebordercolor|'
    r'tabletextalign|tablewidth|bgcolor|color|width|rowbgcolor|'
    r'rowcolor|rowtextalign|colbgcolor|colcolor|coltextalign|'
    r'textalign)(?:=[^<>"\']*)?>|<\^\d+>|<-\d+>|<[():]>',
    re.IGNORECASE
)


def _sanitize_source_html(value):
    if not isinstance(value, str):
        return ''

    value = re.sub(r'<.*?>.*?</.*?>', '', value, flags=re.DOTALL)
    return re.sub(r'<.*?>', '', value, flags=re.DOTALL)


def _strip_unsafe_source_elements(value):
    return _UNSAFE_SOURCE_ELEMENT_PATTERN.sub('', value)


@lru_cache(maxsize=1)
def _existing_css_classes():
    stylesheet_path = Path(__file__).resolve().parent / 'static' / 'style.css'
    stylesheet = stylesheet_path.read_text(encoding='utf-8')
    stylesheet = re.sub(r'/\*.*?\*/', '', stylesheet, flags=re.DOTALL)
    selectors = re.findall(r'([^{}]+)\{[^{}]*\}', stylesheet, flags=re.DOTALL)
    return {
        class_match.group(1)
        for selector_group in selectors
        for class_match in re.finditer(
            r'\.([A-Za-z_][A-Za-z0-9_-]*)',
            selector_group
        )
    }


def rendering(text, function=[], db_check_func=None, current_title=None, include_params=None, include_depth=0, include_stack=None, db_read_func=None):
    rendered = text
    syntax_blocks = []
    syntax_marker_prefix = 'WIKISYNTAXBLOCKTOKEN'
    while syntax_marker_prefix in rendered:
        syntax_marker_prefix += 'X'

    def restore_syntax_blocks(value, markdown_blocks=False):
        for syntax_index, syntax_html in enumerate(syntax_blocks):
            syntax_marker = f'{syntax_marker_prefix}{syntax_index}END'
            replacement = (
                f'\n\n{syntax_html}\n\n' if markdown_blocks else syntax_html
            )
            value = value.replace(syntax_marker, replacement)
        return value

    literal_blocks = []
    literal_marker_prefix = 'WIKILITERALBLOCKTOKEN'
    while literal_marker_prefix in rendered:
        literal_marker_prefix += 'X'

    Secured = []
    folding_blocks = []
    style_blocks = []
    protected_table_syntax = []
    protected_marker_prefix = None
    effective_params = include_params or {}
    active_stack = list(include_stack or [])

    def restore_protected_table_syntax(value):
        if not config.SAFE_HTML or protected_marker_prefix is None:
            return value
        for protected_index, source_syntax in enumerate(protected_table_syntax):
            value = value.replace(
                f'{protected_marker_prefix}TABLE{protected_index}END',
                source_syntax
            )
        return value

    def transform_table_cells(line, transform):
        stripped = line.strip()
        if not (stripped.startswith('|') and stripped.endswith('|')):
            return line
        cells = _split_table_cells(line)
        if not cells:
            return line

        def transform_cell(cell):
            metadata = []
            content = _TABLE_CELL_METADATA_PATTERN.sub(
                lambda match: metadata.append(match.group(0)) or '',
                cell
            )
            return ''.join(metadata) + transform(content)

        return '|' + '|'.join(transform_cell(cell) for cell in cells) + '|'

    def link(t):
        def normalize_internal_link_target(target):
            target = target.strip()
            if target.startswith(":분류:"):
                return target[1:]
            elif target.startswith(":파일:"):
                return target[1:]
            return target

        def internal_link_url(doc_name):
            if '#' in doc_name and db_check_func and db_check_func(doc_name):
                return f'/w/{quote(doc_name, safe="/")}'
            if '#' in doc_name and not doc_name.startswith('#'):
                path, anchor = doc_name.split('#', 1)
                return f'/w/{quote(path, safe="/")}#{quote(anchor, safe="")}'
            return f'/w/{quote(doc_name, safe="/")}'

        def relative_wiki_link(target):
            if not target.startswith('/') or target.startswith('//') or '\\' in target:
                return None

            try:
                parsed = urlsplit(target)
            except ValueError:
                return None

            if parsed.scheme or parsed.netloc or not parsed.path.startswith('/'):
                return None

            path = quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
            query = quote(parsed.query, safe="=&?/:@!$'()*+,;%-._~")
            fragment = quote(parsed.fragment, safe="/?:@!$&'()*+,;=%-._~")
            url = urlunsplit(('', '', path, query, fragment))
            link_title = target
            lookup_title = unquote(parsed.path[3:]).strip() if parsed.path.startswith('/w/') else None

            revision_query = re.fullmatch(r'rev=(\d+)', parsed.query)
            if lookup_title is not None and revision_query and not parsed.fragment:
                revision = revision_query.group(1).lstrip('0')
                if revision:
                    link_title = lookup_title or target
                    url = f'/w/{quote(lookup_title, safe="/")}?rev={revision}'

            return link_title, url, lookup_title

        def safe_link_display(value):
            result = []
            cursor = 0
            color_span_depth = 0
            tag_pattern = re.compile(r'<[^>]*>')
            color_span_pattern = re.compile(
                r'<span style="color: (?:#[0-9A-Fa-f]{3,8}|[A-Za-z][A-Za-z0-9-]*);">'
            )

            for match in tag_pattern.finditer(value):
                result.append(html.escape(html.unescape(value[cursor:match.start()]), quote=False))
                tag = match.group(0)
                if color_span_pattern.fullmatch(tag):
                    result.append(tag)
                    color_span_depth += 1
                elif tag == '</span>' and color_span_depth:
                    result.append(tag)
                    color_span_depth -= 1
                cursor = match.end()

            result.append(html.escape(html.unescape(value[cursor:]), quote=False))
            return ''.join(result)

        t = re.sub(
            r'@([^@\s]+)@',
            lambda m: str(effective_params.get(m.group(1), '')),
            t
        )

        def file_link_replacer(m):
            raw = m.group(1).strip()
            parts = [part.strip() for part in raw.split('|') if part.strip()]

            if not parts:
                return m.group(0)

            filename = parts[0]
            attrs = {}

            for item in parts[1:]:
                if '=' in item:
                    key, value = item.split('=', 1)
                    attrs[key.strip().lower()] = value.strip()
                elif item:
                    attrs['alt'] = item

            attrs.setdefault('alt', filename)

            attr_html = []
            for key, value in attrs.items():
                if key in {'width', 'height', 'alt'}:
                    attr_html.append(f'{key}="{html.escape(value)}"')
                elif key == 'class':
                    attr_html.append(f'class="{html.escape(value)}"')
                elif key == 'style':
                    attr_html.append(f'style="{html.escape(value)}"')

            src = f"/images/{filename}"
            return f'<img src="{src}" {" ".join(attr_html)}>'

        t = re.sub(r'\[\[파일:(.*?)\]\]', file_link_replacer, t)

        def external_link_replacer(m):
            url = html.unescape(m.group(1).strip())
            raw_title = m.group(2)
            title = raw_title.strip() if raw_title else url

            plain_title = html.escape(re.sub(r"<[^>]+>", "", url), quote=True)
            safe_url = html.escape(url, quote=True)
            safe_title = safe_link_display(title)

            return f'<a class="wiki-link external" href="{safe_url}" target="_blank" title="{plain_title}">🔗{safe_title}</a>'

        t = re.sub(r'\[\[(https?://[^\|\]]+)(?:\|((?:(?!\]\]).)+))?\]\]', external_link_replacer, t)

        def internal_pipe_link_replacer(m):
            doc_name = normalize_internal_link_target(m.group(1))
            display_name = m.group(2).strip()

            if not doc_name:
                return m.group(0)

            if not display_name:
                display_name = doc_name

            relative_link = relative_wiki_link(doc_name)
            if relative_link:
                link_title, relative_url, lookup_title = relative_link
                plain_title = html.escape(link_title, quote=True)
                safe_doc_url = html.escape(relative_url, quote=True)
                safe_display_name = safe_link_display(display_name)
                if lookup_title is not None and db_check_func and not db_check_func(lookup_title):
                    return f'<a class="wiki-link erroneous" href="{safe_doc_url}" title="{plain_title}">{safe_display_name}</a>'
                return f'<a class="wiki-link" href="{safe_doc_url}" title="{plain_title}">{safe_display_name}</a>'

            plain_title = html.escape(re.sub(r"<[^>]+>", "", doc_name), quote=True)
            if doc_name.startswith('#') and len(doc_name) > 1 and not (db_check_func and db_check_func(doc_name)):
                safe_anchor = html.escape('#' + quote(doc_name[1:], safe=''), quote=True)
                safe_display_name = safe_link_display(display_name)
                return f'<a class="wiki-link" href="{safe_anchor}" title="{plain_title}">{safe_display_name}</a>'

            safe_doc_url = html.escape(internal_link_url(doc_name), quote=True)
            safe_display_name = display_name

            lookup_title = doc_name if doc_name == '#' else doc_name.split('#', 1)[0].strip()

            if lookup_title and db_check_func and not db_check_func(lookup_title):
                return f'<a class="wiki-link erroneous" href="{safe_doc_url}" title="{plain_title}">{safe_display_name}</a>'
            return f'<a class="wiki-link" href="{safe_doc_url}" title="{plain_title}">{safe_display_name}</a>'

        t = re.sub(r'\[\[([^\|\]]*)\|([^\]]*)\]\]', internal_pipe_link_replacer, t)

        def process_categories(t):
            categories = []

            def collector(m):
                before = m.group('before') or ''
                after = m.group('after') or ''
                name = m.group('tag').strip()

                if before and after:
                    return m.group(0)

                categories.append(name)
                return before + after

            t = re.sub(
                r'(?P<before>\\)?\[\[분류:(?P<tag>[^\]]+)\]\](?P<after>\\)?',
                collector,
                t
            )

            if not categories:
                return t

            chips = ''.join(
                f'<a href="/w/{quote(f"분류:{name}", safe="")}" class="category-chip">'
                f'📂 {html.escape(name)}</a>'
                for name in categories
            )

            box = (
                '<div class="category-box">'
                '<span class="category-box-title">분류</span>'
                f'<div class="category-chip-list">{chips}</div>'
                '</div>'
            )

            return box + ('\n' if t else '') + t

        t = process_categories(t)

        def plain_link_replacer(m):
            doc_name = normalize_internal_link_target(m.group(1))
            if not doc_name:
                return m.group(0)

            relative_link = relative_wiki_link(doc_name)
            if relative_link:
                link_title, relative_url, lookup_title = relative_link
                plain_title = html.escape(link_title, quote=True)
                safe_url = html.escape(relative_url, quote=True)
                safe_text = html.escape(link_title, quote=False)
                if lookup_title is not None and db_check_func and not db_check_func(lookup_title):
                    return f'<a class="wiki-link erroneous" href="{safe_url}" title="{plain_title}">{safe_text}</a>'
                return f'<a class="wiki-link" href="{safe_url}" title="{plain_title}">{safe_text}</a>'

            plain_title = html.escape(re.sub(r"<[^>]+>", "", doc_name), quote=True)
            if doc_name.startswith('#') and len(doc_name) > 1 and not (db_check_func and db_check_func(doc_name)):
                safe_anchor = html.escape('#' + quote(doc_name[1:], safe=''), quote=True)
                safe_text = html.escape(re.sub(r"<[^>]+>", "", doc_name), quote=False)
                return f'<a class="wiki-link" href="{safe_anchor}" title="{plain_title}">{safe_text}</a>'

            safe_doc_url = html.escape(internal_link_url(doc_name), quote=True)
            safe_text = html.escape(re.sub(r"<[^>]+>", "", doc_name), quote=False)
            lookup_title = doc_name if doc_name == '#' else doc_name.split('#', 1)[0].strip()
            if lookup_title and db_check_func and not db_check_func(lookup_title):
                return f'<a class="wiki-link erroneous" href="{safe_doc_url}" title="{plain_title}">{safe_text}</a>'
            return f'<a class="wiki-link" href="{safe_doc_url}" title="{plain_title}">{safe_text}</a>'

        t = re.sub(r'\[\[([^\]|]+)\]\]', plain_link_replacer, t)

        return t

    def macro(t):
        def replace_video(m):
            params_str = m.group(1)

            params = {
                "platform": "",
                "src": "",
                "width": "640",
                "height": "360"
            }

            for item in params_str.split(","):
                item = item.strip()

                if "=" in item:
                    key, value = item.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    if key in params:
                        params[key] = value

            platform = params["platform"].lower()
            video_id = params["src"]

            if platform in ("youtube", "yt"):
                embed_url = f"https://www.youtube.com/embed/{video_id}"
            elif platform == "vimeo":
                embed_url = f"https://player.vimeo.com/video/{video_id}"
            else:
                embed_url = video_id

            return (
                f'<iframe width="{params["width"]}" '
                f'height="{params["height"]}" '
                f'src="{embed_url}" '
                f'frameborder="0" '
                f'loading="lazy" '
                f'allowfullscreen></iframe>'
            )

        t = re.sub(r'\[video\((.*?)\)\]', replace_video, t)

        def replace_dday(m):
            date_str = m.group(1).strip()
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                today = datetime.now().date()
                diff = (target_date - today).days

                if diff > 0:
                    return f'-{diff}'
                elif diff < 0:
                    return f'+{abs(diff)}'
                else:
                    return '0'
            except ValueError:
                return m.group(0)

        t = re.sub(r'\[dday\((.*?)\)\]', replace_dday, t)

        def replace_age(m):
            date_str = m.group(1).strip()
            try:
                birth_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                today = datetime.now().date()

                age = today.year - birth_date.year
                if (today.month, today.day) < (birth_date.month, birth_date.day):
                    age -= 1

                return str(max(0, age))
            except ValueError:
                return m.group(0)

        t = re.sub(r'\[age\((.*?)\)\]', replace_age, t)

        t = re.sub(r'\[clearfix\]', '<div class="wiki-clearfix"></div>', t, flags=re.IGNORECASE)

        def replace_page(m):
            namespace = (m.group(1) or '').strip()

            try:
                conn = sqlite3.connect(config.DB_PATH)
                cursor = conn.cursor()

                if not namespace:
                    cursor.execute("SELECT COUNT(*) FROM documents")
                elif namespace == '문서':
                    namespace_conditions = ' AND '.join(
                        'title NOT LIKE ?' for _ in config.NAMESPACE_LIST
                    )
                    namespace_prefixes = [f'{item}:%' for item in config.NAMESPACE_LIST]
                    if namespace_conditions:
                        cursor.execute(
                            f"SELECT COUNT(*) FROM documents WHERE {namespace_conditions}",
                            namespace_prefixes
                        )
                    else:
                        cursor.execute("SELECT COUNT(*) FROM documents")
                else:
                    cursor.execute(
                        "SELECT COUNT(*) FROM documents WHERE title LIKE ?",
                        (f'{namespace}:%',)
                    )

                page_count = cursor.fetchone()[0]
                conn.close()
                return str(page_count)
            except Exception:
                return m.group(0)

        t = re.sub(r'\[page(?:\(([^()]*)\))?\]', replace_page, t, flags=re.IGNORECASE)

        def replace_include(m):
            raw = m.group(1).strip()
            if not raw:
                return m.group(0)

            if ',' in raw:
                doc_name_part, param_part = raw.split(',', 1)
                doc_name = doc_name_part.strip()
                param_pairs = []
                for item in param_part.split(','):
                    item = item.strip()
                    if '=' in item:
                        key, value = item.split('=', 1)
                        param_pairs.append((key.strip(), value.strip()))
            else:
                doc_name = raw.strip()
                param_pairs = []

            if not doc_name:
                return m.group(0)

            if include_depth >= 2:
                return '<div class="wiki-include-limit">[include 제한: 최대 2단계까지 허용]</div>'

            if doc_name in active_stack:
                return f'<div class="wiki-include-circular">[include 순환 포함: {html.escape(doc_name)}]</div>'

            if db_check_func and not db_check_func(doc_name):
                return f'<div class="wiki-include-missing">{html.escape(doc_name)}</div>'

            try:
                if db_read_func is not None:
                    included_text = db_read_func(doc_name)
                else:
                    conn = sqlite3.connect(config.DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("SELECT content FROM documents WHERE title = ?", (doc_name,))
                    row = cursor.fetchone()
                    conn.close()
                    included_text = row[0] if row else None

                if not included_text:
                    return f'<div class="wiki-include-missing">{html.escape(doc_name)}</div>'

                included_text = included_text.lstrip('\r\n')

                params = {}
                for key, value in param_pairs:
                    params[key] = value

                def replace_params(text):
                    def repl(match):
                        name = match.group(1)
                        return params.get(name, '')
                    return re.sub(r'@([^@\s]+)@', repl, text)

                included_text = re.sub(r'\[\[분류:[^\]]+\]\]', '', included_text)
                included_text = included_text.lstrip('\r\n')
                included_rendered = rendering(
                    included_text,
                    function=function,
                    db_check_func=db_check_func,
                    current_title=current_title,
                    include_params=params,
                    include_depth=include_depth + 1,
                    include_stack=active_stack + [doc_name],
                    db_read_func=db_read_func
                )
                return replace_params(included_rendered)
            except Exception:
                return m.group(0)

        def replace_toc(t):
            if '[목차]' not in t:
                return t

            headings = re.findall(r'<h[1-6] id="s-([0-9.]+)"><a id="[^"]*"></a>(.*?)</h[1-6]>', t)
            if not headings:
                return re.sub(r'\[목차\]', '', t)

            items = ''.join(
                f'<li style="margin-left:{num.count(".") * 16}px;">'
                f'<a href="#s-{num}">{num}. {re.sub(r"^\d+(?:\.\d+)*\.\s*", "", text)}</a></li>'
                for num, text in headings
            )
            box = (
                '<div class="toc-box">'
                '<div class="toc-title">목차</div>'
                f'<ul class="toc-list">{items}</ul>'
                '</div>'
            )
            return re.sub(r'\[목차\]', lambda m: box, t)

        def anchor_replacer(m):
            anchor_id = html.escape(m.group(1).strip(), quote=True)
            return f'<a id="{anchor_id}"></a>'

        def ruby_replacer(m):
            text = html.escape(m.group(1).strip())
            ruby_text = html.escape(m.group(2).strip())
            raw_color = m.group(3).strip() if m.group(3) else None

            if raw_color:
                color = html.escape(raw_color)
                return f'<ruby>{text}<rt style="color: {color};">{ruby_text}</rt></ruby>'
            return f'<ruby>{text}<rt>{ruby_text}</rt></ruby>'

        t = re.sub(
            r'(?ms)(?:^|\r?\n)[ \t]*\[include\((.*?)\)\][ \t]*(\r?\n|$)',
            lambda m: replace_include(m) + (m.group(2) if m.group(2) else ''),
            t
        )
        t = re.sub(r'\[include\((.*?)\)\]', replace_include, t)
        t = re.sub(r'\[now\((.*?)\)\]', lambda m: (datetime.now().strftime("%Y-%m-%d %H:%M:%S") + (m.group(1) if ":" in m.group(1) else f"{m.group(1)}:00")), t)
        t = re.sub(r'\[now\]', datetime.now().strftime("%Y-%m-%d %H:%M:%S"), t)
        t = re.sub(r'\[anchor\((.*?)\)\]', anchor_replacer, t)
        t = re.sub(r'\[ruby\(\s*(?:text=\s*)?(.*?)\s*,\s*ruby=(.*?)(?:\s*,\s*color=(.*?))?\s*\)\]', ruby_replacer, t, flags=re.DOTALL)
        t = replace_toc(t)

        return t

    def brace(t, protect_only=False):
        def extract_syntax_blocks(value):
            syntax_pattern = re.compile(
                r'(?<!\\){{#syntax\s+lang\s*=\s*(?:"([^"]*)"|\'([^\']*)\')\s*}}'
                r'(.*?){{/syntax\s*}}(?!\\)',
                re.DOTALL | re.IGNORECASE
            )

            def replace_syntax(match):
                language = (match.group(1) or match.group(2) or '').strip()
                code = match.group(3)
                if code.startswith('\r\n'):
                    code = code[2:]
                elif code.startswith('\n'):
                    code = code[1:]
                if code.endswith('\r\n'):
                    code = code[:-2]
                elif code.endswith('\n'):
                    code = code[:-1]

                try:
                    language_name = language.lstrip('.')
                    try:
                        lexer = get_lexer_by_name(language_name)
                    except ClassNotFound:
                        lexer = get_lexer_for_filename(f'code.{language_name}')
                    highlighted_code = highlight(
                        code,
                        lexer,
                        HtmlFormatter(noclasses=True, nowrap=True)
                    )
                    if highlighted_code.endswith('\n'):
                        highlighted_code = highlighted_code[:-1]
                except ClassNotFound:
                    highlighted_code = html.escape(code, quote=False)

                syntax_index = len(syntax_blocks)
                syntax_blocks.append(
                    '<pre class="wiki-syntax" style="overflow-x: auto;">'
                    f'<code>{highlighted_code}</code></pre>'
                )
                syntax_marker = f'{syntax_marker_prefix}{syntax_index}END'
                if (
                    'markdown' in function
                    and function.index('markdown') < function.index('custom_grammer')
                ):
                    return f'\n\n{syntax_marker}\n\n'
                return syntax_marker

            return syntax_pattern.sub(replace_syntax, value)

        def extract_literal_blocks(value):
            result = []
            cursor = 0

            while True:
                opening = value.find('{{', cursor)
                if opening == -1:
                    result.append(value[cursor:])
                    break

                directive = value[opening + 2:]
                if directive.startswith(('#', '/', 'else}}')):
                    result.append(value[cursor:opening + 2])
                    cursor = opening + 2
                    continue

                depth = 1
                scan = opening + 2
                while scan < len(value):
                    if value.startswith('{{', scan):
                        depth += 1
                        scan += 2
                    elif value.startswith('}}', scan):
                        depth -= 1
                        if depth == 0:
                            result.append(value[cursor:opening])
                            literal_index = len(literal_blocks)
                            literal_blocks.append(value[opening + 2:scan])
                            result.append(
                                f'{literal_marker_prefix}{literal_index}END'
                            )
                            cursor = scan + 2
                            break
                        scan += 2
                    else:
                        scan += 1
                else:
                    result.append(value[cursor:opening + 2])
                    cursor = opening + 2
                    continue

            return ''.join(result)

        if protect_only:
            return extract_literal_blocks(extract_syntax_blocks(t))

        token_pattern = re.compile(r'{{#if\s*\(?(.+?)\)?}}|{{else}}|{{/if}}', re.DOTALL)
        safe_style_properties = {
            'background-color', 'border', 'border-bottom', 'border-bottom-color',
            'border-bottom-left-radius', 'border-bottom-right-radius',
            'border-bottom-style', 'border-bottom-width', 'border-color',
            'border-left', 'border-left-color', 'border-left-style',
            'border-left-width', 'border-radius', 'border-right',
            'border-right-color', 'border-right-style', 'border-right-width',
            'border-style', 'border-top', 'border-top-color',
            'border-top-left-radius', 'border-top-right-radius',
            'border-top-style', 'border-top-width', 'border-width', 'color',
            'display', 'font-family', 'font-size', 'font-style', 'font-weight',
            'height', 'letter-spacing', 'line-height', 'list-style-type',
            'margin', 'margin-bottom', 'margin-left', 'margin-right', 'margin-top',
            'max-height', 'max-width', 'min-height', 'min-width', 'opacity',
            'padding', 'padding-bottom', 'padding-left', 'padding-right',
            'padding-top', 'text-align', 'text-decoration', 'text-indent',
            'text-transform', 'vertical-align', 'white-space', 'width',
            'word-spacing'
        }
        unsafe_style_value_pattern = re.compile(
            r'(?:url\s*\(|expression\s*\(|javascript\s*:|vbscript\s*:|'
            r'@import\b|behavior\s*:|-moz-binding\s*:)',
            re.IGNORECASE
        )

        def safe_style_value(value):
            value = value.strip()
            if (
                not value
                or ';' in value
                or '\\' in value
                or '/*' in value
                or '*/' in value
                or '{' in value
                or '}' in value
                or '<' in value
                or '>' in value
                or any(ord(char) < 32 for char in value)
                or unsafe_style_value_pattern.search(value)
            ):
                return ''
            return value

        def safe_style_declarations(raw_style):
            declarations = []
            for declaration in raw_style.split(';'):
                if ':' not in declaration:
                    continue
                name, value = declaration.split(':', 1)
                name = name.strip().lower()
                value = safe_style_value(value)
                if name in safe_style_properties and value:
                    declarations.append(f'{name}: {value}')
            return '; '.join(declarations)

        def safe_style_rules(raw_css):
            rules = []
            existing_classes = _existing_css_classes() | {'wiki-style-block'}
            rule_pattern = re.compile(r'([^{}]+)\{([^{}]*)\}', re.DOTALL)
            class_selector = r'\.[A-Za-z_][A-Za-z0-9_-]*'
            selector_pattern = re.compile(
                rf'{class_selector}(?:{class_selector})*'
                rf'(?:\s*(?:>|\+|~)\s*{class_selector}(?:{class_selector})*'
                rf'|\s+{class_selector}(?:{class_selector})*)*'
            )

            for match in rule_pattern.finditer(raw_css):
                selectors = []
                for selector in match.group(1).split(','):
                    selector = selector.strip()
                    class_names = re.findall(class_selector, selector)
                    if (
                        selector_pattern.fullmatch(selector)
                        and class_names
                        and all(
                            class_name[1:] not in existing_classes
                            for class_name in class_names
                        )
                    ):
                        selectors.append(selector)

                if not selectors:
                    continue

                declarations = safe_style_declarations(match.group(2))
                if declarations:
                    rules.append(
                        f'{", ".join(selectors)} {{ {declarations}; }}'
                    )

            return '\n'.join(rules)

        def parse_color_block(text):
            pattern = re.compile(
                r'{{#(?!folding(?:\s|}}))((?:[0-9A-Fa-f]{3,8})|(?:[A-Za-z][A-Za-z0-9-]*))\s+([^{}]+?)}}',
                re.DOTALL | re.IGNORECASE
            )

            def replace_color(m):
                color_value = m.group(1).strip()
                text_value = m.group(2).strip()
                if re.fullmatch(r'[0-9A-Fa-f]{3,8}', color_value):
                    color_value = f'#{color_value}'
                return f'<span style="color: {color_value};">{text_value}</span>'

            return pattern.sub(replace_color, text)

        def evaluate_condition(expr):
            expr = html.unescape(expr.strip())

            if not expr:
                return False

            def valid_parameter_name(name):
                forbidden_names = {
                    'title', 'true', 'false', 'yes', 'no', '1', '0',
                    'on', 'off', 'null', 'none', 'nil'
                }
                allowed_pattern = re.compile(r'^[a-zA-Z가-힣_][a-zA-Z가-힣0-9_]*$')
                return (
                    bool(allowed_pattern.fullmatch(name))
                    and name.lower() not in forbidden_names
                )

            def get_parameter_name(token):
                token = token.strip()
                if len(token) >= 2 and token[0] == token[-1] == '@':
                    token = token[1:-1]
                return token if valid_parameter_name(token) else None

            def split_expression_parts(expression, separator):
                parts = []
                quote = None
                parenthesis_depth = 0
                bracket_depth = 0
                start = 0

                for index, char in enumerate(expression):
                    if quote:
                        if char == quote and expression[index - 1] != '\\':
                            quote = None
                        continue
                    if char in {'"', "'"}:
                        quote = char
                    elif char == '(':
                        parenthesis_depth += 1
                    elif char == ')':
                        parenthesis_depth -= 1
                    elif char == '[':
                        bracket_depth += 1
                    elif char == ']':
                        bracket_depth -= 1
                    elif (
                        char == separator
                        and parenthesis_depth == 0
                        and bracket_depth == 0
                    ):
                        parts.append(expression[start:index].strip())
                        start = index + 1

                parts.append(expression[start:].strip())
                return parts

            def parse_function_call(token):
                quote = None
                parenthesis_depth = 0
                bracket_depth = 0

                for index, char in enumerate(token):
                    if quote:
                        if char == quote and token[index - 1] != '\\':
                            quote = None
                        continue
                    if char in {'"', "'"}:
                        quote = char
                    elif char == '(':
                        parenthesis_depth += 1
                    elif char == ')':
                        parenthesis_depth -= 1
                    elif char == '[':
                        bracket_depth += 1
                    elif char == ']':
                        bracket_depth -= 1
                    elif char == '.' and parenthesis_depth == 0 and bracket_depth == 0:
                        method_match = re.match(
                            r'([a-zA-Z_][a-zA-Z0-9_]*)\(',
                            token[index + 1:]
                        )
                        if not method_match:
                            continue

                        method = method_match.group(1)
                        open_index = index + 1 + method_match.end() - 1
                        depth = 1
                        argument_quote = None
                        for close_index in range(open_index + 1, len(token)):
                            current = token[close_index]
                            if argument_quote:
                                if (
                                    current == argument_quote
                                    and token[close_index - 1] != '\\'
                                ):
                                    argument_quote = None
                            elif current in {'"', "'"}:
                                argument_quote = current
                            elif current == '(':
                                depth += 1
                            elif current == ')':
                                depth -= 1
                                if depth == 0:
                                    if close_index == len(token) - 1:
                                        return (
                                            token[:index].strip(),
                                            method.lower(),
                                            token[open_index + 1:close_index]
                                        )
                                    break

                return None

            def parse_slice(token):
                quote = None
                parenthesis_depth = 0
                bracket_start = None

                for index, char in enumerate(token):
                    if quote:
                        if char == quote and token[index - 1] != '\\':
                            quote = None
                        continue
                    if char in {'"', "'"}:
                        quote = char
                    elif char == '(':
                        parenthesis_depth += 1
                    elif char == ')':
                        parenthesis_depth -= 1
                    elif char == '[' and parenthesis_depth == 0:
                        bracket_start = index
                    elif (
                        char == ']'
                        and parenthesis_depth == 0
                        and bracket_start is not None
                        and index == len(token) - 1
                    ):
                        return (
                            token[:bracket_start].strip(),
                            token[bracket_start + 1:index]
                        )

                return None

            if expr.startswith('!'):
                return not evaluate_condition(expr[1:].strip())

            if expr.startswith('exists:'):
                target = expr.split(':', 1)[1].strip()
                return bool(db_check_func and db_check_func(target))

            def resolve_token(token):
                token = token.strip()
                if not token:
                    return ''

                if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
                    return token[1:-1]

                function_call = parse_function_call(token)
                if function_call is not None:
                    source_expr, method, arguments_expr = function_call
                    arguments = split_expression_parts(arguments_expr, ',')
                    source = resolve_token(source_expr)
                    source = '' if source is None else str(source)

                    if method == 'split' and len(arguments) == 2:
                        separator = resolve_token(arguments[0])
                        count = resolve_token(arguments[1])
                        if separator is not None:
                            separator = str(separator)
                        try:
                            count = int(count)
                        except (ValueError, TypeError, OverflowError):
                            return token

                        if separator:
                            positions = []
                            search_from = 0
                            while True:
                                position = source.find(separator, search_from)
                                if position == -1:
                                    break
                                positions.append(position + len(separator))
                                search_from = position + len(separator)

                            if count > 0 and count <= len(positions):
                                return positions[count - 1]
                            if count < 0 and -count <= len(positions):
                                return positions[count]
                            return 0

                    if method == 'rendering' and len(arguments) == 2:
                        original = resolve_token(arguments[0])
                        replacement = resolve_token(arguments[1])
                        original = '' if original is None else str(original)
                        replacement = '' if replacement is None else str(replacement)
                        return source.replace(original, replacement)

                slice_expr = parse_slice(token)
                if slice_expr is not None:
                    source_expr, indices_expr = slice_expr
                    slice_parts = split_expression_parts(indices_expr, ':')
                    if len(slice_parts) in {2, 3}:
                        indices = []
                        valid_indices = True
                        for part in slice_parts:
                            if not part:
                                indices.append(None)
                                continue
                            index_value = resolve_token(part)
                            try:
                                indices.append(int(index_value))
                            except (ValueError, TypeError, OverflowError):
                                valid_indices = False
                                break

                        if valid_indices:
                            source = resolve_token(source_expr)
                            source = '' if source is None else str(source)
                            return source[slice(*indices)]

                def replace_parameter(match):
                    name = match.group(1)
                    if valid_parameter_name(name):
                        return str(effective_params.get(name, ''))
                    return match.group(0)

                token = re.sub(r'@([^@\s]+)@', replace_parameter, token)
                if valid_parameter_name(token) and token in effective_params:
                    return str(effective_params[token])
                lowered = token.lower()
                if lowered in {'true', 'yes', '1', 'on'}:
                    return True
                if lowered in {'false', 'no', '0', 'off', 'null', 'none', 'nil'}:
                    return None
                if lowered == 'title':
                    return current_title or ''
                return token

            def split_ternary(expression):
                quote = None
                depth = 0
                bracket_depth = 0
                question_index = None

                for index, char in enumerate(expression):
                    if quote:
                        if char == quote and (index == 0 or expression[index - 1] != '\\'):
                            quote = None
                        continue
                    if char in {'"', "'"}:
                        quote = char
                    elif char == '(':
                        depth += 1
                    elif char == ')':
                        depth -= 1
                    elif char == '[':
                        bracket_depth += 1
                    elif char == ']':
                        bracket_depth -= 1
                    elif char == '?' and depth == 0 and bracket_depth == 0:
                        question_index = index
                        break

                if question_index is None:
                    return None

                quote = None
                depth = 0
                bracket_depth = 0
                nested_questions = 0
                for index in range(question_index + 1, len(expression)):
                    char = expression[index]
                    if quote:
                        if char == quote and expression[index - 1] != '\\':
                            quote = None
                        continue
                    if char in {'"', "'"}:
                        quote = char
                    elif char == '(':
                        depth += 1
                    elif char == ')':
                        depth -= 1
                    elif char == '[':
                        bracket_depth += 1
                    elif char == ']':
                        bracket_depth -= 1
                    elif depth == 0 and bracket_depth == 0 and char == '?':
                        nested_questions += 1
                    elif depth == 0 and bracket_depth == 0 and char == ':':
                        if nested_questions:
                            nested_questions -= 1
                        else:
                            return (
                                expression[:question_index].strip(),
                                expression[question_index + 1:index].strip(),
                                expression[index + 1:].strip()
                            )

                return None

            def resolve_ternary_value(expression):
                parts = split_ternary(expression)
                if parts is None:
                    return None

                condition, true_value, false_value = parts
                selected_value = (
                    true_value if evaluate_condition(condition) else false_value
                )
                nested_parts = split_ternary(selected_value)
                if nested_parts is not None:
                    return resolve_ternary_value(selected_value)
                if re.search(r'==|!=|>=|<=|>|<', selected_value):
                    return evaluate_condition(selected_value)
                return resolve_token(selected_value)

            def compare_condition_chain(comparison_expr):
                operator_pattern = re.compile(r'==|!=|>=|<=|>|<')
                operator_matches = list(operator_pattern.finditer(comparison_expr))
                if not operator_matches:
                    return None

                operands = []
                operators = []
                start = 0
                for match in operator_matches:
                    operands.append(comparison_expr[start:match.start()].strip())
                    operators.append(match.group())
                    start = match.end()
                operands.append(comparison_expr[start:].strip())

                if any(not operand for operand in operands):
                    return False

                def is_empty_value(value):
                    return value is None or value is False or value == ''

                for operand in operands:
                    if (
                        not (
                            len(operand) >= 2
                            and operand[0] == operand[-1]
                            and operand[0] in {'"', "'"}
                        )
                        and re.search(r'[=!<>]', operand)
                    ):
                        return False

                left_value = resolve_token(operands[0])
                for index, (operator, right) in enumerate(zip(operators, operands[1:])):
                    right_value = resolve_token(right)
                    try:
                        left_num = float(left_value)
                        right_num = float(right_value)
                        if operator == '==':
                            result = left_num == right_num
                        elif operator == '!=':
                            result = left_num != right_num
                        elif operator == '>=':
                            result = left_num >= right_num
                        elif operator == '<=':
                            result = left_num <= right_num
                        elif operator == '>':
                            result = left_num > right_num
                        else:
                            result = left_num < right_num
                    except (ValueError, TypeError, OverflowError):
                        if operator == '==':
                            result = (
                                left_value == right_value
                                or (
                                    is_empty_value(left_value)
                                    and is_empty_value(right_value)
                                )
                            )
                        elif operator == '!=':
                            if right_value is None:
                                parameter_name = get_parameter_name(
                                    operands[index]
                                )
                                is_parameter = (
                                    parameter_name in effective_params
                                    if parameter_name is not None
                                    else False
                                )
                                if is_parameter or operands[index] == 'title':
                                    result = not is_empty_value(left_value)
                                else:
                                    result = False
                            else:
                                result = not (
                                    left_value == right_value
                                    or (
                                        is_empty_value(left_value)
                                        and is_empty_value(right_value)
                                    )
                                )
                        elif operator == '>=':
                            if isinstance(left_value, str) and isinstance(right_value, str):
                                result = left_value >= right_value
                            else:
                                result = False
                        elif operator == '<=':
                            if isinstance(left_value, str) and isinstance(right_value, str):
                                result = left_value <= right_value
                            else:
                                result = False
                        elif operator == '>':
                            if isinstance(left_value, str) and isinstance(right_value, str):
                                result = left_value > right_value
                            else:
                                result = False
                        else:
                            if isinstance(left_value, str) and isinstance(right_value, str):
                                result = left_value < right_value
                            else:
                                result = False

                    if not result:
                        return False
                    left_value = right_value
                return True

            lowered = expr.lower()
            if lowered in {'true', 'yes', '1', 'on'}:
                return True
            if lowered in {'false', 'no', '0', 'off'}:
                return False
            if lowered == 'title':
                return bool(current_title or '')

            compound_assignment_match = re.fullmatch(
                r'\s*(@?[a-zA-Z가-힣_][a-zA-Z가-힣0-9_]*@?)\s*([+\-*/])=\s*(.*?)\s*',
                expr,
                re.DOTALL
            )
            if compound_assignment_match:
                name = get_parameter_name(compound_assignment_match.group(1))
                operator = compound_assignment_match.group(2)
                value_expr = compound_assignment_match.group(3)
                if name in effective_params and value_expr:
                    left_value = effective_params[name]
                    right_value = resolve_token(value_expr)
                    try:
                        left_number = float(left_value)
                        right_number = float(right_value)
                        if operator == '+':
                            result = left_number + right_number
                        elif operator == '-':
                            result = left_number - right_number
                        elif operator == '*':
                            result = left_number * right_number
                        else:
                            result = left_number / right_number
                    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
                        return False

                    if result.is_integer():
                        result = int(result)
                    effective_params[name] = str(result)
                    return bool(effective_params[name])

            assignment_matches = list(re.finditer(r'(?<![=!<>])=(?!=)', expr))
            if len(assignment_matches) == 1:
                assignment_match = assignment_matches[0]
                name = expr[:assignment_match.start()]
                value_expr = expr[assignment_match.end():]
                name = name.strip()
                if name.startswith('@') and name.endswith('@'):
                    name = name[1:-1]
                if valid_parameter_name(name):
                    value_expr = value_expr.strip()
                    if split_ternary(value_expr) is not None:
                        value = resolve_ternary_value(value_expr)
                    elif re.search(r'==|!=|>=|<=|>|<', value_expr):
                        value = evaluate_condition(value_expr)
                    else:
                        value = resolve_token(value_expr)
                    effective_params[name] = '' if value is None else str(value)
                    return bool(effective_params[name])

            ternary_parts = split_ternary(expr)
            if ternary_parts is not None:
                ternary_value = resolve_ternary_value(expr)
                return bool(ternary_value)

            comparison_result = compare_condition_chain(expr)
            if comparison_result is not None:
                return comparison_result

            if re.fullmatch(r'.+\.rendering\(.*\)', expr, re.DOTALL | re.IGNORECASE):
                return bool(resolve_token(expr))

            if expr in effective_params:
                return bool(effective_params[expr])

            return False

        def process_text(text):
            result = []
            last_pos = 0
            wiki_block_pattern = re.compile(
                r'{{#wiki(?:\s+[^{}]*?)?\s*}}',
                re.DOTALL | re.IGNORECASE
            )
            style_block_pattern = re.compile(
                r'{{#style\s*}}',
                re.IGNORECASE
            )

            while True:
                match = token_pattern.search(text, last_pos)
                wiki_match = wiki_block_pattern.search(text, last_pos)
                style_match = style_block_pattern.search(text, last_pos)
                if not match and not wiki_match and not style_match:
                    result.append(text[last_pos:])
                    break

                next_match = min(
                    (
                        candidate for candidate in (match, wiki_match, style_match)
                        if candidate
                    ),
                    key=lambda candidate: candidate.start()
                )

                if next_match is wiki_match or next_match is style_match:
                    rendered_block, next_pos = parse_style_block(
                        text,
                        next_match.start(),
                        'wiki' if next_match is wiki_match else 'style'
                    )
                    result.append(text[last_pos:next_match.start()])
                    result.append(rendered_block)
                    last_pos = next_pos
                else:
                    if match.group(0).startswith('{{#if'):
                        rendered_block, next_pos = parse_if_block(text, match.start())
                        result.append(text[last_pos:match.start()])
                        result.append(rendered_block)
                        last_pos = next_pos
                    else:
                        result.append(text[last_pos:match.start()])
                        result.append(match.group(0))
                        last_pos = match.end()

            return ''.join(result)

        def parse_if_block(text, start_idx):
            opening_match = re.match(r'{{#if\s*(.*?)}}', text[start_idx:], re.DOTALL)
            if not opening_match:
                return '', start_idx + 1

            condition_expr = opening_match.group(1).strip()
            if condition_expr.startswith('(') and condition_expr.endswith(')'):
                condition_expr = condition_expr[1:-1].strip()
            content_start = start_idx + opening_match.end()
            depth = 1
            search_pos = content_start
            else_start = None
            else_end = None
            close_start = None
            close_end = None

            while True:
                match = token_pattern.search(text, search_pos)
                if not match:
                    break

                token = match.group(0)
                if token.startswith('{{#if'):
                    depth += 1
                    search_pos = match.end()
                    continue

                if token == '{{else}}':
                    if depth == 1:
                        else_start = match.start()
                        else_end = match.end()
                    search_pos = match.end()
                    continue

                if token == '{{/if}}':
                    if depth == 1:
                        close_start = match.start()
                        close_end = match.end()
                        break
                    depth -= 1
                    search_pos = match.end()
                    continue

                search_pos = match.end()

            if close_start is None:
                return process_text(text[content_start:]), len(text)

            if evaluate_condition(condition_expr):
                branch_text = text[content_start:else_start if else_start is not None else close_start]
            else:
                if else_start is None:
                    branch_text = ''
                else:
                    branch_text = text[else_end:close_start]

            return process_text(branch_text), close_end or len(text)

        def parse_style_block(text, start_idx, block_name):
            opening_match = re.match(
                r'{{#style\s*}}' if block_name == 'style' else
                r'{{#wiki(?:\s+([^{}]*?))?\s*}}',
                text[start_idx:],
                re.DOTALL | re.IGNORECASE
            )
            if not opening_match:
                return '', start_idx + 1

            attributes = {}
            if block_name == 'wiki':
                raw_attributes = opening_match.group(1) or ''
                attribute_pattern = re.compile(
                    r'([A-Za-z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s]+))'
                )
                for attribute_match in attribute_pattern.finditer(raw_attributes):
                    name = attribute_match.group(1).lower()
                    value = next(
                        value for value in attribute_match.groups()[1:]
                        if value is not None
                    )
                    attributes[name] = value.strip()

            style_declarations = []
            if block_name == 'wiki' and attributes.get('class'):
                classes = ['wiki-style-block', attributes['class']]
            else:
                classes = ['wiki-style-block'] if block_name == 'wiki' else []

            if 'style' in attributes:
                style_declarations.append(
                    safe_style_declarations(attributes['style'])
                )
            content_start = start_idx + opening_match.end()
            opening_pattern = re.compile(
                r'{{#style\s*}}' if block_name == 'style' else
                r'{{#wiki(?:\s+[^{}]*?)?\s*}}',
                re.DOTALL | re.IGNORECASE
            )
            closing_pattern = re.compile(
                rf'{{{{/{block_name}\s*}}}}',
                re.IGNORECASE
            )
            depth = 1
            search_pos = content_start
            close_match = None

            while depth:
                next_open = opening_pattern.search(text, search_pos)
                next_close = closing_pattern.search(text, search_pos)
                if not next_close:
                    break

                if next_open and next_open.start() < next_close.start():
                    depth += 1
                    search_pos = next_open.end()
                else:
                    depth -= 1
                    close_match = next_close
                    search_pos = next_close.end()

            if depth:
                return process_text(text[content_start:]), len(text)

            inner_text = text[content_start:close_match.start()]
            if block_name == 'style':
                rules = safe_style_rules(inner_text)
                style_html = f'<style>\n{rules}\n</style>' if rules else ''
                style_index = len(style_blocks)
                style_blocks.append(style_html)
                return f'\x00WIKI_STYLE_BLOCK_{style_index}\x00', close_match.end()

            rendered_inner = process_text(inner_text)
            opening_tag = '<div'
            if classes:
                opening_tag += f' class="{html.escape(" ".join(classes), quote=True)}"'
            style_value = '; '.join(
                declaration for declaration in style_declarations if declaration
            )
            if style_value:
                opening_tag += f' style="{html.escape(style_value, quote=True)}"'
            return f'{opening_tag}>{rendered_inner}</div>', close_match.end()

        rendered = process_text(t)
        rendered = parse_color_block(rendered)

        return rendered

    def nested_list(t):
        lines = t.splitlines()

        def parse_marker(text):
            stripped = text.strip()
            if stripped.startswith('* '):
                return 'ul', stripped[2:].strip(), None
            if re.match(r'^1\.\s+', stripped):
                return 'ol', re.sub(r'^1\.\s*', '', stripped), None
            if re.match(r'^[a-zA-Z]\.\s+', stripped):
                kind = 'a' if re.match(r'^[a-zA-Z]\.\s+', stripped).group(0)[0].lower() == 'a' else 'i'
                return 'ol', re.sub(r'^[a-zA-Z]\.\s*', '', stripped), kind
            if re.match(r'^i\.\s+', stripped, re.I):
                return 'ol', re.sub(r'^i\.\s*', '', stripped, flags=re.I), 'i'
            return None

        lines = [
            transform_table_cells(
                line,
                lambda cell: nested_list(cell)
                if parse_marker(cell) else cell
            )
            for line in lines
        ]

        def parse_block(start_idx, indent):
            items = []
            i = start_idx
            block_type = None  
            block_kind = None

            while i < len(lines):
                raw_line = lines[i]
                if not raw_line.strip():
                    i += 1
                    continue

                current_indent = len(raw_line) - len(raw_line.lstrip(' '))
                if current_indent < indent:
                    break
                if current_indent > indent:
                    break

                marker = parse_marker(raw_line)
                if not marker:
                    break

                marker_type, content, kind = marker
                if block_type is None:
                    block_type = marker_type
                    block_kind = kind
                elif marker_type != block_type:
                    break

                i += 1
                item_parts = [('line', content)]

                while i < len(lines):
                    next_line = lines[i]
                    if not next_line.strip():
                        i += 1
                        continue

                    next_indent = len(next_line) - len(next_line.lstrip(' '))
                    if next_indent <= indent:
                        break

                    if parse_marker(next_line):
                        nested_html, next_index = parse_block(i, next_indent)
                        if next_index == i:
                            break
                        item_parts.append(('block', nested_html))
                        i = next_index
                    else:
                        item_parts.append(('line', next_line.strip()))
                        i += 1

                items.append(item_parts)

            if not items:
                return '', start_idx

            if block_type == 'ul':
                tag = 'ul'
                attrs = ''
            else:
                tag = 'ol'
                attrs = ' type="i"' if block_kind == 'i' else ' type="a"' if block_kind == 'a' else ''

            html_parts = [f'<{tag}{attrs}>']
            for item_parts in items:
                rendered_content = ''
                previous_is_block = False
                for part_type, part in item_parts:
                    line = blockquote(part) if part_type == 'line' else part
                    is_block = bool(re.match(
                        r'^\s*<(?:blockquote|hr|ul|ol|div)\b',
                        line,
                        re.IGNORECASE
                    ))
                    if rendered_content and not (previous_is_block or is_block):
                        rendered_content += '<br>'
                    rendered_content += line
                    previous_is_block = is_block or bool(re.search(
                        r'</(?:blockquote|ul|ol|div)>\s*$',
                        line,
                        re.IGNORECASE
                    ))
                html_parts.append(f'<li>{rendered_content}</li>')
            html_parts.append(f'</{tag}>')
            return ''.join(html_parts), i

        result = []
        i = 0

        while i < len(lines):
            raw_line = lines[i]
            if not raw_line.strip():
                result.append('')
                i += 1
                continue

            indent = len(raw_line) - len(raw_line.lstrip(' '))
            if parse_marker(raw_line):
                block_html, i = parse_block(i, indent)
                result.append(block_html)
                continue

            result.append(raw_line)
            i += 1

        return '\n'.join(result)

    def toc(t):
        heading_pattern = re.compile(r'^(#{1,6})\s*(.*?)$', re.MULTILINE)

        def make_heading_id(number, text):
            plain_text = text.strip()
            plain_text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', lambda m: m.group(2), plain_text)
            plain_text = re.sub(r'\[\[([^\]|]+)\]\]', lambda m: m.group(1), plain_text)
            plain_text = re.sub(r'<[^>]+>', '', plain_text)
            plain_text = html.unescape(plain_text)
            plain_text = re.sub(r'\s+', ' ', plain_text).strip()
            paragraph_name = plain_text or f'heading-{number}'
            return f's-{number}', paragraph_name

        matched_levels = [len(m.group(1)) for m in heading_pattern.finditer(t)]
        min_level = min(matched_levels) if matched_levels else 1

        level_counters = [0] * 6

        def index(m):
            raw_level = len(m.group(1))
            level = raw_level - min_level + 1

            text = m.group(2).strip()

            level_counters[level - 1] += 1
            for i in range(level, 6):
                level_counters[i] = 0

            heading_number = ".".join(
                str(level_counters[i]) for i in range(level)
            )
            heading_id, paragraph_id = make_heading_id(heading_number, text)
            paragraph_id = html.escape(paragraph_id, quote=True)

            return f'<h{raw_level} id="{heading_id}"><a id="{paragraph_id}"></a>{heading_number}. {text}</h{raw_level}>'

        return heading_pattern.sub(index, t)

    def blockquote(t):
        pattern = r'(?:(?:^[ \t]*(?:>|&gt;))[ \t]*.*\n?)+'

        def _wrap(m):
            inner = re.sub(
                r'^[ \t]*(?:>|&gt;)[ \t]?',
                '',
                m.group(0),
                flags=re.MULTILINE
            )
            lines = inner.splitlines()
            processed = []

            for line in lines:
                stripped = line.strip()
                if re.match(r'^-{4,10}$', stripped):
                    indentation = line[:len(line) - len(line.lstrip())]
                    processed.append(f'{indentation}<hr>')
                else:
                    processed.append(line)

            nested_content = blockquote("\n".join(processed))
            return f'<blockquote>{nested_list(nested_content)}</blockquote>'
        lines = t.splitlines()
        for index, line in enumerate(lines):
            lines[index] = transform_table_cells(
                line,
                lambda cell: re.sub(
                    pattern,
                    _wrap,
                    cell,
                    flags=re.MULTILINE
                )
            )
        return re.sub(pattern, _wrap, '\n'.join(lines), flags=re.MULTILINE)

    def line_breaks(t):
        style_pattern = re.compile(
            r'<style\b[^>]*>.*?</style\s*>',
            re.DOTALL | re.IGNORECASE
        )
        style_matches = iter(style_pattern.finditer(t))
        style_match = next(style_matches, None)
        inline_tag_names = {
            'a', 'abbr', 'acronym', 'b', 'bdi', 'bdo', 'big', 'br', 'button', 'cite',
            'code', 'data', 'del', 'dfn', 'em', 'font', 'i', 'img', 'input', 'kbd',
            'label', 'mark', 'q', 'rb', 'rp', 'rt', 'rtc', 'ruby', 's', 'samp',
            'select', 'slot', 'small', 'span', 'strong', 'sub', 'sup', 'svg', 'textarea',
            'time', 'tt', 'u', 'var', 'wbr', 'ins'
        }
        block_tag_names = {
            'address', 'article', 'aside', 'blockquote', 'dd', 'div', 'dl', 'dt',
            'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3',
            'h4', 'h5', 'h6', 'header', 'hr', 'li', 'main', 'nav', 'ol', 'p',
            'pre', 'section', 'table', 'ul'
        }

        def tag_name_near_newline(text, index, direction):
            if direction == 'before':
                match = re.search(r'<\s*/?\s*([a-zA-Z0-9]+)[^>]*>$', text[:index])
                if match:
                    return match.group(1).lower()
                return ''
            if direction == 'after':
                match = re.search(r'^\s*<\s*/?\s*([a-zA-Z0-9]+)', text[index + 1:])
                if match:
                    return match.group(1).lower()
                return ''
            return ''

        result = []
        i = 0
        while i < len(t):
            if style_match and i == style_match.start():
                result.append(style_match.group(0))
                i = style_match.end()
                style_match = next(style_matches, None)
                continue

            ch = t[i]
            if ch != '\n':
                result.append(ch)
                i += 1
                continue

            prev_char = t[i - 1] if i > 0 else ''
            next_char = t[i + 1] if i + 1 < len(t) else ''
            prev_tag = tag_name_near_newline(t, i, 'before')
            next_tag = tag_name_near_newline(t, i, 'after')
            inline_context = (prev_tag in inline_tag_names) or (next_tag in inline_tag_names)

            if prev_tag in block_tag_names or next_tag in block_tag_names:
                result.append('')
            elif (prev_char == '>' or next_char == '<') and not inline_context:
                result.append('')
            elif prev_char == '\\' and next_char == '\\':
                result.append('<br>')
            else:
                result.append('<br>')
            i += 1

        return ''.join(result)

    def extract_folding_blocks(t):
        opening_pattern = re.compile(
            r'\{\{#folding(?:[ \t]+([^\r\n{}]*?))?\}\}',
            re.IGNORECASE
        )
        closing_pattern = re.compile(r'\{\{/folding\}\}', re.IGNORECASE)
        result = []
        cursor = 0

        while True:
            opening_match = opening_pattern.search(t, cursor)
            if not opening_match:
                result.append(t[cursor:])
                break

            depth = 1
            search_pos = opening_match.end()
            close_match = None

            while depth:
                next_open = opening_pattern.search(t, search_pos)
                next_close = closing_pattern.search(t, search_pos)

                if not next_close:
                    break

                if next_open and next_open.start() < next_close.start():
                    depth += 1
                    search_pos = next_open.end()
                    continue

                depth -= 1
                close_match = next_close
                search_pos = next_close.end()

            if depth:
                result.append(t[cursor:])
                break

            result.append(t[cursor:opening_match.start()])
            title = (opening_match.group(1) or '').strip() or config.FOLDING_STANDARD_TEXT
            inner_text = restore_protected_table_syntax(
                t[opening_match.end():close_match.start()]
            )
            rendered_inner = rendering(
                inner_text.strip('\r\n'),
                function=function,
                db_check_func=db_check_func,
                current_title=current_title,
                include_params=effective_params,
                include_depth=include_depth,
                include_stack=active_stack,
                db_read_func=db_read_func
            )
            folding_index = len(folding_blocks)
            folding_blocks.append(
                f'<details class="wiki-folding"><summary>{html.escape(title)}</summary>'
                f'<div class="wiki-folding-content">{rendered_inner}</div></details>'
            )
            result.append(f'\x00WIKI_FOLDING_{folding_index}\x00')
            cursor = close_match.end()

        return ''.join(result)

    preprocessing_done = False
    custom_grammar_processed = False

    for f in function:
        if not preprocessing_done:
            if 'custom_grammer' in function:
                rendered = brace(rendered, protect_only=True)
            rendered = _strip_unsafe_source_elements(rendered)
            preprocessing_done = True

        if f == "markdown":
            if custom_grammar_processed:
                rendered = restore_syntax_blocks(rendered, markdown_blocks=True)
            rendered = markdown.markdown(
                rendered,
                extensions=["extra", "codehilite", "nl2br", "md_in_html", "toc"]
            )

        elif f == "custom_grammer":
            custom_grammar_processed = True
            if config.SAFE_HTML:
                protected_wiki_blocks = []
                protected_marker_prefix = 'WIKIPRESERVEDWIKISYNTAX'
                while protected_marker_prefix in rendered:
                    protected_marker_prefix += 'X'

                wiki_block_pattern = re.compile(
                    r'{{#wiki(?:\s+[^{}]*?)?\s*}}',
                    re.DOTALL | re.IGNORECASE
                )
                table_syntax_pattern = re.compile(
                    r'<(?:tablealign|tablebgcolor|tablecolor|tablebordercolor|'
                    r'tabletextalign|tablewidth|bgcolor|color|width|rowbgcolor|'
                    r'rowcolor|rowtextalign|colbgcolor|colcolor|coltextalign|'
                    r'textalign)(?:=[^<>"\']*)?>|<\^\d+>|<-\d+>|<[():]>',
                    re.IGNORECASE
                )

                def preserve_source_syntax(value, preserved_values, kind):
                    marker = (
                        f'{protected_marker_prefix}{kind}'
                        f'{len(preserved_values)}END'
                    )
                    preserved_values.append(value)
                    return marker

                rendered = wiki_block_pattern.sub(
                    lambda match: preserve_source_syntax(
                        match.group(0),
                        protected_wiki_blocks,
                        'BLOCK'
                    ),
                    rendered
                )

                def preserve_table_syntax(line_match):
                    return table_syntax_pattern.sub(
                        lambda match: preserve_source_syntax(
                            match.group(0),
                            protected_table_syntax,
                            'TABLE'
                        ),
                        line_match.group(0)
                    )

                rendered = re.sub(
                    r'(?m)^[ \t]*\|[^\r\n]*\|[ \t]*(?=\r?$)',
                    preserve_table_syntax,
                    rendered
                )
                rendered = _sanitize_source_html(rendered)
                for index, source_syntax in enumerate(protected_wiki_blocks):
                    rendered = rendered.replace(
                        f'{protected_marker_prefix}BLOCK{index}END',
                        source_syntax
                    )

            rendered = re.sub(r'\\(.*?)\\', lambda m: ''.join(f'&#{ord(c)};' for c in m.group(1)), rendered)
            rendered = re.sub(r'^//\s*(.*?)$', '', rendered, flags=re.MULTILINE)

            footnotes = []

            def replace_footnote(match):
                footnote_number = len(footnotes) + 1
                footnote_content = match.group(1).strip()
                footnotes.append(footnote_content)
                return f'\x00WIKI_FOOTNOTE_REFERENCE_{footnote_number}\x00'

            rendered = re.sub(
                r'\[\^((?:\[\[[^\]\r\n]*\]\]|\[[^\]\r\n]*\]|[^\]\r\n])+)\]',
                replace_footnote,
                rendered
            )

            rendered = extract_folding_blocks(rendered)

            rendered = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', rendered)
            rendered = re.sub(r'\*(.+?)\*', r'<em>\1</em>', rendered)
            rendered = re.sub(r'__(.+?)__', r'<ins>\1</ins>', rendered)
            rendered = re.sub(r'\^\^(.+?)\^\^', r'<sup>\1</sup>', rendered)
            rendered = re.sub(r',,(.+?),,', r'<sub>\1</sub>', rendered)
            rendered = re.sub(r'^\s*-{4,10}\s*$', r'<hr>', rendered, flags=re.MULTILINE)

            if config.STRIKETHROUGH:
                rendered = re.sub(r'~~(.+?)~~', r'<del>\1</del>', rendered)
            else:
                rendered = re.sub(r'~~(.+?)~~', '', rendered)

            rendered = restore_protected_table_syntax(rendered)
            rendered = toc(rendered)
            rendered = blockquote(rendered)
            rendered = brace(rendered)
            rendered = macro(rendered)
            rendered = link(rendered)
            rendered = nested_list(rendered)
            rendered = table(rendered)

            for index, folding_html in enumerate(folding_blocks):
                rendered = rendered.replace(f'\x00WIKI_FOLDING_{index}\x00', folding_html)

            if "[요약|" in text:
                summary_pattern = r'\[요약\|개요=(.*?)\|핵심=(.*?)\|참고자료=(.*?)\]'
                if m := re.search(summary_pattern, text):
                    box = f'<div class="reduce">{f"<b>개요</b><br>{m.group(1)}" if m.group(1) else ""}{f"<br><b>핵심</b><br>{m.group(2)}" if m.group(2) and m.group(2) != "|" else ""}{f"<br><b>참고 자료</b><br>{m.group(3)}" if m.group(3) and m.group(3) != "|" else ""}</div>'
                    rendered = re.sub(summary_pattern, "", rendered)
                    rendered = box + rendered

            rendered = re.sub(r'\[br\]', r'<br>', rendered, flags=re.MULTILINE)
            rendered = line_breaks(rendered)

            for index, style_html in enumerate(style_blocks):
                rendered = rendered.replace(
                    f'\x00WIKI_STYLE_BLOCK_{index}\x00',
                    style_html
                )

            for number, content in enumerate(footnotes, start=1):
                tooltip_content = rendering(
                    html.unescape(content),
                    function=function,
                    db_check_func=db_check_func,
                    current_title=current_title,
                    include_params=effective_params,
                    include_depth=include_depth,
                    include_stack=active_stack,
                    db_read_func=db_read_func
                ).replace('\n', '<br>')
                reference_html = (
                    f'<sup class="wiki-footnote-reference">'
                    f'<a href="#wiki-footnote-{number}" '
                    f'id="wiki-footnote-reference-{number}">'
                    f'[{number}]</a>'
                    f'<span class="wiki-footnote-tooltip" role="tooltip">'
                    f'{tooltip_content}</span></sup>'
                )
                rendered = rendered.replace(
                    f'\x00WIKI_FOOTNOTE_REFERENCE_{number}\x00',
                    reference_html
                )

            if footnotes:
                footnote_items = []
                for number, content in enumerate(footnotes, start=1):
                    safe_content = rendering(
                        html.unescape(content),
                        function=function,
                        db_check_func=db_check_func,
                        current_title=current_title,
                        include_params=effective_params,
                        include_depth=include_depth,
                        include_stack=active_stack,
                        db_read_func=db_read_func
                    ).replace('\n', '<br>')
                    footnote_items.append(
                        f'<li id="wiki-footnote-{number}">'
                        f'{safe_content} '
                        f'<a href="#wiki-footnote-reference-{number}" '
                        f'aria-label="각주 {number} 본문으로 돌아가기">↩</a></li>'
                    )

                rendered += (
                    '<section class="wiki-footnotes" aria-label="각주">'
                    f'<ol>{"".join(footnote_items)}</ol>'
                    '</section>'
                )

        else:
            continue

    if not preprocessing_done:
        rendered = _strip_unsafe_source_elements(rendered)

    for literal_index, literal_text in enumerate(literal_blocks):
        literal_html = (
            '<span style="white-space: pre-wrap;">'
            f'{html.escape(literal_text, quote=False)}</span>'
        )
        rendered = rendered.replace(
            f'{literal_marker_prefix}{literal_index}END',
            literal_html
        )

    for syntax_index, syntax_html in enumerate(syntax_blocks):
        syntax_marker = f'{syntax_marker_prefix}{syntax_index}END'
        rendered = re.sub(
            rf'<p>\s*{re.escape(syntax_marker)}\s*</p>',
            lambda _: syntax_html,
            rendered
        )
    rendered = restore_syntax_blocks(rendered)

    return rendered