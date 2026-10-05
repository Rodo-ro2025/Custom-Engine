# rendering.py
# --- Official Module ---
import flask
import html
import re
import markdown
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit, urlunsplit
import sqlite3

# --- Personal Module ---
import config
from table import table

def rendering(text, function=[], db_check_func=None, current_title=None, include_params=None, include_depth=0, include_stack=None, db_read_func=None):
    rendered = text
    rendered = re.sub(r'<(?:script|style)[^>]*>.*?</(?:script|style)>', r'', rendered, flags=re.DOTALL | re.IGNORECASE)
    Secured = []
    folding_blocks = []
    effective_params = include_params or {}
    active_stack = list(include_stack or [])

    def link(t):
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
            safe_title = html.escape(re.sub(r"<[^>]+>", "", title), quote=False)

            return f'<a class="wiki-link external" href="{safe_url}" target="_blank" title="{plain_title}">🔗{safe_title}</a>'

        t = re.sub(r'\[\[(https?://[^\|\]]+)(?:\|((?:(?!\]\]).)+))?\]\]', external_link_replacer, t)

        def internal_pipe_link_replacer(m):
            doc_name = m.group(1).strip()
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
                safe_display_name = html.escape(re.sub(r"<[^>]+>", "", display_name), quote=False)
                if lookup_title is not None and db_check_func and not db_check_func(lookup_title):
                    return f'<a class="wiki-link erroneous" href="{safe_doc_url}" title="{plain_title}">{safe_display_name}</a>'
                return f'<a class="wiki-link" href="{safe_doc_url}" title="{plain_title}">{safe_display_name}</a>'

            plain_title = html.escape(re.sub(r"<[^>]+>", "", doc_name), quote=True)
            if doc_name.startswith('#') and len(doc_name) > 1 and not (db_check_func and db_check_func(doc_name)):
                safe_anchor = html.escape('#' + quote(doc_name[1:], safe=''), quote=True)
                safe_display_name = html.escape(re.sub(r"<[^>]+>", "", display_name), quote=False)
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
            doc_name = m.group(1).strip()
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

    def brace(t):
        token_pattern = re.compile(r'{{#if\s*\(?(.+?)\)?}}|{{else}}|{{/if}}', re.DOTALL)

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
            expr = expr.strip()

            if not expr:
                return False

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

                rendering_match = re.fullmatch(r'(.+?)\.rendering\((.*)\)', token, re.DOTALL | re.IGNORECASE)
                if rendering_match:
                    arguments = rendering_match.group(2).split(',', 1)
                    if len(arguments) == 2:
                        source = resolve_token(rendering_match.group(1))

                        def resolve_argument(argument):
                            arg = argument.strip()
                            if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in {'"', "'"}:
                                return arg[1:-1]
                            return resolve_token(arg)

                        original = resolve_argument(arguments[0])
                        replacement = resolve_argument(arguments[1])
                        source = '' if source is None else str(source)
                        original = '' if original is None else str(original)
                        replacement = '' if replacement is None else str(replacement)
                        return source.replace(original, replacement)

                token = re.sub(r'@([^@\s]+)@', lambda m: str(effective_params.get(m.group(1), '')), token)
                if token in effective_params:
                    return str(effective_params[token])
                lowered = token.lower()
                if lowered in {'true', 'yes', '1', 'on'}:
                    return True
                if lowered in {'false', 'no', '0', 'off', 'null', 'none', 'nil'}:
                    return None
                return token

            lowered = expr.lower()
            if lowered in {'true', 'yes', '1', 'on'}:
                return True
            if lowered in {'false', 'no', '0', 'off'}:
                return False

            operator_matches = []
            for operator in ('==', '!=', '>=', '<=', '>', '<'):
                if operator in expr:
                    operator_matches.append(operator)

            if operator_matches:
                operator = sorted(operator_matches, key=len, reverse=True)[0]
                left, right = expr.split(operator, 1)
                left = left.strip()
                right = right.strip()

                if left == 'title':
                    left_value = current_title or ''
                else:
                    left_value = left

                if right == 'title':
                    right_value = current_title or ''
                else:
                    right_value = right

                left_value = resolve_token(left_value)
                right_value = resolve_token(right_value)

                try:
                    left_num = float(left_value)
                    right_num = float(right_value)
                    if operator == '==':
                        return left_num == right_num
                    if operator == '!=':
                        return left_num != right_num
                    if operator == '>=':
                        return left_num >= right_num
                    if operator == '<=':
                        return left_num <= right_num
                    if operator == '>':
                        return left_num > right_num
                    if operator == '<':
                        return left_num < right_num
                except (ValueError, TypeError):
                    if operator == '==':
                        return left_value == right_value
                    if operator == '!=':
                        if right_value is None:
                            is_parameter = (
                                left in effective_params
                                or re.fullmatch(r'@([^@\s]+)@', left) is not None
                            )
                            if is_parameter or left == 'title':
                                return left_value is not None and left_value != ''
                            return False
                        return left_value != right_value
                    if operator == '>=':
                        return left_value >= right_value
                    if operator == '<=':
                        return left_value <= right_value
                    if operator == '>':
                        return left_value > right_value
                    if operator == '<':
                        return left_value < right_value

            if expr.count('=') == 1:
                name, value_expr = expr.split('=', 1)
                name = name.strip()
                if name.startswith('@') and name.endswith('@'):
                    name = name[1:-1]
                if re.fullmatch(r'[^@\s]+', name):
                    value = resolve_token(value_expr.strip())
                    effective_params[name] = '' if value is None else str(value)
                    return True

            if re.fullmatch(r'.+\.rendering\(.*\)', expr, re.DOTALL | re.IGNORECASE):
                return bool(resolve_token(expr))

            if expr in effective_params:
                return bool(effective_params[expr])

            if db_check_func and db_check_func(expr):
                return True

            return False

        def process_text(text):
            result = []
            last_pos = 0
            wiki_block_pattern = re.compile(r'{{#wiki\s*style\s*=\s*"([^"]*)"}}', re.DOTALL)

            while True:
                match = token_pattern.search(text, last_pos)
                wiki_match = wiki_block_pattern.search(text, last_pos)
                if not match and not wiki_match:
                    result.append(text[last_pos:])
                    break

                next_match = min(
                    (candidate for candidate in (match, wiki_match) if candidate),
                    key=lambda candidate: candidate.start()
                )

                if next_match is wiki_match:
                    rendered_block, next_pos = parse_wiki_block(text, wiki_match.start())
                    result.append(text[last_pos:wiki_match.start()])
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

        def parse_wiki_block(text, start_idx):
            opening_match = re.match(r'{{#wiki\s*style\s*=\s*"([^"]*)"}}', text[start_idx:], re.DOTALL)
            if not opening_match:
                return '', start_idx + 1

            style_value = opening_match.group(1).strip()
            content_start = start_idx + opening_match.end()
            close_pattern = re.compile(r'{{/wiki}}', re.DOTALL)
            close_match = close_pattern.search(text, content_start)
            if not close_match:
                return process_text(text[content_start:]), len(text)

            inner_text = text[content_start:close_match.start()]
            rendered_inner = process_text(inner_text)
            style_attr = f' style="{html.escape(style_value)}"' if style_value else ''
            return f'<div class="wiki-style-block"{style_attr}>{rendered_inner}</div>', close_match.end()

        rendered = process_text(t)
        rendered = parse_color_block(rendered)

        return rendered

    def nested_list(t):
        lines = t.splitlines()

        def parse_marker(text):
            stripped = text.strip()
            if stripped.startswith('* '):
                return 'ul', stripped[2:].strip(), None
            if re.match(r'^\d+\.\s+', stripped):
                return 'ol', re.sub(r'^\d+\.\s*', '', stripped), None
            if re.match(r'^[a-zA-Z]\.\s+', stripped):
                kind = 'a' if re.match(r'^[a-zA-Z]\.\s+', stripped).group(0)[0].lower() == 'a' else 'i'
                return 'ol', re.sub(r'^[a-zA-Z]\.\s*', '', stripped), kind
            if re.match(r'^i\.\s+', stripped, re.I):
                return 'ol', re.sub(r'^i\.\s*', '', stripped, flags=re.I), 'i'
            return None

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
                child_html = ''

                while i < len(lines):
                    next_line = lines[i]
                    if not next_line.strip():
                        i += 1
                        continue

                    next_indent = len(next_line) - len(next_line.lstrip(' '))
                    if next_indent <= indent:
                        break

                    child_html, i = parse_block(i, next_indent)
                    break

                items.append((content, child_html))

            if not items:
                return '', start_idx

            if block_type == 'ul':
                tag = 'ul'
                attrs = ''
            else:
                tag = 'ol'
                attrs = ' type="i"' if block_kind == 'i' else ' type="a"' if block_kind == 'a' else ''

            html_parts = [f'<{tag}{attrs}>']
            for content, child_html in items:
                html_parts.append(f'<li>{content}')
                if child_html:
                    html_parts.append(child_html)
                html_parts.append('</li>')
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
        pattern = r'(?:^>[ \t]*.*\n?)+'

        def _wrap(m):
            inner = re.sub(r'^>[ \t]*', '', m.group(0), flags=re.MULTILINE)
            lines = inner.splitlines()
            processed = []

            for line in lines:
                stripped = line.strip()
                if re.match(r'^-{4,10}$', stripped):
                    processed.append('<hr>')
                else:
                    processed.append(line)

            return f'<blockquote>{"\n".join(processed)}</blockquote>'
        return re.sub(pattern, _wrap, t, flags=re.MULTILINE)

    def line_breaks(t):
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
            inner_text = t[opening_match.end():close_match.start()]
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

    for f in function:
        if f == "markdown":
            rendered = markdown.markdown(
                rendered,
                extensions=["extra", "codehilite", "nl2br", "md_in_html", "toc"]
            )

        elif f == "ourwiki":
            if config.SAFE_HTML:
                rendered = html.escape(rendered)

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

            rendered = re.sub(r'\\(.*?)\\', lambda m: ''.join(f'&#{ord(c)};' for c in m.group(1)), rendered)
            rendered = re.sub(r'^//\s*(.*?)$', '', rendered, flags=re.MULTILINE)

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

    return rendered