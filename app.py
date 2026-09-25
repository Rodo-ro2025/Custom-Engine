# app.py
# --- Official Module ---
import flask
from functools import wraps
import urllib.parse
import sqlite3
import os
import re
import shutil
import secrets
import difflib
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import html

# --- Personal Module ---
import rendering
import config

# --- variable ---
app = flask.Flask(__name__)
app.secret_key = config.MASTER_KEY or "Session_Key"


@app.context_processor
def inject_footer_content():
    return {
        "footer_content": config.FOOTER_CONTENT,
        "is_operator": is_admin_role(get_current_user_role())
    }

if app.secret_key == "Session_Key":
    print("[ERROR] Please be careful with security. (No session key)")
if not config.OPERATION_CODE:
    print("[ERROR] Please be careful with security. (No operating code)")

# --- function ---
def Checking_files_and_folders(personality, name, decision=True):
    if personality == "file":
        if not decision:
            if os.path.exists(name):
                os.remove(name)
            else:
                print("[ERROR] Cannot find a folder or file with that name.")
        else:
            if not os.path.exists(name):
                open(name, "w").close()
            else:
                print("[ERROR] There are files or folders with the same name.")
    elif personality == "folder":
        if not decision:
            if os.path.exists(name):
                shutil.rmtree(name)
            else:
                print("[ERROR] Cannot find a folder or file with that name.")
        else:
            if not os.path.exists(name):
                os.makedirs(name)
            else:
                print("[ERROR] There are files or folders with the same name.")

Checking_files_and_folders(personality='file', name=config.DB_PATH)
Checking_files_and_folders(personality='file', name=config.DB_USER_PATH)
Checking_files_and_folders(personality='folder', name="static/" + str(config.IMAGE))
if not config.QUICK_EXECUTION:
    Checking_files_and_folders(personality='folder', name='__pycache__', decision=False)

def prefix(Document):
    Document = urllib.parse.unquote(Document)

    if Document.startswith("문서:"):
        Document = Document[len("문서:"):]

    return Document


def normalize_redirect_target(target):
    if target is None:
        return None

    target = str(target).strip()
    if not target:
        return None

    target = urllib.parse.unquote(target)
    target = target.strip()

    if target.startswith("문서:"):
        target = target[len("문서:"):]

    return target or None


def get_redirect_target(content):
    if not content:
        return None

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("#redirect") or stripped.startswith("#리다이렉트") or stripped.startswith("#넘겨주기"):
            parts = stripped.split(None, 1)
            if len(parts) < 2:
                return None
            return normalize_redirect_target(parts[1])

        brace_match = re.match(r'^\s*\{\{redirect(?:\s*\|\s*|\s*:)?\s*(.+?)\s*\}\}\s*$', stripped)
        if brace_match:
            return normalize_redirect_target(brace_match.group(1))

        bracket_match = re.match(r'^\s*\[\[redirect:(.+?)\]\]\s*$', stripped)
        if bracket_match:
            return normalize_redirect_target(bracket_match.group(1))

    return None


def Document_Check(Document):
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM documents WHERE title = ?", (Document,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def get_document(Document):
    conn = sqlite3.connect(config.DB_PATH)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT content FROM documents WHERE title = ?",
        (Document,)
    )
    row = cursor.fetchone()

    conn.close()

    return row[0] if row else None

def save_document(Document, content, author="GUEST"):
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM wiki_history WHERE title = ?", (Document,))
    rev = cursor.fetchone()[0] + 1

    cursor.execute("""
        INSERT INTO documents (title, content)
        VALUES (?, ?)
        ON CONFLICT(title) DO UPDATE SET content=excluded.content
    """, (Document, content))

    cursor.execute("""
        INSERT INTO wiki_history (title, content, author, rev)
        VALUES (?, ?, ?, ?)
    """, (Document, content, author, rev))
    
    conn.commit()
    conn.close()


def build_auto_create_document_content(kind, **kwargs):
    templates = getattr(config, "AUTO_CREATE_DOCUMENT_CONTENT", {})
    template = templates.get(kind, "")
    if not template:
        return ""

    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def search_documents(query):
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT title, content
        FROM documents
        WHERE title LIKE ? OR content LIKE ?
        ORDER BY id DESC
    """, (f"%{query}%", f"%{query}%"))

    results = cursor.fetchall()
    conn.close()

    return results


def get_document_namespace(title):
    for namespace in config.NAMESPACE_LIST:
        if title.startswith(f"{namespace}:"):
            return namespace
    return "문서"


def get_backlinks(Document):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        rows = conn.execute("SELECT title, content FROM documents ORDER BY title ASC").fetchall()
    finally:
        conn.close()

    escaped_document = re.escape(Document)
    file_target = Document[len("파일:"):] if Document.startswith("파일:") else Document
    escaped_file_target = re.escape(file_target)
    backlink_patterns = {
        "link": re.compile(
            rf'(?<!파일:)(?<!분류:)\[\[{escaped_document}(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]'
        ),
        "file": re.compile(
            rf'\[\[파일:{escaped_file_target}(?:\|[^\]]*)?\]\]'
        ),
        "include": re.compile(
            rf'\[include\(\s*{escaped_document}(?:\s*,[^)]*)?\)',
            re.IGNORECASE
        ),
    }
    backlinks = []

    for title, content in rows:
        content = content or ""
        categories = set()

        if backlink_patterns["link"].search(content):
            categories.add("link")
        if backlink_patterns["file"].search(content):
            categories.add("file")
        if backlink_patterns["include"].search(content):
            categories.add("include")
        if get_redirect_target(content) == Document:
            categories.add("redirect")

        for category in sorted(categories):
            backlinks.append({
                "title": title,
                "namespace": get_document_namespace(title),
                "type": category,
            })

    grouped = {}
    for backlink in backlinks:
        grouped.setdefault(backlink["namespace"], []).append(backlink)

    return {
        namespace: sorted(items, key=lambda item: (item["title"], item["type"]))
        for namespace, items in sorted(grouped.items())
    }

# --- DB-related functions ---
def get_db():
    conn = sqlite3.connect(config.DB_USER_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_document_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE,
            content TEXT,
            is_protected INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT,
            author TEXT,
            rev INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_discussion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            parent_id INTEGER,
            author TEXT,
            content TEXT,
            depth INTEGER,
            topic_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    discussion_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(wiki_discussion)")
    }
    if "topic_code" not in discussion_columns:
        cursor.execute("ALTER TABLE wiki_discussion ADD COLUMN topic_code TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_title TEXT,
            category_name TEXT,
            UNIQUE(document_title, category_name) ON CONFLICT IGNORE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL CHECK(target_type IN ('id', 'ip')),
            target TEXT NOT NULL,
            expires_at TEXT,
            reason TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'all',
            blocked_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()

def init_user_db():
    conn = sqlite3.connect(config.DB_USER_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()
init_user_db()

# --- Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in flask.session:
            return flask.redirect(flask.url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def is_admin_role(role):
    if role is None:
        return False

    normalized = str(role).strip().lower()
    return normalized in {
        "admin",
        "administrator",
        "관리자",
        "운영자",
        "sysadmin",
        "superuser",
    }


def get_current_user_role():
    if flask.session.get('operator_authenticated'):
        return 'admin'

    username = flask.session.get('user')
    if not username:
        return None

    db = get_db()
    try:
        row = db.execute(
            "SELECT role FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        return row['role'] if row else None
    finally:
        db.close()


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in flask.session:
            return flask.redirect(flask.url_for('login'))

        role = get_current_user_role()
        if not is_admin_role(role):
            flask.abort(403)

        return f(*args, **kwargs)
    return decorated_function


def get_client_ip():
    return flask.request.remote_addr or "unknown"


def get_active_blocks(target_type, target):
    if not target:
        return []

    now = datetime.datetime.now().replace(microsecond=0).isoformat(sep=" ")
    conn = sqlite3.connect(config.DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT id, target_type, target, expires_at, reason, action,
                   blocked_by, created_at
            FROM access_blocks
            WHERE active = 1
              AND target_type = ?
              AND target = ?
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY id DESC
            """,
            (target_type, target, now)
        ).fetchall()
        return rows
    finally:
        conn.close()


def block_applies(block, endpoint, method):
    action = block[5]
    if action == "all":
        return True
    if action == "view":
        return endpoint in {"index", "view", "search", "random_page"}
    if action == "edit":
        return endpoint in {
            "editing", "delete_document", "upload_image", "api_protect",
            "discussion"
        }
    if action == "login":
        return endpoint in {"login", "register"}
    return False


def render_blocked_response(block):
    expires_at = block[3]
    expires_text = "무기한"
    if expires_at:
        expires_text = expires_at

    return flask.render_template(
        "blocked.html",
        reason=block[4],
        action=block[5],
        expires_at=expires_text,
        blocked_by=block[6]
    ), 403


@app.before_request
def enforce_access_blocks():
    if flask.request.endpoint == "static":
        return None

    if is_admin_role(get_current_user_role()):
        return None

    endpoint = flask.request.endpoint or ""
    method = flask.request.method
    candidates = []
    username = flask.session.get("user")
    if username:
        candidates.extend(get_active_blocks("id", username))

    if endpoint in {"login", "register"}:
        form_username = flask.request.form.get("id", "").strip()
        if form_username and form_username != username:
            candidates.extend(get_active_blocks("id", form_username))

    candidates.extend(get_active_blocks("ip", get_client_ip()))

    for block in candidates:
        if block_applies(block, endpoint, method):
            return render_blocked_response(block)

    return None

# --- routing ---
@app.route("/")
def index():
    return flask.redirect(flask.url_for("view", Document=config.MAIN_PAGE))

@app.route("/w/<path:Document>")
def view(Document):
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()

    Document = prefix(Document)

    rev = flask.request.args.get('rev', type=int)
    raw_rev = flask.request.args.get('raw', type=int)
    version = None

    if raw_rev is not None:
        cursor.execute(
            "SELECT content FROM wiki_history WHERE title = ? AND rev = ?",
            (Document, raw_rev)
        )
        row = cursor.fetchone()
        content = row[0] if row else None
        version = raw_rev
    elif rev:
        cursor.execute(
            "SELECT content FROM wiki_history WHERE title = ? AND rev = ?",
            (Document, rev)
        )
        row = cursor.fetchone()
        content = row[0] if row else None
        version = rev
    else:
        content = get_document(Document)

    if content is None:
        conn.close()
        error_msg = f"""
        <div class="wiki-error-container">
            <h2>❌ 해당 문서가 존재하지 않습니다.</h2>
            <p>요청하신 <b>{Document}</b> 문서는 아직 작성되지 않은 문서입니다.</p>
            <p>이름이 올바른지 확인하시거나, 아래 링크를 통해 새로운 문서를 작성하실 수 있습니다.</p>
            <hr>
            <a href='{flask.url_for("editing", Document=Document)}' class="wiki-btn-create">✍️ 새 문서 작성하기</a>
        </div>
        """
        return flask.render_template(
            "index.html", 
            title=Document, 
            mode="w", 
            detail=error_msg, 
            letter=False, 
            wiki_name=config.WIKI_NAME, 
            wiki_page=config.MAIN_PAGE, 
            wiki_color=config.LOGO_COLOR
        )

    if raw_rev is not None and content is not None:
        conn.close()
        return flask.render_template(
            "index.html",
            title=Document,
            mode="raw",
            raw_content=content,
            version=version,
            wiki_name=config.WIKI_NAME,
            wiki_page=config.MAIN_PAGE,
            wiki_color=config.LOGO_COLOR
        )

    come_value = flask.request.args.get("from", "")
    redirect_target = get_redirect_target(content)
    if redirect_target and redirect_target != Document:
        redirect_args = dict(flask.request.args.to_dict(flat=True))
        redirect_args.pop("form", None)
        redirect_args["from"] = Document
        conn.close()
        return flask.redirect(flask.url_for("view", Document=redirect_target, **redirect_args))

    try:
        rendered = rendering.rendering(
            content,
            function=config.RENDERING_LIST,
            db_check_func=Document_Check,
            current_title=Document
        )

        if Document.startswith("분류:"):
            category_title = Document.split("분류:", 1)[1].strip()

            search_pattern = f"%[[분류:{category_title}]]%"
            cursor.execute("""
                SELECT title, content FROM documents 
                WHERE content LIKE ? 
                ORDER BY title ASC
            """, (search_pattern,))
            rows = cursor.fetchall()

            category_pattern = re.compile(r'(?<!\\)\[\[분류:' + re.escape(category_title) + r'\]\](?!\\)')
            rows = [row for row in rows if category_pattern.search(row[1])]

            def get_namespace(title):
                for ns in config.NAMESPACE_LIST:
                    prefix = f"{ns}:"
                    if title.startswith(prefix):
                        return ns
                return "문서"

            def get_grouping_title(title):
                for ns in config.NAMESPACE_LIST:
                    prefix = f"{ns}:"
                    if title.startswith(prefix):
                        return title[len(prefix):]
                return title

            def get_initial_group(value):
                if not value:
                    return "문서"

                target = get_grouping_title(value)
                if not target:
                    return "문서"

                first_char = target[0]
                if '\uAC00' <= first_char <= '\uD7A3':
                    initial_index = (ord(first_char) - ord('가')) // 588
                    initial_consonants = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
                    if 0 <= initial_index < len(initial_consonants):
                        return initial_consonants[initial_index]
                    return "문서"
                if 'a' <= first_char.lower() <= 'z':
                    return first_char.lower()
                if '0' <= first_char <= '9':
                    return '0-9'
                return first_char

            grouped = {}
            for r in rows:
                item_title = r[0]
                namespace = get_namespace(item_title)
                group_name = get_initial_group(item_title)
                grouped.setdefault(namespace, {}).setdefault(group_name, []).append(item_title)

            namespace_names = sorted(grouped.keys(), key=lambda x: x)
            tab_buttons = []
            tab_panels = []

            for namespace in namespace_names:
                namespace_groups = grouped[namespace]
                panel_blocks = []

                for group_name in sorted(namespace_groups.keys(), key=lambda x: (x == "문서", x)):
                    items = sorted(namespace_groups[group_name], key=lambda x: x)
                    item_html = []
                    for item_title in items:
                        encoded_url = urllib.parse.quote(item_title)
                        item_html.append(f'<li><a href="/w/{encoded_url}">{item_title}</a></li>')
                    panel_blocks.append(
                        f'<div style="margin-bottom: 14px;">'
                        f'<strong>{html.escape(group_name)}</strong>'
                        f'<ul style="margin: 6px 0 0 20px; padding-left: 0; line-height: 1.7;">{"".join(item_html)}</ul>'
                        f'</div>'
                    )

                panel_id = f"wiki-category-panel-{namespace.replace(' ', '_')}"
                is_first = namespace == namespace_names[0]
                tab_buttons.append(
                    f'<button type="button" class="wiki-category-tab {"active" if is_first else ""}" data-tab="{html.escape(namespace)}" style="padding: 8px 12px; margin-right: 8px; border: 1px solid #ccc; border-radius: 6px; background: {"#007bff" if is_first else "#f5f5f5"}; color: {"white" if is_first else "#333"}; cursor: pointer;">{html.escape(namespace)}</button>'
                )
                tab_panels.append(
                    f'<div id="{panel_id}" class="wiki-category-panel" style="display: {"block" if is_first else "none"}; margin-top: 12px;">' + ''.join(panel_blocks) + '</div>'
                )

            if namespace_names:
                category_list_html = f"""
                <div class="wiki-category-page-list" style="margin-top: 40px; padding: 20px; border-top: 3px double #ccc;">
                    <h3 style="margin-bottom: 15px;">📂 이 분류에 속한 문서 ({len(rows)}개)</h3>
                    <div style="margin-bottom: 12px;">
                        {"".join(tab_buttons)}
                    </div>
                    {"".join(tab_panels)}
                    <script>
                    (function() {{
                        const tabs = document.querySelectorAll('.wiki-category-tab');
                        const panels = document.querySelectorAll('.wiki-category-panel');
                        tabs.forEach(function(tab) {{
                            tab.addEventListener('click', function() {{
                                tabs.forEach(function(btn) {{
                                    btn.classList.remove('active');
                                    btn.style.background = '#f5f5f5';
                                    btn.style.color = '#333';
                                }});
                                this.classList.add('active');
                                this.style.background = '#007bff';
                                this.style.color = 'white';
                                const target = this.getAttribute('data-tab');
                                panels.forEach(function(panel) {{
                                    panel.style.display = 'none';
                                }});
                                const matched = document.getElementById('wiki-category-panel-' + target.replace(/ /g, '_'));
                                if (matched) {{
                                    matched.style.display = 'block';
                                }}
                            }});
                        }});
                    }})();
                    </script>
                </div>
                """
            else:
                category_list_html = """
                <div class="wiki-category-page-list" style="margin-top: 40px; padding: 20px; border-top: 3px double #ccc;">
                    <p style="color: #666; font-style: italic;">📂 이 분류에 속한 문서가 아직 없습니다.</p>
                </div>
                """

            rendered += category_list_html

    finally:
        conn.close()

    length = len(content) < config.STUB_LENGTH
    return flask.render_template(
        "index.html",
        title=Document,
        mode="w",
        detail=rendered,
        letter=length,
        version=version,
        come=come_value,
        wiki_name=config.WIKI_NAME, 
        wiki_page=config.MAIN_PAGE, 
        wiki_color=config.LOGO_COLOR
    )

@app.route("/api/protect/<path:Document>", methods=["GET", "POST"])
@login_required
def api_protect(Document):
    Document = prefix(Document)

    is_admin = is_admin_role(get_current_user_role())

    doc_db = get_document_db()
    try:
        if flask.request.method == "POST":
            if not is_admin:
                return flask.jsonify({"status": "error", "message": "권한이 없습니다."}), 403

            cur = doc_db.execute("SELECT is_protected FROM documents WHERE title = ?", (Document,))
            row = cur.fetchone()
            current_status = row[0] if row else 0
            new_status = 0 if current_status else 1

            doc_db.execute("UPDATE documents SET is_protected = ? WHERE title = ?", (new_status, Document))
            doc_db.commit()

            return flask.jsonify({"status": "success", "is_protected": new_status})

        cur = doc_db.execute("SELECT is_protected FROM documents WHERE title = ?", (Document,))
        row = cur.fetchone()
        is_protected = row[0] if row else 0

        return flask.jsonify({
            "title": Document,
            "is_protected": is_protected,
            "is_admin": is_admin
        })
    finally:
        doc_db.close()

@app.route("/edit/<path:Document>", methods=["GET", "POST"])
@login_required
def editing(Document):
    Document = prefix(Document)

    current_user = flask.session.get("user")
    is_admin = is_admin_role(get_current_user_role())

    if Document.startswith("사용자:"):
        owner_name = Document[len("사용자:"):].split("/", 1)[0]

        if current_user != owner_name and not is_admin:
            flask.abort(403)

    doc_db = get_document_db()
    try:
        cur = doc_db.execute(
            "SELECT is_protected FROM documents WHERE title = ?",
            (Document,)
        )

        row = cur.fetchone()

        if row and row["is_protected"] == 1 and not is_admin:
            flask.abort(403)
    finally:
        doc_db.close()

    if flask.request.method == "POST":
        user_text = flask.request.form.get("content")
        save_document(
            Document,
            user_text,
            author=current_user
        )

        return flask.redirect(
            flask.url_for("view", Document=Document)
        )

    existing = get_document(Document) or ""

    return flask.render_template(
        "index.html",
        title=Document,
        mode="edit",
        detail=existing,
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    )

@app.route("/admin/<path:subject>")
@admin_required
def operator(subject):
    subject = prefix(subject)
    return flask.render_template("admin.html", title=subject, mode="admin", detail="", wiki_name=config.WIKI_NAME, wiki_page=config.MAIN_PAGE, wiki_color=config.LOGO_COLOR)


@app.route("/admin/blocks", methods=["GET"])
@admin_required
def manage_blocks():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        blocks = conn.execute(
            "SELECT * FROM access_blocks ORDER BY active DESC, id DESC"
        ).fetchall()
    finally:
        conn.close()

    return flask.render_template(
        "blocks.html",
        title="차단 관리",
        blocks=blocks,
        error=None,
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    )


@app.route("/admin/blocks/create", methods=["POST"])
@admin_required
def create_block():
    target_type = flask.request.form.get("target_type", "id").strip()
    target = flask.request.form.get("target", "").strip()
    action = flask.request.form.get("action", "all").strip()
    reason = flask.request.form.get("reason", "").strip()
    year = flask.request.form.get("expires_year", "").strip()
    month = flask.request.form.get("expires_month", "").strip()
    day = flask.request.form.get("expires_day", "").strip()

    allowed_target_types = {"id", "ip"}
    allowed_actions = {"all", "view", "edit", "login"}
    expires_at = None

    if target_type not in allowed_target_types:
        error = "차단 대상 종류가 올바르지 않습니다."
    elif not target:
        error = "차단할 ID 또는 IP를 입력하세요."
    elif action not in allowed_actions:
        error = "차단 동작이 올바르지 않습니다."
    elif not reason:
        error = "제재 사유를 입력하세요."
    elif any((year, month, day)) and not all((year, month, day)):
        error = "종료 날짜는 연도, 월, 일을 모두 입력하세요."
    elif any((year, month, day)):
        try:
            expires_at = datetime.datetime.strptime(
                f"{year}-{month}-{day}", "%Y-%m-%d"
            ).replace(hour=23, minute=59, second=59)
            if expires_at <= datetime.datetime.now():
                error = "종료 날짜는 현재보다 이후여야 합니다."
            else:
                expires_at = expires_at.isoformat(sep=" ")
        except ValueError:
            error = "종료 날짜가 올바르지 않습니다."
    else:
        error = None

    if error:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            blocks = conn.execute(
                "SELECT * FROM access_blocks ORDER BY active DESC, id DESC"
            ).fetchall()
        finally:
            conn.close()
        return flask.render_template(
            "blocks.html",
            title="차단 관리",
            blocks=blocks,
            error=error,
            wiki_name=config.WIKI_NAME,
            wiki_page=config.MAIN_PAGE,
            wiki_color=config.LOGO_COLOR
        ), 400

    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO access_blocks
                (target_type, target, expires_at, reason, action, blocked_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_type,
                target,
                expires_at,
                reason,
                action,
                flask.session.get("user", "operator"),
                datetime.datetime.now().replace(microsecond=0).isoformat(sep=" ")
            )
        )
        conn.commit()
    finally:
        conn.close()

    return flask.redirect(flask.url_for("manage_blocks"))


@app.route("/admin/blocks/<int:block_id>/release", methods=["POST"])
@admin_required
def release_block(block_id):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            "UPDATE access_blocks SET active = 0 WHERE id = ?",
            (block_id,)
        )
        conn.commit()
    finally:
        conn.close()

    return flask.redirect(flask.url_for("manage_blocks"))

@app.route("/history/<path:Document>")
def history(Document):
    Document = prefix(Document)

    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT rev, author, datetime(created_at, '+9 hours'), LENGTH(content), content
        FROM wiki_history 
        WHERE title = ? 
        ORDER BY rev DESC
    """, (Document,))
    rows = cursor.fetchall()
    conn.close()

    return flask.render_template(
        "index.html",
        title=Document,
        mode="history",
        history_data=rows,
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    )


@app.route("/compare/<path:Document>")
def compare(Document):
    Document = prefix(Document)
    from_rev = flask.request.args.get("from", type=int)
    to_rev = flask.request.args.get("to", type=int)

    if from_rev is None or to_rev is None or from_rev < 1 or to_rev < 1 or from_rev >= to_rev:
        return flask.abort(400)

    conn = sqlite3.connect(config.DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT rev, content
            FROM wiki_history
            WHERE title = ? AND rev IN (?, ?)
            ORDER BY rev ASC
            """,
            (Document, from_rev, to_rev)
        ).fetchall()
    finally:
        conn.close()

    contents = {row[0]: row[1] or "" for row in rows}
    if from_rev not in contents or to_rev not in contents:
        return flask.abort(404)

    comparison_html = difflib.HtmlDiff(wrapcolumn=120).make_table(
        contents[from_rev].splitlines(),
        contents[to_rev].splitlines(),
        fromdesc=f"이전 버전 r{from_rev}",
        todesc=f"현재 버전 r{to_rev}",
        context=False
    )

    return flask.render_template(
        "index.html",
        title=Document,
        mode="compare",
        comparison_html=comparison_html,
        from_version=from_rev,
        to_version=to_rev,
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    )


@app.route("/backlink/<path:Document>")
def backlink(Document):
    Document = prefix(Document)
    return flask.render_template(
        "index.html",
        title=Document,
        mode="backlink",
        backlinks=get_backlinks(Document),
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    )

def discussion_topic_code(comment_id):
    alphabet = "123456789abcdefghijklmnopqrstuvwxyz"
    length = secrets.randbelow(11) + 20
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def parse_discussion_topic_code(topic_code):
    if not re.fullmatch(r"[1-9a-z]{20,30}", topic_code):
        return None
    return topic_code


@app.route("/discussion/<path:Document>", methods=["GET", "POST"])
@app.route("/discussion/<path:Document>/<topic_code>", methods=["GET", "POST"])
@login_required
def discussion(Document, topic_code=None):
    if topic_code and parse_discussion_topic_code(topic_code) is None:
        Document = f"{Document}/{topic_code}"
        topic_code = None

    Document = prefix(Document)
    topic_id = parse_discussion_topic_code(topic_code) if topic_code else None

    if flask.request.method == "POST":
        content = flask.request.form.get("content")
        parent_id = flask.request.form.get("parent_id")
        author = flask.session.get("user", "GUEST")

        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()

        is_new_topic = topic_id is None and not parent_id
        if is_new_topic:
            topic_id = discussion_topic_code(None)

        if not parent_id and topic_id is not None:
            if isinstance(topic_id, str):
                cursor.execute(
                    "SELECT id FROM wiki_discussion WHERE title = ? AND topic_code = ? AND parent_id IS NULL",
                    (Document, topic_id)
                )
                topic_row = cursor.fetchone()
                if topic_row is None:
                    parent_id = None
                else:
                    parent_id = topic_row[0]
            else:
                parent_id = topic_id

        if not parent_id:
            parent_id = None
            depth = 0
        else:
            try:
                parent_id = int(parent_id)
            except (TypeError, ValueError):
                conn.close()
                return flask.abort(400)

            cursor.execute(
                "SELECT depth, title FROM wiki_discussion WHERE id = ?",
                (parent_id,)
            )

            row = cursor.fetchone()
            if row is None or row[1] != Document:
                conn.close()
                return flask.abort(400)
            depth = row[0] + 1

        cursor.execute("""
            INSERT INTO wiki_discussion
            (title, parent_id, author, content, depth, topic_code)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (Document, parent_id, author, content, depth, topic_id))

        new_comment_id = cursor.lastrowid
        conn.commit()
        conn.close()

        if is_new_topic:
            new_topic_code = topic_id
            return flask.redirect(flask.url_for(
                "discussion", Document=Document, topic_code=new_topic_code
            ))

        return flask.redirect(flask.url_for(
            "discussion", Document=Document,
            topic_code=topic_code or discussion_topic_code(parent_id)
        ))

    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, parent_id, author, content, created_at, depth
            , topic_code
        FROM wiki_discussion
        WHERE title = ?
        ORDER BY id ASC
    """, (Document,))

    all_rows = cursor.fetchall()
    conn.close()

    if topic_id is None:
        rows = [row for row in all_rows if row[1] is None]
    else:
        if not any(row[6] == topic_id and row[1] is None for row in all_rows):
            flask.abort(404)

        topic_row = next(row for row in all_rows if row[6] == topic_id and row[1] is None)
        included_ids = {topic_row[0]}
        changed = True
        while changed:
            changed = False
            for row in all_rows:
                if row[1] in included_ids and row[0] not in included_ids:
                    included_ids.add(row[0])
                    changed = True
        rows = [row for row in all_rows if row[0] in included_ids]

    rendered_rows = []
    comment_ids = {row[0] for row in all_rows}

    def replace_comment_reference(text):
        reference_pattern = re.compile(r'\[\[#(\d+)\]\]|(?<![\w#])#(\d+)')

        def replace_reference(match):
            comment_id = int(match.group(1) or match.group(2))
            if comment_id not in comment_ids:
                return match.group(0)
            return f'DISCUSSIONCOMMENTREF{comment_id}TOKEN'

        return reference_pattern.sub(replace_reference, text)

    for row in rows:
        raw_content = row[3] or ""
        rendered_content = rendering.rendering(
            replace_comment_reference(raw_content),
            function=config.RENDERING_LIST,
            db_check_func=Document_Check,
            current_title=Document
        )
        for comment_id in comment_ids:
            marker = f'DISCUSSIONCOMMENTREF{comment_id}TOKEN'
            rendered_content = rendered_content.replace(
                marker,
                f'<a href="#comment-{comment_id}">#{comment_id}</a>'
            )
        rendered_rows.append(row + (rendered_content,))

    is_admin = False
    if flask.session.get('user'):
        conn = sqlite3.connect(config.DB_USER_PATH) 
        cursor = conn.cursor()

        cursor.execute("SELECT role FROM users WHERE username = ?", (flask.session.get('user'),))
        user_data = cursor.fetchone()

        if user_data and is_admin_role(user_data[0]):
            is_admin = True

        conn.close()

    return flask.render_template(
        "discussion.html",
        title=Document,
        discussions=rendered_rows,
        topic_code=topic_code,
        is_topic=topic_id is not None,
        is_admin=is_admin,
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    )

@app.route("/discussion/delete/<topic_code>/<int:comment_id>/<path:Document>", methods=["POST"])
@admin_required
def delete_comment(topic_code, comment_id, Document):
    Document = prefix(Document)
    
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT topic_code FROM wiki_discussion WHERE id = ? AND title = ?",
            (comment_id, Document)
        )
        comment = cursor.fetchone()
        if comment is None:
            return flask.abort(404)

        cursor.execute(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT id FROM wiki_discussion WHERE id = ? AND title = ?
                UNION ALL
                SELECT child.id
                FROM wiki_discussion AS child
                JOIN descendants AS parent ON child.parent_id = parent.id
                WHERE child.title = ?
            )
            DELETE FROM wiki_discussion
            WHERE id IN (SELECT id FROM descendants)
            """,
            (comment_id, Document, Document)
        )
        conn.commit()

        cursor.execute(
            "SELECT 1 FROM wiki_discussion WHERE title = ? AND topic_code = ? AND parent_id IS NULL",
            (Document, topic_code)
        )
        topic_exists = cursor.fetchone() is not None

    finally:
        conn.close()

    if not topic_exists:
        return flask.redirect(flask.url_for("discussion", Document=Document))

    return flask.redirect(flask.url_for(
        "discussion", Document=Document, topic_code=topic_code
    ))

@app.route("/api/document-exists/<path:Document>")
def api_document_exists(Document):
    Document = prefix(Document)
    exists = Document_Check(Document)
    return flask.jsonify({
        "title": Document,
        "exists": exists,
        "redirect": flask.url_for("view", Document=Document) if exists else None,
    })


@app.route("/search")
def search():
    q = flask.request.args.get("q", "").strip()

    if not q:
        return flask.redirect(flask.url_for("index"))

    results = search_documents(q)

    return flask.render_template("search.html", query=q, results=results, wiki_name=config.WIKI_NAME, wiki_page=config.MAIN_PAGE, wiki_color=config.LOGO_COLOR)

@app.route("/RandomPage")
def random_page():
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()

    namespace_prefixes = tuple(f"{ns}:" for ns in config.NAMESPACE_LIST)
    if not namespace_prefixes:
        cursor.execute("SELECT title FROM documents ORDER BY RANDOM() LIMIT 1")
    else:
        clauses = ' AND '.join('title NOT LIKE ?' for _ in namespace_prefixes)
        params = [f"{prefix}%" for prefix in namespace_prefixes]
        cursor.execute(f"""
            SELECT title
            FROM documents
            WHERE {clauses}
            ORDER BY RANDOM() LIMIT 1
        """, params)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return flask.redirect(flask.url_for("index"))

    return flask.redirect(flask.url_for("view", Document=row[0]))

@app.route("/Sign_Up", methods=["GET", "POST"])
def register():
    if flask.request.method == "POST":
        username = flask.request.form.get("id")
        password = flask.request.form.get("pw")
        operation_code = flask.request.form.get("operation_code")

        if not username or not password:
            return flask.abort(400)

        if not re.fullmatch(r"[A-Za-z0-9]+", username):
            return flask.abort(400)

        conn = sqlite3.connect(config.DB_USER_PATH)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]

        cur.execute(
            "SELECT username FROM users WHERE username = ?",
            (username,)
        )

        if cur.fetchone():
            conn.close()
            return flask.abort(409)

        hashed_pw = generate_password_hash(password)

        if user_count == 0:
            role = "admin"
        else:
            expected_code = config.OPERATION_CODE or "Admin_Code"
            if operation_code == expected_code:
                role = "admin"
            else:
                role = "user"

        cur.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, hashed_pw, role)
        )

        conn.commit()
        conn.close()

        user_document_title = f"사용자:{username}"

        if config.AUTO_CREATE_DOCUMENTS.get("user", True):
            initial_content = build_auto_create_document_content("user", username=username)
            save_document(user_document_title, initial_content, author="SYSTEM")

        return flask.redirect(flask.url_for("login"))

    return flask.render_template(
        "accession.html",
        title="회원가입",
        again=False,
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    )

@app.route("/Revisit", methods=["GET", "POST"])
def login():
    if flask.request.method == "POST":
        user_id = flask.request.form.get("id")
        user_pw = flask.request.form.get("pw")
        operation_code = flask.request.form.get("operation_code", "")

        if not user_id or not user_pw:
            return flask.abort(400)

        conn = sqlite3.connect(config.DB_USER_PATH)
        cur = conn.cursor()

        cur.execute(
            "SELECT password FROM users WHERE username=?",
            (user_id,)
        )

        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user[0], user_pw):
            flask.session.permanent = True
            flask.session['user'] = user_id
            flask.session['operator_authenticated'] = bool(
                config.OPERATION_CODE and operation_code == config.OPERATION_CODE
            )

            return flask.redirect(flask.url_for('index'))
        else:
            return flask.abort(403)

    return flask.render_template("accession.html", title="로그인", again=True, wiki_name=config.WIKI_NAME, wiki_page=config.MAIN_PAGE, wiki_color=config.LOGO_COLOR)

@app.route("/Logout")
def logout():
    flask.session.pop('user', None)
    flask.session.pop('operator_authenticated', None)
    return flask.redirect(flask.url_for("index"))

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload_image():
    if flask.request.method == "GET":
        upload_html = """
        <div class="wiki-upload-container" style="padding: 20px; border: 1px solid #ccc; border-radius: 6px;">
            <h2>📤 위키 이미지 업로드</h2>
            <p>위키 문서에 사용할 이미지를 서버에 바치세요. 업로드 시 자동으로 파일 문서가 생성됩니다.</p>
            <hr>
            <form action="/upload" method="POST" enctype="multipart/form-data" style="margin-top: 20px;">
                <input type="file" name="file" required><br><br>
                <button type="submit" style="padding: 10px 20px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer;">📦 서버로 전송</button>
            </form>
        </div>
        """
        return flask.render_template("index.html", title="이미지 업로드", mode="w", detail=upload_html, letter=False, wiki_name=config.WIKI_NAME, wiki_page=config.MAIN_PAGE, wiki_color=config.LOGO_COLOR)

    if 'file' not in flask.request.files:
        return flask.abort(400)
        
    file = flask.request.files['file']
    
    if file.filename == '':
        return flask.abort(400)
        
    if file:
        filename = file.filename

        image_folder = os.path.join(config.BASE_DIR, "static", str(config.IMAGE))

        if not os.path.exists(image_folder):
            os.makedirs(image_folder)

        file_path = os.path.join(image_folder, filename)
        file.save(file_path)

        wiki_title = f"파일:{filename}"

        try:
            if config.AUTO_CREATE_DOCUMENTS.get("image", True):
                wiki_content = build_auto_create_document_content("image", filename=filename)
                save_document(wiki_title, wiki_content, author=flask.session.get("user", "GUEST"))

        except Exception as e:
            print(f"파일 문서 자동 생성 중 DB 에러 발생: {e}")

        encoded_title = urllib.parse.quote(wiki_title)

        result_html = f"""
        <div class="wiki-success-container" style="padding: 20px; border: 1px solid #28a745; border-radius: 6px; background-color: #f8fff9;">
            <h2 style="color: #28a745;">🎉 업로드 및 파일 문서 생성 완료!</h2>
            <p>서버에 파일이 안전하게 저장되었으며, <b><a href="/w/{encoded_title}" target="_blank" style="color: #007bff; font-weight: bold;">{wiki_title}</a></b> 문서가 자동 생성되었습니다!</p>
            <hr>
            <p>아래 코드를 복사해서 다른 위키 문서 편집창에 자유롭게 붙여넣으세요:</p>
            <div style="background: #e9ecef; padding: 15px; font-family: monospace; font-size: 1.2rem; border-radius: 4px; border: 1px solid #ced4da; margin: 15px 0;">
                <b>[[파일:{filename}]]</b>
            </div>
            <a href="/upload" style="color: #007bff; text-decoration: none;">🔄 다른 이미지 더 올리기</a> | 
            <a href="/" style="color: #007bff; text-decoration: none;">🏠 홈으로 이동</a>
        </div>
        """
        return flask.render_template("index.html", title="업로드 완료", mode="w", detail=result_html, letter=False, wiki_name=config.WIKI_NAME, wiki_page=config.MAIN_PAGE, wiki_color=config.LOGO_COLOR)

@app.route("/images/<filename>")
def serve_image(filename):
    filename = urllib.parse.unquote(filename)
    image_folder = os.path.join(config.BASE_DIR, "static/" + str(config.IMAGE))
    return flask.send_from_directory(image_folder, filename)

@app.route("/delete/<path:Document>", methods=["GET", "POST"])
@login_required
def delete_document(Document):
    Document = prefix(Document)
    current_user = flask.session.get("user")

    if flask.request.method == "POST":
        doc_conn = sqlite3.connect(config.DB_PATH)
        doc_cursor = doc_conn.cursor()
        
        try:
            doc_cursor.execute(
                "DELETE FROM documents WHERE title = ?",
                (Document,)
            )
            doc_conn.commit()
        finally:
            doc_conn.close()

        return flask.redirect(flask.url_for("index"))

    return flask.render_template(
        "delete_confirm.html",
        title="문서 삭제 확인",
        document_title=Document,
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    )

@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(409)
@app.errorhandler(500)
def global_error_handler(e):
    error_name = type(e).__name__
    error_desc = str(e)

    status_code = getattr(e, "code", 500)

    print(error_desc)

    return flask.render_template(
        "error.html",
        title=f"{status_code} {error_name}",
        wiki_name=config.WIKI_NAME,
        wiki_page=config.MAIN_PAGE,
        wiki_color=config.LOGO_COLOR
    ), status_code

if __name__ == "__main__":
    app.run(debug=config.DEBUG_MODE, host=config.HOST, port=config.PORT)