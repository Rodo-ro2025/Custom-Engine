<!-- explanation.md -->
### wiki 풀더
본 wiki 풀더는 `config.py`의 수정만으로 작동하는 위키엔진입니다. **커스텀엔진(Custom Engine)**이라고 불립니다.

### 변수에 대한 설명서
- `config.py` 파일 안에 이미 내용이 들어있는데 그것은 기본값입니다. 원한다면 **'Free editing'** 부분을 수정해주세요.
- **'Please be careful with security when approaching'**
  - **'Please be careful with security when approaching'** 부분은 반드시 오픈소스를 다운로드 받은 후 전부 수정해주시길 바랍니다.
  - **'MASTER_KEY'** 변수는 서버 내부에서 쓰일 키입니다. 기본값은 존재해서 없어도 되기는 하지만, 웬만하면 필수로 적어주시길 바랍니다.
  - **'OPERATION_CODE'** 변수는 운영자 코드입니다. 기본값은 존재해서 없어도 되기는 하지만, 웬만하면 필수로 적어주시길 바랍니다.
- **'Exercise caution when approaching'**
  - **'Exercise caution when approaching'** 부분은 웬만하면 절대 건들지 마세요. 에러가 날 확률이 높습니다.
  - **'IMAGE'** 변수는 값을 바꿀 경우 기존 풀더는 삭제만 해주세요. 추가는 안하셔도 됩니다. 자동으로 생성되거든요. 만약 이미지를 그대로 써야한다면 풀더명만 올바르게 수정해주시면 감사하겠습니다.
  - **'SAFE_HTML'** 변수는 True을 추천합니다. 왜냐하면, 주요 문법들이 다양하게 있으며 자바스크립트 부분을 방지하는 코드가 없기에 True으로 해두는 것을 추천합니다.
  - **'ALLOWED_IMAGE_EXTENSIONS'** 변수는 파일 업로드를 할 때 사용 가능한 모든 확장자들을 말합니다. 이미 업로드 된 파일은 새로 바뀐 조건에 적용되지 않는 점을 기억해주시길 바랍니다.
- **'Free editing'**
  - **'WIKI_NAME'** 변수는 위키명입니다. 원하는 위키명을 작성하면 됩니다. 값은 필수로 적어야합니다.
  - **'MAIN_PAGE'** 변수는 반드시 위키명으로 시작할 필요는 없습니다. 단순 기본값이며, 다른 값으로 하고 싶다면 아래의 제목을 추천합니다.
    - **FrontPage**
    - **MainPage**
    - **대문**
  - **'LOGO_COLOR'** 변수는 CSS 처리에 들어갈 변수입니다. CSS가 이해 가능한 내용만 작성해주시길 바랍니다.
  - **TABLE_ACTIVATION & STRIKETHROUGH**
    - **'TABLE_ACTIVATION'** 변수는 테이블 기능을 허용할 것인지 안 할 것인지를 선택하는 변수입니다.
    - **'STRIKETHROUGH'** 변수는 취소선을 보이게 할 것인지 안 보이게 할 건지 선택하는 변수입니다.
  - **'QUICK_EXECUTION'** 변수는 빠르게 실행하기 위해 컴퓨터가 생성하는 파일을 보존할지 제거할지 선택하는 겁니다. False로 설정할 경우 해당 파일은 자동으로 제거됩니다.
  - **'STUB_LENGTH'** 변수는 해당 수보다 문서 길이가 짧은 경우 자동으로 토막글이 붙습니다.
  - **'RENDERING_LIST'** 변수는 'custom_grammer'와 'markdown' 2가지를 지원합니다. 중복 문법이 있을 수 있으니 주의해서 사용해주세요.
    - **'Markdown'** 변수는 extra, codehilite, nl2br, md_in_html, toc가 있습니다. 모르신다면 AI에게 아래의 내용을 복붙해주세요.
      - **Explain these Python Markdown extensions in Korean: ['extra', 'codehilite', 'nl2br', 'md_in_html', 'toc']**
  - **'NAMESPACE_LIST'** 변수는 분류 메뉴에서 나오는 탭 순서로, 문서 - 변수 순서대로 나오므로 원하는 순서대로 넣으시길 바랍니다. 문서는 맨 처음입니다.
  - **'FOLDING_STANDARD_TEXT'** 변수는 {{#folding}}처럼 아무 제목을 안 넣을 때를 대비해 기본 제목을 넣는 값입니다.
  - **'FOOTER_CONTENT'** 변수는 문서의 각주 내용입니다. 문서 최하단에 출력되는 각주이며, 맨 앞에 스페이스바 4번 또는 탭 1번을 누를 것을 권장합니다.
  - **AUTO_CREATE_DOCUMENTS & AUTO_CREATE_DOCUMENT_CONTENT**
    - **'AUTO_CREATE_DOCUMENTS'** 변수는 자동으로 생성할지에 대한 여부입니다. 권장사항은 true입니다.
    - **'AUTO_CREATE_DOCUMENT_CONTENT'** 변수는 자동으로 어떤 내용을 넣을지에 대한 질문입니다.

### 업데이트 내역
- **Version Beta**
  - **0.1v**: `HTML` 파일 다수 생성. `app.py` 메인 기능 생성.
  - **0.2v**: `rendering.py` 파일 생성.
  - **0.3v**: `rendering.py` 파일 'custom_grammer' 문법 최초 도입.
  - **0.4v**: `app.py` 기능 다수 생성.
  - **0.5v**: `rendering.py` 파일 조건문·{{#wiki}}·리다이렉트 등 추가.
  - **0.6v**: 최종 wiki 풀더 검토.
  - **0.7v**: `rendering.py` 파일 [목차] 기능 추가 및 문단 문법 개선.
  - **0.8v**: `config.py` 파일 자동생성 여부와 자동생성 내용 작성하는 변수 추가.
  - **0.9v**: `rendering.py` 파일 외부링크 버그 일부 개선.
  - **0.10v**: `rendering.py` 파일 앵커 기능 추가.
  - **0.11v**: `rendering.py` 파일 문서 포함 관련 줄바꿈 문제 및 색상 문법 미적용 문제 개선.
  - **0.12v**: `app.py` 파일 역링크 탭 추가.
  - **0.13v**: `app.py` 파일 토론 로직 변경.
  - **0.14v**: `main.js` 단축키 추가.
  - **0.15v**: `templates/footer.html` 파일을 `config.py`의 일부분으로 통합.
  - **0.16v**: `rendering.py` 파일 펼치기·접기 기능 추가.
  - **0.17v**: `app.py` 파일 역사 탭 코드 복사 기능 추가.
  - **0.18v**: `rendering.py` 파일 페이지 수 매크로 추가.
  - **0.19v**: `app.py` 파일 역사 탭 RAW·비교 추가.
  - **0.20v**: `rendering.py` 파일 각주 기능 추가.
  - **0.21v**: `app.py` 파일 차단 기능 추가.
- **Version 1**
  - **1.0v**: 깃허브 오픈소스로 업로드.
  - **1.1v**: 더보기 탭 추가.
  - **1.2v**: 도메인을 기준으로 한 상대 링크 추가.

### 주의사항 및 참고사항
- **주의사항**
  - **'Please be careful with security when approaching'** 부분을 반드시 수정해주시길 바랍니다. 보안상의 이유가 존재합니다.
  - **'Exercise caution when approaching'** 부분은 절대로 건들지마세요. `app.py` 외 여러 파일에서 DB를 불러오는데 필요한 요소가 포함되어있습니다.
  - 변수명을 절대로 변경하지마세요. 변수명을 변경할 경우 `app.py` 등 여러 파일에서 변수명이 불일치해 에러가 발생합니다.
- **참고사항**
  - 여러분 저는 전문가가 아닌 인공지능만 다루는 사람이지 프로그래밍을 할 줄 아는 사람이 아닙니다. 그러므로, 해당 위키를 기대하지 말아주셨으면 좋겠습니다. 개인 위키, 가족 위키, 학교 위키, 친구 위키 등 신뢰 가능한 대상을 중심으로 운영하는 것을 추천드립니다.
  - 처음으로 회원가입을 하는 사람은 운영자가 된다는 점을 알아주세요. 만약에 타 사용자가 운영코드를 모르는 상태로 운영자가 되게 할려면 그 사람이 가장 먼저 회원가입 할 수 있도록 해야합니다.
  - 위키명을 변경할 때 변경하기 전의 끝글자와 변경후의 끝글자에서 종성이 없어지거나 생기거나 했는지 확인하세요. 만약 없어지거나 생겼다면, **'FOOTER_CONTENT'** 변수의 조사 부분을 알맞게 수정하세요.
  - 라이선스를 변경할 때에는 **'FOOTER_CONTENT'** 변수의 링크와 라이선스도 올바르게 수정해주세요. 만약 변경하고 싶은데 무슨 라이선스로 변경해야할지 모르겠다면 `https://creativecommons.org/chooser/`로 접속해서 확인해보세요.
  - 문서 링크는 `[[문서명]]`으로 작성할 수 있습니다. 현재 도메인 기준의 경로로 이동하려면 `[[/w/문서명?rev=1]]`처럼 `/`로 시작하는 경로를 작성합니다. 편집·역사·토론 경로도 사용할 수 있습니다(예: `[[/edit/문서명|문서 편집]]`, `[[/history/문서명|문서 역사]]`, `[[/discussion/문서명|문서 토론]]`). 이 형식은 현재 접속 중인 도메인을 유지하며, 링크 문구가 필요하면 `|표시 문구`를 붙이면 됩니다.
