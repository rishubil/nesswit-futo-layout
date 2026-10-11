#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML>=6.0", "Pillow>=10.0"]
# ///
"""dingul.yml 용 FUTO Keyboard 테마 빌더.

딩굴 flick 키의 상/하/좌/우 문자를 키 아이콘(``[[matchrules.icon]]``)으로 구워서
키 위에 표시하고, 모든 레이아웃의 기능키에 배경을 깐다(``[[matchrules.border]]``,
레이어 -1). 레이아웃 yaml 이 진실의 원천이므로, yaml 을 고치고 이 스크립트를
다시 돌리면 표시도 같이 갱신된다.

  uv run tools/build_theme.py --layout custom0

산출물:
  build/theme/           테마 zip 에 들어가는 원본 파일들
  dist/<id>.zip          FUTO Keyboard 로 임포트할 테마
  build/preview.png          딩굴 미리보기 (기기 화면 흉내)
  build/preview_qwerty.png   qwerty_hacker.yml 미리보기
  build/preview_states.png   기능키 상태 견본 (꺼짐 / 눌림 / Shift 잠김)

앱 동작 근거 (futo-org/android-keyboard master):
  keyboard/KeyboardView.java:465    icon 이 있으면 label 을 그리지 않는다
  keyboard/KeyboardView.java:596    iconW = min(intrinsicW, keyW), 1.75*textSize 로 clamp
  keyboard/KeyboardView.java:606    iconH = iconW  (정사각형 강제)
  keyboard/KeyboardView.java:622    icon.setTint(textColor)  (단색 틴트 강제)
  keyboard/KeyboardView.java:391    textSize 계산에 쓰는 keyHeight 는 min(keyH, keyW)
  res/values/config.xml:51          config_key_letter_ratio_lxx = 66%
  latin/uix/theme/serialization/Toml.kt:402   keyIcons 디코딩
  latin/uix/theme/decodeUtils.kt:13           선택자 파서
  latin/uix/theme/ZipThemes.kt:152            임포트는 theme.txt(TOML)만 읽는다
"""

from __future__ import annotations

import argparse
import io
import json
import struct
import sys
import time
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# 테마 메타데이터
# --------------------------------------------------------------------------

THEME_ID = "i.nesswit.DingulFlick"
THEME_NAME = "딩굴 플릭 힌트 (One Dark)"
THEME_AUTHOR = "nesswit"
THEME_VERSION = 4
THEME_DESCRIPTION = (
    "딩굴 레이아웃 전용 테마. flick 키의 상/하/좌/우 입력 문자를 "
    "키 아이콘으로 구워서 키 위에 표시한다. 기능키에는 배경을 깐다. 색은 Atom One Dark."
)

# --------------------------------------------------------------------------
# 아이콘 기하 구조
#
# 앱은 아이콘을 한 변이 min(keyW, 1.75 * 0.66 * scale_text * min(keyW, keyH)) 인
# 정사각형으로 그린다. 4열짜리 딩굴 레이아웃의 키는 세로보다 가로가 기니까 결국
#
#     아이콘 한 변 = 1.155 * scale_text * 키 높이
#
# 이 되어 아이콘이 키보다 세로로 크다. 넘치는 부분은 키 밖으로 삐져나가고
# (KeyboardView 는 키 단위로 clip 하지 않는다) 실기기에서는 옆 줄에 가려진다.
# 즉 **세로로 쓸 수 있는 공간은 언제나 키 높이 하나뿐**이라 scale_text 를 올려도
# 늘지 않는다. 늘어나는 건 가로 폭뿐이고, 그게 좌우 힌트를 벌리는 유일한 수단이다.
#
# 그래서 글자 크기와 세로 위치는 전부 "키 높이" 단위로 정의하고 (scale_text 와
# 무관하게 고정), 좌우 힌트만 아이콘 가장자리에 붙여서 아이콘이 커진 만큼
# 벌어지게 한다.
# --------------------------------------------------------------------------

CANVAS = 768  # 아이콘 PNG 한 변 (px). 앱이 항상 축소하도록 넉넉하게 잡는다.

# theme.txt 의 options.scale_text. 좌우 힌트 간격을 정하는 유일한 수단이다.
#
# 아이콘이 키 폭에 닿는 1.63 이 이론상 상한이지만, 실제로는 1.0 = 기본값을 쓴다.
#
# 테마는 전역이라 이 값이 모든 레이아웃의 글자를 키운다. 그리고 텍스트 크기는
# min(keyH, keyW) 기준이라 (KeyboardView.java:391) 10열짜리 qwerty 는 키가 좁아서
# (폭 93 / 높이 118) min 이 키 폭으로 잡히고, 글자가 키 폭에 직접 비례해 커진다.
# 1.15 를 실기기에서 확인해 보니 qwerty 글자가 너무 컸다.
#
# 즉 딩굴의 좌우 힌트 간격과 qwerty 의 글자 크기는 같은 노브를 공유하고, 둘 다
# 만족시킬 수 없다. qwerty 를 기본 크기로 두는 쪽을 택했다. 자세한 건 THEME.md 참고.
SCALE_TEXT = 1.0

# 실기기 실측 (키 폭 230 / 행 높이 122). 아이콘이 이 비율을 넘으면 키 폭 쪽에
# 먼저 걸려서 (min(intrinsicWidth, keyWidth)) 아래 계산이 전부 틀어진다.
KEY_ASPECT = 1.89

ICON_PER_KEY_H = 1.75 * 0.66 * SCALE_TEXT  # 아이콘 한 변 / 키 높이
assert ICON_PER_KEY_H < KEY_ASPECT, (
    f"scale_text={SCALE_TEXT} 는 너무 크다. 아이콘 한 변이 키 높이의 "
    f"{ICON_PER_KEY_H:.2f}배가 되어 키 폭({KEY_ASPECT}배)을 넘는다. "
    f"상한은 {KEY_ASPECT / (1.75 * 0.66):.2f}."
)

VISIBLE_V = 1.0 / ICON_PER_KEY_H  # 키 안에 실제로 보이는 세로 비율


def key_h(v: float) -> float:
    """키 높이 단위를 아이콘 비율로 바꾼다."""
    return v / ICON_PER_KEY_H


def key_y(v: float) -> float:
    """키 위쪽 기준 세로 위치를 아이콘 비율로 바꾼다."""
    return 0.5 - key_h(0.5 - v)


# --- 키 높이 기준 (scale_text 를 바꿔도 절대 크기가 유지된다) ---
CENTER_INK_H_KEY = 0.347  # "ㅁ" 기준 가운데 글자 잉크 높이
HINT_INK_H_KEY = 0.156  # "ㅁ" 기준 힌트 글자 잉크 높이
HINT_UP_Y_KEY = 0.154  # ↑ 힌트 잉크 중심 위치
KEY_MARGIN = 0.045  # 키 위아래 여백

# 글자 크기는 "ㅁ" 기준으로 잡지만 실제 잉크 크기는 글자마다 다르다. ㅚ ㅞ 처럼
# 세로로 긴 글자나 ㅣ· ㅡ‖ 처럼 두 글자짜리 라벨은 기준보다 훨씬 크게 그려져서
# 옆/위아래 글자를 침범한다. 그런 글자만 폰트를 줄여 상자 안에 맞춘다.
CENTER_MAX_W_KEY, CENTER_MAX_H_KEY = 0.508, 0.381
HINT_MAX_W_KEY, HINT_MAX_H_KEY = 0.254, 0.214

# --- 위에서 유도한 아이콘 비율 ---
CENTER_Y = 0.500
HINT_UP_Y = key_y(HINT_UP_Y_KEY)
HINT_DOWN_Y = 1.0 - HINT_UP_Y
CENTER_INK_H = key_h(CENTER_INK_H_KEY)
HINT_INK_H = key_h(HINT_INK_H_KEY)
CENTER_MAX_W, CENTER_MAX_H = key_h(CENTER_MAX_W_KEY), key_h(CENTER_MAX_H_KEY)
HINT_MAX_W, HINT_MAX_H = key_h(HINT_MAX_W_KEY), key_h(HINT_MAX_H_KEY)

# 좌우 힌트만 아이콘 가장자리 기준이다. scale_text 를 올리면 여기가 벌어진다.
HINT_LEFT_X = 0.065
HINT_RIGHT_X = 1.0 - HINT_LEFT_X

# 글자를 밀어 넣는 안전 영역. 세로는 키 밖으로 잘리는 부분에 더해 키 위아래
# 여백까지 확보하고, 가로는 아이콘 경계를 피한다. ㅚ 나 ㅋ 처럼 기준 글자보다
# 크게 그려지는 글자만 안쪽으로 밀리고, 작은 글자는 원래 자리에 남는다.
SAFE_TOP = key_y(KEY_MARGIN)
SAFE_BOTTOM = 1.0 - SAFE_TOP
SAFE_LEFT = 0.015
SAFE_RIGHT = 1.0 - SAFE_LEFT

CENTER_ALPHA = 255
# 틴트가 단색으로 강제되므로 농담은 알파로만 준다. 어두운 배경에서는 알파를
# 낮출수록 배경과의 대비가 빨리 죽어서, 밝은 테마보다 조금 높게 잡는다.
HINT_ALPHA = 165

# 아이콘을 그리는 폰트. 같은 파일을 테마에도 넣어서 (`[options.font]`) 앱이
# 텍스트로 그리는 나머지 라벨까지 같은 폰트를 쓰게 한다. 그래야 이미지에 구워진
# 가운데 글자와 `?123` 같은 라벨의 서체가 어긋나지 않는다.
#
# 13MB 라 저장소에 넣지 않고 없으면 받아온다 (assets/ 는 gitignore).
FONT_URL = (
    "https://github.com/orioncactus/pretendard/raw/refs/heads/main"
    "/packages/pretendard-gov/dist/public/variable/PretendardGOVVariable.ttf"
)
FONT_PATH = REPO / "assets" / "PretendardGOVVariable.ttf"
FONT_WEIGHT = 400.0  # 가변 폰트 wght 축 (45~930). Regular.
REF_GLYPH = "ㅁ"  # 폰트 크기 보정 기준 글자

# --------------------------------------------------------------------------
# 색상 (44개 전부 필수) — Atom One Dark
#
#   bg #282c34   bg-dark #21252b   bg-light #2c313a   gutter #4b5263
#   fg #abb2bf   comment #5c6370   blue #61afef   purple #c678dd
#   cyan #56b6c2   green #98c379   red #e06c75   orange #d19a66
# --------------------------------------------------------------------------

COLORS: dict[str, str] = {
    "primary": "#61afef",
    "on_primary": "#21252b",
    "primary_container": "#2f4f6b",
    "on_primary_container": "#cfe6fb",
    "inverse_primary": "#3a6ea5",
    "secondary": "#c678dd",
    "on_secondary": "#21252b",
    "secondary_container": "#4a3352",
    "on_secondary_container": "#eed4f5",
    "tertiary": "#56b6c2",
    "on_tertiary": "#21252b",
    "tertiary_container": "#2c4c51",
    "on_tertiary_container": "#cdeef2",
    "background": "#282c34",
    "on_background": "#abb2bf",
    "surface": "#282c34",
    "on_surface": "#abb2bf",
    "surface_variant": "#3a3f4b",
    "on_surface_variant": "#9099a8",
    "surface_tint": "#61afef",
    "inverse_surface": "#abb2bf",
    "inverse_on_surface": "#282c34",
    "error": "#e06c75",
    "on_error": "#21252b",
    "error_container": "#5c2c31",
    "on_error_container": "#fbd5d8",
    "outline": "#5c6370",
    "outline_variant": "#3e4451",
    "scrim": "#000000",
    "surface_bright": "#3a3f4b",
    "surface_dim": "#1c1f24",
    "surface_container": "#2c313a",
    "surface_container_high": "#333842",
    "surface_container_highest": "#3a3f4b",
    "surface_container_low": "#24272e",
    "surface_container_lowest": "#1c1f24",
    "keyboard_surface": "#282c34",
    "keyboard_surface_dim": "#21252b",
    "keyboard_container": "#3a3f4b",
    "keyboard_container_variant": "#323842",
    "on_keyboard_container": "#abb2bf",
    "keyboard_press": "#4b5263",
    "keyboard_container_pressed": "#4b5263",
    "on_keyboard_container_pressed": "#e6e9ef",
}

# Toml.kt:248 validate() 가 검사하는 색 쌍. 대비가 0.08 미만이면 임포트가 거부된다.
CONTRAST_PAIRS = [
    ("primary", "on_primary"),
    ("secondary", "on_secondary"),
    ("tertiary", "on_tertiary"),
    ("background", "on_background"),
    ("surface", "on_surface"),
    ("primary_container", "on_primary_container"),
    ("secondary_container", "on_secondary_container"),
    ("tertiary_container", "on_tertiary_container"),
]

OPTIONS = {
    "auto_borders": False,
    "center_hints": False,
    "roundedness": 1.0,
    "scale_text": SCALE_TEXT,
    "scale_hints": 1.0,
    "weight_text": 400.0,
    "weight_hints": 500.0,
}

HEADER = """\
# -------------------------------------------------------------------
#                  FUTO Keyboard Theme Configuration
#                        Format version: 1.0
#
# 이 파일은 tools/build_theme.py 가 dingul.yml 에서 생성한다.
# 직접 고치지 말고 yaml 을 고친 뒤 스크립트를 다시 돌릴 것.
#                      https://docs.keyboard.futo.tech/theme/advanced
# -------------------------------------------------------------------\
"""


# --------------------------------------------------------------------------
# dingul.yml 파싱
# --------------------------------------------------------------------------


@dataclass
class FlickKeyInfo:
    label: str  # 선택자에 쓸 key.label
    center: str  # 가운데에 그릴 글자
    directions: dict[str, str] = field(default_factory=dict)  # up/down/left/right
    row: int = 0
    col: int = 0

    @property
    def asset_name(self) -> str:
        # 라벨에 파일명으로 못 쓰는 문자가 섞여 있으므로 위치로 이름을 만든다.
        return f"flick_r{self.row}c{self.col}.png"


def spec_label(spec) -> str:
    """키 스펙에서 라벨 부분만 뽑는다. `라벨|코드` 형식이면 앞부분."""
    text = str(spec)
    # KeySpecParser 와 동일하게 이스케이프되지 않은 첫 `|` 에서 자른다.
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            out.append(text[i + 1])
            i += 2
            continue
        if c == "|":
            break
        out.append(c)
        i += 1
    return "".join(out)


def load_flick_keys(yml_path: Path) -> list[FlickKeyInfo]:
    doc = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
    keys: list[FlickKeyInfo] = []
    for row_index, row in enumerate(doc["rows"]):
        entries = row.get("letters") or row.get("bottom") or []
        for col_index, entry in enumerate(entries):
            if not isinstance(entry, dict) or entry.get("type") != "flick":
                continue
            label = spec_label(entry["primary"])
            directions = {}
            for name in ("up", "left", "down", "right"):
                if entry.get(name) is not None:
                    directions[name] = spec_label(entry[name])
            keys.append(
                FlickKeyInfo(
                    label=label,
                    center=label,
                    directions=directions,
                    row=row_index,
                    col=col_index,
                )
            )
    return keys


# --------------------------------------------------------------------------
# 아이콘 렌더링
# --------------------------------------------------------------------------


def ensure_font() -> None:
    if FONT_PATH.is_file():
        return
    FONT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"폰트 내려받는 중: {FONT_URL}", file=sys.stderr)
    urllib.request.urlretrieve(FONT_URL, FONT_PATH)


def make_font(size: int, weight: float = FONT_WEIGHT) -> ImageFont.FreeTypeFont:
    """가변 폰트를 weight 인스턴스로 고정해서 연다 (기본값 FONT_WEIGHT)."""
    font = ImageFont.truetype(FONT_PATH, size)
    font.set_variation_by_axes([weight])
    return font


def calibrated_font(target_ink_h: float) -> ImageFont.FreeTypeFont:
    """REF_GLYPH 의 잉크 높이가 target_ink_h 픽셀이 되는 폰트를 만든다."""
    probe_size = 200
    probe = make_font(probe_size)
    _, y0, _, y1 = probe.getbbox(REF_GLYPH)
    ink_h = y1 - y0
    return make_font(max(1, round(probe_size * target_ink_h / ink_h)))


def fit_font(
    text: str, font: ImageFont.FreeTypeFont, max_w: float, max_h: float
) -> ImageFont.FreeTypeFont:
    """잉크 상자가 max_w x max_h 안에 들어올 때까지 폰트를 줄인다 (키우지는 않는다)."""
    x0, y0, x1, y1 = font.getbbox(text)
    w, h = x1 - x0, y1 - y0
    if w <= max_w and h <= max_h:
        return font
    ratio = min(max_w / w if w else 1.0, max_h / h if h else 1.0)
    return make_font(max(1, int(font.size * ratio)))


def draw_ink_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    cx: float,
    cy: float,
    alpha: int,
) -> tuple[float, float, float, float]:
    """글자의 잉크 상자 중심을 (cx, cy) 에 맞춘 뒤 안전 영역 안으로 밀어 넣는다.

    폰트 메트릭이 아니라 잉크 기준으로 맞춰야 `_` `^` `,` 같은 글자도
    자기 자리에 시각적으로 중앙 정렬된다.
    """
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font, anchor="la")
    ox = cx - (x0 + x1) / 2
    oy = cy - (y0 + y1) / 2

    box = [x0 + ox, y0 + oy, x1 + ox, y1 + oy]
    for lo, hi, i0, i1, off in (
        (CANVAS * SAFE_LEFT, CANVAS * SAFE_RIGHT, 0, 2, "x"),
        (CANVAS * SAFE_TOP, CANVAS * SAFE_BOTTOM, 1, 3, "y"),
    ):
        shift = 0.0
        if box[i0] < lo:
            shift = lo - box[i0]
        elif box[i1] > hi:
            shift = hi - box[i1]
        if shift:
            box[i0] += shift
            box[i1] += shift
            if off == "x":
                ox += shift
            else:
                oy += shift

    draw.text((ox, oy), text, font=font, anchor="la", fill=(255, 255, 255, alpha))
    return tuple(box)


def render_icon(key: FlickKeyInfo, center_font, hint_font) -> tuple[Image.Image, list[str]]:
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    warnings: list[str] = []

    center_box = draw_ink_centered(
        draw,
        key.center,
        fit_font(key.center, center_font, CANVAS * CENTER_MAX_W, CANVAS * CENTER_MAX_H),
        CANVAS * 0.5,
        CANVAS * CENTER_Y,
        CENTER_ALPHA,
    )

    anchors = {
        "up": (0.5, HINT_UP_Y),
        "down": (0.5, HINT_DOWN_Y),
        "left": (HINT_LEFT_X, 0.5),
        "right": (HINT_RIGHT_X, 0.5),
    }
    gap = CANVAS * 0.02
    for name, text in key.directions.items():
        fx, fy = anchors[name]
        box = draw_ink_centered(
            draw,
            text,
            fit_font(text, hint_font, CANVAS * HINT_MAX_W, CANVAS * HINT_MAX_H),
            CANVAS * fx,
            CANVAS * fy,
            HINT_ALPHA,
        )
        # 가운데 글자와 힌트가 겹치면 눈에 띄게 지저분해지므로 잡아낸다.
        overlaps = (
            box[0] < center_box[2] + gap
            and box[2] > center_box[0] - gap
            and box[1] < center_box[3] + gap
            and box[3] > center_box[1] - gap
        )
        if overlaps:
            warnings.append(f"{key.label}: {name} 힌트 {text!r} 가 가운데 글자와 너무 가깝다")
    return img, warnings


# --------------------------------------------------------------------------
# theme.txt (TOML)
# --------------------------------------------------------------------------


def srgb_luminance(hex_color: str) -> float:
    """Compose 의 Color.luminance() 와 같은 WCAG 상대 휘도."""
    h = hex_color.lstrip("#")
    parts = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in parts)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def check_contrast() -> list[str]:
    problems = []
    for bg, fg in CONTRAST_PAIRS:
        d = abs(srgb_luminance(COLORS[bg]) - srgb_luminance(COLORS[fg]))
        if d < 0.08:
            problems.append(f"{bg}:{fg} 대비 부족 ({d:.3f} < 0.08)")
    return problems


def toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}" if value != int(value) else f"{int(value)}"
    if isinstance(value, int):
        return str(value)
    return toml_str(value)


def build_theme_txt(
    icon_rules: list[tuple[tuple[str, ...], str]],
    icon_assets: list[str],
    border_rules: list[tuple[tuple[str, ...], str]],
    border_assets: list["BorderAsset"],
    embed_font: bool,
) -> str:
    """theme.txt 를 만든다. 규칙은 (선택자 토큰, 자산 이름) 목록이고 앞의 것이 우선이다."""
    out: list[str] = [HEADER, ""]
    out.append(f"name = {toml_str(THEME_NAME)}")
    out.append(f"author = {toml_str(THEME_AUTHOR)}")
    out.append(f"id = {toml_str(THEME_ID)}")
    out.append(f"version = {THEME_VERSION}")
    out.append(f"description = {toml_str(THEME_DESCRIPTION)}")

    out += ["", "[options]"]
    for k, v in OPTIONS.items():
        out.append(f"{k} = {toml_value(v)}")

    out += ["", "[colors]"]
    for k, v in COLORS.items():
        out.append(f"{k} = {toml_str(v)}")

    if embed_font:
        out += ["", "[options.font]", f"font = {toml_str(FONT_PATH.name)}"]

    out += [
        "",
        "# -------------------------------------------------------------------",
        "# 선택자는 공백으로 나뉜 토큰의 AND 조건이다 (decodeUtils.kt:13).",
        "# `layout` 값은 keyboard.mId.mKeyboardLayoutSetName 이고, 개발자 설정으로",
        "# 추가한 커스텀 레이아웃은 추가 순서대로 custom0, custom1, ... 이 된다",
        "# (DevLayoutEditor.kt:95). --layout 으로 맞춰 다시 빌드할 것.",
        "# 같은 키에 걸리는 규칙이 여럿이면 먼저 나온 것만 쓰인다.",
        "# -------------------------------------------------------------------",
        "",
        "# 딩굴 flick 키: 방향 문자를 구운 아이콘",
    ]
    for tokens, asset in icon_rules:
        out += [
            "",
            "[[matchrules.icon]]",
            f"selector = {toml_str(' '.join(tokens))}",
            f"asset = {toml_str(asset)}",
        ]

    out += [
        "",
        "# 키 배경. layer -1 은 앱 기본 배경 아래에 그려진다 (기능키 배경). 레이어 0 은",
        "# 앱 기본 스타일 그대로라 눌림, Shift 잠김 표시가 살아 있다.",
    ]
    for tokens, asset in border_rules:
        out += [
            "",
            "[[matchrules.border]]",
            f"selector = {toml_str(' '.join(tokens))}",
            f"asset = {toml_str(asset)}",
        ]

    out += [
        "",
        "# -------------------------------------------------------------------",
        "# 자산 목록",
        "# -------------------------------------------------------------------",
    ]
    for name in icon_assets:
        out += ["", "[[asset.icon]]", f"name = {toml_str(name)}", "target_density = 640"]

    def floats(v) -> str:
        return "[" + ", ".join(f"{x:.6g}" if x != int(x) else f"{x:.1f}" for x in v) + "]"

    for b in border_assets:
        out += [
            "",
            "[[asset.border]]",
            f"name = {toml_str(b.name)}",
            f"target_density = {b.target_density:g}",
            f"background_tint = {toml_str(b.background_tint)}",
            f"foreground_tint = {toml_str(b.foreground_tint)}",
            f"padding = {floats(b.padding)}",
            f"slicing = {floats(b.slicing)}",
            "gap = [1.0, 1.0, 1.0, 1.0]",
        ]

    return "\n".join(out) + "\n"


def verify_theme_txt(
    theme_txt: str,
    kind: str,
    expected: list[tuple[tuple[str, ...], str]],
    files: set[str],
) -> list[str]:
    """theme.txt 를 다시 읽어서 기대한 선택자가 전부 있고 자산이 zip 에 들어갈지 본다.

    kind 는 "icon" 또는 "border", expected 는 (선택자 토큰, 자산 이름) 목록, files 는 zip 에
    넣을 이미지 이름들. 선택자는 앱처럼 공백으로 split 해서 비교하므로 `\\` `"` 이스케이프가
    틀렸거나 라벨에 공백이 섞였으면 여기서 걸린다.
    """
    doc = tomllib.loads(theme_txt)
    # 앱은 첫 번째로 매칭되는 항목을 쓴다 (CachedKeyedMatcher.find)
    rules: dict[tuple[str, ...], str] = {}
    for rule in doc.get("matchrules", {}).get(kind, []):
        rules.setdefault(tuple(rule["selector"].split(" ")), rule["asset"])
    declared = {a["name"] for a in doc.get("asset", {}).get(kind, [])}
    problems = []
    for tokens, asset in expected:
        if rules.get(tokens) != asset:
            problems.append(f"{kind} 선택자 {' '.join(tokens)!r} -> {asset} 가 theme.txt 에 없다")
        if asset not in declared or asset not in files:
            problems.append(f"{asset} 가 자산 목록이나 zip 에 없다")
    return problems


# --------------------------------------------------------------------------
# 미리보기 (설치 전 눈으로 확인용)
#
# 기기에서 보이는 모습에 가깝게 그린다 (키 크기·간격, 배경 모양, 글자 크기와 위치는
# 기기 실측값과 KeyboardView 의 계산을 따른다. 아래 "기기 실측값" 참고). 다만 앱이
# 아이콘으로 그리는 기능키(백스페이스, 엔터, 언어 전환 …)는 벡터로 흉내 낸 것이고 앱
# 리소스를 가져다 쓴 게 아니다.
# --------------------------------------------------------------------------


# ImageDraw 는 안티앨리어싱을 하지 않아서 선과 원이 계단처럼 나온다. 그래서 아래
# 좌표는 전부 이 배율만큼 키워서 그리고, 저장할 때 LANCZOS 로 줄여 가장자리를 얻는다.
# 최종 크기가 정수로 떨어져야 하므로 키 크기의 약수와 어긋나지 않게 둘 것.
SS = 3


def save_downsampled(img: Image.Image, path: Path) -> None:
    """SS 배로 그린 그림을 최종 크기로 줄여 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img.resize((img.width // SS, img.height // SS), Image.LANCZOS).save(path)


def rgb(name: str) -> tuple[int, int, int]:
    """팔레트 색을 (r, g, b) 로."""
    h = COLORS[name]
    return tuple(int(h[i : i + 2], 16) for i in (1, 3, 5))


def icon_backspace(draw, cx, cy, w, color, stroke=3 * SS) -> None:
    """⌫ — 왼쪽 끝이 뾰족한 오각형 안에 X."""
    h = w * 0.72
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    nose = x0 + h / 2
    draw.polygon(
        [(x0, cy), (nose, y0), (x1, y0), (x1, y1), (nose, y1)], outline=color, width=stroke
    )
    m, d = w * 0.17, h * 0.17
    draw.line([(nose + m, cy - d), (x1 - m, cy + d)], fill=color, width=stroke)
    draw.line([(nose + m, cy + d), (x1 - m, cy - d)], fill=color, width=stroke)


def icon_enter(draw, cx, cy, w, color, stroke=3 * SS) -> None:
    """⏎ — 오른쪽 위에서 내려와 왼쪽으로 꺾이는 화살표."""
    h = w * 0.82
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    a = w * 0.28
    draw.line(
        [(x1, y0), (x1, y1), (x0 + a * 0.8, y1)], fill=color, width=stroke, joint="curve"
    )
    draw.polygon([(x0, y1), (x0 + a, y1 - a * 0.62), (x0 + a, y1 + a * 0.62)], fill=color)


def icon_globe(draw, cx, cy, d, color, stroke=3 * SS) -> None:
    """🌐 — 언어 전환. 원에 경선 하나와 위선 둘."""
    r = d / 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=stroke)
    draw.ellipse([cx - r * 0.44, cy - r, cx + r * 0.44, cy + r], outline=color, width=stroke)
    draw.line([(cx - r, cy), (cx + r, cy)], fill=color, width=stroke)
    for dy in (-r * 0.52, r * 0.52):
        dx = r * 0.83
        draw.line([(cx - dx, cy + dy), (cx + dx, cy + dy)], fill=color, width=stroke)


def icon_smiley(draw, cx, cy, d, color, stroke=3 * SS) -> None:
    """액션 키. FUTO 의 기본 액션이 이모지라 웃는 얼굴로 둔다."""
    r = d / 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=stroke)
    er = max(1.5, r * 0.11)
    for dx in (-r * 0.36, r * 0.36):
        ey = cy - r * 0.3
        draw.ellipse([cx + dx - er, ey - er, cx + dx + er, ey + er], fill=color)
    draw.arc(
        [cx - r * 0.52, cy - r * 0.4, cx + r * 0.52, cy + r * 0.62],
        25,
        155,
        fill=color,
        width=stroke,
    )


def icon_shift(draw, cx, cy, w, color, stroke=3 * SS) -> None:
    """⇧ — 위로 향한 화살표."""
    h = w * 0.94
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    sw = w * 0.25  # 기둥 반폭
    my = y0 + h * 0.55
    draw.polygon(
        [(cx, y0), (x1, my), (cx + sw, my), (cx + sw, y1), (cx - sw, y1), (cx - sw, my), (x0, my)],
        outline=color,
        width=stroke,
    )


def icon_tab(draw, cx, cy, w, color, stroke=2 * SS) -> None:
    """⇥ — 오른쪽 화살표와 벽."""
    h = w * 0.6
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    tip = x1 - w * 0.16
    a = w * 0.26
    draw.line([(x0, cy), (tip - a * 0.5, cy)], fill=color, width=stroke)
    draw.polygon([(tip, cy), (tip - a, cy - a * 0.58), (tip - a, cy + a * 0.58)], fill=color)
    draw.line([(x1, y0), (x1, y1)], fill=color, width=stroke)


# 딩굴 아래 줄 폭. 실기기 스크린샷(926px 폭)에서 잰 경계를 1080 폭으로 늘린 값이다
# ($symbols, ㅋㅋㅋ, $action, $space, $contextual, $enter). 스페이스 오른쪽부터는 눈대중.
DINGUL_BOTTOM_UNITS = [w * 1080 / 920 / (1080 / 4) for w in (145, 105, 70, 340, 130, 130)]

# qwerty_hacker 아래 줄 폭 (눈대중, 920 폭 기준). 칸 폭 108 단위로 바꾼다.
QW_BOTTOM_UNITS = [w * 1080 / 920 / (1080 / 10) for w in (130, 100, 70, 300, 90, 110, 120)]


def render_preview(yml_path: Path, keys: list[FlickKeyInfo], icons: dict[str, Image.Image], path: Path) -> list[str]:
    """딩굴 미리보기. flick 키는 이 테마의 아이콘으로, 나머지는 앱이 그리는 대로."""
    doc = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
    page = parse_page(doc["rows"], {"Regular": 0.25})
    by_pos = {(k.row, k.col): k for k in keys}
    for row in page:
        for k in row:
            info = by_pos.get((k.row, k.col))
            if info is not None:
                k.theme_icon = icons[info.asset_name]
    for k, u in zip(page[-1], DINGUL_BOTTOM_UNITS):
        k.units = u
    render_page(page, DEVICE_W / 4, path)
    return []


def render_qwerty_preview(yml_path: Path, path: Path) -> list[str]:
    """qwerty_hacker.yml 도해. 테마 아이콘은 없고 앱이 그리는 라벨과 롱프레스 힌트뿐이다."""
    doc = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
    page = parse_page(doc["rows"], {"Regular": 0.1})
    for k, u in zip(page[-1], QW_BOTTOM_UNITS):
        k.units = u
    render_page(page, DEVICE_W / 10, path)
    return []


# --------------------------------------------------------------------------
# 기기 실측값
#
# 1080x2400 에뮬레이터에 이 테마(v3)와 다섯 줄짜리 레이아웃을 깐 스크린샷과, 테마 없이
# 기본 키 배경을 켠 스크린샷에서 쟀다. 미리보기 크기가 전부 여기서 나오므로, 다른 기기에
# 맞추려면 이 값만 다시 재면 된다.
# --------------------------------------------------------------------------

DEVICE_W = 1080  # 화면 폭 (px)
# densityDpi 가정. 2.5dp 힌트 여백(6.6px)과 9dp 키 모서리(23.6px)가 스크린샷과 맞는다.
DEVICE_DPI = 420
DEVICE_DENSITY = DEVICE_DPI / 160

# 키 배경 사이 간격. 칸 폭 72 에 배경 폭 60, 줄 간격 137.5 에 키 높이 114 였다.
# 앱 설정의 키 간격(layoutParams.gap)에 따라 달라진다 (LayoutEngine.kt:115).
KEY_GAP_X = 12
KEY_GAP_Y = 23.5

# 키보드 위 액션 바 (제안 줄). 위아래 3px 선 포함 105px, 양 끝에 지름 84 원형 버튼.
ACTION_BAR_H = 105
ACTION_BAR_LINE = 3
ACTION_BAR_BUTTON_D = 84

# 키 모양 (BasicThemeProvider.kt:422-432). auto_borders = false 일 때 값이다.
KEY_RADIUS_DP = 9.0  # 기능키 배경 (keyCornerRadius x roundedness)
SPACE_RADIUS_DP = 48.0  # 스페이스바
ACTION_RADIUS_DP = 128.0  # 엔터 (사실상 알약 모양)
ICON_INTRINSIC_DP = 24.0  # 앱 기본 아이콘(벡터)의 고유 크기

# 키보드 영역 (액션 바 아래). 다섯 줄짜리 레이아웃에서 쟀다. 첫 줄 키 윗변이 영역 위에서
# 14px, 줄 간격 137.5, 위 네 줄 키 높이 114, 아래 줄 키 높이 137, 영역 높이 725. 딩굴과
# qwerty_hacker 도 다섯 줄이라 같은 값을 쓴다 (키보드 높이 설정이 같으면 줄 높이도 같다).
KB_TOP = 14
KB_ROW_PITCH = 137.5
KB_KEY_H = 114
KB_BOTTOM_KEY_H = 137
KB_AREA_H = 725

# 앱 기본 테마(LXX)의 글자 비율과 여백 (res/values/config.xml:51-64, themes-lxx.xml:32-34).
# 비율의 기준은 키마다가 아니라 키보드 전체에서 가장 흔한 키 크기다. v2 레이아웃 키에는
# visualAttributes 가 없어서 mayCloneAndUpdateParams 가 그대로 돌려주고
# (KeyboardView.java:390), 키보드 단위 값은 min(mostCommonKeyWidth, mostCommonKeyHeight)
# 로 정해진다 (KeyboardView.java:210-214, LayoutEngine.kt:818).
KEY_LETTER_RATIO = 0.66  # 한 글자 라벨, Normal 스타일 (mLetterSize)
KEY_LABEL_RATIO = 0.34  # 여러 글자 라벨, 아이콘 키 (mLabelSize. ?123 …)
KEY_HINT_LETTER_RATIO = 0.30  # 우상단 힌트 (mHintLetterSize)
KEY_LARGE_LETTER_RATIO = 0.90  # labelFlags.followKeyLargeLetterRatio (mLargeLetterSize)
KEY_HINT_LABEL_RATIO = 0.30  # labelFlags.followKeyHintLabelRatio (mHintLabelSize)
KEY_HINT_PADDING_DP = 2.5  # 힌트와 키 가장자리 사이 (config_key_hint_letter_padding)
KEY_MAX_LABEL_RATIO = 0.9  # 라벨이 키 폭의 이 비율을 넘으면 가로로 줄인다 (MAX_LABEL_RATIO)


def dp(v: float) -> float:
    return v * DEVICE_DENSITY


# --------------------------------------------------------------------------
# 기능키 배경
#
# auto_borders = false 라 기능키(Shift, Backspace, ?123 …)는 기본 스타일 배경이 투명하다.
# 그래서 `[[matchrules.border]]` 로 둥근 사각형을 깔아 준다. 이때 두 가지를 지켜야 한다.
#
# - 눌림 표시가 보여야 한다. 레이어 0 에 테마 배경이 걸리면 앱은 키의 기본 배경
#   (Key.kt:367 selectBackground, 눌림 배경 포함) 대신 그걸 쓴다 (AdvancedThemeCustomizer.kt:145).
#   그래서 배경을 레이어 -1 에 둔다. 레이어는 오름차순으로 그려지고 (KeyboardView.java:325),
#   레이어 0 은 앱 기본 스타일 그대로라 꺼짐은 투명, 눌림은 keyboard_container_pressed 가
#   우리 배경 위를 덮는다. 잠긴 Shift 는 원래 스타일이 StickyOn 이라 (TemplateKeys.kt:64)
#   `functional` 선택자에 걸리지 않고 앱 기본 배경(secondary)으로 그려진다.
# - 레이어 -1 에서는 글자를 그리지 않는다. foreground_tint 가 그 레이어의 글자색이 되므로
#   (AdvancedThemeCustomizer.kt:146) 알파 0 으로 두면 onDrawKeyTopVisuals 를 건너뛴다
#   (KeyboardView.java:406).
# --------------------------------------------------------------------------

FUNC_BG_ASSET = "func_bg.png"
FUNC_BG_DENSITY = 640  # 자산 기준 밀도. 9dp 모서리가 36px 이 된다
FUNC_BG_SIZE = 96
FUNC_BG_TINT = "keyboard_container"  # 기능키 배경색 (#3a3f4b). 배경 #282c34 보다 조금 밝다
NO_TEXT_TINT = "#00000000"
# 앱 기본 스타일 (BasicThemeProvider.kt:308, 479-535)
PRESSED_BG = "keyboard_container_pressed"  # 눌림 배경 = 스페이스바 색
STICKY_ON_BG, STICKY_ON_FG = "secondary", "on_secondary"  # Shift 잠김 (StickyOn)
PRESSED_FG = "on_keyboard_container_pressed"


@dataclass
class BorderAsset:
    """`[[asset.border]]` 하나. png 는 흰색(틴트 대상)이거나 실제 색이다."""

    name: str
    image: Image.Image
    target_density: float
    slicing: tuple[float, float, float, float]
    background_tint: str = "#ffffff"  # 흰색이면 틴트하지 않는다 (NinePatchBuilder.kt:142)
    foreground_tint: str = NO_TEXT_TINT
    padding: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)  # 여백 없음 (Toml.kt:383-386)


def render_func_bg() -> BorderAsset:
    """기능키 배경: 흰 둥근 사각형. background_tint 가 MULTIPLY 로 색을 입힌다."""
    s = FUNC_BG_SIZE * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    r = KEY_RADIUS_DP * FUNC_BG_DENSITY / 160 * SS
    ImageDraw.Draw(img).rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=(255, 255, 255, 255))
    img = img.resize((FUNC_BG_SIZE, FUNC_BG_SIZE), Image.LANCZOS)
    return BorderAsset(
        name=FUNC_BG_ASSET,
        image=img,
        target_density=FUNC_BG_DENSITY,
        slicing=(0.4, 0.4, 0.6, 0.6),  # 모서리(36px)는 늘리지 않는다
        background_tint=FUNC_BG_TINT,
    )


# 기능키 배경 선택자. Shift 는 Functional, 잠긴 Shift 는 StickyOn 이다 (TemplateKeys.kt:44-76).
# stickyoff 는 지금 템플릿에서 안 쓰지만 같은 모양이어야 하므로 같이 넣는다.
FUNC_BG_SELECTORS = [("layer", "-1", "functional"), ("layer", "-1", "stickyoff")]


@dataclass
class KeyDef:
    """yaml 키 하나를 앱이 그리는 방식으로 정리한 것."""

    row: int
    col: int
    units: float | None  # Regular 키 대비 폭. None 은 남은 폭을 채우는 스페이스
    style: str  # normal | functional | action | spacebar
    ident: str  # 키를 구분하는 값 (스펙 문자열)
    label: str | None = None  # 앱이 그리는 라벨
    icon: str | None = None  # 앱이 그리는 아이콘 ID (tab_key …)
    hint: str | None = None  # 앱이 그리는 우상단 힌트
    hint_icon: str | None = None  # 앱이 우상단에 그리는 힌트 아이콘 (롱프레스 첫 키가 아이콘일 때)
    label_flags: dict | None = None  # yaml attributes.labelFlags (글자/아이콘 크기를 정한다)
    theme_icon: Image.Image | None = None  # 이 테마의 아이콘 (딩굴 flick 키). 라벨을 대신한다
    state: str = "off"  # 미리보기용 상태: off | pressed (눌림) | locked (Shift 잠김)


def app_spec_label(spec) -> str:
    """KeySpecParser.getLabel 과 같은 라벨.

    spec_label 과 다른 점은 `|` 하나짜리 스펙뿐이다. 앱은 이걸 구분자가 아니라
    라벨로 읽는다 (KeySpecParser.java:102-105).
    """
    text = str(spec)
    return text if text == "|" else spec_label(text)


def case_side(side) -> tuple[str, str | None] | None:
    """case 키의 normal/shifted 한쪽을 (라벨, 힌트) 로. 아이콘 키 등은 None."""
    if isinstance(side, dict):
        if side.get("type", "base") != "base" or "spec" not in side:
            return None
        spec, hint = side["spec"], side.get("hint")
    elif isinstance(side, (str, int, float)):
        spec, hint = side, None
    else:
        return None
    if str(spec).startswith("!icon/"):
        return None
    return app_spec_label(spec), (None if hint is None else str(hint))


def entry_units(entry, widths: dict[str, float]) -> float | None:
    """키 폭을 Regular 키 단위로. 스페이스, Grow, 템플릿 기능키는 None (남는 폭을 나눠 갖는다)."""
    if isinstance(entry, str) and entry.startswith("$"):
        return None
    attrs = entry.get("attributes", {}) if isinstance(entry, dict) else {}
    name = attrs.get("width", "Regular")
    if name not in widths:
        return None
    return widths[name] / widths["Regular"]


# 템플릿 키 (TemplateKeys.kt). 스타일과 앱이 그리는 라벨/아이콘.
TEMPLATE_KEYS: dict[str, dict] = {
    "$symbols": dict(style="functional", label="?123"),
    "$action": dict(style="functional", icon="action_emoji"),
    "$contextual": dict(style="functional", icon="action_switch_language"),
    "$enter": dict(style="action", icon="enter_key"),
    "$shift": dict(style="functional", icon="shift_key"),
    "$delete": dict(style="functional", icon="delete_key"),
    "$space": dict(style="spacebar"),
}


def parse_key(entry, row: int, col: int, widths: dict[str, float]) -> KeyDef:
    units = entry_units(entry, widths)
    if isinstance(entry, str) and entry in TEMPLATE_KEYS:
        return KeyDef(row, col, units, ident=entry, **TEMPLATE_KEYS[entry])
    if isinstance(entry, list):
        # [라벨, 롱프레스..., ] 형태. 첫 롱프레스 키가 우상단 힌트가 된다 (Key.kt:260).
        key = KeyDef(row, col, units, "normal", str(entry), label=app_spec_label(entry[0]))
        if len(entry) > 1:
            more = str(entry[1])
            if more.startswith("!icon/"):
                key.hint_icon = more[len("!icon/"):].split("|")[0]
            else:
                key.hint = app_spec_label(more)
        return key
    if not isinstance(entry, dict):
        return KeyDef(row, col, units, "normal", str(entry), label=app_spec_label(entry))
    kind = entry.get("type", "base")
    attrs = entry.get("attributes", {})
    style = str(attrs.get("style", "Normal")).lower()
    flags = attrs.get("labelFlags") if isinstance(attrs.get("labelFlags"), dict) else None
    if kind == "case":
        normal = case_side(entry.get("normal"))
        key = KeyDef(row, col, units, style, f"case:{entry.get('normal')}")
        if normal:
            key.label, key.hint = normal
        return key
    if kind == "flick":
        return KeyDef(row, col, units, "normal", str(entry.get("primary")), label=spec_label(entry["primary"]))
    if kind == "enter":
        return KeyDef(row, col, units, "action", "enter", icon="enter_key")
    if kind == "shift":
        return KeyDef(row, col, units, "functional", "shift", icon="shift_key")
    if kind == "base":
        spec = str(entry.get("spec", ""))
        key = KeyDef(row, col, units, style, spec, label_flags=flags)
        hint = entry.get("hint")
        key.hint = None if hint is None else str(hint)
        if spec.startswith("!icon/"):
            key.icon = spec[len("!icon/"):].split("|")[0]
        else:
            key.label = app_spec_label(spec)
        return key
    return KeyDef(row, col, units, "functional", kind)


def parse_page(rows, widths: dict[str, float]) -> list[list[KeyDef]]:
    page = []
    for r, row in enumerate(rows):
        entries = row.get("letters") or row.get("bottom") or []
        page.append([parse_key(e, r, c, widths) for c, e in enumerate(entries)])
    return page


# --------------------------------------------------------------------------
# 앱이 키를 그리는 방식 (KeyboardView.onDrawKeyTopVisuals) 흉내
# --------------------------------------------------------------------------


@dataclass
class TextSizes:
    """키보드 단위 글자 크기 (px). 기준은 min(가장 흔한 키 폭, 가장 흔한 키 높이)."""

    letter: float
    label: float
    hint: float
    hint_pad: float
    large_letter: float = 0.0
    hint_label: float = 0.0


def text_sizes(base: float, scale: float = 1.0) -> TextSizes:
    return TextSizes(
        letter=int(base * KEY_LETTER_RATIO) * SCALE_TEXT * scale,
        label=int(base * KEY_LABEL_RATIO) * SCALE_TEXT * scale,
        hint=int(base * KEY_HINT_LETTER_RATIO) * OPTIONS["scale_hints"] * scale,
        hint_pad=dp(KEY_HINT_PADDING_DP) * scale,
        large_letter=int(base * KEY_LARGE_LETTER_RATIO) * SCALE_TEXT * scale,
        hint_label=int(base * KEY_HINT_LABEL_RATIO) * SCALE_TEXT * scale,
    )


def key_text_size(key: "KeyDef", ts: TextSizes) -> float:
    """Key.selectTextSize (Key.kt:365) 와 같은 규칙.

    labelFlags 의 follow* 플래그가 있으면 그 크기, 없으면 한 글자거나 Normal 스타일이면
    mLetterSize, 아니면 mLabelSize. 라벨이 없는 아이콘 키는 글자 수 0 이라 mLabelSize 다.
    플래그 우선순위는 앱의 when 순서(letter, large letter, label, hint label)를 따른다.
    """
    flags = key.label_flags or {}
    if flags.get("followKeyLetterRatio"):
        return ts.letter
    if flags.get("followKeyLargeLetterRatio"):
        return ts.large_letter
    if flags.get("followKeyLabelRatio"):
        return ts.label
    if flags.get("followKeyHintLabelRatio"):
        return ts.hint_label
    one = (key.label is not None and len(key.label) == 1) or key.style == "normal"
    return ts.letter if one else ts.label


def ink_bbox(text: str, font: ImageFont.FreeTypeFont) -> tuple[float, float, float, float]:
    """`ms` 앵커(가로 가운데, baseline) 기준 실제 잉크 상자.

    Pillow 의 getbbox 는 가로를 advance 기준으로 주므로, 앱의 getTextBounds 처럼
    잉크 기준 폭이 필요할 때는 직접 그려서 잰다.
    """
    pad = font.size * 2
    size = int(font.getlength(text) + pad * 2)
    img = Image.new("L", (size, int(pad * 2)), 0)
    ImageDraw.Draw(img).text((size / 2, pad), text, font=font, anchor="ms", fill=255)
    box = img.getbbox() or (0, 0, 0, 0)
    return box[0] - size / 2, box[1] - pad, box[2] - size / 2, box[3] - pad


def ink_w(text: str, font) -> float:
    x0, _, x1, _ = ink_bbox(text, font)
    return x1 - x0


def cap_h(font) -> float:
    """'M' 잉크 높이 (TypefaceUtils.getReferenceCharHeight)."""
    _, y0, _, y1 = ink_bbox("M", font)
    return y1 - y0


def app_hint_x(text: str, font, key_w: float, pad: float) -> float:
    """우상단 힌트의 가로 중심 (KeyboardView.java:566)."""
    return key_w - pad - max(ink_w("8", font), ink_w(text, font)) / 2


# 앱 아이콘 흉내. 값은 아이콘 정사각형(한 변 42px) 안에서 실제 글리프가 차지하는 비율로,
# 스크린샷에서 잰 글리프 폭(Tab 36, Backspace 38, Shift 37, 지구본 38, 엔터 34)에서 왔다.
APP_ICONS = {
    "tab_key": lambda d, cx, cy, s, c, sw: icon_tab(d, cx, cy, s * 0.95, c, round(sw * 1.2)),
    "delete_key": lambda d, cx, cy, s, c, sw: icon_backspace(d, cx, cy, s * 0.9, c, sw),
    "shift_key": lambda d, cx, cy, s, c, sw: icon_shift(d, cx, cy, s * 0.95, c, sw),
    "enter_key": lambda d, cx, cy, s, c, sw: icon_enter(d, cx, cy, s * 0.8, c, sw),
    "action_switch_language": lambda d, cx, cy, s, c, sw: icon_globe(d, cx, cy, s * 0.9, c, sw),
    "action_emoji": lambda d, cx, cy, s, c, sw: icon_smiley(d, cx, cy, s * 0.9, c, sw),
}


def draw_app_center(draw, key: KeyDef, box, ts: TextSizes, color, scale: float) -> None:
    """앱이 키 가운데에 그리는 라벨이나 아이콘.

    라벨: 한 글자거나 Normal 스타일이면 mLetterSize, 아니면 mLabelSize (Key.kt:365).
    baseline 은 키 중심 + 'M' 높이 / 2, 폭이 키의 0.9 를 넘으면 가로로 줄인다.
    아이콘: 한 변 min(24dp, 키 폭, 1.75 x textSize) 정사각형 (KeyboardView.java:596).
    아이콘 키의 textSize 는 라벨이 없으므로 mLabelSize 다.
    """
    x0, y0, x1, y1 = box
    kw = x1 - x0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if key.label is not None and key.label != "":
        font = make_font(round(key_text_size(key, ts)), OPTIONS["weight_text"])
        baseline = cy + cap_h(font) / 2
        w = ink_w(key.label, font)
        if w > kw * KEY_MAX_LABEL_RATIO:
            # 앱은 setTextScaleX 로 가로만 줄인다. 그대로 흉내 낸다.
            ratio = kw * KEY_MAX_LABEL_RATIO / w
            layer = Image.new("L", (int(w * 2 + 4), int(font.size * 3)), 0)
            ImageDraw.Draw(layer).text(
                (layer.width / 2, font.size * 2), key.label, font=font, anchor="ms", fill=255
            )
            layer = layer.resize((max(1, int(layer.width * ratio)), layer.height), Image.LANCZOS)
            draw._image.paste(  # noqa: SLF001  (ImageDraw 의 대상 이미지)
                Image.new(draw._image.mode, layer.size, color),
                (round(cx - layer.width / 2), round(baseline - font.size * 2)),
                layer,
            )
            return
        draw.text((cx, baseline), key.label, font=font, anchor="ms", fill=color)
        return
    if key.icon in APP_ICONS:
        side = min(dp(ICON_INTRINSIC_DP) * scale, kw, 1.75 * key_text_size(key, ts))
        APP_ICONS[key.icon](draw, cx, cy, side, color, max(1, round(3.0 * scale)))


def app_theme_icon_side(key: KeyDef, key_w: float, ts: TextSizes) -> int:
    """테마 아이콘의 한 변: min(고유 크기, 키 폭, 1.75 x textSize) (KeyboardView.java:596-606).

    textSize 는 key_text_size() (labelFlags 반영). 고유 크기(PNG 폭)는 따로 검사한다.
    """
    return int(min(key_w, 1.75 * key_text_size(key, ts)))


# --------------------------------------------------------------------------
# 기기처럼 그리는 미리보기 (액션 바, 키 모양, 기능키 배경)
# --------------------------------------------------------------------------


def draw_action_bar(img: Image.Image, scale: float) -> None:
    """키보드 위 액션 바. 위아래 선, 왼쪽 > 버튼, 오른쪽 마이크 버튼 (스크린샷 기준)."""
    draw = ImageDraw.Draw(img)
    w = img.width
    h = ACTION_BAR_H * scale
    line = ACTION_BAR_LINE * scale
    draw.rectangle([0, 0, w, h], fill=COLORS["keyboard_surface_dim"])
    draw.rectangle([0, 0, w, line], fill=COLORS["keyboard_container"])
    draw.rectangle([0, h - line, w, h], fill=COLORS["keyboard_container"])
    r = ACTION_BAR_BUTTON_D * scale / 2
    cy = h / 2
    fg = rgb("on_surface_variant")
    for cx in (18 * scale + r, w - 18 * scale - r):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLORS["keyboard_container"])
    cx = 18 * scale + r
    a = r * 0.22
    draw.line(
        [(cx - a * 0.5, cy - a), (cx + a * 0.5, cy), (cx - a * 0.5, cy + a)],
        fill=fg, width=max(1, round(2.5 * scale)), joint="curve",
    )
    cx = w - 18 * scale - r
    mw, mh = r * 0.22, r * 0.5
    draw.rounded_rectangle([cx - mw / 2, cy - mh * 0.75, cx + mw / 2, cy + mh * 0.1], radius=mw / 2, fill=fg)
    draw.arc([cx - mw, cy - mh * 0.5, cx + mw, cy + mh * 0.35], 0, 180, fill=fg, width=max(1, round(2 * scale)))
    draw.line([(cx, cy + mh * 0.35), (cx, cy + mh * 0.6)], fill=fg, width=max(1, round(2 * scale)))


def draw_key_shape(draw, box, style: str, scale: float, state: str = "off") -> None:
    """앱 기본 스타일 + 이 테마의 기능키 배경을 키 상자(간격 제외)에 그린다.

    레이어 -1 의 기능키 배경 위에 레이어 0 의 앱 기본 배경이 덮인다. 눌림은
    keyboard_container_pressed, 잠김(StickyOn)은 secondary 다 (BasicThemeProvider.kt:256, 513).
    """
    x0, y0, x1, y1 = box
    if state in ("pressed", "locked") and style != "action":
        r = min(dp(SPACE_RADIUS_DP if style == "spacebar" else KEY_RADIUS_DP) * scale, (x1 - x0) / 2, (y1 - y0) / 2)
        fill = COLORS[PRESSED_BG] if state == "pressed" else COLORS[STICKY_ON_BG]
        draw.rounded_rectangle(box, radius=r, fill=fill)
    elif style in ("functional", "stickyoff"):
        r = min(dp(KEY_RADIUS_DP) * scale, (x1 - x0) / 2, (y1 - y0) / 2)
        draw.rounded_rectangle(box, radius=r, fill=COLORS[FUNC_BG_TINT])
    elif style == "spacebar":
        r = min(dp(SPACE_RADIUS_DP) * scale, (x1 - x0) / 2, (y1 - y0) / 2)
        draw.rounded_rectangle(box, radius=r, fill=COLORS[PRESSED_BG])
    elif style == "action":
        r = min(dp(ACTION_RADIUS_DP) * scale, (x1 - x0) / 2, (y1 - y0) / 2)
        draw.rounded_rectangle(box, radius=r, fill=COLORS["primary"])


def page_boxes(page: list[list[KeyDef]], cell: float, scale: float):
    """키마다 (키, 상자) 를 낸다. 상자는 간격을 뺀, 앱이 배경을 그리는 영역.

    폭이 정해지지 않은 키(None)는 남는 폭을 똑같이 나눠 갖고, 그런 키가 없는 줄이 화면보다
    좁으면 가운데로 모은다 (LayoutEngine.kt:752).
    """
    total = DEVICE_W / cell
    for r, row in enumerate(page):
        fixed = sum(k.units for k in row if k.units is not None)
        flex = [k for k in row if k.units is None]
        fill = (total - fixed) / len(flex) if flex else 0
        x = 0.0 if flex else (total - fixed) * cell / 2
        y0 = KB_TOP + r * KB_ROW_PITCH
        bottom = r == len(page) - 1
        kh = KB_BOTTOM_KEY_H if bottom else KB_KEY_H
        for k in row:
            cw = (k.units if k.units is not None else fill) * cell
            box = (
                (x + KEY_GAP_X / 2) * scale,
                y0 * scale,
                (x + cw - KEY_GAP_X / 2) * scale,
                (y0 + kh) * scale,
            )
            x += cw
            yield k, box


def paste_tinted(img: Image.Image, icon: Image.Image, side: int, xy, color) -> None:
    """아이콘을 단색으로 틴트해서 붙인다 (icon.setTint(textColor), SRC_IN)."""
    icon = icon.resize((side, side), Image.LANCZOS)
    tinted = Image.new("RGBA", icon.size, color + (0,))
    tinted.putalpha(icon.getchannel("A"))
    img.alpha_composite(tinted, (round(xy[0]), round(xy[1])))


def render_page(
    page: list[list[KeyDef]], cell: float, path: Path, area_h: float = KB_AREA_H, bar: bool = True
) -> None:
    """레이아웃 한 페이지를 기기 화면처럼 그린다 (액션 바 + 키보드 영역).

    키마다 앱 기본 스타일 배경(+ 이 테마의 기능키 배경), 가운데 라벨/아이콘, 우상단 힌트를
    KeyboardView 의 크기·위치 계산대로 그린다.
    """
    s = SS
    w = DEVICE_W * s
    top = ACTION_BAR_H * s if bar else 0
    img = Image.new("RGB", (w, round(top + area_h * s)), COLORS["keyboard_surface"])
    if bar:
        draw_action_bar(img, s)
    kb = Image.new("RGBA", (w, round(area_h * s)), COLORS["keyboard_surface"])
    draw = ImageDraw.Draw(kb)
    ts = text_sizes(min(round(cell), KB_KEY_H), s)
    fg, action_fg, hint_fg = rgb("on_keyboard_container"), rgb("on_primary"), rgb("on_surface_variant")

    boxes = list(page_boxes(page, cell, s))
    for key, box in boxes:
        draw_key_shape(draw, box, key.style, s, key.state)
    for key, box in boxes:
        kw, kh = box[2] - box[0], box[3] - box[1]
        color = action_fg if key.style == "action" else fg
        if key.state == "pressed":
            color = rgb(PRESSED_FG)
        elif key.state == "locked":
            color = rgb(STICKY_ON_FG)
        if key.theme_icon is not None:
            # 테마 아이콘: 한 변 min(키 폭, 1.75 x textSize), 키 가운데 (KeyboardView.java:596)
            side = app_theme_icon_side(key, kw, ts)
            paste_tinted(kb, key.theme_icon, side, (box[0] + (kw - side) / 2, box[1] + (kh - side) / 2), color)
        else:
            draw_app_center(draw, key, box, ts, color, s)
        if key.hint:
            font = make_font(round(ts.hint), OPTIONS["weight_hints"])
            ascent, _ = font.getmetrics()
            draw.text(
                (box[0] + app_hint_x(key.hint, font, kw, ts.hint_pad), box[1] + ascent + ts.hint_pad),
                key.hint, font=font, anchor="ms", fill=hint_fg,
            )
        elif key.hint_icon in APP_ICONS:
            # 힌트 아이콘: 한 변 hintSize, 우상단 (KeyboardView.java:580-593)
            size = ts.hint
            APP_ICONS[key.hint_icon](
                draw, box[2] - ts.hint_pad - size / 2, box[1] + ts.hint_pad + size / 2,
                size, hint_fg, max(1, round(2 * s)),
            )

    img.paste(kb.convert("RGB"), (0, top))
    save_downsampled(img, path)


def render_states_preview(path: Path) -> None:
    """기능키 상태 견본: 꺼짐 / 잠김 Shift, 눌린 Esc, 엔터."""
    keys = [
        KeyDef(0, 0, 2, "functional", "s0", icon="shift_key"),
        KeyDef(0, 1, 2, "functional", "s1", icon="shift_key", state="locked"),
        KeyDef(0, 2, 2, "functional", "e1", label="Esc", state="pressed"),
        KeyDef(0, 3, 3, "action", "enter", icon="enter_key"),
    ]
    render_page([keys], DEVICE_W / 15, path, area_h=KB_TOP * 2 + KB_BOTTOM_KEY_H, bar=False)


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yml", type=Path, default=REPO / "dingul.yml")
    ap.add_argument(
        "--layout",
        action="append",
        default=None,
        metavar="NAME",
        help="선택자에 넣을 레이아웃 세트 이름. 커스텀 레이아웃은 custom0, custom1, ... "
        "(기본값: custom0). 여러 번 지정 가능.",
    )
    ap.add_argument(
        "--qwerty-yml",
        type=Path,
        default=REPO / "qwerty_hacker.yml",
        help="미리보기만 그리는 보조 레이아웃. 테마에는 들어가지 않는다.",
    )
    ap.add_argument("--build-dir", type=Path, default=REPO / "build")
    ap.add_argument("--dist-dir", type=Path, default=REPO / "dist")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument(
        "--no-embed-font",
        action="store_true",
        help=f"{FONT_PATH.name} 을 테마에 넣지 않는다. zip 이 훨씬 작아지는 대신 "
        "`?123` 같은 라벨은 기기 기본 폰트로 그려져서 아이콘과 서체가 어긋난다.",
    )
    args = ap.parse_args()

    layouts = args.layout or ["custom0"]
    embed_font = not args.no_embed_font

    ensure_font()

    problems = check_contrast()
    if problems:
        print("색 대비 검증 실패 (앱이 임포트를 거부한다):", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 1

    keys = load_flick_keys(args.yml)
    if not keys:
        print(f"{args.yml} 에서 flick 키를 찾지 못했다.", file=sys.stderr)
        return 1

    center_font = calibrated_font(CANVAS * CENTER_INK_H)
    hint_font = calibrated_font(CANVAS * HINT_INK_H)

    theme_dir = args.build_dir / "theme"
    theme_dir.mkdir(parents=True, exist_ok=True)
    for old in theme_dir.glob("*.png"):
        old.unlink()

    icons: dict[str, Image.Image] = {}
    all_warnings: list[str] = []
    for key in keys:
        img, warnings = render_icon(key, center_font, hint_font)
        icons[key.asset_name] = img
        all_warnings += warnings

    borders: list[BorderAsset] = [render_func_bg()]
    border_rules: list[tuple[tuple[str, ...], str]] = [(sel, FUNC_BG_ASSET) for sel in FUNC_BG_SELECTORS]

    icon_rules = [
        (("layout", layout, "label", key.label), key.asset_name) for layout in layouts for key in keys
    ]
    theme_txt = build_theme_txt(icon_rules, list(icons), border_rules, borders, embed_font)
    (theme_dir / "theme.txt").write_text(theme_txt, encoding="utf-8")
    for name, img in icons.items():
        img.save(theme_dir / name)
    for b in borders:
        b.image.save(theme_dir / b.name)

    # 버전 파일: version(1B) + epoch millis(8B, little-endian)  (ZipThemes.kt:80)
    version_blob = struct.pack("<bq", 1, int(time.time() * 1000))
    (theme_dir / "FUTOKeyboardTheme_Version").write_bytes(version_blob)

    # 딩굴 flick 키와 기능키 배경이 전부 선택자와 자산을 받았는지 zip 을 만들기 전에 확인한다.
    files = set(icons) | {b.name for b in borders}
    problems = verify_theme_txt(theme_txt, "icon", icon_rules, files)
    problems += verify_theme_txt(theme_txt, "border", border_rules, files)
    if problems:
        print("theme.txt 검증 실패:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 1

    args.dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = args.dist_dir / f"{THEME_ID}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("FUTOKeyboardTheme_Version", version_blob)
        z.writestr("theme.txt", theme_txt)
        for name, img in [*icons.items(), *((b.name, b.image) for b in borders)]:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            z.writestr(name, buf.getvalue())
        if embed_font:
            z.write(FONT_PATH, FONT_PATH.name)

    previews: list[Path] = []
    if not args.no_preview:
        all_warnings += render_preview(args.yml, keys, icons, args.build_dir / "preview.png")
        previews.append(args.build_dir / "preview.png")
        if args.qwerty_yml.is_file():
            all_warnings += render_qwerty_preview(args.qwerty_yml, args.build_dir / "preview_qwerty.png")
            previews.append(args.build_dir / "preview_qwerty.png")
        render_states_preview(args.build_dir / "preview_states.png")
        previews.append(args.build_dir / "preview_states.png")

    print(
        f"flick 키 {len(keys)}개, 레이아웃 {', '.join(layouts)}, "
        f"scale_text {SCALE_TEXT}, 폰트 {'포함' if embed_font else '미포함'}"
    )
    for key in keys:
        dirs = " ".join(f"{n[0]}:{v}" for n, v in key.directions.items())
        print(f"  r{key.row}c{key.col}  label {key.label!r:8} {dirs}")
    print(f"\n기능키 배경: {', '.join(' '.join(s) for s in FUNC_BG_SELECTORS)}")
    print(f"\n{zip_path}  ({zip_path.stat().st_size / 1024:.0f} KB)")
    for p in previews:
        print(p)
    for w in all_warnings:
        print(f"경고: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
