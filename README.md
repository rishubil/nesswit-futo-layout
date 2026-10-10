# nesswit-futo-layout

개인적으로 쓰는 [FUTO Keyboard](https://keyboard.futo.org/) 커스텀 레이아웃 저장소.
레이아웃 정의(yaml)와, 딩굴 플릭 힌트를 키 위에 그려 주는 커스텀 테마 빌더가 들어 있다.

| 파일 | 내용 |
|---|---|
| `dingul.yml` | 딩굴 방식 한글 플릭 레이아웃 |
| `qwerty_hacker.yml` | 기호를 손보고 숫자 줄을 뺀 QWERTY |
| `tools/build_theme.py` | 딩굴 플릭 힌트(와 KBD75 시프트 문자)를 키에 구워 넣는 테마 빌더 ([THEME.md](THEME.md)) |

---

## 레이아웃 추가

FUTO Keyboard 개발자 설정의 레이아웃 에디터에서 yaml 내용을 붙여넣어 추가한다.
추가한 **순서대로** 내부 이름이 `custom0`, `custom1`, … 로 정해지며
(`DevLayoutEditor.kt:95`), 테마 선택자가 이 이름을 쓰므로 순서를 바꿨다면 테마를
다시 빌드해야 한다. 자세한 건 [THEME.md](THEME.md#레이아웃-이름-custom0--custom1--) 참고.

레이아웃 문법은 앱 저장소의 `java/assets/layouts/LayoutSpec.md` 에 정리되어 있다.

---

## 딩굴 (`dingul.yml`)

키를 누른 채 상/하/좌/우로 밀어(flick) 문자를 입력하는 4열 한글 레이아웃.
원본 딩굴과 달리 **ㅒ / ㅖ 는 ㅐ / ㅔ 를 두 번 입력**해서 넣는다 (`ㅇ+ㅐ+ㅐ = 얘`).

![딩굴 레이아웃 미리보기](build/preview.png)

아래 테마 빌더가 만드는 미리보기 렌더(`build/preview.png`)다. 가운데 큰 글자가 기본 입력,
주변 넷이 방향별 입력이며, 테마를 설치하면 실제 키보드에도 이대로 힌트가 보인다.

- 자음 키의 좌/우는 같은 문자다(ㅋ, ㅌ, ㅍ, ㅊ). 어느 쪽으로 밀어도 된다.
- 3열은 모음 전용이다. `ㅣ·` `ㅡ‖` `··` 는 천지인처럼 획을 더하는 용도.
- 숫자는 ㅅ / ㅇ / ㅎ 키의 방향 입력에 흩어져 있다.
- 아래 줄은 `?123` · `ㅋㅋㅋ` · 액션 · 스페이스 · 컨텍스트 키 · 엔터.

`showPopup: false`, `moreKeyMode: OnlyExplicit` 이라 롱프레스 팝업은 뜨지 않는다.

---

## QWERTY (`qwerty_hacker.yml`)

![쿼티 레이아웃 미리보기](build/preview_qwerty.png)

별도 숫자 행을 켜는 대신(`numberRowMode: AlwaysDisabled`) 첫 줄에 숫자를 직접 두고,
각 키의 롱프레스에 기호를 몰아넣은 영문 레이아웃. 키 우상단의 작은 글자가 롱프레스로
나오는 문자다.

- 괄호·연산자는 `qwerty` 줄, 따옴표류와 `;` `:` 는 `asdf` 줄에 있다.
- `z` 롱프레스는 탭, `x` `c` 는 `«` `»`, `v` `b` 는 `<` `>` 다.
- 아래 줄에 코드 블록용 ` ``` ` 키를 두었다.

---

## 딩굴 플릭 힌트 테마

앱은 어느 방향에 무슨 글자가 있는지 표시해 주지 않는다. `tools/build_theme.py` 는
`dingul.yml` 을 읽어 방향 문자를 그려 넣은 키 아이콘을 만들고, 그걸 묶어 임포트할 수
있는 커스텀 테마 zip 을 만든다.

```
uv run tools/build_theme.py --layout custom0
```

[uv script](https://docs.astral.sh/uv/guides/scripts/) 라 `uv` 만 있으면 되고, 결과물은
`dist/i.nesswit.DingulFlick.zip` 이다. 설치 절차, 앱 코드 조사 결과, 조정할 수 있는 값은
전부 [THEME.md](THEME.md) 에 있다.

테마는 모든 레이아웃의 기능키(Esc, Ctrl, Shift, Backspace …)에 배경을 깐다. 수정키의 래치·잠김
표시는 앱 기본 그대로 보인다 ([THEME.md](THEME.md#기능키-배경)).

`qwerty_kbd75.yml` 도 쓴다면 `--kbd75-layout custom0` 처럼 그 레이아웃 번호를 주면, 같은 테마에
키마다 시프트 문자(우상단)와 Fn 기능(우하단)을 표시하는 오버레이도 들어간다. 이때 KBD75 미리보기
`build/preview_kbd75.png` 와 `build/preview_kbd75_fn.png` 도 같이 만든다. 자세한 건
[THEME.md](THEME.md#kbd75-시프트-문자와-fn-기능-qwerty_kbd75yml) 참고.

**`dingul.yml` 을 고쳤다면 테마를 다시 빌드해야 한다.** 자동 동기화되지 않아서
표시와 실제 입력이 어긋날 수 있다.

빌드 산출물은 gitignore 대상이다. 위에 띄운 미리보기 두 장(`build/preview.png`,
`build/preview_qwerty.png`)만 예외로 커밋하고, 나머지 미리보기(`preview_states.png`,
`preview_kbd75*.png`)는 커밋하지 않는다. 미리보기는 테마를 설치했을 때 기기 화면에 가깝게 그리므로,
`qwerty_hacker.yml` 을 고쳤을 때도 다시 빌드하면 쿼티 미리보기가 갱신된다.
