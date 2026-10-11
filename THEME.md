# 딩굴 플릭 힌트 테마 (One Dark)

`dingul.yml` 의 flick 키에 상/하/좌/우로 입력되는 문자를 키 위에 표시하는 FUTO Keyboard 커스텀 테마.
색은 Atom One Dark 팔레트(`bg #282c34`, `fg #abb2bf`, 액센트 `blue #61afef`), 폰트는 Pretendard GOV.
모든 레이아웃의 기능키(Shift, Backspace, `?123` …)에는 배경을 깐다 ([아래](#기능키-배경)).

```
uv run tools/build_theme.py --layout custom0
```

`tools/build_theme.py` 는 [uv script](https://docs.astral.sh/uv/guides/scripts/) 라 의존성
(`PyYAML`, `Pillow`)이 파일 안에 선언되어 있다. 따로 설치할 게 없고 `uv` 만 있으면 된다.
폰트는 첫 실행 때 `assets/` 로 내려받는다 (13MB, gitignore 대상).

| 산출물 | 내용 |
|---|---|
| `dist/i.nesswit.DingulFlick.zip` | 폰으로 옮겨 임포트할 테마 (약 6.9MB — 대부분 폰트) |
| `build/preview.png` | 딩굴 미리보기. 설치했을 때 기기 화면처럼 그린다 |
| `build/preview_qwerty.png` | `qwerty_hacker.yml` 미리보기 (README 용) |
| `build/preview_states.png` | 기능키 상태 견본: 꺼짐 / 잠김 Shift, 눌린 Esc, 엔터 |
| `build/theme/` | zip 에 들어간 원본 파일들 (theme.txt, 딩굴 아이콘 15개, 기능키 배경 1개) |

빌드 산출물은 gitignore 대상이고, README 에 띄우는 미리보기 두 장만 예외로 커밋한다.
폰으로 옮길 zip 은 그때그때 빌드해서 쓴다.

미리보기는 **설치했을 때 기기에서 보일 모습**에 가깝게 그린다. 키 크기·간격·줄 높이, 액션 바,
배경 모양(기능키 배경, 스페이스바 알약, 엔터)은 1080x2400 에뮬레이터 스크린샷에서 잰 값이고
(`DEVICE_*` `KEY_GAP_*` `KB_*` `ACTION_BAR_*` 상수), 라벨·힌트의 크기와 위치는 `KeyboardView` 의
계산을 그대로 따른다. 기능키 아이콘(백스페이스, 엔터, 언어 전환, 시프트 …)만은 앱 리소스가 아니라
`icon_*()` 함수가 벡터로 흉내 낸 그림이다. 같은 입력이면 매번 같은 그림이 나온다.

`ImageDraw` 에는 안티앨리어싱이 없어서 선과 원이 계단처럼 나온다. 그래서 미리보기는 `SS`
배(기본 3배)로 그린 뒤 `save_downsampled()` 이 LANCZOS 로 줄인다. 좌표 상수도 전부 `SS` 가
곱해진 값이니, 미리보기 쪽 픽셀 값을 손볼 때는 실제 크기의 `SS` 배라는 점을 염두에 둘 것.

---

## 설치

1. `uv run tools/build_theme.py` 로 빌드한다.
2. `dist/i.nesswit.DingulFlick.zip` 을 폰으로 옮긴다.
3. FUTO Keyboard 설정 > Themes > 커스텀 테마 임포트에서 zip 을 고른다.
4. **레이아웃 이름이 맞아야 힌트가 보인다.** 아래 참고.

반복 테스트 중이라면 개발자 설정의 `DevAutoAcceptThemeImport` 를 켜서 임포트 확인 단계를 건너뛸 수 있다.

### 레이아웃 이름 (`custom0` / `custom1` / …)

선택자는 `layout <레이아웃세트이름> label <라벨>` 형태이고, 개발자 설정으로 추가한 커스텀 레이아웃은
**추가한 순서대로** `custom0`, `custom1`, … 이 된다 (`DevLayoutEditor.kt:95`).

이 저장소에는 레이아웃이 둘(`dingul.yml`, `qwerty_hacker.yml`) 있으므로 딩굴이 몇 번인지는 폰에서
확인해야 한다. 개발자 설정의 레이아웃 목록에서 딩굴이 위에서 몇 번째인지 세면 되고 (0부터), 딩굴이
두 번째면 이렇게 다시 빌드한다.

```
uv run tools/build_theme.py --layout custom1
```

확실치 않으면 후보를 여러 개 넣어도 된다. 다만 `.` `/` `?` 같은 라벨은 다른 커스텀 레이아웃에도
있을 수 있어서 엉뚱한 키에 아이콘이 붙을 수 있다.

```
uv run tools/build_theme.py --layout custom0 --layout custom1
```

힌트가 아예 안 보이면 레이아웃 이름이 틀린 것이다. 선택자가 잘못되면 그 항목만 조용히 무시되고
앱 내 BugViewer 에 기록되므로 (`decodeUtils.kt:46`) 거기부터 확인할 것.

---

## 왜 이렇게 구현했나

### 앱에는 방향별 문자 표시 기능이 없다

`KeyDrawingConfiguration` (`AdvancedThemeCustomizer.kt:24`) 이 가진 텍스트 슬롯은 `label` 1개와
`hintLabel` 1개(또는 `hintIcon`) 뿐이고, 힌트는 우상단 한 곳에만 그려진다. 그래서 방향 문자를 미리
그려 넣은 이미지를 키마다 씌우는 방식으로 우회한다.

> 참고로 앱은 이미 원하는 그림을 그릴 줄 안다. `KeyPreviewView.drawFlickKeys()`
> (`keyboard/internal/KeyPreviewView.java:95`) 가 키를 누를 때 뜨는 **프리뷰 팝업**에 방향 문자를
> `Direction.toVector()` 로 중앙 대비 0.33 지점에 배치해 그린다. 앱에 기능을 추가한다면 이 로직을
> `KeyboardView` 로 옮기는 게 가장 빠른 길이다. 테마 방식이 한계에 부딪히면 이쪽을 다시 볼 것.

### `keyIcons` 를 쓴다 (`keyBackgrounds` 아님)

키에 이미지를 씌우는 경로는 둘이다.

| | `keyBackgrounds` | `keyIcons` |
|---|---|---|
| 그려지는 영역 | 키 전체 (9-patch) | 중앙 정사각형 |
| 중앙 글자 | 엔진이 텍스트로 그림 | 이미지가 라벨을 대체 |
| 색 | 이미지 원본 색 유지 | `textColor` 단색 틴트 강제 |

`keyBackgrounds` 는 중앙 글자를 굽지 않아도 되는 대신 **9-patch stretch 구간이 늘어나면 그 구간에
걸친 그림도 같이 늘어난다.** 상하좌우 문자는 각 변의 중앙, 즉 보통 stretch 구간에 놓이므로 마커를
문자 사이 여백에 정확히 끼워 넣어야 하고 키 크기가 바뀔 때마다 결과가 달라진다. 아이콘은 정사각형
그대로 균일 축소되므로 그 문제가 없어서 이쪽을 택했다.

대신 아이콘 경로의 제약을 전부 전제로 설계했다.

- **가운데 글자도 이미지에 구워야 한다.** 아이콘이 매칭되면 앱이 라벨 텍스트를 그리지 않는다
  (`KeyboardView.java:465` 의 `if (label != null && icon == null)`).
- **단색 틴트가 강제된다** (`icon.setTint(textColor)`). 그래서 가운데 글자와 힌트의 농담 차이는
  색이 아니라 **알파**로 준다 (힌트 알파 165/255). 틴트는 SRC_IN 이라 알파가 보존된다.
- **정사각형이 강제된다** (`iconHeight = iconWidth`).
- 테마 폰트 설정이 아이콘에는 적용되지 않는다. 그래서 같은 폰트를 이미지에도 굽고 테마에도 넣는다.

### 테마 파일은 `theme.txt` (TOML) 여야 한다

`config.json` 도 스키마상 존재하지만, **임포트 경로에서 JSON 핸들러가 주석 처리되어 있다**
(`ZipThemes.kt:152`). JSON 만 든 zip 은 "Config not found" 로 임포트가 실패한다.
설치된 뒤 읽는 `loadFile` 만 JSON 을 처리한다. 그래서 이 빌더는 TOML 을 낸다.

zip 구조는 이렇다 (`ZipThemes.kt:80-125`).

```
theme.zip
├── FUTOKeyboardTheme_Version   # 9바이트: version(1B, 값 1) + epoch millis(8B, little-endian)
├── theme.txt                   # TOML. 맨 위에 `Format version: 1.0` 주석 필요
├── PretendardGOVVariable.ttf   # [options.font]
└── flick_r*c*.png              # matchrules.icon 이 참조하는 이미지들
```

- 설치된 커스텀 테마 위치: `context.filesDir/themes/<id>.zip`
- `id` 는 3자 이상이어야 하고 밑줄로 끝나면 안 된다
- 색상은 `#RGB` / `#RRGGBB` / `#RRGGBBAA` (TOML 은 RGBA 순서, `serialization/Common.kt:13`)

### 선택자 문법

`[[matchrules.icon]]` 의 `selector` 는 **공백으로 구분된 토큰 나열**이고 모든 토큰이 AND 조건이다.
파서는 `decodeUtils.kt:13` `decodeKeyedBitmapKey`, 매칭은 `KeyedBitmaps.kt:70` `matchesKey`.

| 토큰 | 인자 | 의미 |
|---|---|---|
| `label` | 문자열 | `key.label` 과 일치 |
| `code` | 정수 | 키 코드 |
| `outputtext` | 문자열 | 출력 문자열 |
| `icon` | 문자열 | 아이콘 ID |
| `layout` | 문자열 | 레이아웃 세트 이름 |
| `row` / `col` | 정수 | 행/열 위치 (음수는 뒤에서부터) |
| `rowmod` / `colmod` | 정수 2개 | `(row+a) % n == 0` |
| `ratio` | `Tallest`\|`Tall`\|`Squarish`\|`Wide`\|`ExtraWide`\|`Widest` | 키 종횡비 |
| `layer` | 정수 | 레이어 (아이콘은 0만) |
| `pressed` / `popup` / `morekeysbox` | 없음 | 상태·용도 |
| 스타일 키워드 | 없음 | `normal` `nobackground` `functional` `stickyoff` `stickyon` `action` `spacebar` `morekey` |

함정 세 가지.

- **공백으로 split** 하므로 라벨에 공백이 있으면 지목할 수 없다. 딩굴 레이아웃은 해당 없음.
  인자 쪽은 소문자로 바꾸지 않으므로 `\` `"` `'` 같은 라벨도 그대로 쓰면 된다. TOML 문자열 안에서는
  `\\` `\"` 로 이스케이프해야 하고, 빌더가 `json.dumps` 로 처리한다.
- `label` 은 `key.label` 과 비교한다. `primary: "ㅣ·|ㅣ"` 처럼 `라벨|코드` 형식이면 **라벨 부분만**
  매칭된다 → `label ㅣ·`. 빌더가 알아서 잘라낸다. 단 `|` 하나짜리 스펙은 앱이 라벨 `|` 로 읽는다
  (`KeySpecParser.java:102`).
- **아이콘 선택자는 힌트에도 매칭된다.** 앱은 같은 `[[matchrules.icon]]` 목록을 힌트 아이콘을 찾는
  데도 쓰고 (`AdvancedThemeCustomizer.kt:86`), 이때 `label` 은 키의 힌트 라벨과 비교한다
  (`KeyedBitmaps.kt` `matchesHint`). 즉 같은 레이아웃에 힌트가 `1` 인 키가 있으면 그 힌트가 `1` 키
  아이콘으로 바뀐다. 키 배경(`[[matchrules.border]]`)은 힌트와 비교하지 않는다.

같은 선택자가 둘 이상이면 **먼저 나온 항목만** 쓰인다 (`CachedKeyedMatcher.find`).

### 아이콘 크기 — 세로 여유가 전부다

앱의 아이콘 크기 계산은 이렇다 (`KeyboardView.java:596`).

```java
iconWidth = Math.min(icon.getIntrinsicWidth(), keyWidth);
if (iconWidth > kdc.getTextSize() * 1.75f) iconWidth = (int)(kdc.getTextSize() * 1.75f);
iconHeight = iconWidth;   // 정사각형
```

`textSize` 를 계산할 때 쓰는 키 높이는 `min(keyH, keyW)` 이고 (`KeyboardView.java:391`), 폰에서
letter ratio 는 66% 다 (`res/values/config.xml:51`). 정확히는 키마다가 아니라 **키보드에서 가장 흔한
키 크기**의 `min` 이다. v2 레이아웃 키에는 `visualAttributes` 가 없어서 키별 값으로 바뀌지 않는다
(`KeyboardView.java:210-214`, `LayoutEngine.kt:818`). 딩굴은 키가 다 같아서 차이가 없다. 4열짜리 딩굴 레이아웃은 키가 세로보다 가로로
기니까 결국:

```
아이콘 한 변 = 1.75 x 0.66 x scale_text x 키높이 = 1.155 x scale_text x 키높이
```

즉 **아이콘이 키보다 세로로 크다.** `KeyboardView` 는 키 단위로 clip 하지 않으므로 넘치는 부분은
옆 줄로 삐져나가 가려진다. 결과적으로:

- **세로로 쓸 수 있는 공간은 언제나 키 높이 하나뿐이다.** 여기에 ↑힌트 + 가운데 글자 + ↓힌트가
  다 들어가야 하고, `scale_text` 를 올려도 늘지 않는다. 원본 딩굴 앱도 사정은 같아서 가운데 글자가
  일반 라벨보다 작다.
- **`scale_text` 로 늘어나는 건 가로 폭뿐이고, 그게 좌우 힌트를 벌리는 유일한 수단이다.**

그래서 빌더는 글자 크기와 세로 위치를 전부 **키 높이 단위**로 정의해 `scale_text` 와 무관하게
고정하고 (`CENTER_INK_H_KEY` 등), 좌우 힌트만 아이콘 가장자리에 붙여 아이콘이 커진 만큼 벌어지게
한다 (`HINT_LEFT_X`).

아이콘 PNG 는 768px 로 크게 만든다. 그래야 `min(intrinsicWidth, ...)` 가 아니라 항상
`1.75 * textSize` 쪽이 걸려서, 기기 밀도와 무관하게 위 계산대로 크기가 결정된다.

### `scale_text` 상한

실기기 실측 기준 키 폭 230 / 행 높이 122 (비율 1.89) 이므로, 아이콘이 키 폭에 닿는 건 1.63 배다.
빌더가 이 조건을 `assert` 로 잡는다.

하지만 실제로는 **기본값 1.0 을 쓴다.** 이유는 딩굴 레이아웃 바깥에 있다.

**테마는 전역이라 `scale_text` 가 모든 레이아웃의 글자를 키운다.** 그리고 텍스트 크기 계산에 쓰는
값은 `min(keyH, keyW)` 다 (`KeyboardView.java:391`). 10열짜리 qwerty 는 키가 가로로 좁아서
(실측 폭 93 / 높이 118) `min` 이 **키 폭**으로 잡히고, 그래서 글자가 키 폭에 직접 비례해 커진다.

```
qwerty 글자 크기 = 0.66 x 93 x scale_text
    scale_text 1.0  -> 62px   (현재. 앱 기본과 같다)
    scale_text 1.15 -> 71px   (실기기 확인 결과 너무 컸다)
    scale_text 1.4  -> 86px   (힌트 첨자와 부딪힌다)
```

4열짜리 딩굴은 `min` 이 키 높이로 잡혀서 여유가 있지만 qwerty 는 그렇지 않다. 즉 **딩굴의 좌우
힌트 간격과 qwerty 의 글자 크기가 같은 노브를 공유하고, 둘 다 만족시킬 수 없다.** 아이콘 크기를
키우는 다른 방법은 없다 — `iconWidth = min(intrinsic, keyWidth, 1.75 * textSize)` 라서 이미지를
크게 만들어도 상한만 걸릴 뿐이고, 1.75 는 하드코딩이다.

qwerty 를 기본 크기로 두는 쪽을 택했다. 딩굴 아이콘은 키 폭의 61% 를 쓴다 (1.15 였다면 70%).

`?123` `ㅋㅋㅋ` 같은 아래 줄 라벨도 `scale_text` 를 따라가므로 미리보기가 `MAX_LABEL_RATIO`(0.9)
기준으로 넘치는지 검사해 경고한다. 다만 폰트를 바꾸면 이 기준(`PREVIEW_BOTTOM_INK_H`)도 다시
재야 한다 — Pretendard 로 바꾼 뒤 `ㅋㅋㅋ` 는 오히려 좁아졌다.

### 조정할 수 있는 값

전부 `tools/build_theme.py` 상단 상수다.

| 상수 | 용도 |
|---|---|
| `SCALE_TEXT` | 좌우 힌트 간격. 올리면 qwerty 글자도 같이 커진다. 위 참고 |
| `CENTER_INK_H_KEY` / `HINT_INK_H_KEY` | `ㅁ` 기준 글자 크기 (키 높이 대비) |
| `CENTER_MAX_*_KEY` / `HINT_MAX_*_KEY` | `ㅚ` `ㅡ‖` 처럼 유난히 큰 글자를 줄이는 상한 |
| `HINT_UP_Y_KEY` / `HINT_LEFT_X` | 힌트 위치 |
| `KEY_MARGIN` | 키 위아래 여백 |
| `HINT_ALPHA` | 힌트 농도 (틴트가 단색이라 농담은 알파로만 준다) |
| `FONT_URL` / `FONT_WEIGHT` | 폰트와 가변축 weight (45~930) |
| `COLORS` | 44개 색 전부. One Dark 팔레트가 들어 있다 |
| `FUNC_BG_TINT` | 기능키 배경색 (팔레트 이름). [아래](#기능키-배경) 참고 |
| `DEVICE_*` / `KEY_GAP_*` / `KB_*` / `ACTION_BAR_*` | 기기 실측값. 미리보기 크기가 여기서 나온다 |
| `KEY_*_RATIO` / `KEY_HINT_PADDING_DP` / `*_RADIUS_DP` | 앱 기본 테마의 글자 비율, 힌트 여백, 키 모서리 |

빌더는 글자가 안전 영역을 벗어나거나 가운데 글자와 겹치면 경고를 낸다. 경고 없이 끝나면 잘린
글자는 없다. 색을 바꿨다면 `check_contrast()` 가 앱과 같은 기준(`Toml.kt:248`, 색 쌍 8개의 휘도차
0.08 이상)으로 검사해서 통과 못 하면 zip 을 만들지 않고 멈춘다.

`auto_borders = false` 라 글자 키에는 배경이 안 깔린다. 기능키 배경은 이 옵션과 따로 테마가 깐다
([아래](#기능키-배경)). 모든 키에 배경을 원하면 `true` 로 바꾸면 되지만, 그러면 앱 기본 배경과
겹친다.

`--no-embed-font` 로 폰트를 빼면 zip 이 100KB 아래로 줄지만, `?123` 같은 라벨이 기기 기본 폰트로
그려져서 이미지에 구워진 가운데 글자와 서체가 어긋난다.

---

## 기능키 배경

`auto_borders = false` 이면 앱은 기능키(Functional 스타일: Shift, Backspace, 언어 전환,
`?123` …)에 배경을 그리지 않는다 (`BasicThemeProvider.kt:341`). 글자 키와
구분이 안 돼서, 테마가 `[[matchrules.border]]` 로 둥근 사각형을 깐다.

```toml
[[matchrules.border]]
selector = "layer -1 functional"      # 같은 규칙이 stickyoff 에도 하나 더 있다
asset = "func_bg.png"

[[asset.border]]
name = "func_bg.png"                  # 96px 흰 둥근 사각형, 모서리 36px (= 9dp @ 640dpi)
target_density = 640
background_tint = "keyboard_container"  # #3a3f4b. 흰 이미지에 MULTIPLY 로 색을 입힌다
foreground_tint = "#00000000"         # 이 레이어에서는 글자를 그리지 않는다
padding = [0.0, 0.0, 1.0, 1.0]        # 여백 없음 (오른쪽/아래는 1.0 이 0 이다, Toml.kt:385-386)
slicing = [0.4, 0.4, 0.6, 0.6]        # 모서리는 늘리지 않는다
```

**레이어 -1 에 두는 게 핵심이다.** 레이어 0 에 테마 배경이 걸리면 앱은 키의 기본 배경 대신 그걸
쓰므로 (`AdvancedThemeCustomizer.kt:145`) 누를 때의 하이라이트(`Key.kt:367` `selectBackground`)가
사라진다. 레이어는 오름차순으로 그려지므로 (`KeyboardView.java:325`) 레이어 -1 에 깔면 그 위에
레이어 0 의 앱 기본 배경이 덮인다.

| 상태 | 앱이 그리는 방식 | 이 테마에서 보이는 모습 |
|---|---|---|
| 꺼짐 (Shift 는 한 번 누른 상태도) | Functional 스타일 (배경 투명) | 레이어 -1 의 `keyboard_container` (#3a3f4b) + 글자 `#abb2bf` |
| 눌림 | Functional 의 눌림 배경 (`BasicThemeProvider.kt:256`) | `keyboard_container_pressed` (#4b5263) + 밝은 글자 `#e6e9ef` |
| Shift 잠김 | StickyOn 스타일 (`BasicThemeProvider.kt:513`) | `secondary` 보라 (#c678dd) + 어두운 글자 `#21252b` |

Shift 는 꺼짐/한 번이 Functional, 잠김이 StickyOn 이다 (`TemplateKeys.kt:44-76`). 스타일 키워드는
`key.visualStyle` 과 비교하므로 (`KeyedBitmaps.kt:63`) 잠긴 Shift 에는 `functional` 규칙이 걸리지 않고
앱 기본 StickyOn 배경이 그대로 보인다. 일반 키를 누를 때의 하이라이트와 엔터(Action, `primary` 알약), 스페이스바(`keyboard_container_pressed` 알약,
48dp)는 앱 기본 그대로다. `build/preview_states.png` 가 이 상태들을 그린 견본이다.

색은 팔레트 값을 그대로 쓰므로 `COLORS` 를 바꿨다면 대비 검사(`check_contrast()`)만 다시 통과하면
된다. 이번 변경에서 팔레트는 바꾸지 않았다.

---

## 한계

1. **레이아웃과 자동 동기화되지 않는다.** `dingul.yml` 을 고쳤으면 이 스크립트를 다시 돌려야
   표시와 실제 입력이 맞는다. 커밋 전에 습관적으로 한 번 돌리는 편이 안전하다.
2. **테마에 종속된다.** 다른 테마로 바꾸면 힌트가 통째로 사라진다.
3. **레이아웃 이름에 종속된다.** 커스텀 레이아웃을 추가/삭제해서 순서가 바뀌면 다시 빌드해야 한다.
4. **다른 사용자나 일본어 플릭 자판은 혜택을 못 받는다.** 앱 기능으로 만들 경우와의 차이.

---

## 참고 코드 위치

조사 기준: `futo-org/android-keyboard` master (`94aea3d4a`).

| 내용 | 위치 |
|---|---|
| 선택자 파서 | `latin/uix/theme/decodeUtils.kt:13` |
| 선택자 매칭 로직 | `latin/uix/theme/KeyedBitmaps.kt:70` `matchesKey` |
| 테마 옵션 스키마 | `latin/uix/theme/AdvancedThemeOptions.kt` |
| 키 그리기 설정 조립 | `latin/uix/theme/AdvancedThemeCustomizer.kt:123` |
| 실제 키 렌더링 | `keyboard/KeyboardView.java:443` `onDrawKeyTopVisuals` |
| 힌트 위치 (우상단) | `keyboard/KeyboardView.java:556` |
| 글자/힌트 비율 | `res/values/config.xml:51-64`, `res/values/themes-lxx.xml:32` |
| 힌트 아이콘 매칭 | `latin/uix/theme/AdvancedThemeCustomizer.kt:86`, `KeyedBitmaps.kt` `matchesHint` |
| 라벨 파싱 (세로 막대 단독) | `keyboard/internal/KeySpecParser.java:98` |
| 키 배경 디코딩 (border 자산) | `latin/uix/theme/serialization/Toml.kt:151`, `:175`, `:364` |
| 9-patch 생성 / 틴트 | `latin/uix/utils/NinePatchBuilder.kt:154`, `:140` |
| 레이어별 그리기 | `keyboard/KeyboardView.java:317-330`, `AdvancedThemeCustomizer.kt:123` |
| 기본 키 스타일 (auto_borders) | `latin/uix/BasicThemeProvider.kt:341`, `:434-535` |
| 키 기본 배경 선택 (눌림 포함) | `keyboard/Key.kt:367` `selectBackground` |
| Shift 템플릿 키 (잠김 = StickyOn) | `v2keyboard/TemplateKeys.kt:44-76` |
| 아이콘 크기 계산 | `keyboard/KeyboardView.java:596` |
| zip 테마 저장/로드/임포트 | `latin/uix/theme/ZipThemes.kt` |
| TOML 테마 스키마 / 검증 | `latin/uix/theme/serialization/Toml.kt:55`, `:248` |
| JSON 테마 스키마 | `latin/uix/theme/serialization/Json.kt:149` |
| 커스텀 레이아웃 이름 | `latin/uix/settings/pages/DevLayoutEditor.kt:95` |
| flick 키 정의 | `v2keyboard/FlickKey.kt` |
| 레이아웃 문서 | `java/assets/layouts/LayoutSpec.md` |
| 테마 문서 / 에디터 | https://docs.keyboard.futo.tech/theme/advanced · https://keyboard.futo.tech/theme-editor |
