# table.py
# --- Official Module ---
import html
import re

# --- Personal Module ---
import config
import rendering


STYLE_TAGS = {
    'tablealign',
    'tablebgcolor',
    'tablecolor',
    'tablebordercolor',
    'tablewidth',
    'bgcolor',
    'color',
    'width',
    'rowbgcolor',
    'rowcolor',
    'colbgcolor',
    'colcolor',
    'textalign',
}


def _normalize_css_value(prop, value):
    value = str(value).strip()
    if not value:
        return ''

    if prop == 'width':
        if re.fullmatch(r'\d+(?:\.\d+)?(?:px|em|rem|vh|vw|ch|ex|cm|mm|in|pt|pc|%)', value):
            return value
        if re.fullmatch(r'\d+(?:\.\d+)?', value):
            return f'{value}px'
        return value

    return value


def _build_style(style_map):
    if not style_map:
        return ''

    parts = []
    for key, value in style_map.items():
        if value:
            parts.append(f'{key}: {value};')
    return ' '.join(parts)


def _extract_cell_metadata(text):
    cleaned = text
    styles = []
    row_span = 1
    col_span = 1

    for match in re.finditer(r'<([^>]+)>', text):
        token = match.group(1)

        if re.fullmatch(r'\^(\d+)', token):
            row_span = max(row_span, int(token[1:]))
            cleaned = cleaned.replace(match.group(0), '', 1)
        elif re.fullmatch(r'-(\d+)', token):
            col_span = max(col_span, int(token[1:]))
            cleaned = cleaned.replace(match.group(0), '', 1)
        elif token in {'(', ':', ')'}:
            alignment = {'(': 'right', ':': 'center', ')': 'left'}[token]
            styles.append(('textalign', alignment))
            cleaned = cleaned.replace(match.group(0), '', 1)
        else:
            tag_name = token.split('=', 1)[0].lower()
            value = (token.split('=', 1)[1] if '=' in token else '').strip()
            if tag_name in STYLE_TAGS:
                styles.append((tag_name, value))
                cleaned = cleaned.replace(match.group(0), '', 1)

    return cleaned.strip(), styles, row_span, col_span


def _apply_style(style_map, prop, value):
    if value is None:
        return
    style_map[prop] = _normalize_css_value(prop, value)


def _style_from_tag(tag, value, scope):
    style_map = {}

    if scope == 'table':
        if tag == 'tablealign':
            normalized = (value or '').lower()
            if normalized == 'center':
                style_map['margin-left'] = 'auto'
                style_map['margin-right'] = 'auto'
            elif normalized == 'right':
                style_map['float'] = 'right'
                style_map['width'] = 'auto'
                style_map['margin-left'] = '12px'
                style_map['margin-right'] = '0'
            else:
                style_map['margin-left'] = '0'
                style_map['margin-right'] = 'auto'
        elif tag == 'tablebgcolor':
            _apply_style(style_map, 'background-color', value)
        elif tag == 'tablecolor':
            _apply_style(style_map, 'color', value)
        elif tag == 'tablebordercolor':
            _apply_style(style_map, 'border-color', value)
            _apply_style(style_map, 'border-style', 'solid')
            _apply_style(style_map, 'border-width', '1px')
        elif tag == 'tablewidth':
            _apply_style(style_map, 'width', value)

    elif scope == 'cell':
        if tag == 'bgcolor':
            _apply_style(style_map, 'background-color', value)
        elif tag == 'color':
            _apply_style(style_map, 'color', value)
        elif tag == 'width':
            _apply_style(style_map, 'width', value)
        elif tag == 'textalign':
            _apply_style(style_map, 'text-align', value)

    elif scope == 'row':
        if tag == 'rowbgcolor':
            _apply_style(style_map, 'background-color', value)
        elif tag == 'rowcolor':
            _apply_style(style_map, 'color', value)

    elif scope == 'col':
        if tag == 'colbgcolor':
            _apply_style(style_map, 'background-color', value)
        elif tag == 'colcolor':
            _apply_style(style_map, 'color', value)

    return style_map


def table(t):
    if not config.TABLE_ACTIVATION:
        return t

    lines = t.splitlines()
    if not lines:
        return t

    result = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped and '|' in stripped:
            table_lines = []
            while index < len(lines):
                current_line = lines[index]
                current_stripped = current_line.strip()
                if not current_stripped or '|' not in current_stripped:
                    break
                table_lines.append(current_line)
                index += 1

            table_styles = {}
            col_styles = []
            row_entries = []

            table_styles['border-collapse'] = 'collapse'

            for raw_line in table_lines:
                cells = [cell.strip() for cell in raw_line.split('|')]
                if cells and cells[0] == '':
                    cells = cells[1:]
                if cells and cells[-1] == '':
                    cells = cells[:-1]

                if not cells:
                    continue

                row_cells = []
                row_styles = {}

                for cell_index, cell in enumerate(cells):
                    clean_cell, cell_tags, row_span, col_span = _extract_cell_metadata(cell)
                    cell_style_map = {}

                    for tag, value in cell_tags:
                        if tag.startswith('table'):
                            table_styles.update(_style_from_tag(tag, value, 'table'))
                        elif tag in {'bgcolor', 'color', 'width', 'textalign'}:
                            cell_style_map.update(_style_from_tag(tag, value, 'cell'))
                        elif tag in {'rowbgcolor', 'rowcolor'}:
                            row_styles.update(_style_from_tag(tag, value, 'row'))
                        elif tag in {'colbgcolor', 'colcolor'}:
                            if len(col_styles) <= cell_index:
                                col_styles.extend([{}] * (cell_index - len(col_styles) + 1))
                            col_styles[cell_index].update(_style_from_tag(tag, value, 'col'))

                    if len(col_styles) <= cell_index:
                        col_styles.extend([{}] * (cell_index - len(col_styles) + 1))

                    row_cells.append((clean_cell, cell_style_map, row_span, col_span))

                row_entries.append((row_cells, row_styles))

            if row_entries:
                html_rows = []
                pending_rowspans = {}

                has_table_border = table_styles and 'border-color' in table_styles

                for row_entry in row_entries:
                    cells, row_style_map = row_entry
                    cells = list(cells)

                    row_style_attr = ''
                    if row_style_map:
                        row_style_attr = f' style="{_build_style(row_style_map)}"'

                    row_html = []
                    current_col = 0

                    for cell_data in cells:
                        text, cell_style, row_span, col_span = cell_data

                        while pending_rowspans.get(current_col, 0) > 0:
                            pending_rowspans[current_col] -= 1
                            current_col += 1

                        merged_style = {}
                        if current_col < len(col_styles):
                            merged_style.update(col_styles[current_col])
                        if row_style_map:
                            merged_style.update(row_style_map)
                        if cell_style:
                            merged_style.update(cell_style)

                        merged_style['border-style'] = 'none'

                        if has_table_border:
                            merged_style['border-style'] = 'solid'
                            merged_style['border-width'] = '2px' 
                            merged_style['border-color'] = table_styles.get('border-color', '#808080')

                        style_parts = []
                        if merged_style:
                            style_parts.append(f'style="{_build_style(merged_style)}"')
                        if col_span > 1:
                            style_parts.append(f'colspan="{col_span}"')
                        if row_span > 1:
                            style_parts.append(f'rowspan="{row_span}"')

                        style_attr = ''
                        if style_parts:
                            style_attr = f' {" ".join(style_parts)}'

                        rendered_cell = text if text else ''
                        if rendered_cell:
                            rendered_cell = rendering.rendering(
                                rendered_cell,
                                function=config.RENDERING_LIST,
                                db_check_func=None,
                                current_title=None
                            )
                            rendered_cell = rendered_cell.replace('\n', '')

                        row_html.append(f'<td{style_attr}>{rendered_cell}</td>')

                        for span_col in range(col_span):
                            pending_rowspans[current_col + span_col] = row_span - 1
                        current_col += col_span

                    html_rows.append(f'<tr{row_style_attr}>{"".join(row_html)}</tr>')

                table_style = _build_style(table_styles)
                result.append(f'<table class="wiki_table"{f" style=\"{table_style}\"" if table_style else ""}>{"".join(html_rows)}</table>')
                continue

        result.append(line)
        index += 1

    return '\n'.join(result)