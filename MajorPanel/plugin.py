# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
#  Major Enigma Panel  -  لوحة أوامر لينوكس بواجهة عصرية لـ Enigma2 (OpenATV 7.6 / 8)
#  Python 3 only.  يقرأ ملف الأوامر من GitHub ويعرضه بعرض List وبعدة ثيمات.
#  الصور المدمجة موجودة في الملف assets.py (تُحمَّل عند فتح البانل فقط).
# ---------------------------------------------------------------------------
import base64
import collections
import gc
import glob
import json
import os
import re
import shutil
import ssl
import struct
import sys
import textwrap
import time
import traceback
from urllib.request import Request, urlopen

from enigma import (eConsoleAppContainer, eListboxPythonMultiContent, getDesktop, gFont,
                    ePoint, eSize, eTimer, RT_HALIGN_CENTER, RT_HALIGN_LEFT, RT_HALIGN_RIGHT,
                    RT_VALIGN_CENTER, RT_VALIGN_TOP)
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryPixmapAlphaBlend, MultiContentEntryText
from Components.Pixmap import Pixmap
from Components.ScrollLabel import ScrollLabel
from Plugins.Plugin import PluginDescriptor
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Standby import TryQuitMainloop
from Screens.VirtualKeyBoard import VirtualKeyBoard
from skin import parseColor
from Tools.LoadPixmap import LoadPixmap
from twisted.internet.threads import deferToThread

from .lstparser import parse_commands

try:
    from enigma import BT_SCALE
except ImportError:
    BT_SCALE = 0
try:
    from enigma import RT_WRAP
except ImportError:
    RT_WRAP = 0

try:    # تشغيل الأوامر على طرفية حقيقية (pty) لتظهر الخطوات مثل التيرمنال
    import codecs
    import fcntl
    import pty
    import select
    import signal
    import subprocess
    import termios
    import threading
    HAVE_PTY = True
except Exception:
    HAVE_PTY = False

# ============================ الإعدادات / SETTINGS ===========================
# كل الروابط تُبنى من هذا المتغير الواحد - لتغيير المستودع عدّل السطر التالي فقط
# (وعدّل نفس العنوان في أول installer.sh)
GITHUB_RAW = "https://raw.githubusercontent.com/major79879/Major-Enigma-Panel/refs/heads/main"
COMMANDS_URL = GITHUB_RAW + "/MP_Commands.lst"            # ملف الأوامر
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
TITLE = "Major Enigma Panel"
CREDIT = "By John Kamel"
# تحديث البانل نفسه (إعادة التثبيت) - ملف installer.sh موجود في جذر المستودع (خارج مجلد MajorPanel)
INSTALLER_URL = GITHUB_RAW + "/installer.sh"
PLUGIN_VERSION = "11"                                        # رقم إصدار هذه النسخة (يظهر V11) - غيّره مع كل إصدار
VERSION_URL = GITHUB_RAW + "/Version.txt"                    # ملف الإصدار على GitHub: يحوي رقماً فقط مثل 12
UPDATE_CMD = 'wget -q --no-check-certificate -O - "%s" | /bin/sh -s norestart' % INSTALLER_URL
SETTINGS_FILE = "/etc/enigma2/majorpanel_settings.json"      # عرض البانل + الثيم المختار
RUN_LOG = "/tmp/majorpanel_run.log"                          # سجل تشخيصي لشاشة التنفيذ
ASSET_DIR = "/tmp/majorpanel"                                # صور مؤقتة صغيرة تُحذف عند إغلاق البانل
ERROR_LOG = "/tmp/majorpanel_error.log"
DEFAULT_SETTINGS = {"view": "list", "theme": "blue_fire", "anim": False, "mainmenu": True, "splash": True,
                    "autoupdate": True}
# ============================================================================

# ---- مصدر واحد لتعريف الثيمات (يُستخدم في plugin.py وفي توليد الصور) ----
_BTN = dict(red="#F43F6E", green="#12C97F", yellow="#E9A91A", blue="#2F7CFF")
_OKS = dict(ok="#34E3A0", bad="#FF4D6D", warn="#FFC53D")

THEMES = {
    "classic": dict(
        name="Classic", modern=False,
        bg="#0E1117", card="#161B22", card2="#1C2330", line="#30363D", text="#E6EDF3", muted="#8B949E",
        accent="#58A6FF", second="#3FB950", sel="#1F6FEB", hdr="#1F6FEB", term="#0A0D12",
        red="#DA3633", green="#238636", yellow="#9E6A03", blue="#1F6FEB",
        ok="#3FB950", bad="#F85149", warn="#D29922",
        stops=None, title_set=None, sel_key=None),
    "neon_blue": dict(
        name="Neon Blue", modern=True,
        bg="#050B1E", card="#0B1634", card2="#0E1D42", line="#1D3B66", text="#E8F1FF", muted="#7F95B8",
        accent="#19D3FF", second="#34E3A0", sel="#0D4C8C", hdr="#19D3FF", term="#030816",
        stops=((25, 211, 255), (47, 124, 255), (139, 92, 255), (224, 61, 255), (255, 79, 163)),
        title_set="cool", sel_key="neon_blue",
        fill=((9, 44, 96), (15, 74, 136)), border=(25, 211, 255), **_BTN, **_OKS),
    "orange": dict(
        name="Orange & Black", modern=True,
        bg="#0A0604", card="#170F0A", card2="#22160E", line="#4A2F18", text="#FFF2E3", muted="#B39578",
        accent="#FF8A1F", second="#FFC857", sel="#5A3008", hdr="#FF8A1F", term="#070402",
        stops=((255, 205, 64), (255, 150, 30), (255, 96, 40), (255, 50, 80), (230, 30, 130)),
        title_set="warm", sel_key="orange",
        fill=((64, 32, 4), (118, 62, 10)), border=(255, 138, 31), **_BTN, **_OKS),
    "yellow": dict(
        name="Dark Grey & Yellow", modern=True,
        bg="#0D0E11", card="#17191E", card2="#20232A", line="#3B3E48", text="#F6F5EE", muted="#9C9FA8",
        accent="#FFD21F", second="#FFE57A", sel="#5A4A08", hdr="#FFD21F", term="#08090B",
        stops=((255, 240, 90), (255, 210, 31), (255, 170, 30), (255, 120, 40), (255, 80, 70)),
        title_set="warm", sel_key="yellow",
        fill=((58, 48, 8), (110, 92, 12)), border=(255, 210, 31), **_BTN, **_OKS),
    "green": dict(
        name="Green & Black", modern=True,
        bg="#030A06", card="#09150F", card2="#0F1E17", line="#17392A", text="#E6FFF2", muted="#78A68E",
        accent="#2BFF88", second="#B6FF5C", sel="#0B5A33", hdr="#2BFF88", term="#020805",
        stops=((46, 255, 136), (120, 255, 100), (190, 255, 70), (255, 235, 70), (255, 140, 50)),
        title_set="green", sel_key="green",
        fill=((6, 60, 34), (10, 100, 56)), border=(43, 255, 136), **_BTN, **_OKS),
    "purple": dict(
        name="Purple & Pink", modern=True,
        bg="#08040F", card="#130A26", card2="#1B0F36", line="#33205C", text="#F3EBFF", muted="#9A86C0",
        accent="#B866FF", second="#FF6EC7", sel="#4A1A8A", hdr="#B866FF", term="#05020B",
        stops=((120, 100, 255), (184, 102, 255), (236, 80, 230), (255, 79, 163), (255, 110, 110)),
        title_set="cool", sel_key="purple",
        fill=((46, 14, 90), (86, 26, 150)), border=(184, 102, 255), **_BTN, **_OKS),
    "red": dict(
        name="Red & Black", modern=True,
        bg="#0A0406", card="#180A10", card2="#22111A", line="#45161F", text="#FFECEF", muted="#B58A93",
        accent="#FF2D55", second="#FFA3B5", sel="#7A0F28", hdr="#FF2D55", term="#070204",
        stops=((255, 150, 70), (255, 70, 60), (255, 30, 85), (230, 20, 140), (180, 30, 210)),
        title_set="warm", sel_key="red",
        fill=((86, 10, 26), (140, 16, 44)), border=(255, 45, 85), **_BTN, **_OKS),
    "aqua": dict(
        name="Aqua & Mint", modern=True,
        bg="#031013", card="#081E24", card2="#0C2A32", line="#12485A", text="#E6FFFF", muted="#7BAFB8",
        accent="#00F0D0", second="#7DFFB0", sel="#07555C", hdr="#00F0D0", term="#020C0E",
        stops=((0, 240, 208), (0, 200, 255), (90, 160, 255), (160, 120, 255), (255, 100, 200)),
        title_set="green", sel_key="aqua",
        fill=((6, 66, 72), (10, 108, 112)), border=(0, 240, 208), **_BTN, **_OKS),
    "blue_fire": dict(
        name="Blue Fire", modern=True,
        bg="#050A1C", card="#0A1430", card2="#0E1B3F", line="#223A6E", text="#EAF2FF", muted="#8397BC",
        accent="#2FA8FF", second="#FF9A3D", sel="#14346E", hdr="#2FA8FF", term="#030715",
        stops=((30, 150, 255), (90, 120, 255), (170, 100, 230), (255, 130, 90), (255, 170, 50)),
        title_set="dual", sel_key="blue_fire",
        fill=((6, 22, 60), (30, 18, 30)), border=(47, 168, 255), **_BTN, **_OKS),
    "twilight": dict(
        name="Twilight", modern=True,
        bg="#090717", card="#130F2E", card2="#1A1440", line="#342B6B", text="#F0EEFF", muted="#9490C4",
        accent="#8F86FF", second="#FFB347", sel="#2E2470", hdr="#8F86FF", term="#05040E",
        stops=((90, 120, 255), (150, 100, 255), (220, 100, 200), (255, 140, 90), (255, 190, 70)),
        title_set="dual", sel_key="twilight",
        fill=((16, 12, 52), (36, 18, 36)), border=(143, 134, 255), **_BTN, **_OKS),
    "ember_night": dict(
        name="Ember Night", modern=True,
        bg="#080A18", card="#131528", card2="#1B1D38", line="#3A3560", text="#FFF3E8", muted="#A99EB5",
        accent="#FF9F43", second="#4DB2FF", sel="#5A3410", hdr="#FF9F43", term="#04050E",
        stops=((255, 159, 67), (255, 110, 80), (200, 90, 170), (110, 110, 240), (77, 178, 255)),
        title_set="dual", sel_key="ember_night",
        fill=((38, 18, 6), (8, 20, 56)), border=(255, 159, 67), **_BTN, **_OKS),
    "ocean_sun": dict(
        name="Ocean Sunset", modern=True,
        bg="#04101A", card="#08202E", card2="#0C2B3C", line="#1A4A60", text="#E8FAFF", muted="#7FAEC0",
        accent="#1FD1C6", second="#FF8A65", sel="#0C4A5C", hdr="#1FD1C6", term="#020A10",
        stops=((31, 209, 198), (60, 150, 240), (150, 110, 240), (255, 120, 150), (255, 150, 90)),
        title_set="cool", sel_key="ocean_sun",
        fill=((4, 34, 46), (40, 18, 24)), border=(31, 209, 198), **_BTN, **_OKS),
    "aurora": dict(
        name="Aurora", modern=True,
        bg="#040F10", card="#08202A", card2="#0D2C38", line="#1C4A5C", text="#E8FFFB", muted="#7FB0B0",
        accent="#4DF0C0", second="#9B8CFF", sel="#0B4A4A", hdr="#4DF0C0", term="#020A0C",
        stops=((77, 240, 192), (60, 200, 255), (110, 150, 255), (170, 120, 255), (255, 130, 200)),
        title_set="green", sel_key="aurora",
        fill=((4, 40, 36), (24, 12, 52)), border=(77, 240, 192), **_BTN, **_OKS),
    "royal_gold": dict(
        name="Royal Gold", modern=True,
        bg="#060A18", card="#0E1630", card2="#141E40", line="#2E3A66", text="#FFF7E0", muted="#9AA3BD",
        accent="#F5C451", second="#5AA9FF", sel="#3A3010", hdr="#F5C451", term="#03060F",
        stops=((245, 196, 81), (255, 160, 60), (255, 120, 90), (120, 140, 255), (90, 170, 255)),
        title_set="warm", sel_key="royal_gold",
        fill=((8, 16, 46), (44, 34, 8)), border=(245, 196, 81), **_BTN, **_OKS),
    "sakura": dict(
        name="Sakura Neon", modern=True,
        bg="#12060E", card="#1E0C18", card2="#2A1121", line="#5A2547", text="#FFEAF4", muted="#C493AE",
        accent="#FF5FA2", second="#FFC46B", sel="#6A1F47", hdr="#FF5FA2", term="#0B0309",
        stops=((255, 95, 162), (255, 130, 140), (255, 170, 110), (255, 200, 107), (255, 226, 150)),
        title_set="warm", sel_key="sakura",
        fill=((54, 12, 36), (40, 20, 26)), border=(255, 95, 162), **_BTN, **_OKS),
    "glacier": dict(
        name="Glacier", modern=True,
        bg="#050C14", card="#0A1826", card2="#0E2236", line="#24476A", text="#EAF7FF", muted="#88A9C4",
        accent="#7DE3FF", second="#B8A6FF", sel="#124E78", hdr="#7DE3FF", term="#030811",
        stops=((125, 227, 255), (110, 190, 255), (150, 160, 255), (184, 166, 255), (220, 190, 255)),
        title_set="cool", sel_key="glacier",
        fill=((8, 38, 64), (24, 24, 56)), border=(125, 227, 255), **_BTN, **_OKS),
    "crimson_gold": dict(
        name="Crimson Gold", modern=True,
        bg="#0D0505", card="#1A0A0A", card2="#261010", line="#5A2222", text="#FFF1E6", muted="#C09A86",
        accent="#FF6A3D", second="#FFC83D", sel="#6B1D12", hdr="#FF6A3D", term="#080303",
        stops=((240, 60, 90), (255, 100, 70), (255, 150, 50), (255, 200, 61), (255, 226, 120)),
        title_set="warm", sel_key="crimson_gold",
        fill=((60, 10, 16), (52, 34, 8)), border=(240, 60, 90), **_BTN, **_OKS),
    "violet_storm": dict(
        name="Violet Storm", modern=True,
        bg="#0A0618", card="#140D2C", card2="#1B1240", line="#3C2A7A", text="#F1EBFF", muted="#A094CC",
        accent="#B26BFF", second="#4DC8FF", sel="#3A1F8A", hdr="#B26BFF", term="#06030F",
        stops=((178, 107, 255), (140, 110, 255), (90, 140, 255), (77, 200, 255), (100, 235, 230)),
        title_set="cool", sel_key="violet_storm",
        fill=((36, 14, 80), (10, 36, 72)), border=(178, 107, 255), **_BTN, **_OKS),
    "cyber_lime": dict(
        name="Cyber Lime", modern=True,
        bg="#070D06", card="#0F1A0C", card2="#162512", line="#345A22", text="#F1FFE6", muted="#98B88A",
        accent="#B6F23A", second="#3AD6C8", sel="#3E6A10", hdr="#B6F23A", term="#040803",
        stops=((182, 242, 58), (120, 230, 90), (58, 214, 200), (60, 170, 255), (110, 130, 255)),
        title_set="green", sel_key="cyber_lime",
        fill=((30, 58, 10), (8, 44, 50)), border=(182, 242, 58), **_BTN, **_OKS),
    "graphite": dict(
        name="Graphite", modern=False,
        bg="#121416", card="#1A1D21", card2="#22262B", line="#343A41", text="#E9ECEF", muted="#9AA3AD",
        accent="#4FD1C5", second="#F6AD55", sel="#2C7A7B", hdr="#2C7A7B", term="#0C0E10",
        red="#D9534F", green="#2F9E6B", yellow="#B7832F", blue="#2C7A7B",
        ok="#4FD1A1", bad="#F26D6D", warn="#E5B14A",
        stops=None, title_set=None, sel_key=None),
    "midnight_indigo": dict(
        name="Midnight Indigo", modern=False,
        bg="#0F1220", card="#171B30", card2="#1E2340", line="#343C66", text="#E6E9FB", muted="#98A0C8",
        accent="#8B9CFF", second="#7EE0B5", sel="#3A4AA8", hdr="#4C5FD5", term="#0A0D18",
        red="#D6506B", green="#2FA37A", yellow="#BE8F2E", blue="#4C5FD5",
        ok="#6EE0AE", bad="#FF6B86", warn="#E8C15A",
        stops=None, title_set=None, sel_key=None),
    "forest": dict(
        name="Forest", modern=False,
        bg="#0C1511", card="#131F19", card2="#1A2A22", line="#2B4538", text="#E4F1EA", muted="#8CAA9B",
        accent="#56D39B", second="#E6C45A", sel="#1F7A57", hdr="#1F8F63", term="#08100C",
        red="#CF4F4A", green="#2E9E62", yellow="#B8912A", blue="#2F7F9E",
        ok="#56D39B", bad="#F26B66", warn="#E6C45A",
        stops=None, title_set=None, sel_key=None),
    "warm_slate": dict(
        name="Warm Slate", modern=False,
        bg="#14161A", card="#1C2027", card2="#252A33", line="#3A414D", text="#F0EDE8", muted="#A7A39B",
        accent="#F0B445", second="#6FB7FF", sel="#8A5E12", hdr="#C98A1C", term="#0E1013",
        red="#D4524A", green="#3AA06A", yellow="#C98A1C", blue="#3C7FD0",
        ok="#5CCB8A", bad="#F0675E", warn="#F0B445",
        stops=None, title_set=None, sel_key=None),
    "rose_dusk": dict(
        name="Rose Dusk", modern=False,
        bg="#16101A", card="#1F1725", card2="#291E31", line="#433050", text="#F3E9F4", muted="#AE98B5",
        accent="#F08BB4", second="#8FD3C8", sel="#8E3A66", hdr="#B04B80", term="#0F0A13",
        red="#D9507F", green="#3BA38F", yellow="#C08B3A", blue="#7A6AD0",
        ok="#7ED9B7", bad="#FF6F9A", warn="#F2C265",
        stops=None, title_set=None, sel_key=None),
}
MODERN_ORDER = ["blue_fire", "twilight", "ember_night", "ocean_sun", "aurora", "royal_gold",
                "sakura", "glacier", "crimson_gold", "violet_storm", "cyber_lime",
                "neon_blue", "orange", "yellow", "green", "purple", "red", "aqua"]
CLASSIC_ORDER = ["classic", "graphite", "midnight_indigo", "forest", "warm_slate", "rose_dusk"]

_state = dict(DEFAULT_SETTINGS)


def load_settings():
    """Reads theme / animation / menu settings from disk into _state and returns it."""
    data = {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        pass
    theme = data.get("theme", DEFAULT_SETTINGS["theme"])
    view = data.get("view", DEFAULT_SETTINGS["view"])
    _state["view"] = view if view in ("list", "grid") else DEFAULT_SETTINGS["view"]
    _state["theme"] = theme if theme in THEMES else DEFAULT_SETTINGS["theme"]
    _state["anim"] = bool(data.get("anim", DEFAULT_SETTINGS["anim"]))
    _state["mainmenu"] = bool(data.get("mainmenu", DEFAULT_SETTINGS["mainmenu"]))
    _state["splash"] = bool(data.get("splash", DEFAULT_SETTINGS["splash"]))
    _state["autoupdate"] = bool(data.get("autoupdate", DEFAULT_SETTINGS["autoupdate"]))
    return _state


def save_settings(theme, anim=False, mainmenu=True, splash=True, view="list", autoupdate=True):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"view": view, "theme": theme, "anim": bool(anim), "mainmenu": bool(mainmenu), "splash": bool(splash),
                       "autoupdate": bool(autoupdate)}, f)
        return True
    except Exception:
        return False


def menu_enabled():
    """Show the panel in the image's main Menu?  (Settings -> Main Menu)"""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("mainmenu", True))
    except Exception:
        return DEFAULT_SETTINGS["mainmenu"]


def release_actions(actionmap):
    """Unbind an ActionMap ONLY if the framework has not already done it. A second unbind of the same
    keys while the screen below (the TV infobar) is being re-bound can leave the remote's arrow keys dead."""
    try:
        if getattr(actionmap, "execActive", False):
            actionmap.execEnd()
    except Exception as e:
        dlog_error("release_actions: %s" % e)


def safe(fn):
    """Key handler wrapper: an exception inside a key press must never break the screen (it is logged)."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            dlog_error("key handler %s failed:\n%s" % (getattr(fn, "__name__", "?"), traceback.format_exc()))
    return wrapper


def T():
    """Current theme dict."""
    return THEMES.get(_state["theme"]) or THEMES["neon_blue"]


def tc():
    t = T()
    return dict(bg=t["bg"], card=t["card"], card2=t["card2"], line=t["line"], text=t["text"], muted=t["muted"],
                acc=t["accent"], second=t["second"], sel=t["sel"], hdr=t["hdr"], term=t["term"],
                red=t["red"], green=t["green"], yellow=t["yellow"], blue=t["blue"],
                ok=t["ok"], bad=t["bad"], warn=t["warn"])


_W = max(getDesktop(0).size().width(), 1280)
_H = max(getDesktop(0).size().height(), 720)
SC = _W / 1920.0


def s(v):
    """Scale a 1920x1080 design value to the current desktop resolution."""
    return int(round(v * SC))


def rect(x, y, w, h):
    return 'position="%d,%d" size="%d,%d"' % (s(x), s(y), s(w), s(h))


def hexint(h):
    return int(h.lstrip("#"), 16)


def ring_hex(th):
    """'#RRGGBB' of the theme's emblem ring - used by the version number and the INSTALL / INSTALLED badge."""
    b = th.get("border")
    if b:
        return "#%02X%02X%02X" % tuple(b)
    return th["accent"]


def setColor(widget, hexcolor):
    try:
        widget.instance.setForegroundColor(parseColor(hexcolor))
    except Exception:
        pass


def dlog(msg):
    """Tiny diagnostic log (/tmp/majorpanel_run.log) - helps to debug the execution screen."""
    try:
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


# ------------------------------ تحميل البيانات ومعلومات الجهاز -----------------
def _fetch(url, timeout=20):
    ctx = ssl._create_unverified_context()      # بعض الصور بدون شهادات CA
    sep = "&" if "?" in url else "?"
    req = Request(url + sep + "t=%d" % int(time.time()),
                  headers={"User-Agent": "MajorPanel/1.0", "Cache-Control": "no-cache"})
    return urlopen(req, timeout=timeout, context=ctx).read().decode("utf-8", "ignore")



def load_online():
    """Runs in a worker thread. Returns (text, 'online') or raises."""
    text = _fetch(COMMANDS_URL)
    if "+++" not in text:
        raise ValueError("bad file")
    return text, "online"


def read_file(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return default


def _boxinfo(*keys):
    try:
        from Components.SystemInfo import BoxInfo
    except Exception:
        return ""
    for k in keys:
        try:
            v = BoxInfo.getItem(k)
            if v:
                return str(v)
        except Exception:
            pass
    return ""


def _branding(*names):
    try:
        import boxbranding
    except Exception:
        return ""
    for n in names:
        try:
            v = getattr(boxbranding, n)()
            if v:
                return str(v)
        except Exception:
            pass
    return ""


def get_box_details():
    """Returns (display title, image info text, [ids used to find the box picture])."""
    brand = _boxinfo("displaybrand", "machinebrand", "brand") or _branding("getMachineBrand")
    name = _boxinfo("displaymodel", "machinename", "model") or _branding("getMachineName")
    build_id = (_boxinfo("machinebuild", "model") or _branding("getBoxType")
                or read_file("/proc/stb/info/boxtype") or read_file("/proc/stb/info/model"))
    if not name:
        name = build_id
    if brand and name and brand.lower() not in name.lower():
        title = "%s %s" % (brand, name)
    else:
        title = name or "Enigma2"

    distro = _boxinfo("distro") or _branding("getImageDistro") or "OpenATV"
    if distro.lower() == "openatv":
        distro = "OpenATV"
    version = _boxinfo("imageversion") or _branding("getImageVersion")
    build = _boxinfo("imagebuild") or _branding("getImageBuild")
    image = distro
    if version:
        image += " " + version
    if build:
        image += "  (build %s)" % build
    return title, image, [build_id, _boxinfo("model"), name, title]


def get_cpu():
    """CPU line: chipset / SoC (+ architecture and number of cores), e.g. 'BCM72604 | ARMv8 | 4 cores'."""
    info = read_file("/proc/cpuinfo")
    cores = len(re.findall(r"^processor\s*:", info, re.M))

    def field(*keys):
        for key in keys:
            m = re.search(r"^%s\s*:\s*(.+)$" % re.escape(key), info, re.M | re.I)
            if m and m.group(1).strip():
                return m.group(1).strip()
        return ""

    chip = _boxinfo("socfamily", "chipset") or read_file("/proc/stb/info/chipset") or field("Hardware")
    if not chip:
        model = field("cpu model")                                  # MIPS: "Broadcom BMIPS5000 V1.0"
        chip = re.sub(r"^broadcom\s+", "", model, flags=re.I)
    chip = chip.strip().upper()
    if re.match(r"^\d{4}\w*$", chip):                               # "7252S" -> "BCM7252S"
        chip = "BCM" + chip
    try:
        machine = os.uname().machine.lower()
    except Exception:
        machine = ""
    arch = {"aarch64": "ARMv8", "armv8l": "ARMv8", "armv7l": "ARMv7", "armv7": "ARMv7", "mips": "MIPS",
            "mipsel": "MIPS"}.get(machine, machine.upper())
    parts = [p for p in (chip, arch) if p]
    if cores:
        parts.append("%d core%s" % (cores, "" if cores == 1 else "s"))
    return " | ".join(parts) or "Unknown"


def png_size(path):
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except Exception:
        pass
    return None


def find_box_image(ids):
    names = []
    for i in ids:
        if not i:
            continue
        for n in (i, i.lower(), i.replace(" ", "").lower(), i.replace(" ", "_").lower()):
            if n not in names:
                names.append(n)
    dirs = ["/usr/share/enigma2/receivers", "/usr/share/enigma2/boxes",
            "/usr/share/enigma2/skin_default/receivers", os.path.join(PLUGIN_DIR, "boxes")]
    try:
        from Tools.Directories import resolveFilename, SCOPE_GUISKIN
        dirs.insert(0, resolveFilename(SCOPE_GUISKIN, "receivers"))
    except Exception:
        pass
    for n in names:
        for d in dirs:
            p = os.path.join(d, n + ".png")
            if os.path.isfile(p):
                return p
    for n in names:                         # بحث أوسع داخل مجلدات السكن
        for pattern in ("/usr/share/enigma2/*/%s.png", "/usr/share/enigma2/*/*/%s.png"):
            hits = glob.glob(pattern % n)
            if hits:
                return hits[0]
    default = os.path.join(PLUGIN_DIR, "boxes", "default.png")
    return default if os.path.isfile(default) else _default_box_image()


def get_meminfo():
    """(used MB, total MB)"""
    info = {}
    for line in read_file("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        try:
            info[k] = int(v.split()[0])
        except Exception:
            pass
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable")
    if avail is None:
        avail = info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0)
    return max(total - avail, 0) / 1024.0, total / 1024.0


def get_ip():
    """IPv4 address of the receiver: eth0 first, then any other active interface."""
    import socket
    try:
        import fcntl as _fcntl
        try:
            names = sorted(os.listdir("/sys/class/net"), key=lambda n: (n != "eth0", n))
        except OSError:
            names = []
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for name in names:
                if name == "lo":
                    continue
                try:
                    raw = _fcntl.ioctl(sock.fileno(), 0x8915,                  # SIOCGIFADDR
                                       struct.pack("256s", name[:15].encode()))[20:24]
                    ip = socket.inet_ntoa(raw)
                except OSError:
                    continue
                if not ip.startswith(("127.", "0.")):
                    return ip
        finally:
            sock.close()
    except Exception:
        pass
    try:                                        # بديل: عنوان المصدر للمسار الافتراضي
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))       # UDP: لا يُرسل أي شيء فعلياً
            return sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        return None


def fmt_size(nbytes):
    gb = nbytes / (1024.0 ** 3)
    if gb >= 1000:
        return "%.2f TB" % (gb / 1024.0)
    return "%d GB" % round(gb)


def fmt_pair(used, total):
    """'359 / 916 GB' (or TB) - same look as the RAM line."""
    if total / (1024.0 ** 3) >= 1000:
        return "%.2f / %.2f TB" % (used / 1024.0 ** 4, total / 1024.0 ** 4)
    return "%d / %d GB" % (round(used / 1024.0 ** 3), round(total / 1024.0 ** 3))


def get_hdd():
    """First mounted external disk (USB / SATA, /dev/sdX) or None."""
    found = []
    for line in read_file("/proc/mounts").splitlines():
        parts = line.split()
        if len(parts) >= 3 and re.match(r"^/dev/sd[a-z]+\d*$", parts[0]):
            found.append((parts[0], parts[1].replace("\\040", " "), parts[2]))
    if not found:
        return None
    dev, mount, fstype = next((m for m in found if m[1] == "/media/hdd"), found[0])
    try:
        st = os.statvfs(mount)
    except Exception:
        return None
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    free = st.f_bavail * st.f_frsize
    base = re.sub(r"\d+$", "", os.path.basename(dev))
    model = " ".join(read_file("/sys/block/%s/device/%s" % (base, k)) for k in ("vendor", "model")).strip()
    return {"mount": mount, "fstype": fstype, "used": used, "free": free,
            "total": used + free, "model": model}


# ------------------------------ الصور المدمجة --------------------------------
# assets.py كبير (صور base64): نستخرج منه فقط ما يلزم الثيم والعرض المختارين إلى /tmp،
# ثم نحذف الوحدة من الذاكرة فوراً. وعند إغلاق البانل يُحذف مجلد /tmp/majorpanel بالكامل.
_icon_cache = {}


def asset_path(name):
    return os.path.join(ASSET_DIR, name + ".png")


def pix(name):
    """Pixmap of an extracted asset (None if missing)."""
    p = asset_path(name)
    try:
        return LoadPixmap(p) if os.path.isfile(p) else None
    except Exception:
        return None


def release_assets():
    """Drop the big assets module from RAM."""
    try:
        pkg = sys.modules.get(__package__)
        if pkg is not None and hasattr(pkg, "assets"):
            delattr(pkg, "assets")
        sys.modules.pop((__package__ or "") + ".assets", None)
    except Exception:
        pass
    gc.collect()


def cleanup_assets():
    _icon_cache.clear()
    shutil.rmtree(ASSET_DIR, ignore_errors=True)
    gc.collect()


def dlog_error(msg):
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _put(name, data):
    with open(asset_path(name), "wb") as f:
        f.write(base64.b64decode(data))


def prep_assets(theme_key, anim, splash=False, view="list"):
    """Extracts only the pictures needed for this theme / animation setting."""
    try:
        from . import assets as a
    except Exception as e:
        dlog_error("assets.py not available: %s" % e)
        return False
    ok = False
    try:
        _icon_cache.clear()
        shutil.rmtree(ASSET_DIR, ignore_errors=True)
        os.makedirs(ASSET_DIR, exist_ok=True)
        th = THEMES.get(theme_key) or THEMES["neon_blue"]
        _put("logo", a.LOGO)
        if splash:
            _put("splash", a.SPLASH)
        _put("box_default", a.DEFAULT_BOX)
        if th["modern"]:
            glow = a.LOGO_GLOW
            if anim:
                for i, g in enumerate(glow):
                    _put("lg%d" % i, g)
            else:
                _put("lg_static", glow[min(3, len(glow) - 1)])
            fam = a.TITLE[th["title_set"]]
            _put("tglow", fam["glow"])
            for i, fr in enumerate(fam["frames"] if anim else fam["frames"][:1]):
                _put("f%02d" % i, fr)
        wanted = ("tile", "tile_bg") if view == "grid" else ("cats", "items")
        for kind, data in (a.SEL.get(theme_key) or {}).items():
            if kind in wanted:
                _put("sel_%s_%s" % (kind, theme_key), data)
        seg = a.SEG[theme_key]
        _put("seg_off", seg["off"])
        for i, d_ in enumerate(seg["on"]):
            _put("seg_on%d" % i, d_)
        for size in ((64, 96) if view == "grid" else (48,)):
            for key, data in getattr(a, "ICONS%d" % size).items():
                _put("ic%d_%s" % (size, key), data)
        _put("pill", a.PILLS[theme_key]["off"])
        if view == "grid":
            _put("emblem", a.EMBLEM[theme_key])
        ok = True
    except Exception as e:
        dlog_error("prep_assets failed: %s" % e)
    del a
    release_assets()
    return ok


def _default_box_image():
    p = asset_path("box_default")
    return p if os.path.isfile(p) else None


# ------------------------------ أيقونات الأقسام ------------------------------
# الكلمة (جزء من اسم القسم، بحروف صغيرة) -> اسم الأيقونة. الترتيب مهم.
ICON_RULES = (
    ("fast", "bolt"), ("panel", "panel"), ("tool", "tools"), ("cam", "key"),
    ("audio", "audio"), ("sub", "cc"), ("epg", "epg"), ("iptv", "tv"),
    ("skin", "skin"), ("setting", "settings"), ("media", "media"),
    ("channel", "dish"), ("picon", "picon"), ("boot", "power"), ("logo", "power"),
    ("image", "disc"), ("spinner", "spinner"), ("feed", "rss"),
    ("backup", "backup"), ("restore", "restore"), ("other", "puzzle"),
)


def icon_key(cat_name):
    n = cat_name.lower()
    if n == "all":
        return "all"
    if n.startswith("search:"):
        return "search"
    for word, icon in ICON_RULES:
        if word in n:
            return icon
    return "grid"


def get_icon(cat_name, size=48):
    """Pixmap of a category icon (48 px).
    A file icons/<name>.png next to plugin.py overrides the built-in one."""
    key = icon_key(cat_name)
    ck = (key, size)
    if ck not in _icon_cache:
        ptr = None
        try:
            own = os.path.join(PLUGIN_DIR, "icons", key + ".png")
            ptr = LoadPixmap(own) if os.path.isfile(own) else pix("ic%d_%s" % (size, key))
        except Exception:
            ptr = None
        _icon_cache[ck] = ptr
    return _icon_cache[ck]


# ------------------------------ مساعدات الـ Skin ------------------------------
BAR_SEGS = 30


def wid(name, r, font=None, fg=None, bg=None, halign=None, valign=None, z=2, extra="", transparent=True):
    a = ['<widget name="%s" %s' % (name, rect(*r))]
    if font:
        a.append('font="Regular;%d"' % s(font))
    if fg:
        a.append('foregroundColor="%s"' % fg)
    a.append('backgroundColor="%s"' % (bg or T()["card"]))
    if transparent:
        a.append('transparent="1"')
    if halign:
        a.append('halign="%s"' % halign)
    if valign:
        a.append('valign="%s"' % valign)
    a.append('zPosition="%d"' % z)
    if extra:
        a.append(extra)
    return " ".join(a) + "/>"


def box(r, color, radius=0, z=0):
    return '<eLabel %s backgroundColor="%s"%s zPosition="%d"/>' % (
        rect(*r), color, (' cornerRadius="%d"' % s(radius)) if radius else "", z)


def pixw(name, r, z=2):
    return '<widget name="%s" %s alphatest="blend" scale="1" zPosition="%d"/>' % (name, rect(*r), z)


def setVisible(widget, on):
    try:
        inst = widget.instance
        if inst:
            inst.show() if on else inst.hide()
    except Exception:
        pass


def noNativeKeys(screen):
    """Our screens move their lists from their own ActionMap, so the lists must not also grab the remote's
    arrow keys natively (an experiment against arrow keys staying dead in other screens after the panel)."""
    total = off = 0
    has = False
    try:
        for v in screen.values():
            inst = getattr(v, "instance", None)
            if inst is not None and hasattr(inst, "setSelectionEnable"):          # a list widget
                total += 1
                if hasattr(inst, "allowNativeKeys"):
                    has = True
                    try:
                        inst.allowNativeKeys(False)
                        off += 1
                    except Exception as e:
                        dlog_error("allowNativeKeys: %s" % e)
    except Exception as e:
        dlog_error("noNativeKeys: %s" % e)
    dlog("native keys off for %d of %d lists (allowNativeKeys available: %s)" % (off, total, has))


def barw(name, r, bg, z=3):
    """A one-row list used as a neon bar (the segments are pictures drawn by the list)."""
    return ('<widget name="%s" %s backgroundColor="%s" backgroundColorSelected="%s" scrollbarMode="showNever" '
            'transparent="0" zPosition="%d"/>' % (name, rect(*r), bg, bg, z))


def sel_attr(kind, w, h):
    """selectionPixmap attribute (neon border) for a list. Pictures are pixel-exact (1920 wide
    desktops only) and exist only for the Modern themes; otherwise the solid color is used."""
    t = T()
    p = asset_path("sel_%s_%s" % (kind, _state["theme"]))
    if not t["modern"] or s(w) != w or not os.path.isfile(p):
        return ""
    return ' selectionPixmap="%s"' % p


def device_layout(y0, pic_h):
    """Vertical layout (design px) of the receiver-info block inside a card starting at y0."""
    L = {}
    y = y0 + 13
    L["model"] = (y, 40); y += 42
    L["pic"] = (y, pic_h); y += pic_h + 2
    L["image"] = (y, 28); y += 28
    L["py"] = (y, 28); y += 28
    L["ip"] = (y, 30); y += 32
    L["cpu"] = (y, 30); y += 36
    L["ram"] = (y, 30); y += 32
    L["ram_track"] = (y, 10); y += 20
    L["hdd"] = (y, 30); y += 32
    L["hdd_track"] = (y, 10)
    return L


def device_xml(L, x=1340, width=510):
    c = tc()
    out = [
        wid("b_model", (x, L["model"][0], width, L["model"][1]), font=30, fg="#FFFFFF", halign="center", valign="center"),
        pixw("box_pic", (x, L["pic"][0], width, L["pic"][1])),
        wid("b_image", (x, L["image"][0], width, L["image"][1]), font=22, fg=c["muted"], halign="center", valign="center"),
        wid("b_py", (x, L["py"][0], width, L["py"][1]), font=22, fg=c["second"], halign="center", valign="center"),
        wid("b_ip", (x, L["ip"][0], width, L["ip"][1]), font=24, fg=c["acc"], halign="center", valign="center"),
        wid("b_cpu", (x, L["cpu"][0], width, L["cpu"][1]), font=24, fg=c["text"], halign="center", valign="center"),
        wid("b_ram", (x, L["ram"][0], width, L["ram"][1]), font=24, fg=c["text"], halign="center", valign="center"),
        barw("ram_bar", (x, L["ram_track"][0], width, 10), c["card"]),
        wid("b_hdd", (x, L["hdd"][0], width, L["hdd"][1]), font=24, fg=c["text"], halign="center", valign="center"),
        barw("hdd_bar", (x, L["hdd_track"][0], width, 10), c["card"]),
    ]
    return "\n".join(out)


def header_xml():
    t = T()
    c = tc()
    out = [
        box((0, 0, 1920, 110), c["card"]),
        '<eLabel position="0,%d" size="%d,%d" backgroundColor="%s" zPosition="1"/>' % (s(106), _W, max(2, s(4)), c["hdr"]),
        wid("title", (156, 20, 520, 70), font=46, fg=(c["acc"] if t["modern"] else "#FFFFFF"), valign="center"),
        pixw("title_glow", (146, 13, 520, 84)),
        pixw("title_img", (146, 13, 520, 84), z=3),
        pixw("logo_glow", (34, 5, 100, 100)),
        pixw("logo_img", (34, 5, 100, 100), z=3),
        wid("credit", (686, 20, 400, 70), font=24, fg=c["muted"], valign="center", extra='noWrap="1"'),
        wid("h_ver", (925, 20, 160, 70), font=36, fg=ring_hex(t), halign="center", valign="center"),
        wid("h_server", (1090, 20, 340, 70), font=28, fg=c["warn"], halign="right", valign="center"),
        wid("clock", (1560, 4, 300, 62), font=52, fg="#FFFFFF", halign="right", valign="center"),
        wid("date", (1440, 66, 420, 36), font=24, fg=c["muted"], halign="right", valign="center"),
    ]
    return "\n".join(out)


def buttons_xml(hint_extra=""):
    c = tc()
    out = []
    for name, x, w, col in (("key_red", 40, 440, c["red"]), ("key_green", 500, 440, c["green"]),
                            ("key_yellow", 960, 440, c["yellow"]), ("key_blue", 1420, 460, c["blue"])):
        out.append('<widget name="%s" %s font="Regular;%d" foregroundColor="#FFFFFF" backgroundColor="%s" '
                   'cornerRadius="%d" halign="center" valign="center" zPosition="2"/>' % (
                       name, rect(x, 955, w, 66), s(30), col, s(16)))
    out.append(wid("hint", (40, 1030, 1840, 40), font=22, fg=c["muted"], bg=c["bg"], halign="center", valign="center"))
    return "\n".join(out)


# --------------------------------- الشاشة الأساسية ---------------------------
SERVER_OFFLINE_MSG = u"تعذّر الاتصال بسيرفر البانل - تحقق من الإنترنت | Cannot connect to panel server"

# سياقات الأزرار المعتادة فقط. (لا نربط سياقات وضع التلفاز مثل InfobarChannelSelection حتى لا نؤثر
# على أزرار الاتجاهات بعد الخروج من البانل)
ACTION_CONTEXTS = ["OkCancelActions", "ColorActions", "DirectionActions", "NavigationActions",
                   "EPGSelectActions", "MenuActions"]


class PanelBase(Screen):
    NO_NATIVE = False                   # Grid: القوائم لا تلتقط أسهم الريموت بنفسها
    """Everything shared by the panel screens: header, clock, server state, device info
    (RAM / HDD / IP ...), animated title, loading the commands, search, install, settings."""
    DEV = device_layout(575, 72)          # lower-right card
    PIC = (1340, DEV["pic"][0], 510, DEV["pic"][1])      # always the same area the layout reserved
    HINT = ""

    def __init__(self, session):
        self.t = T()
        self.skin = self.buildSkin()
        Screen.__init__(self, session)
        self.setTitle(TITLE)
        self.allcats = []       # [(cat, [items])]
        self.cats = []          # current view (all or search results)
        self.catIdx = 0
        self.query = ""
        self.barKey = {}
        self.segPix = None
        self.titleFrames = []
        self.glowFrames = []
        self.titleIdx = 0
        self.glowIdx = 0
        self.tick = 0

        for name in ("title", "credit", "h_ver", "h_server", "clock", "date", "b_model", "b_image", "b_py", "b_ip",
                     "b_cpu", "b_ram", "b_hdd"):
            self[name] = Label("")
        self["title"].setText(TITLE)
        self["credit"].setText(CREDIT)
        self["h_ver"].setText(u"V" + PLUGIN_VERSION)
        for name in ("title_glow", "title_img", "logo_glow", "logo_img", "box_pic"):
            self[name] = Pixmap()
        for prefix in ("ram", "hdd"):
            self["%s_bar" % prefix] = MenuList([], content=eListboxPythonMultiContent)
            self["%s_bar" % prefix].l.setItemHeight(s(10))
        self["key_red"] = Label(u"خروج | Exit")
        self["key_green"] = Label(u"تثبيت | Install")
        self["key_yellow"] = Label(u"بحث | Search")
        self["key_blue"] = Label(u"تحديث الأوامر | Refresh")
        self["hint"] = Label(self.HINT)
        self.createViewWidgets()

        keys = {
            "ok": self.askInstall, "green": self.askInstall,
            "cancel": self.exit, "red": self.exit,
            "yellow": self.search,
            "blue": self.refresh,                       # تحديث الأوامر
            "menu": self.openSettings,                  # الإعدادات
            "info": self.askUpdate,                     # تحديث البانل نفسه
            "left": self.keyLeft, "right": self.keyRight,
            "up": self.keyUp, "down": self.keyDown,
            "pageUp": self.prevCat, "pageDown": self.nextCat,
        }
        self["actions"] = ActionMap(ACTION_CONTEXTS, dict((k, safe(v)) for k, v in keys.items()), -1)

        self.closing = False
        self.tickCount = 0
        self.tickTimer = self.makeTimer(self.onTick)        # مؤقت واحد: الساعة كل 2 ثانية والإحصاءات كل 4
        self.titleTimer = self.makeTimer(self.titleTick)    # للحركة فقط (اختياري)
        self.onClose.append(self.releaseAll)
        self.onExecBegin.append(self.resumeTitle)
        self.onExecEnd.append(self.pauseTitle)
        self.onLayoutFinish.append(self.start)

    def makeTimer(self, callback):
        tm = eTimer()
        try:
            tm.callback.append(callback)
        except AttributeError:
            if not hasattr(self, "_tconn"):
                self._tconn = []
            self._tconn.append(tm.timeout.connect(callback))
        return tm

    # ---- to be provided by the views ----
    def buildSkin(self):
        raise NotImplementedError

    def createViewWidgets(self):
        pass

    def buildView(self, keepCat=None):
        pass

    def currentItem(self):
        return None

    def keyLeft(self):
        pass

    def keyRight(self):
        pass

    def keyUp(self):
        pass

    def keyDown(self):
        pass

    def onCatChanged(self):
        pass

    # ----------------------------- بدء التشغيل -------------------------------
    def start(self):
        if self.NO_NATIVE:
            noNativeKeys(self)
        reset_installed_cache()
        self.loadSegments()
        self.loadTitle()
        self.showBoxInfo()
        self.updateStats()
        self.updateClock()
        self.tickTimer.start(2000, False)
        self.refresh()

    def onTick(self):
        self.tickCount += 1
        self.updateClock()
        if self.tickCount % 2 == 0:
            self.updateStats()

    def releaseAll(self):
        """On close: stop and DISCONNECT the timers (so the screen can be freed), unbind the keys
        explicitly (nothing may stay bound after the panel is closed) and free pictures / data."""
        self.closing = True
        for tm in (self.tickTimer, self.titleTimer):
            try:
                tm.stop()
                del tm.callback[:]
            except Exception:
                pass
        self._tconn = []
        release_actions(self["actions"])
        try:
            self.freeMemory()
        except Exception as e:
            dlog_error("freeMemory: %s" % e)

    def freeMemory(self):
        """Release pictures and data as soon as the screen closes."""
        self.segPix = None
        self.titleFrames = []
        self.glowFrames = []
        self.allcats = []
        self.cats = []
        gc.collect()

    def updateClock(self):
        self["clock"].setText(time.strftime("%H:%M"))
        self["date"].setText(time.strftime("%A %d %B"))

    # ---------------------- اللوجو واسم البانل المتحرك -----------------------
    def loadTitle(self):
        anim = _state["anim"]
        try:
            logo = pix("logo")
            if logo and self["logo_img"].instance:
                self["logo_img"].instance.setPixmap(logo)
                self["logo_img"].instance.show()
            if self.t["modern"]:
                names = ["lg%d" % i for i in range(5)] if anim else ["lg_static"]
                glow = [pix(n) for n in names]
                if glow and all(glow) and self["logo_glow"].instance:
                    self["logo_glow"].instance.setPixmap(glow[min(3, len(glow) - 1)])
                    self["logo_glow"].instance.show()
                    if anim:
                        self.glowFrames = glow
                frames = [pix("f%02d" % i) for i in range(12 if anim else 1)]
                tglow = pix("tglow")
                if tglow and frames and all(frames) and self["title_img"].instance:
                    self["title_glow"].instance.setPixmap(tglow)
                    self["title_glow"].instance.show()
                    self["title_img"].instance.setPixmap(frames[0])
                    self["title_img"].instance.show()
                    self["title"].hide()
                    if anim:
                        self.titleFrames = frames
        except Exception as e:
            dlog_error("loadTitle: %s" % e)
            self.titleFrames = []
            self.glowFrames = []
        self.resumeTitle()

    def titleTick(self):
        self.tick += 1
        if self.titleFrames:
            self.titleIdx = (self.titleIdx + 1) % len(self.titleFrames)
            self["title_img"].instance.setPixmap(self.titleFrames[self.titleIdx])
        if self.glowFrames and self.tick % 2 == 0:      # نبض هادئ لتوهج اللوجو
            n = len(self.glowFrames)
            self.glowIdx = (self.glowIdx + 1) % (2 * n - 2)
            self["logo_glow"].instance.setPixmap(
                self.glowFrames[self.glowIdx if self.glowIdx < n else 2 * n - 2 - self.glowIdx])

    def pauseTitle(self):
        self.titleTimer.stop()

    def resumeTitle(self):
        if _state["anim"] and (self.titleFrames or self.glowFrames):
            self.titleTimer.start(90, False)

    # ----------------------------- تحميل الأوامر -----------------------------
    def refresh(self):
        self.setServer("connecting")
        d = deferToThread(load_online)
        d.addCallback(self.onlineOK)
        d.addErrback(self.onlineFail)

    def onlineOK(self, result):
        if self.closing:
            return
        text, src = result
        self.setServer("online")
        self.setData(text)

    def onlineFail(self, failure):
        if not self.closing:
            self.setServer("offline")

    def setServer(self, state):
        """state: online | offline | connecting  (shown at the top as: Server: Online ...)"""
        label, color = {"online": ("Online", self.t["ok"]),
                        "offline": ("Offline", self.t["bad"]),
                        "connecting": ("Connecting...", self.t["warn"])}[state]
        self["h_server"].setText("Server:  " + label)
        setColor(self["h_server"], color)
        if state == "offline":
            self["hint"].setText(SERVER_OFFLINE_MSG)
            setColor(self["hint"], self.t["bad"])
        else:
            self["hint"].setText(self.HINT)
            setColor(self["hint"], self.t["muted"])

    def setData(self, text):
        try:
            data = parse_commands(text)
        except Exception as e:
            self["hint"].setText("Parse error: %s" % e)
            return
        keepCat = self.cats[self.catIdx][0] if self.cats else None
        self.allcats = data
        self.buildView(keepCat)

    def categoriesFor(self, keepCat=None):
        """Applies the search query; fills self.cats (with "All" first) and self.catIdx."""
        if self.query:
            q = self.query.lower()
            hits = [it for c, items in self.allcats for it in items
                    if q in (u"%s %s %s %s" % (it["name"], it["author"], it["desc"], c)).lower()]
            self.cats = [(u"Search: %s" % self.query, hits)]
        else:
            everything = [it for _, items in self.allcats for it in items]
            self.cats = ([("All", everything)] + list(self.allcats)) if everything else list(self.allcats)
        self.catIdx = 0
        if keepCat:
            for i, (n, _) in enumerate(self.cats):
                if n == keepCat:
                    self.catIdx = i
                    break

    # ------------------------- معلومات الجهاز --------------------------------
    def showBoxInfo(self):
        try:
            title, image, ids = get_box_details()
        except Exception:
            title, image, ids = "Enigma2", "", []
        self["b_model"].setText(title)
        self["b_image"].setText(image)
        self["b_py"].setText("Python %d.%d.%d" % tuple(sys.version_info[:3]))
        try:
            self["b_cpu"].setText("CPU   %s" % get_cpu())
        except Exception as e:
            dlog_error("get_cpu: %s" % e)
        try:
            path = find_box_image(ids)
            if path:
                self.setBoxPicture(path)
        except Exception:
            pass

    def setBoxPicture(self, path):
        inst = self["box_pic"].instance
        ptr = LoadPixmap(path)
        if not inst or not ptr:
            return
        px, py, pw, ph = self.PIC
        maxw, maxh = s(pw), s(ph)
        size = png_size(path) or (maxw, maxh)
        ratio = min(maxw / float(size[0]), maxh / float(size[1]))
        w, h = max(1, int(size[0] * ratio)), max(1, int(size[1] * ratio))
        try:
            inst.setScale(1)
        except Exception:
            pass
        inst.resize(eSize(w, h))
        inst.move(ePoint(s(px) + (maxw - w) // 2, s(py) + (maxh - h) // 2))
        inst.setPixmap(ptr)
        inst.show()

    def loadSegments(self):
        n = BAR_SEGS if self.t["stops"] else 3
        on = [pix("seg_on%d" % i) for i in range(n)]
        self.segPix = {"off": pix("seg_off"), "on": on}
        for prefix in ("ram", "hdd"):
            lst = self["%s_bar" % prefix]
            try:
                lst.instance.setSelectionEnable(0)
            except Exception:
                pass

    def setBar(self, prefix, pct):
        """Neon LED bar: the first N gradient segments are lit (more colors appear as it fills).
        In the Classic theme all lit segments take one color that follows the usage level.
        Drawn by ONE list widget per bar (no per-segment widgets)."""
        pixs = self.segPix
        if not pixs or not pixs["off"]:
            return
        on = 0 if pct <= 0 else max(1, int(round(BAR_SEGS * min(pct, 100.0) / 100.0)))
        level = -1 if self.t["stops"] else (0 if pct < 75 else (1 if pct < 90 else 2))
        key = (on, level)
        if self.barKey.get(prefix) == key:
            return
        self.barKey[prefix] = key
        pitch = 510.0 / BAR_SEGS
        row = [prefix]
        for i in range(BAR_SEGS):
            if i < on:
                ptr = pixs["on"][i if level < 0 else level]
            else:
                ptr = pixs["off"]
            if ptr:
                row.append(MultiContentEntryPixmapAlphaBlend(
                    pos=(s(i * pitch), 0), size=(max(2, s(pitch - 3)), s(10)), png=ptr, flags=BT_SCALE))
        self["%s_bar" % prefix].setList([row])

    def updateStats(self):
        try:                                            # عنوان IP
            ip = get_ip()
            if ip:
                self["b_ip"].setText("IP Address   %s" % ip)
                setColor(self["b_ip"], self.t["accent"])
            else:
                self["b_ip"].setText("IP Address   Not connected")
                setColor(self["b_ip"], self.t["muted"])
        except Exception:
            pass
        try:                                            # الرام
            used, total = get_meminfo()
            if total:
                pct = used * 100.0 / total
                self["b_ram"].setText("RAM   %d / %d MB   (%d%%)" % (used, total, pct))
                self.setBar("ram", pct)
        except Exception:
            pass
        try:                                            # الهارد الخارجي
            hdd = get_hdd()
            if hdd and hdd["total"]:
                pct = hdd["used"] * 100.0 / hdd["total"]
                label = "USB" if "usb" in hdd["mount"].lower() else "HDD"
                self["b_hdd"].setText("%s   %s   (%d%%)" % (label, fmt_pair(hdd["used"], hdd["total"]), pct))
                self.setBar("hdd", pct)
            else:
                self["b_hdd"].setText("HDD   Not connected")
                self.setBar("hdd", 0)
        except Exception:
            pass
        self.extraStats()

    def extraStats(self):
        pass

    # ----------------------------- التنقل بين الأقسام ------------------------
    def prevCat(self):
        self.moveCat(-1)

    def nextCat(self):
        self.moveCat(1)

    def moveCat(self, step):
        if len(self.cats) < 2:
            return
        self.catIdx = (self.catIdx + step) % len(self.cats)
        self.onCatChanged()

    # ----------------------------- البحث -------------------------------------
    def search(self):
        self.session.openWithCallback(self.searchDone, VirtualKeyBoard,
                                      title=u"Search (leave empty to clear)", text=self.query)

    def searchDone(self, text=None):
        if text is None:
            return
        self.query = text.strip()
        self.buildView()

    # ----------------------------- تنفيذ -------------------------------------
    def askInstall(self):
        it = self.currentItem()
        if not it:
            return
        self.session.openWithCallback(
            self.confirmed, MessageBox,
            u"%s\n\nتنفيذ التثبيت الآن؟\nInstall now?" % it["name"],
            MessageBox.TYPE_YESNO)

    def confirmed(self, answer):
        it = self.currentItem()
        if answer and it:
            self.hide()                     # يظهر الفيديو خلف نافذة التيرمنال
            run_item(self.session, it, VERB_INSTALL, self.afterRun)

    def afterRun(self, *args):
        if not self.closing:
            try:
                self.show()
            except Exception:
                pass
            reset_installed_cache()
            try:
                self.refreshInstalled()
            except Exception as e:
                dlog_error("refreshInstalled: %s" % e)

    def refreshInstalled(self):
        pass

    # ------------------------- الإعدادات وتحديث البانل -----------------------
    def openSettings(self):
        self.session.openWithCallback(self.settingsDone, SettingsScreen)

    def settingsDone(self, changed=False):
        if changed:
            self.close("reopen")            # يعيد فتح البانل بالعرض والثيم الجديدين

    def askUpdate(self):
        self.session.openWithCallback(
            self.confirmUpdate, MessageBox,
            u"تحديث Major Enigma Panel بالكامل (إعادة التثبيت)؟\nUpdate / reinstall the whole panel now?",
            MessageBox.TYPE_YESNO)

    def confirmUpdate(self, answer):
        if answer:
            self.hide()
            run_item(self.session, update_item(), VERB_UPDATE, self.afterRun)

    def exit(self):
        if self.closing:
            return
        self.closing = True
        self.close()


INSTALLED_FILE = "/etc/enigma2/majorpanel_installed.json"     # ما نُفّذ بنجاح من البانل
_installed = {"keys": None, "sys": None}
ACTION_WORDS = ("update", "remove", "uninstall", "delete", "clean", "fix", "restore", "backup", "reset", "restart", "install")


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def item_key(it):
    return "%s|%s" % (_norm(it.get("cat")), _norm(it.get("name")))


def load_installed():
    if _installed["keys"] is None:
        try:
            with open(INSTALLED_FILE, "r", encoding="utf-8") as f:
                _installed["keys"] = set(json.load(f).get("keys", []))
        except Exception:
            _installed["keys"] = set()
    return _installed["keys"]


def mark_installed(it):
    """Remembers an item whose command finished with exit code 0 (the update item of the panel itself is ignored)."""
    if not it or not it.get("cat"):
        return
    keys = load_installed()
    keys.add(item_key(it))
    try:
        with open(INSTALLED_FILE, "w", encoding="utf-8") as f:
            json.dump({"keys": sorted(keys)}, f)
    except Exception as e:
        dlog_error("mark_installed: %s" % e)


def system_names():
    """Normalized names of plugin folders and installed opkg packages (cached until the panel is reopened / a run ends)."""
    if _installed["sys"] is None:
        names = set()
        base = "/usr/lib/enigma2/python/Plugins"
        for sub in ("Extensions", "SystemPlugins"):
            try:
                for d in os.listdir(os.path.join(base, sub)):
                    n = _norm(d)
                    if len(n) >= 3:
                        names.add(n)
            except Exception:
                pass
        try:
            with open("/var/lib/opkg/status", "r", encoding="utf-8", errors="ignore") as f:
                for block in f.read().split("\n\n"):
                    if "install ok installed" not in block:
                        continue
                    for line in block.split("\n"):
                        if line.startswith("Package:"):
                            raw = re.sub(r"^enigma2-plugin-(extensions|systemplugins|softcams|skins|picons|settings|drivers|channel-settings)?-?",
                                         "", line.split(":", 1)[1].strip().lower())
                            n = _norm(raw)
                            if len(n) >= 3:
                                names.add(n)
                            break
        except Exception:
            pass
        _installed["sys"] = names
    return _installed["sys"]


def reset_installed_cache():
    _installed["keys"] = None
    _installed["sys"] = None


def installed_checker():
    """Returns check(item) -> True if the item was installed by this panel or a plugin with a matching name is on the box."""
    keys = load_installed()
    names = system_names()

    def check(it):
        if item_key(it) in keys:
            return True
        n = _norm(it.get("name"))
        if len(n) < 3:
            return False
        if n in names:
            return True
        if n.startswith(ACTION_WORDS):          # "Update X" / "Remove X" are actions, not the plugin itself
            return False
        for x in names:
            short, long_ = (n, x) if len(n) <= len(x) else (x, n)
            if len(short) >= 6 and short in long_ and len(short) >= 0.75 * len(long_):
                return True
        return False
    return check


def fetch_remote_version(holder):
    """Worker thread: reads Version.txt from GitHub. holder gets ver (str) or error, then done=True."""
    try:
        text = _fetch(VERSION_URL, timeout=4)
        lines = text.strip().splitlines()
        v = re.sub(r"^[vV]\s*", "", lines[0].strip()) if lines else ""
        if re.match(r"^[0-9A-Za-z._-]{1,20}$", v):
            holder["ver"] = v
        else:
            holder["error"] = "bad version file"
    except Exception as e:
        holder["error"] = str(e)
    holder["done"] = True


def update_item():
    return {"name": u"Major Enigma Panel", "cmd": UPDATE_CMD, "author": "", "desc": "", "cat": ""}


# --------------------------------- عرض القائمة (List) -------------------------
class ListPanel(PanelBase):
    HINT = ("LEFT / RIGHT : category     UP / DOWN : select     OK : install     "
            "BLUE : refresh     MENU : settings     INFO : update panel")

    def buildSkin(self):
        c = tc()
        sa_c, sa_i = sel_attr("cats", 390, 84), sel_attr("items", 770, 100)
        lst = ('<widget name="%s" %s backgroundColor="%s" backgroundColorSelected="%s" foregroundColor="%s" '
               'foregroundColorSelected="#FFFFFF" scrollbarMode="showNever"%s transparent="0" zPosition="2"/>')
        parts = [
            '<screen name="MajorPanelList" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (_W, _H, c["bg"]),
            header_xml(),
            box((40, 135, 420, 800), c["card"], 24),
            lst % ("cats", rect(55, 150, 390, 770), c["card"], c["card"] if sa_c else c["sel"], c["text"], sa_c),
            box((485, 135, 800, 800), c["card"], 24),
            lst % ("items", rect(500, 150, 770, 770), c["card"], c["card"] if sa_i else c["sel"], c["text"], sa_i),
            box((1310, 135, 570, 430), c["card"], 24),
            wid("d_cat", (1340, 153, 360, 40), font=26, fg=c["acc"]),
            wid("d_count", (1700, 153, 150, 40), font=26, fg=c["muted"], halign="right"),
            wid("d_name", (1340, 198, 510, 100), font=38, fg="#FFFFFF", valign="top"),
            wid("d_author", (1340, 302, 510, 40), font=28, fg=c["second"]),
            box((1340, 352, 510, 2), c["line"], z=2),
            wid("d_desc_h", (1340, 364, 510, 34), font=24, fg=c["acc"], halign="right"),
            wid("d_desc", (1340, 402, 510, 150), font=32, fg=c["text"], halign="right", valign="top"),
            box((1310, 575, 570, 360), c["card"], 24),
            device_xml(self.DEV),
            buttons_xml(),
            '</screen>',
        ]
        return "\n".join(parts)

    def createViewWidgets(self):
        self["cats"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        self["items"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        for name, big, small, h in (("cats", 28, 24, 84), ("items", 34, 26, 100)):
            lst = self[name].l
            lst.setFont(0, gFont("Regular", s(big)))
            lst.setFont(1, gFont("Regular", s(small)))
            lst.setFont(2, gFont("Regular", s(20)))
            lst.setItemHeight(s(h))
        self["d_cat"] = Label("")
        self["d_count"] = Label("")
        self["d_name"] = Label("")
        self["d_author"] = Label("")
        self["d_desc_h"] = Label(u"شرح الإضافة")
        self["d_desc"] = Label("")

    def buildView(self, keepCat=None):
        self.categoriesFor(keepCat)
        t = self.t
        txt, mut, sec = hexint(t["text"]), hexint(t["muted"]), hexint(t["second"])
        rows = []
        for n, items in self.cats:
            row = [n]
            icon = get_icon(n, 48)
            if icon:
                row.append(MultiContentEntryPixmapAlphaBlend(pos=(s(18), s(20)), size=(s(44), s(44)),
                                                             png=icon, flags=BT_SCALE))
            row.append(MultiContentEntryText(pos=(s(76), 0), size=(s(236), s(84)), font=0,
                                             flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=n,
                                             color=txt, color_sel=0xFFFFFF))
            row.append(MultiContentEntryText(pos=(s(316), 0), size=(s(62), s(84)), font=1,
                                             flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=str(len(items)),
                                             color=mut, color_sel=0xFFFFFF))
            rows.append(row)
        self["cats"].setList(rows)
        self["cats"].moveToIndex(self.catIdx)
        self.fillItems()

    def fillItems(self):
        t = self.t
        txt, sec = hexint(t["text"]), hexint(t["second"])
        acc = hexint(ring_hex(t))
        items = self.cats[self.catIdx][1] if self.cats else []
        check = installed_checker()
        pill = pix("pill")
        rows = []
        for it in items:
            done = check(it)
            row = [it,
                   MultiContentEntryText(pos=(s(24), s(8)), size=(s(540), s(46)), font=0,
                                         flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=it["name"],
                                         color=txt, color_sel=0xFFFFFF),
                   MultiContentEntryText(pos=(s(24), s(56)), size=(s(540), s(36)), font=1,
                                         flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
                                         text=it["author"] or it["cat"],
                                         color=sec, color_sel=0xDDEEFF)]
            if pill:
                row.append(MultiContentEntryPixmapAlphaBlend(pos=(s(574), s(28)), size=(s(180), s(44)),
                                                             png=pill, flags=BT_SCALE))
            row.append(MultiContentEntryText(pos=(s(574), s(28)), size=(s(180), s(44)), font=2,
                                             flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER,
                                             text="INSTALLED" if done else "INSTALL",
                                             color=acc, color_sel=acc))
            rows.append(row)
        self["items"].setList(rows)
        if rows:
            self["items"].moveToIndex(0)
        self.updateDetails()

    def refreshInstalled(self):
        """After a run: redraw the rows (badges) and keep the selected row."""
        idx = self["items"].getSelectionIndex() if self["items"].list else 0
        self.fillItems()
        if self["items"].list:
            self["items"].moveToIndex(min(idx, len(self["items"].list) - 1))
            self.updateDetails()

    def currentItem(self):
        cur = self["items"].getCurrent()
        return cur[0] if cur else None

    def updateDetails(self):
        it = self.currentItem()
        if not it:
            for k in ("d_cat", "d_count", "d_name", "d_author"):
                self[k].setText("")
            self["d_desc"].setText(u"لا توجد نتائج | No results" if self.query else "")
            return
        total = len(self.cats[self.catIdx][1])
        self["d_cat"].setText(it["cat"])
        self["d_count"].setText("%d / %d" % (self["items"].getSelectionIndex() + 1, total))
        self["d_name"].setText(it["name"])
        self["d_author"].setText((u"by " + it["author"]) if it["author"] else "")
        self["d_desc"].setText(it["desc"] or u"—")

    def onCatChanged(self):
        self["cats"].moveToIndex(self.catIdx)
        self.fillItems()

    def keyLeft(self):
        self.moveCat(-1)

    def keyRight(self):
        self.moveCat(1)

    def keyUp(self):
        self["items"].up()
        self.updateDetails()

    def keyDown(self):
        self["items"].down()
        self.updateDetails()

# --------------------------------- عرض الشبكة (Grid) -------------------------
GRID_COLS, GRID_ROWS = 8, 2
GRID_PER = GRID_COLS * GRID_ROWS
TILE_W, TILE_H = 218, 170
TILE_PITCH, TILE_YPITCH = 230, 184
STAT_LABELS = ("SECTIONS", "IN SECTION", "TOTAL", "UPTIME")


def get_uptime():
    try:
        return float(read_file("/proc/uptime").split()[0])
    except Exception:
        return 0.0


def fmt_uptime(sec):
    sec = int(sec)
    d, h, m = sec // 86400, (sec % 86400) // 3600, (sec % 3600) // 60
    return "%dd %dh" % (d, h) if d else "%dh %02dm" % (h, m)


class GridPanel(PanelBase):
    NO_NATIVE = True
    """Light Grid view: ONE list widget draws the 16 tiles of the page (pictures + text),
    so the screen has only a handful of widgets."""
    DEV = device_layout(125, 110)
    PIC = (1340, DEV["pic"][0], 510, 110)
    HINT = ("ARROWS : move     UP / DOWN at the edge (or PAGE keys) : sections     OK : install     "
            "BLUE : refresh     MENU : settings")

    def buildSkin(self):
        c = tc()
        parts = [
            '<screen name="MajorPanelGrid" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (_W, _H, c["bg"]),
            header_xml(),
            # --- منطقة العنوان والتفاصيل ---
            wid("g_cap", (40, 135, 700, 34), font=24, fg=c["acc"], bg=c["bg"]),
            wid("g_sec", (40, 170, 960, 76), font=56, fg="#FFFFFF", bg=c["bg"], valign="center"),
            wid("g_name", (40, 252, 960, 46), font=36, fg=c["text"], bg=c["bg"], valign="center"),
            wid("g_author", (40, 298, 960, 34), font=26, fg=c["second"], bg=c["bg"]),
            wid("g_desc", (40, 336, 960, 96), font=30, fg=c["text"], bg=c["bg"], halign="right", valign="top"),
            # --- بطاقة الأرقام ---
            box((40, 446, 960, 74), c["card"], 18),
        ]
        for i in range(4):
            x = 40 + i * 240
            parts.append(wid("st%d_v" % i, (x, 450, 240, 40), font=36, fg="#FFFFFF", halign="center", valign="center"))
            parts.append(wid("st%d_l" % i, (x, 490, 240, 26), font=18, fg=c["muted"], halign="center", valign="center"))
            if i:
                parts.append(box((x, 458, 2, 54), c["line"], z=2))
        parts += [
            # --- الشعار الكبير للقسم (حلقة جاهزة كصورة + أيقونة) ---
            pixw("emb_bg", (1022, 142, 256, 256), z=1),
            pixw("emb_ic", (1102, 222, 96, 96), z=3),
            pixw("g_pill", (1035, 438, 230, 52), z=3),
            wid("g_pilltxt", (1035, 438, 230, 52), font=28, fg=c["text"], halign="center", valign="center", z=4),
            # --- معلومات الجهاز ---
            box((1310, 125, 570, 395), c["card"], 24),
            device_xml(self.DEV),
            # --- كل البلاطات في قائمة واحدة ---
            ] + self.tileWidgets() + [
            wid("g_page", (40, 912, 800, 34), font=22, fg=c["muted"], bg=c["bg"]),
            buttons_xml(),
            '</screen>',
        ]
        return "\n".join(parts)

    def tileWidgets(self):
        c = tc()
        out = []
        # قائمتان حقيقيتان مخفيتان (مثل وضع List تماماً): تتبعان المحدد ولا ترسمان شيئاً
        for name in ("cats", "items"):
            out.append('<widget name="%s" %s backgroundColor="%s" backgroundColorSelected="%s" '
                       'scrollbarMode="showNever" transparent="1" zPosition="1"/>' % (
                           name, rect(40, 540, 20, 20), c["bg"], c["bg"]))
        for i in range(GRID_PER):
            r, col = divmod(i, GRID_COLS)
            x, y = 40 + col * TILE_PITCH, 540 + r * TILE_YPITCH
            out.append(pixw("tb%d" % i, (x, y, TILE_W, TILE_H), z=2))
            out.append(pixw("ti%d" % i, (x + 77, y + 22, 64, 64), z=4))
            out.append(wid("tt%d" % i, (x + 8, y + 98, TILE_W - 16, 66), font=22, fg=c["text"], bg=c["bg"],
                           halign="center", valign="top", z=4))
        out.append(pixw("tsel", (40, 540, TILE_W, TILE_H), z=3))
        return out

    def createViewWidgets(self):
        for n in ("g_cap", "g_sec", "g_name", "g_author", "g_desc", "g_page"):
            self[n] = Label("")
        for i in range(4):
            self["st%d_v" % i] = Label("")
            self["st%d_l" % i] = Label(STAT_LABELS[i])
        self["emb_bg"] = Pixmap()
        self["g_pill"] = Pixmap()
        self["g_pilltxt"] = Label("")
        self["emb_ic"] = Pixmap()
        for i in range(GRID_PER):
            self["tb%d" % i] = Pixmap()
            self["ti%d" % i] = Pixmap()
            self["tt%d" % i] = Label("")
        self["tsel"] = Pixmap()
        for name in ("cats", "items"):                      # نفس نوع قوائم وضع List
            self[name] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
            self[name].l.setFont(0, gFont("Regular", s(22)))
            self[name].l.setItemHeight(s(20))
        self.sel = 0
        self.tilePix = None
        self.tileBgPix = None

    # ------------------------------ بدء التشغيل ------------------------------
    def start(self):
        self.tilePix = pix("sel_tile_%s" % _state["theme"])
        self.tileBgPix = pix("sel_tile_bg_%s" % _state["theme"])
        try:
            if self.tileBgPix:
                for i in range(GRID_PER):
                    if self["tb%d" % i].instance:
                        self["tb%d" % i].instance.setPixmap(self.tileBgPix)
            if self.tilePix and self["tsel"].instance:
                self["tsel"].instance.setPixmap(self.tilePix)
        except Exception as e:
            dlog_error("grid tiles: %s" % e)
        try:
            emb = pix("emblem")
            if emb and self["emb_bg"].instance:
                self["emb_bg"].instance.setPixmap(emb)
                self["emb_bg"].instance.show()
        except Exception:
            pass
        PanelBase.start(self)

    def freeMemory(self):
        self.tilePix = None
        self.tileBgPix = None
        PanelBase.freeMemory(self)

    # --------------------------------- العرض ---------------------------------
    def buildView(self, keepCat=None):
        self.categoriesFor(keepCat)
        self.sel = 0
        self.fillLists()
        self.refreshGrid()

    def items(self):
        return self.cats[self.catIdx][1] if self.cats else []

    def currentItem(self):
        items = self.items()
        return items[self.sel] if 0 <= self.sel < len(items) else None

    def pageStart(self):
        return (self.sel // GRID_PER) * GRID_PER

    def fillLists(self):
        """The two hidden real lists (same type as the List view): categories + items of the current category."""
        rows = [[n] for n, _ in self.cats]
        self["cats"].setList(rows)
        if rows:
            self["cats"].moveToIndex(self.catIdx)
        self.fillItemsList()

    def fillItemsList(self):
        items = self.items()
        self["items"].setList([[it] for it in items])
        if items:
            self["items"].moveToIndex(0)

    def fillPage(self):
        items = self.items()
        n = len(items)
        start = self.pageStart()
        cat = self.cats[self.catIdx][0] if self.cats else ""
        icon = get_icon(cat, 64) if cat else None
        for i in range(GRID_PER):
            idx = start + i
            on = idx < n
            setVisible(self["tb%d" % i], on)
            setVisible(self["tt%d" % i], on)
            setVisible(self["ti%d" % i], bool(on and icon))
            if on:
                self["tt%d" % i].setText(items[idx]["name"])
                if icon:
                    try:
                        if self["ti%d" % i].instance:
                            self["ti%d" % i].instance.setPixmap(icon)
                    except Exception:
                        pass

    def placeSel(self):
        n = len(self.items())
        try:
            if n:
                self["items"].moveToIndex(self.sel)
        except Exception:
            pass
        inst = self["tsel"].instance
        if not inst:
            return
        if not n or not self.tilePix:
            inst.hide()
            return
        r, c = divmod(self.sel - self.pageStart(), GRID_COLS)
        inst.move(ePoint(s(40 + c * TILE_PITCH), s(540 + r * TILE_YPITCH)))
        inst.show()

    def buildRows(self):
        self.fillPage()
        self.placeSel()

    def refreshGrid(self):
        n = len(self.items())
        self.sel = min(self.sel, max(n - 1, 0))
        self.buildRows()
        self.updateHero()

    def updateHero(self):
        items = self.items()
        n = len(items)
        cat = self.cats[self.catIdx][0] if self.cats else ""
        self["g_cap"].setText("SECTION %02d / %02d" % (self.catIdx + 1, len(self.cats)) if self.cats else "")
        self["g_sec"].setText(cat.upper())
        it = self.currentItem()
        if it:
            self["g_name"].setText(it["name"])
            self["g_author"].setText((u"by " + it["author"]) if it["author"] else it["cat"])
            self["g_desc"].setText(it["desc"] or u"—")
        else:
            self["g_name"].setText("")
            self["g_author"].setText("")
            self["g_desc"].setText(u"لا توجد نتائج | No results" if self.query else "")
        self.showBadge(it)
        pages = max(1, (n + GRID_PER - 1) // GRID_PER)
        self["g_page"].setText("PAGE %d/%d     %d plugins" % (self.sel // GRID_PER + 1, pages, n) if n else "")
        try:
            big = get_icon(cat, 96) if cat else None
            if big and self["emb_ic"].instance:
                self["emb_ic"].instance.setPixmap(big)
                self["emb_ic"].instance.show()
        except Exception:
            pass
        total = sum(len(i) for _, i in self.allcats)
        self["st0_v"].setText(str(len(self.allcats)))
        self["st1_v"].setText(str(n))
        self["st2_v"].setText(str(total))
        self["st3_v"].setText(fmt_uptime(get_uptime()))

    def showBadge(self, it):
        """INSTALL / INSTALLED pill of the selected item (under the big emblem)."""
        try:
            done = bool(it) and installed_checker()(it)
            inst = self["g_pill"].instance
            pm = pix("pill")
            if it and pm and inst:
                inst.setPixmap(pm)
                inst.show()
            elif inst:
                inst.hide()
            if it:
                self["g_pilltxt"].setText("INSTALLED" if done else "INSTALL")
                setColor(self["g_pilltxt"], ring_hex(self.t))
            else:
                self["g_pilltxt"].setText("")
        except Exception as e:
            dlog_error("showBadge: %s" % e)

    def refreshInstalled(self):
        self.updateHero()

    def extraStats(self):
        try:
            self["st3_v"].setText(fmt_uptime(get_uptime()))
        except Exception:
            pass

    # -------------------------------- التنقل ---------------------------------
    def onCatChanged(self):
        self.sel = 0
        self.fillItemsList()
        try:
            self["cats"].moveToIndex(self.catIdx)
        except Exception:
            pass
        self.refreshGrid()

    def moveSel(self, delta):
        n = len(self.items())
        if not n:
            return
        new = min(max(self.sel + delta, 0), n - 1)
        if new == self.sel:
            return
        old_page = self.pageStart()
        self.sel = new
        if self.pageStart() != old_page:
            self.fillPage()                 # صفحة جديدة: نملأ البلاطات من جديد
        self.placeSel()                     # وإلا نحرّك إطار التحديد فقط
        self.updateHero()

    def keyLeft(self):
        self.moveSel(-1)

    def keyRight(self):
        self.moveSel(1)

    def keyUp(self):
        if self.sel < GRID_COLS and len(self.cats) > 1:         # أعلى صف: القسم السابق
            self.moveCat(-1)
        else:
            self.moveSel(-GRID_COLS)

    def keyDown(self):
        n = len(self.items())
        if n and self.sel // GRID_COLS >= (n - 1) // GRID_COLS and len(self.cats) > 1:   # آخر صف: القسم التالي
            self.moveCat(1)
        else:
            self.moveSel(GRID_COLS)


# --------------------------------- شاشة الإعدادات -----------------------------
SETTINGS_ROWS = ("view", "style", "color", "anim", "splash", "autoupdate", "mainmenu", "update")


def settings_skin():
    c = tc()
    parts = [
        '<screen name="MajorPanelSettings" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (_W, _H, c["bg"]),
        box((0, 0, 1920, 110), c["card"]),
        '<eLabel position="0,%d" size="%d,%d" backgroundColor="%s" zPosition="1"/>' % (s(106), _W, max(2, s(4)), c["hdr"]),
        wid("s_title", (60, 20, 1000, 70), font=46, fg="#FFFFFF", valign="center"),
        box((360, 150, 1200, 790), c["card"], 24),
        '<widget name="rows" %s backgroundColor="%s" backgroundColorSelected="%s" foregroundColor="%s" '
        'foregroundColorSelected="#FFFFFF" scrollbarMode="showNever" transparent="0" zPosition="2"/>' % (
            rect(390, 175, 1140, 510), c["card"], c["sel"], c["text"]),
        wid("s_prev", (390, 690, 1140, 40), font=26, fg=c["acc"], valign="center"),
    ]
    parts.append('<widget name="swatches" %s backgroundColor="%s" backgroundColorSelected="%s" scrollbarMode="showNever" '
                 'transparent="1" zPosition="2"/>' % (rect(390, 735, 1140, 90), c["card"], c["card"]))
    parts += [
        wid("s_note", (390, 830, 1140, 108), font=22, fg=c["muted"], valign="top"),
        '<widget name="key_red" %s font="Regular;%d" foregroundColor="#FFFFFF" backgroundColor="%s" cornerRadius="%d" '
        'halign="center" valign="center" zPosition="2"/>' % (rect(500, 955, 440, 66), s(30), c["red"], s(16)),
        '<widget name="key_green" %s font="Regular;%d" foregroundColor="#FFFFFF" backgroundColor="%s" cornerRadius="%d" '
        'halign="center" valign="center" zPosition="2"/>' % (rect(980, 955, 440, 66), s(30), c["green"], s(16)),
        wid("hint", (40, 1030, 1840, 40), font=22, fg=c["muted"], bg=c["bg"], halign="center", valign="center"),
        '</screen>',
    ]
    return "\n".join(parts)


class SettingsScreen(Screen):
    def __init__(self, session):
        self.t = T()
        self.skin = settings_skin()
        Screen.__init__(self, session)
        st = load_settings()
        self.orig = (st["view"], st["theme"], st["anim"])
        self.view = st["view"]
        self.anim = st["anim"]
        self.mainmenu = st["mainmenu"]
        self.splash = st["splash"]
        self.autoupdate = st["autoupdate"]
        cur = st["theme"] if st["theme"] in THEMES else MODERN_ORDER[0]
        is_modern = THEMES[cur]["modern"]
        self.style = "modern" if is_modern else "classic"
        self.color = cur if is_modern else MODERN_ORDER[0]          # لون Modern المختار
        self.ccolor = cur if not is_modern else CLASSIC_ORDER[0]    # لون Classic المختار

        self["s_title"] = Label(u"الإعدادات | Settings")
        self["rows"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        self["rows"].l.setFont(0, gFont("Regular", s(34)))
        self["rows"].l.setItemHeight(s(64))
        self["s_prev"] = Label("")
        self["swatches"] = MenuList([], content=eListboxPythonMultiContent)
        self["swatches"].l.setFont(0, gFont("Regular", s(20)))
        self["swatches"].l.setItemHeight(s(90))
        self["s_note"] = Label(u"Animation (الاسم واللوجو المتحركان) أجمل لكنه يستهلك معالجاً وذاكرة أكثر - الأفضل إيقافه للأداء الأخف.\n"
                               u"Main Menu: إظهار البانل في القائمة الرئيسية للصورة (Menu).\nAuto Check Update: فحص تحديث البانل عند فتحها، يعمل مع شاشة Splash.\nChanges apply after saving; the panel reopens by itself.")
        self["key_red"] = Label(u"إلغاء | Cancel")
        self["key_green"] = Label(u"حفظ وتطبيق | Save & Apply")
        self["hint"] = Label("LEFT / RIGHT : change     UP / DOWN : select     OK : on 'Update panel' runs the update")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {"ok": self.ok, "green": self.save, "red": self.cancel, "cancel": self.cancel,
             "left": self.left, "right": self.right, "up": self.up, "down": self.down}, -1)
        self.onLayoutFinish.append(self.refreshAll)
        self.onClose.append(self.releaseKeys)

    def themeKey(self):
        return self.color if self.style == "modern" else self.ccolor

    def refreshAll(self):
        idx = self["rows"].getSelectionIndex() if self["rows"].list else 0
        txt, mut, acc = hexint(self.t["text"]), hexint(self.t["muted"]), hexint(self.t["accent"])
        modern = self.style == "modern"
        values = (
            ("View", "List" if self.view == "list" else "Grid", True),
            ("Style", "Classic" if self.style == "classic" else "Modern", True),
            ("Color", THEMES[self.themeKey()]["name"], True),
            ("Animation", "On" if self.anim else "Off", True),
            ("Splash", "On" if self.splash else "Off", True),
            ("Auto Check Update", "On" if self.autoupdate else "Off", True),
            ("Main Menu", "Show" if self.mainmenu else "Hide", True),
            ("Update panel", u"Run  \u25b6", True),
        )
        rows = []
        for i, (name, value, active) in enumerate(values):
            arrows = ("<  %s  >" % value) if (active and i < len(values) - 1) else value
            rows.append([name,
                         MultiContentEntryText(pos=(s(30), 0), size=(s(500), s(64)), font=0,
                                               flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=name,
                                               color=txt if active else mut, color_sel=0xFFFFFF),
                         MultiContentEntryText(pos=(s(520), 0), size=(s(590), s(64)), font=0,
                                               flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=arrows,
                                               color=acc if active else mut, color_sel=0xFFFFFF)])
        self["rows"].setList(rows)
        self["rows"].moveToIndex(idx)
        th = THEMES[self.themeKey()]
        self["s_prev"].setText(u"Preview:  %s%s" % ("" if th["modern"] else "Classic  ·  ", th["name"]))
        self.drawSwatches(th)

    def drawSwatches(self, th):
        """Five color blocks of the theme being chosen, drawn by a list (colored text cells) so they always repaint."""
        cells = [None]
        for i, key in enumerate(("bg", "card2", "accent", "second", "sel")):
            col = hexint(th[key])
            kw = dict(pos=(s(10 + i * 220), s(5)), size=(s(190), s(80)), font=0,
                      flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text="", color=col, color_sel=col,
                      backcolor=col, backcolor_sel=col)
            try:
                cells.append(MultiContentEntryText(border_width=max(1, s(2)), border_color=hexint(th["line"]), **kw))
            except TypeError:
                cells.append(MultiContentEntryText(**kw))
        self["swatches"].setList([cells])

    def current(self):
        return SETTINGS_ROWS[self["rows"].getSelectionIndex()]

    def change(self, step):
        row = self.current()
        if row == "view":
            self.view = "grid" if self.view == "list" else "list"
        elif row == "style":
            self.style = "modern" if self.style == "classic" else "classic"
        elif row == "color":
            order = MODERN_ORDER if self.style == "modern" else CLASSIC_ORDER
            cur = self.color if self.style == "modern" else self.ccolor
            nxt = order[(order.index(cur) + step) % len(order)]
            if self.style == "modern":
                self.color = nxt
            else:
                self.ccolor = nxt
        elif row == "anim":
            self.anim = not self.anim
        elif row == "splash":
            self.splash = not self.splash
        elif row == "autoupdate":
            self.autoupdate = not self.autoupdate
        elif row == "mainmenu":
            self.mainmenu = not self.mainmenu
        self.refreshAll()

    def left(self):
        self.change(-1)

    def right(self):
        self.change(1)

    def up(self):
        self["rows"].up()

    def down(self):
        self["rows"].down()

    def ok(self):
        if self.current() == "update":
            self.session.openWithCallback(
                self.confirmUpdate, MessageBox,
                u"تحديث Major Enigma Panel بالكامل (إعادة التثبيت)؟\nUpdate / reinstall the whole panel now?",
                MessageBox.TYPE_YESNO)
        else:
            self.save()

    def confirmUpdate(self, answer):
        if answer:
            run_item(self.session, update_item(), VERB_UPDATE)

    def releaseKeys(self):
        release_actions(self["actions"])

    def save(self):
        theme = self.themeKey()
        changed = (self.view, theme, self.anim) != self.orig     # تغيير القائمة الرئيسية لا يحتاج إعادة فتح
        save_settings(theme, self.anim, self.mainmenu, self.splash, self.view, self.autoupdate)
        self.close(changed)

    def cancel(self):
        self.close(False)


# --------------------------------- شاشة التيرمنال ------------------------------
# نافذة مثل شاشة Console في الصورة: صندوق مستدير فوق الفيديو، عنوان، سجل ملوّن (ألوان ANSI)،
# وزرّان:  Cancel (أحمر) / Hide (أخضر).  الأمر الحقيقي والروابط لا تظهر (تُستبدل بـ [link hidden]).
VERB_INSTALL = u"التثبيت التلقائي لـ"
VERB_UPDATE = u"التحديث التلقائي لـ"

LOG_X, LOG_Y, LOG_W, LOG_H, LOG_LINE = 316, 214, 1270, 680, 34
WRAP_COLS = 84
MAX_LINES = 300
MAX_ROWS = 600
DEF_FG = "#D6E2F5"
ANSI_NORMAL = {30: "#8FA0BF", 31: "#FF5C6C", 32: "#3DDC84", 33: "#FFD54A",
               34: "#5AA9FF", 35: "#E27BFF", 36: "#3DE3E3", 37: "#E8F1FF"}
ANSI_BRIGHT = {30: "#B4C2DC", 31: "#FF8090", 32: "#6BFFA8", 33: "#FFE985",
               34: "#8CC4FF", 35: "#F0A8FF", 36: "#8CF5F5", 37: "#FFFFFF"}

SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")                              # ألوان فقط
CSI_OTHER_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-ln-~]")            # أي تحكم آخر (مؤشر / مسح ...)
OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")             # عنوان النافذة
CHARSET_RE = re.compile(r"\x1b[()][0-9A-Za-z]")
ESC_DONE_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-Za-z]|[=>78M])")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f]")        # رموز تحكم متبقية (ما عدا ESC)
URL_RE = re.compile(r"(?:https?|ftps?)://[^\s'\"<>]+", re.I)
XTRACE_RE = re.compile(r"^\++ ")                                      # أسطر "+ command" الناتجة عن sh -x
LINK_MASK = u"[link hidden]"


def sgr_apply(params, state):
    """state = (foreground code or None, bold)."""
    fg, bold = state
    codes = [int(p) if p.isdigit() else 0 for p in params.split(";")] if params else [0]
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0:
            fg, bold = None, False
        elif c == 1:
            bold = True
        elif c == 22:
            bold = False
        elif 30 <= c <= 37:
            fg = c
        elif 90 <= c <= 97:
            fg, bold = c - 60, True
        elif c == 39:
            fg = None
        elif c in (38, 48):                         # ألوان 256 / RGB: نتجاهلها
            i += 2 if (i + 1 < len(codes) and codes[i + 1] == 5) else 4
        i += 1
    return fg, bold


def sgr_color(state):
    fg, bold = state
    if fg is None:
        return "#FFFFFF" if bold else DEF_FG
    return (ANSI_BRIGHT if bold else ANSI_NORMAL)[fg]


def scan_line(line, state):
    """Returns (hex color of the first visible text in the line, state after the line)."""
    first = None
    last = 0
    for m in SGR_RE.finditer(line):
        if first is None and line[last:m.start()].strip():
            first = state
        state = sgr_apply(m.group(1), state)
        last = m.end()
    if first is None:
        first = state
    return sgr_color(first), state


def run_skin():
    c = tc()
    fill = "#10" + c["card2"].lstrip("#")          # لون الصندوق (شبه معتم)
    parts = [
        '<screen name="MajorPanelRun" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="#99000000">' % (_W, _H),
        box((258, 83, 1366, 921), c["acc"], 34, z=0),
        box((261, 86, 1360, 915), fill, 32, z=1),
        wid("title", (316, 112, 1250, 84), font=40, fg="#FFFFFF", valign="center"),
        '<widget name="log" %s backgroundColor="%s" backgroundColorSelected="%s" scrollbarMode="showNever" '
        'transparent="1" zPosition="3"/>' % (rect(LOG_X, LOG_Y, LOG_W, LOG_H), fill, fill),
        box((LOG_X + LOG_W + 10, LOG_Y, 6, LOG_H), c["line"], 3, z=2),
        '<widget name="sb" %s backgroundColor="%s" cornerRadius="%d" transparent="0" zPosition="3"/>' % (
            rect(LOG_X + LOG_W + 10, LOG_Y, 6, 40), c["acc"], s(3)),
        box((338, 944, 18, 18), c["red"], 9, z=2),
        wid("key_red", (370, 924, 190, 58), font=30, fg="#FFFFFF", halign="left", valign="center"),
        box((568, 944, 18, 18), c["green"], 9, z=2),
        wid("key_green", (600, 924, 330, 58), font=30, fg="#FFFFFF", halign="left", valign="center"),
        wid("status", (940, 924, 630, 58), font=28, fg=c["warn"], halign="right", valign="center"),
        '</screen>',
    ]
    return "\n".join(parts)


def run_in_pty(cmd, holder, out):
    """Worker thread: runs `cmd` on a pseudo-terminal (so the output behaves like a real terminal:
    line by line, colors, progress bars...) and appends the decoded text to the deque `out`.
    The UI polls the deque from the main thread - no cross-thread GUI calls."""
    master = None
    try:
        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 110, 0, 0))
        except Exception:
            pass
        env = dict(os.environ)
        env.update({"TERM": "xterm", "COLUMNS": "110", "LINES": "40"})
        proc = subprocess.Popen(["/bin/sh", "-c", cmd], stdin=subprocess.DEVNULL,
                                stdout=slave, stderr=slave, close_fds=True, env=env,
                                start_new_session=True)
        holder["proc"] = proc
        os.close(slave)
        decoder = codecs.getincrementaldecoder("utf-8")("ignore")
        while True:
            ready, _, _ = select.select([master], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    out.append(text)
            elif proc.poll() is not None:       # انتهى الأمر ولا يوجد ناتج متبقٍ
                break
        rc = proc.wait()
    except Exception as e:
        holder["error"] = str(e)
        dlog("pty error: %s" % e)
        rc = -2
    finally:
        if master is not None:
            try:
                os.close(master)
            except OSError:
                pass
    holder["rc"] = rc


class RunScreen(Screen):
    def __init__(self, session, item, verb=VERB_INSTALL):
        self.t = T()
        self.skin = run_skin()
        Screen.__init__(self, session)
        self.item = item
        self.lines = []         # finished lines (raw, with color codes)
        self.partial = ""       # current unfinished line
        self.carry = ""         # incomplete escape sequence waiting for the next chunk
        self.cr = False         # last char was a bare carriage return (progress bars)
        self.done = False
        self.success = False
        self.closed = False
        self.hidden = False
        self.follow = True      # keep the window on the last lines
        self.offset = 0         # first visible row (when the user scrolled up)
        self.allrows = []       # [(text, color)] - every wrapped row of the log
        self.dirty = False
        self.ticks = 0
        self.gotOutput = False
        self.mode = ""
        self.q = collections.deque()
        self.holder = {"rc": None, "proc": None, "error": None}
        self.container = None

        self["title"] = Label(u"%s %s" % (verb, item["name"]))
        self["log"] = MenuList([], content=eListboxPythonMultiContent)
        self["log"].l.setFont(0, gFont("Regular", s(26)))
        self["log"].l.setItemHeight(s(LOG_LINE))
        self["sb"] = Label("")
        self["status"] = Label(u"جارٍ التنفيذ... | Running...")
        self["key_red"] = Label(u"Cancel")
        self["key_green"] = Label(u"Hide")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "red": self.onRed, "cancel": self.onRed,
                "green": self.onGreen, "ok": self.onOk,
                "up": self.scrollUp, "down": self.scrollDown,
                "left": self.pageUp, "right": self.pageDown,
            }, -1)
        self.pollTimer = eTimer()
        try:
            self.pollTimer.callback.append(self.poll)
        except AttributeError:
            self._pollConn = self.pollTimer.timeout.connect(self.poll)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def releaseKeys(self):
        release_actions(self["actions"])

    # ------------------------------ السجل -----------------------------------
    def feed(self, text):
        text = self.carry + text
        self.carry = ""
        k = text.rfind("\x1b")
        if k != -1 and not ESC_DONE_RE.match(text, k) and len(text) - k < 64:
            self.carry = text[k:]               # تسلسل ألوان مقطوع: ننتظر باقيه
            text = text[:k]
        text = OSC_RE.sub("", text)
        text = CSI_OTHER_RE.sub("", text)
        text = CHARSET_RE.sub("", text).replace("\t", "    ")
        for part in re.split(r"(\r\n|\n|\r)", text):
            if part == "":
                continue
            if part == "\r":
                self.cr = True
            elif part in ("\n", "\r\n"):
                self.lines.append(self.partial)
                self.partial = ""
                self.cr = False
            else:
                part = CTRL_RE.sub("", part)
                if self.cr:             # شريط تقدم: استبدل السطر الحالي
                    self.partial = ""
                    self.cr = False
                self.partial += part
        if len(self.lines) > MAX_LINES:
            del self.lines[:-MAX_LINES]
        self.dirty = True

    def render(self):
        if self.closed:
            return
        self.dirty = False
        state = (None, False)
        cmd = self.item.get("cmd")
        allrows = []
        for raw in self.lines + ([self.partial] if self.partial else []):
            col, state = scan_line(raw, state)
            plain = SGR_RE.sub("", raw)
            if XTRACE_RE.match(plain):
                continue
            if cmd:
                plain = plain.replace(cmd, "")              # لا يظهر أمر التنفيذ نفسه
            plain = URL_RE.sub(LINK_MASK, plain)            # ولا تظهر الروابط
            color = hexint(col)
            for seg in (textwrap.wrap(plain, WRAP_COLS, drop_whitespace=False,
                                      replace_whitespace=False) or [""]):
                allrows.append((seg, color))
        if len(allrows) > MAX_ROWS:
            allrows = allrows[-MAX_ROWS:]
        self.allrows = allrows
        self.draw()

    def visRows(self):
        return max(1, LOG_H // LOG_LINE)

    def draw(self):
        """Shows only the rows that fit the window: the last ones while following, otherwise from self.offset."""
        total = len(self.allrows)
        vis = self.visRows()
        maxoff = max(0, total - vis)
        self.offset = maxoff if self.follow else min(max(self.offset, 0), maxoff)
        rows = []
        for seg, color in self.allrows[self.offset:self.offset + vis]:
            rows.append([None, MultiContentEntryText(
                pos=(0, 0), size=(s(LOG_W), s(LOG_LINE)), font=0,
                flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=seg, color=color, color_sel=color)])
        self["log"].setList(rows)
        try:
            inst = self["sb"].instance
            if inst:
                if total > vis:
                    th = max(s(30), int(s(LOG_H) * vis / float(total)))
                    y = s(LOG_Y) + int((s(LOG_H) - th) * (self.offset / float(maxoff)))
                    inst.resize(eSize(s(6), th))
                    inst.move(ePoint(s(LOG_X + LOG_W + 10), y))
                    inst.show()
                else:
                    inst.hide()
        except Exception:
            pass

    def moveWin(self, delta):
        maxoff = max(0, len(self.allrows) - self.visRows())
        self.offset = min(max(self.offset + delta, 0), maxoff)
        self.follow = self.offset >= maxoff
        self.draw()

    def start(self):
        setColor(self["status"], self.t["warn"])
        self.feed(u"\x1b[1;36m> Starting...\x1b[0m\n\n")
        self.render()
        dlog("run '%s' | pty available: %s" % (self.item.get("name", ""), HAVE_PTY))
        if HAVE_PTY:
            self.mode = "pty"
            try:
                threading.Thread(target=run_in_pty, daemon=True,
                                 args=(self.item["cmd"], self.holder, self.q)).start()
                self.pollTimer.start(100, False)
                return
            except Exception as e:
                dlog("thread start failed: %s" % e)
        self.startConsole()

    def startConsole(self):
        """Fallback: eConsoleAppContainer (stdout + stderr merged)."""
        self.mode = "console"
        dlog("using console mode")
        self.container = eConsoleAppContainer()
        self._conns = []
        for sig, cb in (("appClosed", self.finished), ("dataAvail", self.onData), ("stderrAvail", self.onData)):
            try:
                sig_obj = getattr(self.container, sig)
            except AttributeError:
                continue
            try:
                sig_obj.append(cb)
            except AttributeError:
                self._conns.append(sig_obj.connect(cb))
        self.container.execute("exec 2>&1; " + self.item["cmd"])

    def onData(self, data):
        if self.closed:
            return
        if isinstance(data, bytes):
            data = data.decode("utf-8", "ignore")
        self.gotOutput = True
        self.feed(data)
        self.render()

    def poll(self):
        """Main-thread timer: moves text produced by the worker thread to the screen."""
        if self.closed or self.done:
            return
        while self.q:
            self.feed(self.q.popleft())
            self.gotOutput = True
        self.ticks += 1
        if self.dirty and self.ticks % 2 == 0:              # لا نعيد الرسم أكثر من 5 مرات في الثانية
            self.render()
        rc = self.holder["rc"]
        if rc is not None and not self.q:
            self.pollTimer.stop()
            if self.holder.get("error") and not self.gotOutput:
                dlog("pty failed, falling back to console")
                self.startConsole()
            else:
                self.finished(rc)

    def finished(self, retval):
        if self.done or self.closed:
            return
        self.done = True
        self.success = (retval == 0)
        if self.success:
            mark_installed(self.item)
        dlog("finished rc=%s mode=%s output=%s" % (retval, self.mode, self.gotOutput))
        self.feed(u"\n\x1b[%sm--- finished (exit code %s) ---\x1b[0m\n" % ("1;32" if self.success else "1;31", retval))
        self.follow = True
        self.render()
        self.wake()
        self["key_red"].setText(u"Close")
        if self.success:
            self["status"].setText(u"تم بنجاح | Finished successfully")
            setColor(self["status"], self.t["ok"])
            self["key_green"].setText(u"Restart GUI")
            self.askRestart()
        else:
            self["status"].setText(u"انتهى برمز خطأ %s | Finished with code %s" % (retval, retval))
            setColor(self["status"], self.t["bad"])
            self["key_green"].setText(u"")

    # ------------------------------ الأزرار ---------------------------------
    def wake(self):
        """If the window is hidden (Hide button) show it again. Returns True if it was hidden."""
        if self.hidden:
            self.hidden = False
            try:
                self.show()
            except Exception:
                pass
            return True
        return False

    def killProcess(self):
        proc = self.holder.get("proc")
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        elif self.container is not None:
            try:
                self.container.kill()
            except Exception:
                pass

    def onRed(self):                    # Cancel / Close
        if self.wake():
            return
        if not self.done:
            self.killProcess()
            self.pollTimer.stop()
            self.finished(-1)
        else:
            self.close()

    def onGreen(self):                  # Hide  (بعد الانتهاء: Restart GUI)
        if self.wake():
            return
        if not self.done:
            self.hidden = True
            self.hide()                 # أي زر يعيد إظهار النافذة
        elif self.success:
            self.askRestart()

    def onOk(self):
        if self.wake():
            return
        if self.done and self.success:
            self.askRestart()

    def scrollUp(self):
        if not self.wake():
            self.moveWin(-1)

    def scrollDown(self):
        if not self.wake():
            self.moveWin(1)

    def pageUp(self):
        if not self.wake():
            self.moveWin(-(self.visRows() - 1))

    def pageDown(self):
        if not self.wake():
            self.moveWin(self.visRows() - 1)

    def askRestart(self):
        text = u"إعادة تشغيل الواجهة الآن؟\nRestart GUI now?"
        try:
            self.session.openWithCallback(self.restartAnswer, MessageBox, text, MessageBox.TYPE_YESNO, default=False)
        except TypeError:
            self.session.openWithCallback(self.restartAnswer, MessageBox, text, MessageBox.TYPE_YESNO)

    def restartAnswer(self, answer):
        if answer:
            self.session.open(TryQuitMainloop, 3)

    def cleanup(self):
        self.closed = True
        try:
            self.pollTimer.stop()
            del self.pollTimer.callback[:]
        except Exception:
            pass
        self.releaseKeys()
        if not self.done:
            self.killProcess()
        if self.container is not None:
            for sig in ("appClosed", "dataAvail", "stderrAvail"):
                try:
                    del getattr(self.container, sig)[:]
                except Exception:
                    pass


def run_item(session, item, verb=VERB_INSTALL, callback=None):
    """Runs the item's command inside the terminal window (RunScreen)."""
    session.openWithCallback(callback if callback else (lambda *a: None), RunScreen, item, verb)


# --------------------------------- شاشة البداية (Splash) -----------------------
# تظهر مرة واحدة عند فتح البانل فقط (لا تظهر عند إعادة فتحها بعد تغيير الإعدادات).
# OK = تخطي والدخول للبانل ، EXIT = إلغاء فتح البانل. يمكن إيقافها من الإعدادات (Splash).
SPLASH_MS = 1700
SPLASH_TICK = 40
SPLASH_MAX_MS = 6000                    # أقصى انتظار لنتيجة فحص التحديث


def splash_skin():
    c = tc()
    bar_w = 600
    parts = [
        '<screen name="MajorPanelSplash" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (_W, _H, c["bg"]),
        pixw("sp_logo", (780, 150, 360, 360), z=3),
        pixw("sp_name", (700, 560, 520, 84), z=3),
        wid("sp_text", (460, 560, 1000, 84), font=56, fg="#FFFFFF", bg=c["bg"], halign="center", valign="center", z=3),
        wid("sp_by", (460, 655, 1000, 50), font=30, fg=c["muted"], bg=c["bg"], halign="center", valign="center"),
        wid("sp_ver", (460, 702, 1000, 48), font=34, fg=ring_hex(T()), bg=c["bg"], halign="center", valign="center"),
        box((960 - bar_w // 2, 780, bar_w, 8), c["line"], 4, z=2),
        '<widget name="sp_bar" %s backgroundColor="%s" cornerRadius="%d" zPosition="3"/>' % (
            rect(960 - bar_w // 2, 780, 10, 8), c["acc"], s(4)),
        wid("sp_hint", (460, 820, 1000, 40), font=22, fg=c["muted"], bg=c["bg"], halign="center", valign="center"),
        '</screen>',
    ]
    return "\n".join(parts)


class SplashScreen(Screen):
    def __init__(self, session):
        self.t = T()
        self.skin = splash_skin()
        Screen.__init__(self, session)
        self["sp_logo"] = Pixmap()
        self["sp_name"] = Pixmap()
        self["sp_text"] = Label("")
        self["sp_by"] = Label(u"By John Kamel")
        self["sp_ver"] = Label(u"V" + PLUGIN_VERSION)
        self["sp_bar"] = Label("")
        self["sp_hint"] = Label(u"Checking for updates ...     (OK : skip   EXIT : cancel)" if _state.get("autoupdate", True)
                                else u"OK : skip     EXIT : cancel")
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.skip, "cancel": self.abort}, -1)
        self.elapsed = 0
        self.finished = False
        self.do_check = bool(_state.get("autoupdate", True))
        self.check = {"done": not self.do_check, "ver": None, "error": None}
        self.timer = eTimer()
        try:
            self.timer.callback.append(self.tick)
        except AttributeError:
            self._conn = self.timer.timeout.connect(self.tick)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def start(self):
        try:
            logo = pix("splash") or pix("logo")
            if logo and self["sp_logo"].instance:
                self["sp_logo"].instance.setPixmap(logo)
                self["sp_logo"].instance.show()
            name = pix("f00")                       # الاسم المتدرج (للثيمات الحديثة)
            if name and self["sp_name"].instance:
                self["sp_name"].instance.setPixmap(name)
                self["sp_name"].instance.show()
            else:
                self["sp_text"].setText(TITLE)
        except Exception as e:
            dlog_error("splash start: %s" % e)
        if self.do_check:
            try:
                import threading
                threading.Thread(target=fetch_remote_version, args=(self.check,), daemon=True).start()
            except Exception as e:
                dlog_error("update check: %s" % e)
                self.check["done"] = True
        self.timer.start(SPLASH_TICK, False)

    def decide(self):
        ver = self.check.get("ver")
        if ver and ver.lower() != PLUGIN_VERSION.lower():
            return ("update", ver)
        return "go"

    def tick(self):
        if self.finished:
            return
        self.elapsed += SPLASH_TICK
        frac = min(1.0, self.elapsed / float(SPLASH_MS))
        try:
            w = max(10, int(s(600) * frac))
            self["sp_bar"].instance.resize(eSize(w, s(8)))
        except Exception:
            pass
        if frac >= 1.0 and (self.check["done"] or self.elapsed >= SPLASH_MAX_MS):
            self.finish(self.decide())

    def finish(self, result):
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        self.close(result)

    def skip(self):
        self.finish("go")

    def abort(self):
        self.finish("cancel")

    def cleanup(self):
        self.finished = True
        try:
            self.timer.stop()
            del self.timer.callback[:]
        except Exception:
            pass
        release_actions(self["actions"])


# --------------------------------- التسجيل -----------------------------------
_relaunch = {}


def onPanelClosed(session, result=None):
    if result == "reopen":
        # نترك للواجهة لحظة لتحرير الشاشة القديمة قبل بناء الجديدة (يخفف ذروة الذاكرة)
        gc.collect()
        tm = eTimer()
        try:
            tm.callback.append(lambda: launch(session))
        except AttributeError:
            _relaunch["conn"] = tm.timeout.connect(lambda: launch(session))
        _relaunch["timer"] = tm
        tm.start(350, True)
    else:
        cleanup_assets()                    # لا يبقى أي شيء في /tmp عند الخروج


def open_panel(session):
    cls = GridPanel if _state.get("view") == "grid" else ListPanel
    try:
        session.openWithCallback(lambda result=None: onPanelClosed(session, result), cls)
    except Exception:
        dlog_error("%s failed:\n%s" % (cls.__name__, traceback.format_exc()))
        if cls is GridPanel:                # لا نترك المستخدم بدون بانل: نرجع لوضع List
            _state["view"] = "list"
            save_settings(_state["theme"], _state["anim"], _state["mainmenu"], _state["splash"], "list", _state["autoupdate"])
            prep_assets(_state["theme"], _state["anim"], False, "list")
            open_panel(session)
            return
        try:
            cleanup_assets()
            session.open(MessageBox, u"تعذّر تشغيل Major Panel - راجع /tmp/majorpanel_error.log\nMajor Panel could not start.",
                         MessageBox.TYPE_ERROR, timeout=10)
        except Exception as e:
            dlog_error("message box failed: %s" % e)


def askUpdate(session, new_version):
    text = (u"يوجد إصدار جديد من Major Enigma Panel\n"
            u"الإصدار الحالي: V%s     |     الإصدار الجديد: V%s\n\n"
            u"هل تريد التحديث الآن؟\n"
            u"A new version is available. Update now?") % (PLUGIN_VERSION, new_version)

    def answer(yes):
        if yes:
            run_item(session, update_item(), VERB_UPDATE, lambda *a: open_panel(session))
        else:
            open_panel(session)                                 # الرفض: ندخل البانل مباشرة
    try:
        session.openWithCallback(answer, MessageBox, text, MessageBox.TYPE_YESNO, default=True)
    except TypeError:
        session.openWithCallback(answer, MessageBox, text, MessageBox.TYPE_YESNO)


def splashDone(session, result=None):
    if result == "cancel":
        cleanup_assets()
    elif isinstance(result, tuple) and result and result[0] == "update":
        askUpdate(session, result[1])
    else:
        open_panel(session)


def launch(session, splash=False):
    load_settings()
    show = bool(splash and _state["splash"])
    prep_assets(_state["theme"], _state["anim"], show, _state["view"])
    if show:
        try:
            session.openWithCallback(lambda result=None: splashDone(session, result), SplashScreen)
            return
        except Exception:
            dlog_error("splash failed:\n%s" % traceback.format_exc())
    open_panel(session)


def main(session, **kwargs):
    launch(session, splash=True)


def menuHook(menuid, **kwargs):
    """Adds Major Enigma Panel to the main Menu of the image (can be switched off in the panel Settings)."""
    if menuid == "mainmenu" and menu_enabled():
        return [(TITLE, main, "major_enigma_panel", 1)]
    return []


def Plugins(**kwargs):
    icon = "plugin.png" if os.path.isfile(os.path.join(PLUGIN_DIR, "plugin.png")) else None
    kw = {"icon": icon} if icon else {}
    return [
        PluginDescriptor(name=TITLE, description="Modern Linux commands panel",
                         where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main, **kw),
        PluginDescriptor(name=TITLE, description="Modern Linux commands panel",
                         where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main),
        PluginDescriptor(name=TITLE, description="Modern Linux commands panel",
                         where=PluginDescriptor.WHERE_MENU, fnc=menuHook),
    ]
