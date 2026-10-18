# config.py
import os

# --- Please be careful with security when approaching ---
MASTER_KEY = "X9f!a7Qz#Lm2^tBv@R4k"
OPERATION_CODE = "pW3$Zr8*Yh1!nKj6%Tq"

# --- Exercise caution when approaching ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'wiki.db')
DB_USER_PATH = os.path.join(BASE_DIR, 'users.db')

DEBUG_MODE = True
HOST = "0.0.0.0"
PORT = 5000

IMAGE = "image"
SAFE_HTML = True
ALLOWED_IMAGE_EXTENSIONS = {"avif", "bmp", "gif", "jfif", "jpeg", "jpg", "png", "webp"}

# --- Free editing ---
WIKI_NAME = "MYWIKI"
MAIN_PAGE = f"{WIKI_NAME}:대문"
LOGO_COLOR = "white"

TABLE_ACTIVATION = True
STRIKETHROUGH = True
QUICK_EXECUTION = False
STUB_LENGTH = 150

RENDERING_LIST = ["custom_grammer"]
NAMESPACE_LIST = ["분류", "틀", "템플릿", "파일", WIKI_NAME, "사용자"]

FOLDING_STANDARD_TEXT = "펼치기 · 접기"
FOOTER_CONTENT = f'''
    <footer>
        <p>
        이 저작물은 <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en" target="_blank">CC BY-NC-SA 4.0 KR</a>에 따라 이용할 수 있습니다.
        <br>기여하신 문서의 저작권은 각 기여자에게 있으며, 각 기여자는 기여하신 부분의 저작권을 갖습니다.
        <br>
        <br>{WIKI_NAME}는 백과사전이 아니며 검증되지 않았거나, 편향적이거나, 잘못된 서술이 있을 수 있습니다.
        <br>{WIKI_NAME}는 위키위키입니다. 여러분이 직접 문서를 고칠 수 있으며, 다른 사람의 의견을 원할 경우 직접 토론을 발제할 수 있습니다.
        <br><b>© 2026 {WIKI_NAME}</b>
        </p>
    </footer>'''

AUTO_CREATE_DOCUMENTS = {
    "user": True,
    "image": True
}
AUTO_CREATE_DOCUMENT_CONTENT = {
    "user": "[[분류:사용자 문서]]",
    "image": """[[분류:파일/미분류]]
[[파일:{filename}|width=100%]]
[목차]
## 개요
| <tablebordercolor=#cccccc><rowbgcolor=black><rowcolor=white> **항목** | **설명** |
| 출처 | 출처를 반드시 삽입해 주세요. |
| 날짜 | 이미지가 만들어진 날짜를 삽입해 주세요. |
| 저작자 | 이미지의 저작자를 삽입해 주세요. |
| 저작권 | 이미지의 저작권과 관련된 기타 정보를 삽입해 주세요. |
| 기타 | 기타 정보가 있으면 삽입해 주세요. |

## 이미지 설명
이미지의 자세한 설명을 적어 주세요."""
}
