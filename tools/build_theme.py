#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML>=6.0", "Pillow>=10.0"]
# ///
"""dingul.yml 전용 FUTO Keyboard 테마 빌더.

flick 키의 상/하/좌/우 문자를 키 아이콘(``[[matchrules.icon]]``)으로 구워서
키 위에 표시한다. 레이아웃 yaml 이 진실의 원천이므로, yaml 을 고치고 이
스크립트를 다시 돌리면 힌트도 같이 갱신된다.

  uv run tools/build_theme.py --layout custom0

산출물:
  build/theme/           테마 zip 에 들어가는 원본 파일들
  dist/<id>.zip          FUTO Keyboard 로 임포트할 테마
  build/preview.png      설치 전에 눈으로 확인하는 가짜 키보드 렌더
  build/preview_qwerty.png   qwerty_hacker.yml 도해 (테마와는 무관, README 용)

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
THEME_VERSION = 2
THEME_DESCRIPTION = (
    "딩굴 레이아웃 전용 테마. flick 키의 상/하/좌/우 입력 문자를 "
    "키 아이콘으로 구워서 키 위에 표시한다. 색은 Atom One Dark."
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


def make_font(size: int) -> ImageFont.FreeTypeFont:
    """가변 폰트를 FONT_WEIGHT 인스턴스로 고정해서 연다."""
    font = ImageFont.truetype(FONT_PATH, size)
    font.set_variation_by_axes([FONT_WEIGHT])
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


def build_theme_txt(keys: list[FlickKeyInfo], layouts: list[str], embed_font: bool) -> str:
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
        "# (DevLayoutEditor.kt:95). 딩굴이 몇 번인지에 맞춰 --layout 으로 다시 빌드할 것.",
        "# -------------------------------------------------------------------",
    ]
    for layout in layouts:
        for key in keys:
            out += [
                "",
                "[[matchrules.icon]]",
                f"selector = {toml_str(f'layout {layout} label {key.label}')}",
                f"asset = {toml_str(key.asset_name)}",
            ]

    out += [
        "",
        "# -------------------------------------------------------------------",
        "# 아이콘 자산 목록",
        "# -------------------------------------------------------------------",
    ]
    for key in keys:
        out += [
            "",
            "[[asset.icon]]",
            f"name = {toml_str(key.asset_name)}",
            "target_density = 640",
        ]

    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# 미리보기 (설치 전 눈으로 확인용)
#
# 목적은 힌트가 키를 넘치거나 겹치는지 눈으로 보는 것이라 픽셀 단위로 실기기와
# 같을 필요는 없다. 다만 어느 키가 무엇인지 알아볼 수는 있어야 해서, 앱이 아이콘
# 으로 그리는 기능키(백스페이스, 엔터, 언어 전환 …)는 여기서 벡터로 흉내 낸다.
# 아이콘 모양은 흉내일 뿐이고 앱 리소스를 가져다 쓴 게 아니다.
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


# 기능키(style: Functional)에만 배경이 깔린다. `auto_borders = false` 라
# 글자 키는 배경 없이 글자만 그려진다.
FUNCTIONAL_KINDS = {"func", "space", "action", "globe", "shift", "delete"}


def draw_bottom_row(draw, keys, by, h, label_font, hint_font=None) -> list[str]:
    """아래 줄을 그린다. keys 는 (x0, x1, kind, label, hint) 목록."""
    warnings: list[str] = []
    fg, hint_fg = rgb("on_keyboard_container"), rgb("on_surface_variant")
    for x0, x1, kind, label, hint in keys:
        # 키 경계를 옅게 그려서 힌트가 옆/아래 키를 침범하는지 눈으로 본다
        draw.rectangle(
            [x0 + 2 * SS, by + 2 * SS, x1 - 2 * SS, by + h - 2 * SS],
            outline=COLORS["outline_variant"],
            width=SS,
        )
        cx, cy = (x0 + x1) / 2, by + h / 2
        pad = 10 * SS
        if kind == "enter":
            d = min(x1 - x0 - 2 * pad, h - 20 * SS)
            draw.ellipse([cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2], fill=COLORS["primary"])
            icon_enter(draw, cx + d * 0.03, cy - d * 0.05, d * 0.44, rgb("on_primary"))
            continue
        if kind in FUNCTIONAL_KINDS:
            inset = (18 if kind == "space" else 14) * SS
            draw.rounded_rectangle(
                [x0 + pad, by + inset, x1 - pad, by + h - inset],
                radius=inset,
                fill=COLORS["keyboard_container_variant"],
            )
        d = min(x1 - x0, h) * 0.42
        if kind == "action":
            icon_smiley(draw, cx, cy, d, fg)
        elif kind == "globe":
            icon_globe(draw, cx, cy, d, fg)
        elif label:
            lx0, _, lx1, _ = label_font.getbbox(label)
            if lx1 - lx0 > (x1 - x0) * 0.9:
                warnings.append(
                    f"아래 줄 {label!r} 라벨이 키를 넘친다 "
                    f"(라벨 {(lx1 - lx0) / SS:.0f}px / 키 {(x1 - x0) / SS:.0f}px). "
                    f"scale_text={SCALE_TEXT} 를 낮출 것."
                )
            draw.text((cx, cy), label, font=label_font, anchor="mm", fill=fg)
        if hint and hint_font is not None:
            draw.text(
                (x1 - (x1 - x0) * 0.24, by + h * 0.26),
                hint,
                font=hint_font,
                anchor="mm",
                fill=hint_fg,
            )
    return warnings


# 실기기 스크린샷(926px 폭) 실측. 아래 줄 키 경계의 x 좌표.
PREVIEW_KEY_W, PREVIEW_KEY_H = 230 * SS, 122 * SS

# 아래 줄 키. (x0, x1, 그리는 방식, 라벨).
#
# dingul.yml 의 마지막 행과 같은 순서다 ($symbols, ㅋㅋㅋ, $action, $space,
# $contextual, $enter). 앞의 셋은 스크린샷 실측이고, 스페이스 오른쪽 경계부터는
# 실측값이 없어서 눈대중으로 나눴다. 미리보기는 힌트가 키를 넘치는지 보려고 그리는
# 그림이라 이 줄의 폭이 조금 달라도 상관없다.
PREVIEW_BOTTOM = [
    (x0 * SS, x1 * SS, kind, label, hint)
    for x0, x1, kind, label, hint in [
        (0, 145, "func", "?123", None),
        (145, 250, "text", "ㅋㅋㅋ", None),
        (250, 320, "action", None, None),
        (320, 660, "space", None, None),
        (660, 790, "globe", None, None),
        (790, 920, "enter", None, None),
    ]
]

# 아래 줄 라벨은 앱이 텍스트로 그린다. 크기 규칙(mLabelSize / mLetterSize / auto
# scale 중 무엇이 걸리는지)을 코드만 보고 확정하기 어려워서, scale_text = 1.0 인
# 실기기 스크린샷 기준으로 잡고 scale_text 만큼 키운다.
#
# 스크린샷에서 `ㅋㅋㅋ` 는 폭 105 짜리 키에서 80px 을 썼다. 같은 폭이 나오는
# Pretendard 크기의 잉크 높이가 18px 이라 이 값을 쓴다 (높이를 눈으로 재는 것보다
# 폭을 맞추는 쪽이 정확하다). 임계값 0.9 는 앱의 MAX_LABEL_RATIO 와 같다.
PREVIEW_BOTTOM_INK_H = 18 * SS


def render_preview(
    keys: list[FlickKeyInfo], icons: dict[str, Image.Image], path: Path
) -> list[str]:
    key_w, key_h = PREVIEW_KEY_W, PREVIEW_KEY_H
    cols, rows = 4, 4
    bottom_h = key_h
    width = cols * key_w
    height = rows * key_h + bottom_h

    fg_rgb = rgb("on_keyboard_container")
    img = Image.new("RGB", (width, height), COLORS["keyboard_surface"])
    draw = ImageDraw.Draw(img)

    # 앱과 동일한 아이콘 크기 계산 (KeyboardView.java:596)
    text_size = 0.66 * min(key_w, key_h) * SCALE_TEXT
    side = int(min(key_w, text_size * 1.75))

    by_pos = {(k.row, k.col): k for k in keys}
    for r in range(rows):
        for c in range(cols):
            kx, ky = c * key_w, r * key_h
            key = by_pos.get((r, c))
            # 키 경계를 옅게 그려서 힌트가 옆/아래 키를 침범하는지 눈으로 본다
            draw.rectangle(
                [kx + 2 * SS, ky + 2 * SS, kx + key_w - 2 * SS, ky + key_h - 2 * SS],
                outline=COLORS["outline_variant"],
                width=SS,
            )
            if key is None:
                # 딩굴 첫 줄 오른쪽 끝은 백스페이스
                draw.rounded_rectangle(
                    [kx + 14 * SS, ky + 12 * SS, kx + key_w - 14 * SS, ky + key_h - 12 * SS],
                    radius=10 * SS,
                    fill=COLORS["keyboard_container_variant"],
                )
                icon_backspace(draw, kx + key_w / 2, ky + key_h / 2, key_h * 0.44, fg_rgb)
                continue
            icon = icons[key.asset_name].resize((side, side), Image.LANCZOS)
            tinted = Image.new("RGBA", icon.size, fg_rgb + (0,))
            tinted.putalpha(icon.getchannel("A"))
            img.paste(tinted, (kx + (key_w - side) // 2, ky + (key_h - side) // 2), tinted)

    # 아래 줄. scale_text 는 여기 라벨까지 키우므로 넘치는지 같이 확인한다.
    label_font = calibrated_font(PREVIEW_BOTTOM_INK_H * SCALE_TEXT)
    warnings = draw_bottom_row(draw, PREVIEW_BOTTOM, rows * key_h, bottom_h, label_font)

    save_downsampled(img, path)
    return warnings


# --------------------------------------------------------------------------
# 쿼티 미리보기
#
# 이쪽은 테마와 상관이 없다. flick 이 아닌 레이아웃은 구울 아이콘이 없으므로
# yaml 의 라벨과 롱프레스 힌트를 그대로 그린다. README 에 넣을 도해 용도이고,
# 키 폭과 글자 크기는 실측이 아니라 눈대중이다.
# --------------------------------------------------------------------------


QW_KEY_W, QW_KEY_H = 92 * SS, 118 * SS
QW_WIDTH = 920 * SS
QW_LABEL_INK_H = 38 * SS
QW_HINT_INK_H = 19 * SS

# 아래 줄 키 폭. 합이 QW_WIDTH 다.
QW_BOTTOM_W = [w * SS for w in (130, 100, 70, 300, 90, 110, 120)]

SPECIAL_KEYS: dict[str, tuple[str, str | None]] = {
    "$symbols": ("func", "?123"),
    "$action": ("action", None),
    "$space": ("space", None),
    "$contextual": ("globe", None),
    "$enter": ("enter", None),
    "$shift": ("shift", None),
    "$delete": ("delete", None),
}


def plain_label(spec, warnings: list[str]) -> str:
    """스펙에서 라벨을 뽑는다. 라벨이 통째로 사라지면 원본을 쓰고 경고를 남긴다.

    `|` 하나짜리 스펙이 여기 걸린다. 파서가 첫 `|` 를 라벨/코드 구분자로 보고
    자르기 때문에 라벨이 빈 문자열이 된다.
    """
    raw = str(spec)
    label = spec_label(raw)
    if label or not raw:
        return label
    warnings.append(
        f"{raw!r} 스펙은 라벨이 비어 버린다. 파서가 `|` 를 라벨/코드 구분자로 읽기 "
        f"때문이고, 실기기에서도 글자가 안 나올 수 있으니 `\\|` 로 이스케이프해 볼 것. "
        f"미리보기에는 원본을 그대로 그린다."
    )
    return raw


def parse_plain_key(item, warnings: list[str]) -> tuple[str, str | None, str | None]:
    """flick 이 아닌 키 하나를 (kind, label, hint) 로 바꾼다."""
    if isinstance(item, str):
        if item in SPECIAL_KEYS:
            kind, label = SPECIAL_KEYS[item]
            return kind, label, None
        return "text", plain_label(item, warnings), None
    if isinstance(item, dict):
        return "text", plain_label(item.get("spec", ""), warnings), None
    # [라벨, 롱프레스, 시프트] 형태. 세 번째는 시프트 상태에서만 보이므로 버린다.
    hint = plain_label(item[1], warnings) if len(item) > 1 else None
    return "text", plain_label(item[0], warnings), hint


def qw_row_boxes(keys: list[tuple]) -> list[tuple[float, float]]:
    """행 안에서 각 키가 차지할 x 구간. 시프트/백스페이스만 1.5 배 넓다."""
    weights = [1.5 if k[0] in ("shift", "delete") else 1.0 for k in keys]
    if set(weights) == {1.0}:
        # 글자만 있는 행은 기본 키 폭을 유지하고 가운데로 모은다 (asdf 줄)
        start = (QW_WIDTH - QW_KEY_W * len(keys)) / 2
        return [(start + i * QW_KEY_W, start + (i + 1) * QW_KEY_W) for i in range(len(keys))]
    unit = QW_WIDTH / sum(weights)
    xs = [0.0]
    for w in weights:
        xs.append(xs[-1] + w * unit)
    return list(zip(xs, xs[1:]))


def render_qwerty_preview(yml_path: Path, path: Path) -> list[str]:
    doc = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
    warnings: list[str] = []
    rows: list[list[tuple]] = []
    bottom: list[tuple] = []
    for row in doc["rows"]:
        entries = row.get("letters") or row.get("bottom") or []
        keys = [parse_plain_key(k, warnings) for k in entries]
        if "bottom" in row:
            bottom = keys
        else:
            rows.append(keys)

    height = (len(rows) + 1) * QW_KEY_H
    img = Image.new("RGB", (QW_WIDTH, height), COLORS["keyboard_surface"])
    draw = ImageDraw.Draw(img)
    fg, hint_fg = rgb("on_keyboard_container"), rgb("on_surface_variant")
    label_font = calibrated_font(QW_LABEL_INK_H * SCALE_TEXT)
    hint_font = calibrated_font(QW_HINT_INK_H * SCALE_TEXT)

    for r, keys in enumerate(rows):
        y0, y1 = r * QW_KEY_H, (r + 1) * QW_KEY_H
        for (x0, x1), (kind, label, hint) in zip(qw_row_boxes(keys), keys):
            draw.rectangle(
                [x0 + 2 * SS, y0 + 2 * SS, x1 - 2 * SS, y1 - 2 * SS],
                outline=COLORS["outline_variant"],
                width=SS,
            )
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if kind in FUNCTIONAL_KINDS:
                draw.rounded_rectangle(
                    [x0 + 8 * SS, y0 + 10 * SS, x1 - 8 * SS, y1 - 10 * SS],
                    radius=12 * SS,
                    fill=COLORS["keyboard_container_variant"],
                )
            d = min(x1 - x0, y1 - y0) * 0.42
            if kind == "shift":
                icon_shift(draw, cx, cy, d, fg)
            elif kind == "delete":
                icon_backspace(draw, cx, cy, d * 1.2, fg)
            elif label:
                draw.text((cx, cy), label, font=label_font, anchor="mm", fill=fg)
            if not hint:
                continue
            hx, hy = x1 - (x1 - x0) * 0.24, y0 + (y1 - y0) * 0.26
            if hint.startswith("!icon/"):
                # 지금 쓰이는 건 z 의 탭 하나뿐이다. 모르는 아이콘은 그리지 않는다.
                if "tab" in hint:
                    icon_tab(draw, hx, hy, (x1 - x0) * 0.3, hint_fg)
            else:
                draw.text((hx, hy), hint, font=hint_font, anchor="mm", fill=hint_fg)

    edges = [0]
    for w in QW_BOTTOM_W:
        edges.append(edges[-1] + w)
    boxes = [(x0, x1, *key) for x0, x1, key in zip(edges, edges[1:], bottom)]
    draw_bottom_row(
        draw, boxes, len(rows) * QW_KEY_H, QW_KEY_H,
        calibrated_font(PREVIEW_BOTTOM_INK_H * SCALE_TEXT), hint_font,
    )
    save_downsampled(img, path)
    return warnings


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
        img.save(theme_dir / key.asset_name)
        all_warnings += warnings

    theme_txt = build_theme_txt(keys, layouts, embed_font)
    (theme_dir / "theme.txt").write_text(theme_txt, encoding="utf-8")

    # 버전 파일: version(1B) + epoch millis(8B, little-endian)  (ZipThemes.kt:80)
    version_blob = struct.pack("<bq", 1, int(time.time() * 1000))
    (theme_dir / "FUTOKeyboardTheme_Version").write_bytes(version_blob)

    args.dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = args.dist_dir / f"{THEME_ID}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("FUTOKeyboardTheme_Version", version_blob)
        z.writestr("theme.txt", theme_txt)
        for key in keys:
            buf = io.BytesIO()
            icons[key.asset_name].save(buf, format="PNG")
            z.writestr(key.asset_name, buf.getvalue())
        if embed_font:
            z.write(FONT_PATH, FONT_PATH.name)

    if not args.no_preview:
        all_warnings += render_preview(keys, icons, args.build_dir / "preview.png")
        if args.qwerty_yml.is_file():
            all_warnings += render_qwerty_preview(
                args.qwerty_yml, args.build_dir / "preview_qwerty.png"
            )

    print(
        f"flick 키 {len(keys)}개, 레이아웃 {', '.join(layouts)}, "
        f"scale_text {SCALE_TEXT}, 폰트 {'포함' if embed_font else '미포함'}"
    )
    for key in keys:
        dirs = " ".join(f"{n[0]}:{v}" for n, v in key.directions.items())
        print(f"  r{key.row}c{key.col}  label {key.label!r:8} {dirs}")
    print(f"\n{zip_path}  ({zip_path.stat().st_size / 1024:.0f} KB)")
    if not args.no_preview:
        print(f"{args.build_dir / 'preview.png'}")
        if args.qwerty_yml.is_file():
            print(f"{args.build_dir / 'preview_qwerty.png'}")
    for w in all_warnings:
        print(f"경고: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
