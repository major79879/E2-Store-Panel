# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
#  E2 Store  -  لوحة أوامر لينوكس بواجهة عصرية لـ Enigma2 (OpenATV 7.6 / 8)
#  Python 3 only.  يقرأ ملف LinuxCommands.lst من GitHub ويعرضه كأقسام وبطاقات.
# ---------------------------------------------------------------------------
import glob
import os
import re
import ssl
import struct
import time
from urllib.request import Request, urlopen

from enigma import (eConsoleAppContainer, eListboxPythonMultiContent, getDesktop, gFont,
                    ePoint, eSize, eTimer, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER)
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

try:    # تشغيل الأوامر على طرفية حقيقية (pty) لتظهر الخطوات مثل التيرمنال
    import codecs
    import fcntl
    import pty
    import select
    import signal
    import subprocess
    import termios
    import threading
    from twisted.internet import reactor
    HAVE_PTY = True
except Exception:
    HAVE_PTY = False

# ============================ الإعدادات / SETTINGS ===========================
# رابط ملف الأوامر على GitHub (عدّله لو اختلف المسار عندك)
COMMANDS_URL = "https://raw.githubusercontent.com/major79879/E2-Store-Panel/refs/heads/main/E2Store_Commands.lst"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
OLD_CACHE_FILES = ("/etc/enigma2/e2store_cache.lst", "/etc/enigma2/modernpanel_cache.lst")  # نسخ قديمة تُحذف تلقائياً
TITLE = "E2 Store Panel"
# تحديث البانل نفسه (إعادة التثبيت) - ملف installer.sh موجود في جذر المستودع (خارج مجلد E2Store)
INSTALLER_URL = "https://raw.githubusercontent.com/major79879/E2-Store-Panel/refs/heads/main/installer.sh"
UPDATE_CMD = 'wget -q --no-check-certificate -O - "%s" | /bin/sh -s norestart' % INSTALLER_URL

# الألوان / COLORS
C_BG, C_CARD, C_LINE = "#050B1E", "#0B1634", "#1D3B66"       # فضاء كحلي / بطاقات / خطوط
C_TEXT, C_MUTED = "#E8F1FF", "#7F95B8"
C_CYAN, C_MINT, C_AMBER = "#19D3FF", "#34E3A0", "#FFC53D"    # ألوان النيون
C_ACCENT, C_SEL = "#2F7CFF", "#0D4C8C"                       # أزرق نيون / لون السطر المحدد
C_GREEN, C_RED, C_YELLOW = "#12C97F", "#F43F6E", "#E9A91A"   # ألوان أزرار الريموت
# ============================================================================

_W = max(getDesktop(0).size().width(), 1280)
_H = max(getDesktop(0).size().height(), 720)
SC = _W / 1920.0


def s(v):
    """Scale a 1920x1080 design value to the current desktop resolution."""
    return int(round(v * SC))


def rect(x, y, w, h):
    return 'position="%d,%d" size="%d,%d"' % (s(x), s(y), s(w), s(h))


def setColor(widget, hexcolor):
    try:
        widget.instance.setForegroundColor(parseColor(hexcolor))
    except Exception:
        pass


# ------------------------------ تحميل البيانات -------------------------------
def _fetch(url, timeout=20):
    ctx = ssl._create_unverified_context()      # بعض الصور بدون شهادات CA
    sep = "&" if "?" in url else "?"
    req = Request(url + sep + "t=%d" % int(time.time()),
                  headers={"User-Agent": "E2Store/1.0", "Cache-Control": "no-cache"})
    return urlopen(req, timeout=timeout, context=ctx).read().decode("utf-8", "ignore")


def remove_old_cache():
    for path in OLD_CACHE_FILES:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass


def load_online():
    """Runs in a worker thread. Returns (text, 'online') or raises."""
    text = _fetch(COMMANDS_URL)
    if "+++" not in text:
        raise ValueError("bad file")
    return text, "online"


# ------------------------------ معلومات الجهاز -------------------------------
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


import base64

# صورة ريسيفر عامة مدمجة تُستخدم عند عدم وجود صورة للجهاز في النظام
DEFAULT_BOX_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAlgAAACqCAMAAABGfcHVAAAAYFBMVEUAAAAOERcdJC4WGyJXpf4fb+swNj0/uVDSmSJIhctT"
    "nO8jOE8sSWsvUHZDebgnQF00Woc4Y5UfLkA/capOkNwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwNiKpAAAA"
    "IHRSTlMA//////////////////////////8AAAAAAAAAAAAAAGTP5fYAAANhSURBVHja7dzrbqJAAIDRFkq5SO1t3/9ZFwW7"
    "7codp0E454dRSkwcv8wYCjw8AAAAAAAAAAAAAAAAAAAAAABA4wkuVMWK2zKIhGjLABKgrK83ieBieVqqoretRV0ZRTrT0hWr"
    "KUtWjEhLV6yjLF0xqiwTFiuYsnRFkLJ0RZDFsCOsR/ZseVitXRlYHheW1RaWQaWlrKVhGVFa05oUlq4IUtZVWAaTrrKExerC"
    "MpR0lrUgLANJd1nCQljsISzDSE9ZwkJYCAthCQthISyEJSyEhbAQlrAQFks8zycsAmQ1nJaw9txVPN9QWcLab1fxMv1l/UZY"
    "z2ywq4GywoelqlWmdfdhPd/gE9y/1ZV1k2+l70OFDktWo36RCGtiWLqaWlZa69kjqfXskdWEJaz/supJK/mnP6v+tO48LF1N"
    "KytNh8pKkqGysmxMWcLaU1hpOlRWkgyVlWWjytpSWE95nr/FL3n+enp1qF5FZZ5XW8tqW17WOxya3fYYVpoOlZUkQ2Vl2biy"
    "thRWcXqI8vjw5/Qkj+LyWG8tq+dRlVtxyq3ebY9hpelQWUkyVFaWjSxrc2Edyjg6Pyk+qhf11vwQfyVVCEtYc8KqlJ/nx+Lz"
    "0Gwtmj+fJq/jbsNK06GykmSorCwbW9bWfmNVLX1UC995UXzJ37+FVc1j1Q5FdNlNWMKaNGNFdTXRIa7XxJ9L4dubGUtYs8I6"
    "lnVf1dxUtXTe+vrtx7ulUFhzlsL3l+rxeP6N1ax4p46aww3FZUE8r5HCEpYDpMISlrCE5TiW41jCEpaw/K9QWHsKy9kNwgoT"
    "lvOxhBUmLGeQCitMWM55d857mK5cpSMsYbmuUFebC8uV0M1X4Epo925w74YbTMLuNuNuM3cbFmu0gftjsdKy3NGPQGW5Bykr"
    "S2vorYVFEMJCWAirlrBtwkJYCEtYwhIWwkJYwhKW41jc1XEsZdHdlbAQFvsIS1l0drUoLGXR1ZWwWGFYyqKjq0lhKYsgXbWE"
    "JS1asrpFWMriuquJYbWXpS1VLeyqKyxYHpayGNPVpLCURZCuLIYEWAhNWYSasJRFmK6asqRFT1ZzulIWYbq6lCUt2rOa29VX"
    "WdriuqoFXX1PC356WMYAEqIrbRGmKm0RqioAAAAAAAAAAAAAAAAAAAAA4Bf9Be89F+4TUAq0AAAAAElFTkSuQmCC"
)


def _default_box_image():
    path = "/tmp/e2store_default_box.png"
    try:
        with open(path, "wb") as f:
            f.write(base64.b64decode("".join(DEFAULT_BOX_B64)))
        return path
    except Exception:
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


def png_size(path):
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except Exception:
        pass
    return None


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
_icon_cache = {}


def icon_key(cat_name):
    n = cat_name.lower()
    if n.startswith("search:"):
        return "search"
    for word, icon in ICON_RULES:
        if word in n:
            return icon
    return "grid"


def _extract_icon(key):
    data = ICONS_B64.get(key)
    if not data:
        return None
    try:
        folder = "/tmp/e2store_icons"
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, key + ".png")
        with open(path, "wb") as f:
            f.write(base64.b64decode("".join(data)))
        return path
    except Exception:
        return None


def get_icon(cat_name):
    """Pixmap for a category. A file icons/<name>.png next to plugin.py overrides the built-in one."""
    key = icon_key(cat_name)
    if key not in _icon_cache:
        path = os.path.join(PLUGIN_DIR, "icons", key + ".png")
        if not os.path.isfile(path):
            path = _extract_icon(key)
        try:
            _icon_cache[key] = LoadPixmap(path) if path else None
        except Exception:
            _icon_cache[key] = None
    return _icon_cache[key]


# --------------------------------- الشاشة الرئيسية ---------------------------
HINT_TEXT = ("LEFT / RIGHT : category     UP / DOWN : select     OK : install     "
             "BLUE / INFO : update panel     MENU : refresh list")
OFFLINE_MSG = u"تعذّر الاتصال بسيرفر البانل - تحقق من الإنترنت | Cannot connect to panel server"


# تدرج النيون المستخدم في شريطي الرام والهارد (كلما امتلأ الشريط ظهرت ألوان أكثر)
NEON_STOPS = ((25, 211, 255), (47, 124, 255), (139, 92, 255), (224, 61, 255), (255, 79, 163))
BAR_SEGS = 30


def neon_hex(t):
    """t in 0..1 -> '#RRGGBB' along cyan > blue > violet > magenta > pink"""
    t = min(max(t, 0.0), 1.0) * (len(NEON_STOPS) - 1)
    i = min(int(t), len(NEON_STOPS) - 2)
    f = t - i
    a, b = NEON_STOPS[i], NEON_STOPS[i + 1]
    return "#%02X%02X%02X" % tuple(int(round(a[k] + (b[k] - a[k]) * f)) for k in range(3))


def sel_pixmap_attr(w, h):
    """selectionPixmap attribute (neon cyan border). Pictures are pixel-exact, so they are only
    used for the sizes we ship (1920 / 1280 wide desktops); otherwise the solid color is used."""
    key = "%dx%d" % (s(w), s(h))
    data = SEL_B64.get(key)
    if not data:
        return ""
    try:
        folder = "/tmp/e2store_sel"
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, key + ".png")
        with open(path, "wb") as f:
            f.write(base64.b64decode("".join(data)))
        return ' selectionPixmap="%s"' % path
    except Exception:
        return ""


def bar_segments_xml(prefix, y):
    """Segmented neon LED bar: widgets <prefix>_seg0..N, each with its own gradient color."""
    pitch = 510.0 / BAR_SEGS
    out = []
    for i in range(BAR_SEGS):
        out.append('  <widget name="%s_seg%d" position="%d,%d" size="%d,%d" backgroundColor="%s" '
                   'cornerRadius="%d" transparent="0" zPosition="3"/>' % (
                       prefix, i, s(1340 + i * pitch), s(y), max(2, s(pitch - 3)), s(10),
                       neon_hex(i / float(BAR_SEGS - 1)), s(3)))
    return "\n".join(out)


def main_skin():
    return u'''
<screen name="E2Store" position="0,0" size="%(W)d,%(H)d" flags="wfNoBorder" backgroundColor="%(bg)s">
  <eLabel position="0,0" size="%(W)d,%(hh)d" backgroundColor="%(card)s" zPosition="0"/>
  <eLabel position="0,%(hl)d" size="%(W)d,%(lw)d" backgroundColor="%(cyan)s" zPosition="1"/>
  <widget name="title" %(r_title)s font="Regular;%(f46)d" foregroundColor="%(cyan)s" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <widget name="title_glow" %(r_timg)s alphatest="blend" scale="1" zPosition="2"/>
  <widget name="title_img" %(r_timg)s alphatest="blend" scale="1" zPosition="3"/>
  <widget name="logo_glow" %(r_logo)s alphatest="blend" scale="1" zPosition="2"/>
  <widget name="logo_img" %(r_logo)s alphatest="blend" scale="1" zPosition="3"/>
  <widget name="credit" %(r_credit)s font="Regular;%(f26)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <widget name="h_server" %(r_hserver)s font="Regular;%(f28)d" foregroundColor="#FFC53D" backgroundColor="%(card)s" transparent="1" halign="right" valign="center" zPosition="2"/>
  <widget name="h_stats" %(r_hstats)s font="Regular;%(f28)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="right" valign="center" zPosition="2"/>

  <eLabel %(r_card1)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="cats" %(r_cats)s backgroundColor="%(card)s" backgroundColorSelected="%(sel)s" foregroundColor="%(text)s" foregroundColorSelected="#FFFFFF" scrollbarMode="showNever"%(selcats)s transparent="0" zPosition="2"/>

  <eLabel %(r_card2)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="items" %(r_items)s backgroundColor="%(card)s" backgroundColorSelected="%(sel)s" foregroundColor="%(text)s" foregroundColorSelected="#FFFFFF" scrollbarMode="showNever"%(selitems)s transparent="0" zPosition="2"/>

  <eLabel %(r_card3)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="d_cat" %(r_dcat)s font="Regular;%(f26)d" foregroundColor="%(cyan)s" backgroundColor="%(card)s" transparent="1" zPosition="2"/>
  <widget name="d_count" %(r_dcount)s font="Regular;%(f26)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" halign="right" zPosition="2"/>
  <widget name="d_name" %(r_dname)s font="Regular;%(f38)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="top" zPosition="2"/>
  <widget name="d_author" %(r_dauthor)s font="Regular;%(f28)d" foregroundColor="%(mint)s" backgroundColor="%(card)s" transparent="1" zPosition="2"/>
  <eLabel %(r_sep)s backgroundColor="%(line)s" zPosition="2"/>
  <widget name="d_desc_h" %(r_ddeschd)s font="Regular;%(f24)d" foregroundColor="%(cyan)s" backgroundColor="%(card)s" transparent="1" halign="right" zPosition="2"/>
  <widget name="d_desc" %(r_ddesc)s font="Regular;%(f32)d" foregroundColor="#E6EDF3" backgroundColor="%(card)s" transparent="1" halign="right" valign="top" zPosition="2"/>

  <eLabel %(r_card4)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="b_model" %(r_bmodel)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="box_pic" %(r_bpic)s alphatest="blend" scale="1" zPosition="2"/>
  <widget name="b_image" %(r_bimage)s font="Regular;%(f22)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="b_ip" %(r_bip)s font="Regular;%(f24)d" foregroundColor="%(cyan)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="b_ram" %(r_bram)s font="Regular;%(f24)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <eLabel %(r_rtrack)s backgroundColor="%(line)s" cornerRadius="%(cr3)d" zPosition="2"/>
  %(segs)s
  <widget name="b_hdd" %(r_bhdd)s font="Regular;%(f24)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <eLabel %(r_htrack)s backgroundColor="%(line)s" cornerRadius="%(cr3)d" zPosition="2"/>

  <widget name="key_red" %(r_b1)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(red)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_green" %(r_b2)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(green)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_yellow" %(r_b3)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(yellow)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_blue" %(r_b4)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(acc)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="hint" %(r_hint)s font="Regular;%(f22)d" foregroundColor="%(muted)s" backgroundColor="%(bg)s" transparent="1" halign="center" valign="center" zPosition="2"/>
</screen>''' % dict(
        W=_W, H=_H, bg=C_BG, card=C_CARD, line=C_LINE, text=C_TEXT, muted=C_MUTED, acc=C_ACCENT,
        red=C_RED, green=C_GREEN, yellow=C_YELLOW, cyan=C_CYAN, mint=C_MINT, sel=C_SEL,
        selcats=sel_pixmap_attr(390, 84), selitems=sel_pixmap_attr(770, 100),
        segs=bar_segments_xml("ram", 832) + "\n" + bar_segments_xml("hdd", 888),
        r_timg=rect(146, 13, 440, 84), r_logo=rect(34, 5, 100, 100),
        hh=s(110), hl=s(106), lw=max(2, s(4)), cr=s(24), cr2=s(16), cr3=s(5),
        f22=s(22), f24=s(24), f26=s(26), f28=s(28), f30=s(30), f32=s(32), f38=s(38), f46=s(46),
        # --- الشريط العلوي ---
        r_title=rect(156, 20, 400, 70), r_credit=rect(606, 20, 370, 70),
        r_hserver=rect(980, 20, 350, 70), r_hstats=rect(1340, 20, 520, 70),
        r_card1=rect(40, 135, 420, 800), r_cats=rect(55, 150, 390, 770),
        r_card2=rect(485, 135, 800, 800), r_items=rect(500, 150, 770, 770),
        # --- البطاقة العلوية: تفاصيل الإضافة ---
        r_card3=rect(1310, 135, 570, 430),
        r_dcat=rect(1340, 153, 360, 40), r_dcount=rect(1700, 153, 150, 40),
        r_dname=rect(1340, 198, 510, 100), r_dauthor=rect(1340, 302, 510, 40),
        r_sep=rect(1340, 352, 510, 2),
        r_ddeschd=rect(1340, 364, 510, 34), r_ddesc=rect(1340, 402, 510, 150),
        # --- البطاقة السفلية: معلومات الجهاز ---
        r_card4=rect(1310, 585, 570, 350),
        r_bmodel=rect(1340, 598, 510, 40), r_bpic=rect(1340, 640, 510, 90),
        r_bimage=rect(1340, 732, 510, 30), r_bip=rect(1340, 762, 510, 30),
        r_bram=rect(1340, 800, 510, 30), r_rtrack=rect(1340, 832, 510, 10),
        r_bhdd=rect(1340, 856, 510, 30), r_htrack=rect(1340, 888, 510, 10),
        r_b1=rect(40, 955, 440, 66), r_b2=rect(500, 955, 440, 66),
        r_b3=rect(960, 955, 440, 66), r_b4=rect(1420, 955, 460, 66),
        r_hint=rect(40, 1030, 1840, 40),
    )


class E2Store(Screen):
    def __init__(self, session):
        self.skin = main_skin()
        Screen.__init__(self, session)
        self.setTitle(TITLE)

        self["title"] = Label(TITLE)
        self["title_glow"] = Pixmap()
        self["title_img"] = Pixmap()
        self["logo_glow"] = Pixmap()
        self["logo_img"] = Pixmap()
        self["credit"] = Label("By John Kamel & Robin John")
        self["h_server"] = Label("")
        self["h_stats"] = Label("")
        self["cats"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        self["items"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        for name, big, small, h in (("cats", 28, 24, 84), ("items", 34, 26, 100)):
            lst = self[name].l
            lst.setFont(0, gFont("Regular", s(big)))
            lst.setFont(1, gFont("Regular", s(small)))
            lst.setItemHeight(s(h))

        # تفاصيل الإضافة
        self["d_cat"] = Label("")
        self["d_count"] = Label("")
        self["d_name"] = Label("")
        self["d_author"] = Label("")
        self["d_desc_h"] = Label(u"شرح الإضافة")
        self["d_desc"] = Label("")
        # معلومات الجهاز
        self["b_model"] = Label("")
        self["box_pic"] = Pixmap()
        self["b_image"] = Label("")
        self["b_ip"] = Label("")
        self["b_ram"] = Label("")
        for prefix in ("ram", "hdd"):
            for i in range(BAR_SEGS):
                self["%s_seg%d" % (prefix, i)] = Label("")
        self.barOn = {}
        self["b_hdd"] = Label("")

        self["key_red"] = Label(u"خروج | Exit")
        self["key_green"] = Label(u"تثبيت | Install")
        self["key_yellow"] = Label(u"بحث | Search")
        self["key_blue"] = Label(u"تحديث البانل | Update")
        self["hint"] = Label(HINT_TEXT)

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "EPGSelectActions", "MenuActions"],
            {
                "ok": self.askInstall, "green": self.askInstall,
                "cancel": self.exit, "red": self.exit,
                "yellow": self.search,
                "blue": self.askUpdate, "info": self.askUpdate,     # تحديث البانل
                "menu": self.refresh,                               # تحديث قائمة الأوامر
                "left": self.prevCat, "right": self.nextCat,
                "up": self.up, "down": self.down,
            }, -1)

        self.allcats = []       # [(cat, [items])]
        self.cats = []          # current view (all or search results)
        self.catIdx = 0
        self.query = ""

        self.statTimer = eTimer()
        try:
            self.statTimer.callback.append(self.updateStats)
        except AttributeError:
            self._statConn = self.statTimer.timeout.connect(self.updateStats)
        self.onClose.append(self.statTimer.stop)

        # اسم البانل: موجة ألوان نيون متحركة
        self.titleFrames = []
        self.titleIdx = 0
        self.glowFrames = []
        self.glowIdx = 0
        self.tick = 0
        self.titleTimer = eTimer()
        try:
            self.titleTimer.callback.append(self.titleTick)
        except AttributeError:
            self._titleConn = self.titleTimer.timeout.connect(self.titleTick)
        self.onClose.append(self.titleTimer.stop)
        self.onExecBegin.append(self.resumeTitle)
        self.onExecEnd.append(self.pauseTitle)
        self.onLayoutFinish.append(self.start)

    # ----------------------------- تحميل ------------------------------------
    def _loadPix(self, folder, name, data):
        path = os.path.join(folder, name + ".png")
        with open(path, "wb") as f:
            f.write(base64.b64decode("".join(data)))
        return LoadPixmap(path)

    def loadTitle(self):
        folder = "/tmp/e2store_title"
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            return
        try:                                        # اللوجو المتوهج قبل الاسم
            logo = self._loadPix(folder, "logo", LOGO_B64)
            glow = [self._loadPix(folder, "lg%d" % i, d) for i, d in enumerate(LOGO_GLOW_B64)]
            if logo and glow and all(glow):
                self["logo_img"].instance.setPixmap(logo)
                self["logo_img"].instance.show()
                self["logo_glow"].instance.setPixmap(glow[0])
                self["logo_glow"].instance.show()
                self.glowFrames = glow
        except Exception:
            self.glowFrames = []
        try:                                        # اسم البانل: موجة ألوان
            glow = self._loadPix(folder, "glow", TITLE_GLOW_B64)
            frames = [self._loadPix(folder, "f%02d" % i, d) for i, d in enumerate(TITLE_FRAMES_B64)]
            if glow and frames and all(frames):
                self["title_glow"].instance.setPixmap(glow)
                self["title_glow"].instance.show()
                self["title_img"].instance.setPixmap(frames[0])
                self["title_img"].instance.show()
                self["title"].hide()
                self.titleFrames = frames
        except Exception:
            self.titleFrames = []                   # يبقى الاسم نصاً عادياً
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
        if self.titleFrames or self.glowFrames:
            self.titleTimer.start(90, False)

    def start(self):
        self.loadTitle()
        self.showBoxInfo()
        self.updateStats()
        self.statTimer.start(3000, False)
        remove_old_cache()
        self.updateHeaderStats()
        self.refresh()

    def refresh(self):
        self.setServer("connecting")
        d = deferToThread(load_online)
        d.addCallback(self.onlineOK)
        d.addErrback(self.onlineFail)

    def onlineOK(self, result):
        text, src = result
        self.setServer("online")
        self.setData(text)

    def onlineFail(self, failure):
        self.setServer("offline")

    def setServer(self, state):
        """state: online | offline | connecting  (shown at the top as: Server: Online ...)"""
        label, color = {"online": ("Online", C_MINT),
                        "offline": ("Offline", "#FF4D6D"),
                        "connecting": ("Connecting...", C_AMBER)}[state]
        self["h_server"].setText("Server:  " + label)
        setColor(self["h_server"], color)
        if state == "offline":
            self["hint"].setText(OFFLINE_MSG)
            setColor(self["hint"], "#FF4D6D")
        else:
            self["hint"].setText(HINT_TEXT)
            setColor(self["hint"], C_MUTED)

    def updateHeaderStats(self):
        total = sum(len(items) for _, items in self.allcats)
        self["h_stats"].setText("Category: %d      Order: %d" % (len(self.allcats), total))

    def setData(self, text):
        try:
            data = parse_commands(text)
        except Exception as e:
            self["hint"].setText("Parse error: %s" % e)
            return
        keepCat = self.cats[self.catIdx][0] if self.cats else None
        self.allcats = data
        self.updateHeaderStats()
        self.buildView(keepCat)

    # ------------------------- معلومات الجهاز --------------------------------
    def showBoxInfo(self):
        try:
            title, image, ids = get_box_details()
        except Exception:
            title, image, ids = "Enigma2", "", []
        self["b_model"].setText(title)
        self["b_image"].setText(image)
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
        maxw, maxh = s(510), s(90)
        size = png_size(path) or (maxw, maxh)
        ratio = min(maxw / float(size[0]), maxh / float(size[1]))
        w, h = max(1, int(size[0] * ratio)), max(1, int(size[1] * ratio))
        try:
            inst.setScale(1)
        except Exception:
            pass
        inst.resize(eSize(w, h))
        inst.move(ePoint(s(1340) + (maxw - w) // 2, s(640) + (maxh - h) // 2))
        inst.setPixmap(ptr)
        inst.show()

    def setBar(self, prefix, pct):
        """Neon LED bar: shows the first N gradient segments (more colors appear as it fills)."""
        on = 0 if pct <= 0 else max(1, int(round(BAR_SEGS * min(pct, 100.0) / 100.0)))
        if self.barOn.get(prefix) == on:
            return
        self.barOn[prefix] = on
        for i in range(BAR_SEGS):
            seg = self["%s_seg%d" % (prefix, i)]
            if i < on:
                seg.show()
            else:
                seg.hide()

    def updateStats(self):
        try:                                            # عنوان IP
            ip = get_ip()
            if ip:
                self["b_ip"].setText("IP Address   %s" % ip)
                setColor(self["b_ip"], C_CYAN)
            else:
                self["b_ip"].setText("IP Address   Not connected")
                setColor(self["b_ip"], C_MUTED)
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

    # ----------------------------- العرض ------------------------------------
    def buildView(self, keepCat=None):
        if self.query:
            q = self.query.lower()
            hits = [it for c, items in self.allcats for it in items
                    if q in (u"%s %s %s %s" % (it["name"], it["author"], it["desc"], c)).lower()]
            self.cats = [(u"Search: %s" % self.query, hits)]
        else:
            self.cats = self.allcats
        self.catIdx = 0
        if keepCat:
            for i, (n, _) in enumerate(self.cats):
                if n == keepCat:
                    self.catIdx = i
                    break
        rows = []
        for n, items in self.cats:
            row = [n]
            icon = get_icon(n)
            if icon:
                row.append(MultiContentEntryPixmapAlphaBlend(pos=(s(18), s(20)), size=(s(44), s(44)),
                                                             png=icon, flags=BT_SCALE))
            row.append(MultiContentEntryText(pos=(s(76), 0), size=(s(236), s(84)), font=0,
                                             flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=n,
                                             color=0xE8F1FF, color_sel=0xFFFFFF))
            row.append(MultiContentEntryText(pos=(s(316), 0), size=(s(62), s(84)), font=1,
                                             flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER,
                                             text=str(len(items)),
                                             color=0x7F95B8, color_sel=0xFFFFFF))
            rows.append(row)
        self["cats"].setList(rows)
        self["cats"].moveToIndex(self.catIdx)
        self.fillItems()

    def fillItems(self):
        items = self.cats[self.catIdx][1] if self.cats else []
        rows = []
        for it in items:
            rows.append([it,
                         MultiContentEntryText(pos=(s(24), s(8)), size=(s(720), s(46)), font=0,
                                               flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=it["name"],
                                               color=0xE8F1FF, color_sel=0xFFFFFF),
                         MultiContentEntryText(pos=(s(24), s(56)), size=(s(720), s(36)), font=1,
                                               flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
                                               text=it["author"] or it["cat"],
                                               color=0x34E3A0, color_sel=0xBFE9FF)])
        self["items"].setList(rows)
        if rows:
            self["items"].moveToIndex(0)
        self.updateDetails()

    def current(self):
        cur = self["items"].getCurrent()
        return cur[0] if cur else None

    def updateDetails(self):
        it = self.current()
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

    # ----------------------------- التنقل ------------------------------------
    def prevCat(self):
        self.moveCat(-1)

    def nextCat(self):
        self.moveCat(1)

    def moveCat(self, step):
        if len(self.cats) < 2:
            return
        self.catIdx = (self.catIdx + step) % len(self.cats)
        self["cats"].moveToIndex(self.catIdx)
        self.fillItems()

    def up(self):
        self["items"].up()
        self.updateDetails()

    def down(self):
        self["items"].down()
        self.updateDetails()

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
        it = self.current()
        if not it:
            return
        self.session.openWithCallback(
            self.confirmed, MessageBox,
            u"%s\n\nتنفيذ التثبيت الآن؟\nInstall now?" % it["name"],
            MessageBox.TYPE_YESNO)

    def confirmed(self, answer):
        it = self.current()
        if answer and it:
            self.session.open(RunScreen, it)

    # ------------------------- تحديث البانل نفسه -----------------------------
    def askUpdate(self):
        self.session.openWithCallback(
            self.confirmUpdate, MessageBox,
            u"تحديث E2 Store Panel بالكامل (إعادة التثبيت)؟\nUpdate / reinstall the whole panel now?",
            MessageBox.TYPE_YESNO)

    def confirmUpdate(self, answer):
        if answer:
            self.session.open(RunScreen, {"name": u"تحديث البانل | Update E2 Store Panel",
                                          "cmd": UPDATE_CMD, "author": "", "desc": "", "cat": ""})

    def exit(self):
        self.close()


# --------------------------------- شاشة التنفيذ ------------------------------
C_TERM = "#030816"


def run_skin():
    return u'''
<screen name="E2StoreRun" position="0,0" size="%(W)d,%(H)d" flags="wfNoBorder" backgroundColor="%(bg)s">
  <eLabel position="0,0" size="%(W)d,%(hh)d" backgroundColor="%(card)s" zPosition="0"/>
  <eLabel position="0,%(hl)d" size="%(W)d,%(lw)d" backgroundColor="%(cyan)s" zPosition="1"/>
  <widget name="title" %(r_title)s font="Regular;%(f46)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <eLabel %(r_card)s backgroundColor="%(term)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="log" %(r_log)s font="Regular;%(f26)d" foregroundColor="#BFD4F2" backgroundColor="%(term)s" scrollbarMode="showOnDemand" zPosition="2"/>
  <widget name="status" %(r_status)s font="Regular;%(f34)d" foregroundColor="#FFC53D" backgroundColor="%(bg)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="key_red" %(r_b1)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(red)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_green" %(r_b2)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(green)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
</screen>''' % dict(
        W=_W, H=_H, bg=C_BG, card=C_CARD, term=C_TERM, acc=C_ACCENT, cyan=C_CYAN, red=C_RED, green=C_GREEN,
        hh=s(110), hl=s(106), lw=max(2, s(4)), cr=s(24), cr2=s(16),
        f26=s(26), f30=s(30), f34=s(34), f46=s(46),
        r_title=rect(60, 20, 1800, 70),
        r_card=rect(40, 135, 1840, 715), r_log=rect(65, 155, 1790, 675),
        r_status=rect(40, 865, 1840, 70),
        r_b1=rect(40, 955, 900, 66), r_b2=rect(980, 955, 900, 66))


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")          # أكواد التحكم (ألوان / مؤشر)
OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")    # عنوان النافذة
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")        # أي رموز تحكم متبقية
URL_RE = re.compile(r"(?:https?|ftps?)://[^\s'\"<>]+", re.I)
XTRACE_RE = re.compile(r"^\++ ")                              # أسطر "+ command" الناتجة عن sh -x
LINK_MASK = u"[link hidden]"
MAX_LINES = 400


def run_in_pty(cmd, holder, on_data, on_done):
    """Run `cmd` on a pseudo-terminal in a worker thread, so the output looks (and is
    flushed) exactly like in a real terminal: progress bars, line-by-line steps, etc."""
    rc, master = -1, None
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
                    reactor.callFromThread(on_data, text)
            elif proc.poll() is not None:       # انتهى الأمر ولا يوجد ناتج متبقٍ
                break
        rc = proc.wait()
    except Exception as e:
        reactor.callFromThread(on_data, u"\n[error] %s\n" % e)
    finally:
        if master is not None:
            try:
                os.close(master)
            except OSError:
                pass
        reactor.callFromThread(on_done, rc)


class RunScreen(Screen):
    def __init__(self, session, item):
        self.skin = run_skin()
        Screen.__init__(self, session)
        self.item = item
        self.lines = []         # finished lines (raw)
        self.partial = ""       # current unfinished line
        self.cr = False         # last char was a bare carriage return (progress bars)
        self.done = False
        self.closed = False
        self.holder = {}

        self["title"] = Label(item["name"])
        self["log"] = ScrollLabel("")
        self["status"] = Label(u"جارٍ التنفيذ... | Running...")
        self["key_red"] = Label(u"إيقاف | Stop")
        self["key_green"] = Label("")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "red": self.onRed, "cancel": self.onRed,
                "green": self.onGreen, "ok": self.onGreen,
                "up": self["log"].pageUp, "down": self["log"].pageDown,
                "left": self["log"].pageUp, "right": self["log"].pageDown,
            }, -1)

        # تحديث الشاشة على فترات قصيرة حتى لا تُثقل الجهاز أثناء أشرطة التقدم
        self.renderTimer = eTimer()
        try:
            self.renderTimer.callback.append(self.render)
        except AttributeError:
            self._rtConn = self.renderTimer.timeout.connect(self.render)

        self.container = None
        if not HAVE_PTY:                    # بديل احتياطي إن لم تتوفر وحدة pty
            self.container = eConsoleAppContainer()
            self._conns = []
            for sig, cb in (("appClosed", self.finished), ("dataAvail", self.onData),
                            ("stderrAvail", self.onData)):
                try:
                    sig_obj = getattr(self.container, sig)
                except AttributeError:
                    continue
                try:
                    sig_obj.append(cb)
                except AttributeError:
                    self._conns.append(sig_obj.connect(cb))
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    # ------------------------------ السجل -----------------------------------
    def feed(self, text):
        text = OSC_RE.sub("", ANSI_RE.sub("", text)).replace("\t", "    ")
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

    def render(self):
        if self.closed:
            return
        lines = [l for l in self.lines + [self.partial] if not XTRACE_RE.match(l)]
        text = "\n".join(lines)
        cmd = self.item["cmd"]
        if cmd:
            text = text.replace(cmd, "")                # لا يظهر أمر التنفيذ نفسه
        text = URL_RE.sub(LINK_MASK, text)              # ولا تظهر الروابط
        self["log"].setText(text)
        try:
            self["log"].lastPage()
        except Exception:
            pass

    def start(self):
        setColor(self["status"], C_AMBER)
        self.feed(u"Starting installation...\n\n")
        self.render()
        if HAVE_PTY:
            threading.Thread(target=run_in_pty, daemon=True,
                             args=(self.item["cmd"], self.holder, self.onData, self.finished)).start()
        else:
            self.container.execute("exec 2>&1; " + self.item["cmd"])

    def onData(self, data):
        if self.closed:
            return
        if isinstance(data, bytes):
            data = data.decode("utf-8", "ignore")
        self.feed(data)
        if not self.renderTimer.isActive():
            self.renderTimer.start(120, True)

    def finished(self, retval):
        if self.done or self.closed:
            return
        self.done = True
        self.feed(u"\n\n--- finished (exit code %s) ---\n" % retval)
        self.render()
        self["key_red"].setText(u"إغلاق | Close")
        if retval == 0:
            self["status"].setText(u"تم بنجاح | Finished successfully")
            setColor(self["status"], C_MINT)
            self["key_green"].setText(u"إعادة تشغيل الواجهة | Restart GUI")
        else:
            self["status"].setText(u"انتهى برمز خطأ %s | Finished with code %s" % (retval, retval))
            setColor(self["status"], "#FF4D6D")

    # ------------------------------ الأزرار ---------------------------------
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

    def onRed(self):
        if not self.done:
            self.killProcess()
            self.finished(-1)
        else:
            self.close()

    def onGreen(self):
        if self.done and self["key_green"].getText():
            self.session.openWithCallback(
                self.restartAnswer, MessageBox,
                u"إعادة تشغيل الواجهة الآن؟\nRestart GUI now?", MessageBox.TYPE_YESNO)

    def restartAnswer(self, answer):
        if answer:
            self.session.open(TryQuitMainloop, 3)

    def cleanup(self):
        self.closed = True
        try:
            self.renderTimer.stop()
        except Exception:
            pass
        if not self.done:
            self.killProcess()
        if self.container is not None:
            for sig in ("appClosed", "dataAvail", "stderrAvail"):
                try:
                    del getattr(self.container, sig)[:]
                except Exception:
                    pass


# --------------------------------- التسجيل -----------------------------------
def main(session, **kwargs):
    session.open(E2Store)


def menuHook(menuid, **kwargs):
    """Adds E2 Store Panel to the main Menu of the image."""
    if menuid == "mainmenu":
        return [(TITLE, main, "e2store_panel", 1)]
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


# ------------------------- بيانات الأيقونات المدمجة ---------------------------
# أيقونات PNG ملونة 48x48 (مدمجة حتى يبقى المجلد على GitHub بنفس الملفات الأربعة)
ICONS_B64 = {
    "bolt": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADDUlEQVR42tWZu4sUQRDGf/NYxUBQTzBRAxMVMfCBGvgIREQ0"
        "E9EzMDJQQRQj/QPUyOAwEg+U84w1NvURCKILhycmIkYmRj5Obnfa4KqhHPYxN1M9u9MwsDvMVtfX9fU3X9dG7vUhmjziEcwZ"
        "NRlABDjLeeOaq+2A7cBxuZc0BUAkVwJMAz+tAqc1AUiADnAP2AO8lftZEyrgkz8B3ABeAn8VpcYaQCyrvAl4JAm/sZw7roH3"
        "DpgFNsj3dlNkNAG6wF3gsNAoA+as+B8SgOf9SeAmsCiC8Q34Ks+4cQWgeT+TS/Sj5QYOASCSmJHwfp2A8fbhvfW8cSDq3Fa8"
        "TxSAd+Ns5nzyp4T3HWUVEtkHphvYEoDn/UbgsTJskUr2i1xjByBS11NgQhKMc8nOSRUSSwqlhtTRet8rbhto5fZEv9EtqlJp"
        "AN6nfWz0C6nA4rhUIO9zsj6UjGVFz8s5IB6wBzJgJXAf+K6siDmASG3QWWC9JJkMqNTVgrGfAT+UFQlSgaK816MzhPOpvOjO"
        "yPcoFIXyPqdTME6/Z5wkuwBckOTjolIbV+D9jNEB3VPvMjAvQLPlJFRG758on1MFgK/etMRMh1CtEoW8mtwBjiiL7Er2fzzv"
        "27LBC23asgB88NPALbnXGvIbNwCEB/0LOCf8L2WxiwLwnJwH9g5YYa/bq4DnQrNeQPzqXwE+laHOcgE4dSApMnYCa/ok73n/"
        "UISgdPJlZDQewm2fzFF5Ni+xmvfXyvK+CoCsoCzuG1DF38Ak8EcAVDpaWp/IMklqV4/4Xu8vKb3vVp3QEoBXkS1y6fiV9b4u"
        "ALDU+1yhVtdE7+tsq+xXnNd6Pyl676xaKtYAvIM8qN4JlXxOnQD8C2wC2Ko2dBDeh+pKAOwGVotPaoXifagKaP7nfY4p7627"
        "EvoFd0A+t4CLVX1OnX2hTKRzh8R8YOFz6gLgY2wDNgMfgOsheR+iAoh8OuCs8J5QvLcG4JM8xtKfeJ+tfE5dALrAWuAVMKW6"
        "FjQFAGKNp/i/G13LsJLRBUY0LL1QNAoA/wA78dVTTYEt2AAAAABJRU5ErkJggg=="
    ),
    "panel": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAACr0lEQVR42u2Zu4sUQRCHv57bVVGREz3kfIGiiS8QjBVMRNQ/"
        "QAMjQY00EQVFEfEyMzFRMNbEwNhERHwngoGCyF10Bh7i4eN2Z8fAX0tfM7MzuzvOeGwXDLfc1szUV1XdXVVrxt8mLGSJWOAS"
        "AALAsAM0CkLWBZoAHf3tGSDSzfaqO1M6vQC4N+wBtuuzqdDzAJPAE6CVBZEGYKS4BbgD7KvZ+++A08DjNAjjncSR6NcCL4Fx"
        "oA2M6Ps4Bbrdw3rqVVpAU+/dCzyVLXFWBKz3b8j4OWARMKvvlgFfHN05YI2gp6VbljSB5Q7EbWCXH4GGZ3wMjAEH9bkJPACu"
        "AQ+BJcAL4Lg8fwKYEMAV4L7voQEWbRO4AJwRxDatx+fuO3yABFgNrJCCkYFfgXXS2wHMCGCT84yN+n+ZMgGcEkwCrBeA6baI"
        "YylbpVHgNXAJOABcls4IcBXYAPxU2kXeLjJIBBKlpLXFOOstdxcynhEGuK7LPcGngSMpJ/ug263xnEjWc4vsHN9T9t+sg62s"
        "A88+Z3aQUsLS3lRum4z0MCWlTVoEFntp1BfA7v+gZouHshq1YbsFvO9WUP3D4m0UuOhUAn0B3AVe1eTgpcD5bnYW2YVWSq+M"
        "E7bXCIzlbcmNgguorYhUDdAOPXEACAABIAAEgKEHMFQ30MqzLylSSvg3/fL60irEvueHZ3yjSAS+qUm3tMc0FbD1UBWXrbmO"
        "qitrC2rGj0TaZK4DPAL2O0OlDxqtmJJbx7x2cqcz3vkMbJZz/0JkTSXOAc9kfAvYWtMasA4EOKuUmlfWRynTAAO8AQ4DU84D"
        "6pCmJhMngXuyd15JbzJ+ZrWptAo45DT2VS1i68iP/BlpfspqaU2X34mr7MDyJNOWRk4nZro11BVGI+63pUyKtHWhlAgAASAA"
        "9C2/AVWpv1QwtnGtAAAAAElFTkSuQmCC"
    ),
    "tools": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADvklEQVR42u2ZPWjVUBiGn5ybWytisQ6CoINr/ZkUtNWpg4oo"
        "tCAIDq2rP1iEgpODOojipO0kqB0qWMWKgiAiHbSDg2gVQRTEQcVFsKLW23sTh34HPtKb5PTSJFfwQODm5iR53++839+Jd+NC"
        "hX95+AW/3wCeOg+AsNkJeEAJqArguOs1FzJ5E7DAqnK+BlgnOCrAB+Czum7nF07AyqQmoA8B+4D1wFI17yfwChgHrgFfRWZB"
        "kgbzAB/KMQi8BE4DmwV8oLS/DNgKnAOmgKMKvFcEAfvSVuAOcB5YqfQfCgajiAZyfRVwCbgNLIkj4WcM3giocWAnMCvv9BPu"
        "sfdVgBZgWkh59aRkMg6RNeCsgK8A5TgpRMasgB8Sf6nGRSSTcbTZBJwUAGXHe2dl7mXxgZL8HxbhA4PK4t4CwR8T8InJzWSk"
        "/Zo46x61Iq7gh1zBZ0XAgt0CtCsHTBq1OrJxKiuylFCHCotJIxDAwwuxfB4E2h0tb4CbwBGJPEngTZ4Eqo4GDIBtQJeE2lLK"
        "XC8vAu8doo9NXGuBB0CnEPfrJNwA6AG6NfYsCFjNv1ClQlrUCoDlQqIrQqIs57uBUeBj1isQyHPfApMqrLpIqS2yEq0SXruB"
        "u8Az4J2uULOSkC+gJ5KyaAwJuxLbgRlgl4AvAxejhs+CQFmcsRcYUGGSBZBoA+5JJh+TMnsCuC9zqllVo2VZ8l4JjSWxvreA"
        "Z9gKdoWU3wDfgP56zzIZgjcxWbjmkNxCWUWA78Becd55JbXJAPyYsqKJybpGNS7RwwaBFuC5+MKkytCLnsgs+B6xvBcD3mbd"
        "RxKhjGpu9GEk0pyQaPQ6qbn3M5BNPfC20hwB+qQX3iEZuEOuzQBvxNpPgT+RxmjRdyWisvFSwF8XRywBv4GHciRVtUGav/gZ"
        "yyYKXju2buSjOxiBQ/JrmEAjsulX80LlE7ntjRplvUZkEwW/qCnftUG3WuxtQDaZgHchoHcXDktY2+AAfiQP8GkEbPg6AFyR"
        "ekRnSq9Iy6cRsC/fCFxVZW1JNSGFg0/KxBbAcQW+zPwPErY8yFU2LgRsudopQEoJzYvH3FZ4X97gXWohP6EUtk5ckbqdOomp"
        "MALW4lORPjdq/YC5ryrTaTVLUSswHNkuDCOp3shWYIV8PpY4E6jJKjwGTslvHYFsvT4q24HGcR8o1xWwJM4A+4EnwA/gl2yZ"
        "DAAHleMWMtIysZXJLTlWy/mnyJ4OzUpAt4EB8KVOmUGzE9Clr6dCZeHgG+kHwiL13kgYbfrxn0DR4y/rhCwVjrG0+wAAAABJ"
        "RU5ErkJggg=="
    ),
    "key": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAD1ElEQVR42u2ZT2hcVRTGf+/O5A9qbElTkCgxEekfFymUDF0E"
        "EbKoiyK0CIKlBFelErsvtLQQcSXiJi2l6EJaQUFBN1IXLqwIbbRGSyGKgl00tCYY/yyCzrx5z8134fh6X2amk0yMvAeXN9x7"
        "373nO+c73zv3TZRefo7NfDk2+VUAKAAUAAoABYACwKa+yi3Oj9SywFMg0f0/CSACSkBsjM1br95JIOUmaZbIeAeMAnuAYY3f"
        "BW4A3wEr6isJyIYD8IZ0A68AkzI+dN0C3gPeBBY7BcI1YXwF+Ap4wxgfAzU1T6th4AQwBzyvZ0sbBcAbvx+4ItrE6vNU6lLz"
        "c/3YIPABMNUJEC6nrw7sBT4Geo0hJdHOAX8AvynByxqz+TIDvLjeIFxAbZDRF43xTmNV4DwwAewAngT2Aa8Bv5r1SgJyARjS"
        "b9eJJPZSeQx4ytAlAn4GDgNXM8/Mqr0t0OMyOAEeAqaBl0S3dpP6HgmPzJk4MqC+BXZrsvf808DXUqS6WchTqApsVxIPGq+v"
        "KArL6x0Bz/1d8n6qVgLeMcZXA16pamwJeFU082MPKqG/bENaUzlqCbhp+v4FwEdgTHfP/VTUcA02j7XGR8DrQJ9xwvQaOfwT"
        "4IB1RCixHjcIHfAn8IPhdd7lxxaBn0xfZJ6931Y1tO1rJKNRwLC4xXDHOcm3WvMOs807pVv3ZyXtdW9nCMAvphhLgYeBkZwq"
        "NAR8q+aTkdVyg1bKyVG7Z5fWDyaxN/q6UZa67oekLqvlQVmlxQQwYHII4HPJsAvQMNLeW7SPTdoPRekxY1+8moymwAPA98Bj"
        "RgqXVQctKJw1s2BkjO9S3TRqno2BJ4DbDaj3CHDH0NYB2/Q2nwH+BnqkhhVvr8tEoCzdvmQApVrofW1SzRifyvhe4C0BteOf"
        "GeAh6vj+/gCofjk0yTs0ZTntk8OXxM54ZBy4Brys6HjQA8AL0vlJs4YHf1J3X+zltRA16yahe3TvXq2U8C+uJeCoND02tc0Q"
        "cE46/6PGRhQhu2FNG50CvmnjBeaLxgVDoYW8HAiV01PiH6YuSgOKUc8kpdNzx5sw3if2TmA+kwMVnfR6zBqJrQbyZNGXwGeB"
        "I8DvGUmraZGqSeiSAXZaxrsGL7/QBwN//o6MCKwAf6lVmz1SehDvit9ngIPS4ZBm14BPVQvNmmg1OuAn5khaycjofM4LNm1E"
        "oRCdAB4FnpEu20P9HPCF5Lejh/qoyb+Y/Jmg3sQ8WqBNyFnZ6KRr8V0oMQa6TBgjMydp06EtR63VL3NrYWTxbbQAUAAoABQA"
        "CgAFgP8NgH8A4hw+q6+OuEsAAAAASUVORK5CYII="
    ),
    "audio": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADxklEQVR42u2ZXYhNURiGn33OnplCI8qFESkjSZILIRTyk6Rc"
        "KCVCQvlLbvyVTLnwkxuMRC5cDFcuUCREMYySJLlglP/CFY05M5x9lpt31eqYM2ftcfaZOTmrVu2z99p7fe+33u9b77dOYI7O"
        "oZJbigpvVQBVAFUA5W9BJQNIAaYSAQTqOWB0KVchVUavG+AQ0KzrdCUACOX1IcAFYD8Qea5Y2neCJI3PAmOBi8BMgfGJAeMJ"
        "NJEVCBzjFwKtMr5L8wUeGWo4sNmxMSgXAPu9LLAVuAE0yJuhJ3iA08AZ4KxWLV0OAGlNFgIngVP6fs6Tz/b9A8BKIANsBHbK"
        "IekkAYTy8ijgJrDN4XDK0/Mp9TvAR6AO+AUcB6bpe2lfAJbHvj2rSe4B8xyP+eZ7A/zW+FZglRPsKeCEvmd8ARgZ4dvXAneB"
        "Rv0OYwQ8QD2wT16uAe4DR4BarcIMYLFD0YJp1HJ2NrBB1ymPjLFM17mYqTmQs07ICY2aN6VNb7V2bqN4uJ6/CoUATALWxTDE"
        "9CGmQqAb2CLjM8B64JkAZYAWYK9sWgCMAL45wAtO2CUqdHnQJ3K0TpyW0zttwFvRJQL2aOcOgCsaZ3fz6U7GKlkQ91XTWHo+"
        "1SrYNDoSmC8PvwC+aB4DTBloBY0FcQt4pwA22rkBOoF2x6nj8yjb7wCMDMsCzx1DJzjPvznjhw3UkjLQPkA+xwskiwEDwBY5"
        "ABMdI986z+ud8ZmBBsAWO1NFm6yMfqzntQ7vAV7l19VhET2e89DlQR8dYb3foCrNGvUduK3r8dJXVge99C1oavSCb4qM+pBO"
        "0/L4KkmFTmAQcA74qjFLHKH4C3joZK8eAdgg+QI8KWKY3Q2HylMm5rFJpJU7DSwF5koDHXSotcah2gPgg6MWegRg6XJN3afV"
        "AU3A7rzc7is/OiUlDgObFKg5XU+W52uB83lyp2gQB569W9v/aqBD38zGlBPvRaUO3RsHHHOU7RvgssZGvlnIeHYrO1qARUqB"
        "YQwQxjmFSANjgEtKn5Zmu7RSfx2MlSKNGsdTj4BZkgYWhIkBIgK2qzj6KXo2A1cFLkpyH7BV2Gdlj2YnxnIxgrpJjhisImmH"
        "I/QSP5WInCDbJm9mdS/yDOoOBXUzsFz3C54nJbET55w8f0ql4CfRIfIM6tdywI9CGihpKWGcs6C7yvFthXjcS1AHxWIoaS1k"
        "g7tdRcrlniRxLw4omgBCkm82BjLAChUrge/ZZ3+cjfbGbZRhSvYnRznltPkH5dqvFOppd6cSVyCxiqgKoArgfwbwB7S6FoVC"
        "saDSAAAAAElFTkSuQmCC"
    ),
    "cc": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADrklEQVR42u2ZSWgUQRSGv+7pxIW4owfxoCC4gIgRRb0IIrl4"
        "dDmI28HlIAQUbyIueBBU0IuCxHgSCVE8hOBBxYMgCi4gRBC8uKAIioiIJpnp9vKXlGV1nO5pZxKYgma6q/vvfv+r9179VRPs"
        "eJ8wllvIGG9NAk0CTQJjvEX/uB8ApQbbGOvITKAEVIDyKHC0saVqAgYwDdgArAYm1tnoMvAYuAW8UbjH1RAwxm8EzgFzGuj5"
        "3cA34ARwxjcSYYrxW4HrMn6ogQTKwCTgNHBStv1hc2BpoRBIgHnAANCq6xLwAvio5/63eAr0OxlYrvNhoAXoAG7bIxE5o1EG"
        "9gLj5fkSsAe4XAfDfW090Au06fuHRCDxhZCJrXV6oBXoA7rkldA5SvLKOB0t6gurOKrBRsAd5aFx9HJgipI5cEfAsJpqDeMT"
        "68XDzmhVUkpbOFLdzoA1RJ9a99sUWl9lY+KrQhWnSlUsQnaiRxqtVfroA+CeztNIZMVWHCf/NalFIySRL2GN95YC3UC7c/8B"
        "sBN45SGRFeuzIahFCxmDliiR2p0SOwSsAe4rVhPr/bVgCxFzhvkEoAeYqY+2Aq+BdzpHSTnbwuXFFqpGS/LgNmARMKiPXgAW"
        "AAuBq0C/vNxnxXBebFyEGsV52XarxD4H9qt/UAb6qkkt2MIIDAPT5SETGtf0GzmKNbAMMOd5sIUSSIBZmiPMJPJE/bFTKdyq"
        "kRdb+Ios8AitemALq0JfgO9W32LhAyvRS75aXSO2EAKR1OhL6yObnWnfyAO7hpuQyYMtnEAC3JARQ8BaoFPhEAOHgVNW2bS9"
        "mxdbWBKX9dJLwAFghvrOa8lptI1Rs53AI8u7ebGFjYAZ2k/ALl1H8maHPjyoZ1doLZ1YVSgPtvAqZGbVfmAT8NmSAEYGfNAi"
        "5Jbl/bzYQmbiIIXETe0YbJEIiyXEepSwvm2QrNgwTYFmkdPDnlEyL38LnNXhk9xpo5gFG3pm6iCNgInXH1bffHko8pCNrI0A"
        "WwbEVYRmNdgI+AnMtXCD6vs9a0eO4iwDD7XoKCteuzXEjdhSmQcctCrZgIrB7xzxrYm7gH26btPCuk+6vZ7N7ArOkOfHARdd"
        "xRo4/5GZBDoKHLPEViM3eM2eUK8S/48KFaZUiuPAkVFgPDL+inYLQ3eOCFL+pTQslwm4UkvCoM458EwS5K5TaP45D8Ty/DMd"
        "jW7G80mWiaxi7ZLFDdpaNEKwkncmjrMu8f5DGBWmhUZlaxJoEmgSGOPtF2kZQNGbbaFiAAAAAElFTkSuQmCC"
    ),
    "epg": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAECElEQVR42u2ZT2hcRRjAf2/2bbUlpo3QQguNglIa9SAFQaEU"
        "C4We2mMPQkFQkmPRg4eCFDz01ouIRDxaRA8BQQShUPRkCaE9tLSBgqA9SZImSE3S7PvjId/Ax3Rmd957u9lEM7DMvHnffjPf"
        "/z8vOfdNyU4ehh0+TIP/JZ511dEKrKNHWvPgIrCuOvLAemASsPBngDngAXAdeEGkkFTAY4CrwDxwD/igzp2SikacACVwH5hQ"
        "+5PA1yLRLEJtcuBt4De13wGOAIvqnNoq1OrBzZaozgbQBkYFVxqp9wmwX3DkspcBI8CKSMFVzdKnZmmEbvpGptSgBfwte1kE"
        "ARbmsfy/VGqzEIkjSIAV3VngsKx9knjR0dd3RQVMhFFbmAl1pr3LJLDsqJC9wyow4zLXtQGLfBZ4a5u5/CfAIWBNExhSoRUR"
        "ZR7wz66NFDXcaeLBnXuMtxDGPvYZdjcjTgOHdHOLTUcrEHNM6B7/21Ril4BdAv4rBMSEfhvCo/OTPozEidCNCEgapN39GEUT"
        "AhLgT+D2kCTwCvBGEwIM8DMwNSTuTwHTTVXoORWZsy20zQzYNwgjNgE9LSLqiaxHLoSqEfKY/CqtYVAxSVseyZisqXtPK17+"
        "pNSuhUq9DfAtcEOVi1eAl9V7JJ//BPhHnifk2eb7FvYG8N2gCHgdeN/zbl4ONkLAe8AxD8c/VQQcDeDqCEMG0lZZV6VjquZV"
        "B25Z1RO2b7TsuOGOwFjOW1xPBtkX0kFNz6ZLPWECwdDuaTVLq6Y3dYxYF+9ZIFrmHglkASPWEqjcKKtKwF6nfWLnfZ6i322z"
        "HHRc6x7nvV2PDIoAA9wBPle1sp1vOdz7ChiX50R1FdYVvt8Fl/VCFtevkd2NWgTMyq+X/78Wge8hcKnLvYpBqNDzbPZBfS2P"
        "NfU85sFdAkvKE7WBAx5ca46k+kZABlwAvvC40cuSdLXFPc4AbzpGvAKckBngHeAHjxudFnwMSgJjAePW44AHLnWMuB3AVcmI"
        "TQ03WgqX9Vx4pKXdpIV1VapUzawOgQZuUwISz7P7IwKmDlzSDxXaUJ231OmgtRQe+ys973V0dmOICeAq5ezaBFj//KpKoxfF"
        "47hGvOhE6GWBc414QeFfEBjXiJcUnuOOuj1T0rrdaXupzyRz3JCI+T2bX1MOAi8p4uz8CPhL7b3mic45cFddbtTJWC2uBeAP"
        "Ydyk7LWBH4HzKoB6CbAfHMYl6o6JcbWHVBPnKiE8DfziEmA8XsYIBy6y+eVlWJe3dmGAj+TyxvVSaYDqFvCTBJuPgVPK1ydb"
        "cHHrTueAL4GbLud7GbE1vvvAh8R/wOs3EU+VJPKqXqhwcvlsSCrUtUnQi6vFFqpNre5GWkGc23Ls+Pb6v23IJkIDtPbHAAAA"
        "AElFTkSuQmCC"
    ),
    "tv": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAACyUlEQVR42u2Zv4vUQBTHP5PkwBUtPNBTDiws1EIEsVIREbX2"
        "nxALsbAQC7ERbRS1VDgrf2N5va2dnY2eIuIvRFFR77S4/LDYNzg7lwyZ7G6yBzMwZJOdZN73/Zh57zuqOH6P1dwiVnkLALpu"
        "ieM/ZfSuWw4UPgAi10sdtRjI6gDQwitgNzBtWKTNppW3BDwH/hqyVQLQAw4D14E9E6L9N8BF4K4NIikx0UHgiQzMJiAGCmAb"
        "cAdYA8yZ7hRZgZIAN+X5sgyMOu6xyJYB14DNpmITS/u7pGfAFHAZuF/mey0t8TmwX7QOsB44KjLFQGrHwEYxmXabOeB9xy70"
        "ErgEzIpsm1xBnIrwegVYZ5iybQtoOXrWs9QFQJVsILnxuwsAmUvGkAsFAAFAABAABAABQAAQWImVdagJsCt2QlUouXABiK37"
        "pYqMsM2i/o+VCccuAIvWy0eAR1WURksV2V4ptDKRY3HATELuanP1gAVgi4CIgY8du/mMKHpZQO0EXmuAiaHxWMx1DnhgVGiz"
        "HQPQRdUUcEWEL2UlMrl/CJwCfuCmHutMXFjXpq6UAleB8y5eSE8aAbeAeeCQXUTXKAHXAhfkWsj39PUG8M6zxv4FPBXXXjlp"
        "xQHHsEH7jT4lWRjAFLAdeNXwm7W5UdOdfDY6LegGx54xLXP6KiivGp/UCB6XRka1uTXea5oGqXJM+JVqWv67BGQ6rlTCx1WO"
        "AQf4T8WbRFSv4t2zwCcGzx8U8AJ4bFi0GBcA7bsngNse+Yy+nnSM3Qec8Y0P1fCYdYE+5Z2WBLpyxEdaol1zqd0KfPZZZn3T"
        "aT3+iwgZixXNHhuC2b1qfAL8pH8Ko3xcKGrg/0pM/VYmVkP2WHb90wIiGmcM6IOFZ/TPz3YwSMc3WT4V8EFcR/kup0nDSSPg"
        "twAZdfrcyj6gl85RlaQ5DZO9YbLNriq1wEpMVPsH2DS4HR8FeWcAAAAASUVORK5CYII="
    ),
    "skin": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADbUlEQVR42tWayWsUQRSHv+6ZCYJogigxKB48xQUXEgyCgQhR"
        "FC9G3A6iF8GD+IcI+QP0IMSTCOIcPCguEEQPgktQQQ8iLqigoAEXNDPT5eWVPIvu6Z5J9UynYEimezL9+9X73qtXRYI3o4aF"
        "PMoLQGMoLwNE8nPBGAhFdKSuBdpEkQ2UgAawHhgH3gLXxMw/E0U1UAFqwHHggtJ5HTgI/Jb3Jiyw+BPARYlEDZgD9gInJQol"
        "y1hRxU8p9iuitQaMuElSRGymFOuB3I/kM3eLaMDFxhVfA3qAq2IulAQvRBLHYeOKr4j4wworU4QIpGETJ/6/dSAsODZW/CF1"
        "PypCDmTFpiozb+LEd8tAK9gkzny3DHjBplsGvGHTDQNescnbQOh8r3ds8twP6AeHqn/xik1eESiJgNXAZhFRzwObPCJgNx8r"
        "gJtiYhuwKSM2ph3xvgxY8ctF/Dq5/gBYrNDyho1PhEIl/hawRbAxwFKFlVdsfBmwJwVrgWklvqwaLhPTz3sT7yuJe4E1ChVi"
        "sLEiLwFH54uNLwN2Bp8AO4AvKh/iRgOYFIxKPsT7iIDF4imwB/iaYCKQ6zeAUbkfdtOAFWRPDAAeA9ubmEDKbL+TGx0zEEiC"
        "2srSkNcAcEzKYj8wBMwqE0btoA4AV/Sedt5Lf8rhbqB41cwOALtE0JgkMlKFxoBPwCOgT4QGciBVlUmo+1r+0xYyox42AOwG"
        "9ovIPidBI/m+abk/BMwAS8RoVTV2/pqvhAhYPpcB+4CJBNEWw8CpTJEk63dgA3DZ98ynGbAPOwecShGdVF7rwE7gfh4zn5bE"
        "Vuiw/D4nONnKE2RYoctyijauar/3UU4QEAErgUF5cNhm2fsGfHbPcvKOgBU6KN1k1KJ4o8rsEVnkQl8rbysGRpw+JuuoS9TO"
        "AHckyg1yGmHCDCIbEtoQXwHOSwHIpfKkGWjIgze2uFrbv7sHnE5p7HIzYN+vUi1ymIF5i8174T5yWoiOGxgGFsXMoFGb9bpK"
        "8DLwR1bcj3kmbdZWYquqJMY5Jgkc4z+Ad8BZ4GEnuG9mwM7akAjtce7/BF4Dz2UjMwO8FHSsyY6Jdw3YHqZXdli/gFfAM0fs"
        "hyY4RnR4lBPWgQngRROxJWfjbroh3jVgWZ8FbqeIbVCQkRQB/c8VhRGb1YApumg9/gIH9Dh6JETUcQAAAABJRU5ErkJggg=="
    ),
    "settings": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAACzklEQVR42u2Yu4sUQRCHv96dWzVRMFAwMtFQVA4OzjsPMTMQ"
        "RBGU00AuNzPU2L9ALlJTH4ipnIGgni/wAf4BPkCDQ+SSk72dHZPfQNPMzu5N1+zewlYyS29PT1V1ddXX5aZ/3GOcpcGYy8SA"
        "iQGRkkS+3wScfmdAOi4G5EqnPcaz7WyA8xRcAE7IkJfAq4I5QzegaMxXJgX2AXeBM8G8R8ASsK7wCnfGQlJfnyJlO30WmAIe"
        "yPvh3AtACzg3rPOQFITGksZ/e2OZPPoOOCrl21LWl03grMLqJ3BMhsTsQK7DHmAvsAxs5JGReIZ0gBvA7ZLFZoF5Ldgo+dgs"
        "8Bl4XIPTjwNX5NA0VGJ/n5fbwI4+czLNadcUNQf8c5l4B8MBN/U8GHg51dwWsApc75Fl8nfe6vlUO9uMVDr/1l/glh+SrgKN"
        "7gY+AIfk5aZnZAv4qDOwMYo06qRQWQ5fV7Z5CBwOqvIX4KKUb9agr+uXRrMB0mhDik4DV4GTWvQFcB/4532odnEVLzQNoFvh"
        "P3OOqspC3YJwy73eHSAMzDgqicwMnQoxbMpRibFRDIGjolkoRsw5alAWit2BGI5qWLJQjFhxVBQLxYgVR1ViodgLSCxHmbJQ"
        "jJhzVBUWipFYjjJhodg+lClHWYfQIHxjwVHmVdeVeC6sJTEcVZsB+cV/Rrl+J/AGWNF4aIRZqFZlodCju4A7imtfngPXgO+G"
        "faJaWGgZWCx49zTwBJir64pZlYVyvvmqcFkUyySBd9sq/eeBZwqvzhZ3wLQvFMolFafMO8hFWWUB+CRkHmlfqIhvWn0Kn9Oc"
        "zVH2hYoOUlPefV+Sv/OdWRWkVe0T1cpCU8o28z345hdwBFjbLn0hCi4ilxXfM0FV/qZzsmbUJ6qFhZxuUHOqA6eUmV6Lb/4o"
        "xGrpE1mxUNnVc8t8MyqUMOObURgwDBTvub1jLRMDJgZEyn85vhCCDk8I2QAAAABJRU5ErkJggg=="
    ),
    "media": (
        "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"
        "gg=="
    ),
    "dish": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAES0lEQVR42u2ZTagVZRjHf+/MuYnekjQvBQWl2AeBoJC10Mxo"
        "UVEgqHFvCJdqEy00FFrYrk3uDYTcyJUSDSyJSPrAqIWJuFAwKwkhF1K4EdMw7zlnWvh/4GGYOfNxZq73gi8MZ2bOzPs+/+f5"
        "v8/XhG0HE+byiJjj4w6A2z06s1SuGAg6T4DeXAIQZQgcAf25AMAEfQ54DZgPfA0clkWS2QzAhJ8Eptz9t4BdwPtZlohmmfCP"
        "Afuk6Wmgq9+dwCt6Jh4GgN9cTQMIwFq3B0bEkKDrl/RsqAvAJk5aAGH8vqpfz/VEivtnmDhgJn4ZWKBJm6JfLJqMAe8JzIjW"
        "6+r8BnBA/1XeA7Fe2iyPsF/3mgARy6pLgG+ApyXsn5q7A1wGNgBnswB0StLmcWCvzjcBB4EJTZbp3ioIPybhV8kSrwPfAeuk"
        "/Z8FIjMWdAp4aSA+BhZpwa6scQgY172qILzw3wIrJfwEcETPHC0TyKISvN+iwNLVwh2dmyVGBSDUpM1KzTcBfC6tBz0XZ9Gm"
        "DAB7aZ4CSJrvHeCmLLEtyz+X1LzRZtwJP+3yn16RZaMBCyXAq8ATEjBKubYR4Brwpe71awo/kRK+kXTaUE9m+GUc748AvzhP"
        "NQxtpuu4sSiHPj3gHrm1kEEP4/uhEvwvSxuaBIDykgcyIq9Fxr+Bnwry9VZoUxbA8hxu2/UFhf48Fxq1RZuyAJ5M7Yf0/rjg"
        "tJzngpcoKDVKm7KBbLTg3ZsFidl9wDFgRdO0mamCZh6wVOfjwBdNC18E4HrBu3cNcMEBuAQ8JUscd1ln610J4/i5rALCXS9z"
        "MSEPxO8DCvXW+kIG4I+cZyIHYOGAAsfSj6Ig1xqA88BfGW7SAt39SnnDgDyo35bmiwBYCXcyJ1AlbnMmNeuBVluLRon9OamC"
        "JXsbRSWfrYaCY0YAWLL2FfBbRkFh6fYC4AOXrUbOInlHNBMAbKH/gA9zigrLc7aouOk6UItyjoVNb+gw4AOHN/kxVWW91IY1"
        "Ya4AqxW8jgJ3Z1Cmr2M78KlTQGuBLHGaf1vB6N5UcWPUWizBfwUeLlhzUgAGdUCSYSnktRYrIL3jON5PzZEo/d7gBEgfVipe"
        "S1k5corsVfVoZTZUTwt8JkvEGZE1OMGjAi8Upza8NbDQfnqxStOtrEewjsRe4A1xPtb9JNXfLDNXXxaJlfDtAE4Ba4ATDlyj"
        "2ahZYgo4A+wGnq3YC0LR+3vN9aAKp+vAVnWmaZpCae0F4DTwPPCuCpsy0disMwa8IK/2EPAR8IgTPjTlhfIEGBWVVolKIxUX"
        "TVyg/FeNgx/UPnwTuDioEzcMAOP8TvUva8cet+5i4Bn33x5ufcgIbVjAxqPS4A2n/bo5TuIs0nE1RtIGAJv0E259gBul+TFV"
        "tQCq6oWCWonrtQf6DWSYFjsuqugPVVKMTs3FftTR9Kj8raHOHrD0ouncPqmT3NVtq7RaJlYZ/wP6TUwXrTyVkAAAAABJRU5E"
        "rkJggg=="
    ),
    "picon": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAEEUlEQVR42u3ZS4gcVRQG4K+qa4wadaOJE0EjREHEKC58JUFQ"
        "cKMLHxvHlfhAFKJZqIjiiwQURBdBRzGEuBAiiorvhYIK7lwowYWiiIgJ6kpIBM1MP1zkXLiOVT3dMz0zHcmFovpxu+//n3Pu"
        "f849VXx0cJOjeZSO8nGMwDECS0igRDUGGFtx1Y6qz4866I4Bgc4cTPMSSBMvxD3YjAkUywy8F/ev8Qo+qSNR1YRNB1PYjdVj"
        "4IHzcAsex47A2K3bA2Ww3hiMV2N2DAh0w6jbcWO8b9V5oEQb23B8gK/wOr6dy3wBo8hCoxVr/Rn3Kgw2EWCTMSdxa3zfxSN4"
        "JwuvfxFox31TTJgI8FNLaN2NWI8DEet142c8FQTOx+n4LRm0apDPZK19Ya3jRhROJWZwGfYEoDR+xJ34PNYrY819mQf/I+3z"
        "6fyqcOls5qHFgO/gbHyA0+Yoyga8j0vxXRZOqxrUaaBM3Btx0uzh4QA/kyWpVrw/CU/GvGIQDMtZSiQPbg5QVU1O6kV4rRo0"
        "ZFeiFiqGUKuxIpAs/mWAbNeUDAW+wuHYyGNFoBsAn8ahANjOrokAvn0lPVD0CZFE4HtcF7JZZdd+XB/5YOCkWY0YfG8AL5T4"
        "AhfjqpDV/fgMf2Tgy+UkkBbdiEdxcyabvQYSh/BeQyU89MYaRdhMYBcuxy94ID6b7RNOZXZvDwt+VHsgWe25AP837o8ibLaP"
        "kXrZoWlmoYViOQJpbEfI3BuvU/mxG1vis1Yf8l1cizPmEYGRE0gl8QVxfkh1egJR4Q2sy0rkOs9dhA+jjO8Ni6lcRNzDCXgt"
        "7nn9kgq3dUGimmPdBH4DPo7XW0ORusPgKhcZ99PhgbowSR7agudjfitTrDV4G2vjuxNjH/WGCaNyEXF/O27LTlT95t4dV5pb"
        "4t1oHLQjK3dwE67JyI6cQLLqJXh5wIWSt17C1aE4b+KKBvLPZkfIkRJImfYU7M0WHqS6THP24EXcEKSqhnbOHaMup4tM8nbh"
        "nHnksekwsz56Td2G3xbx3XacOoislkPG/X2h+e0FZPEiS17lPCXJWjzRcPBZEIG/cCV2DrPB+nhyvj3TxV04EwcXQyCxX4NX"
        "4497WT2zFJfsMP9MbPqhirm8ejwcFnkLZ80hvZS90om4T2XEyrpyvam5m8bJETqT0Z9Z7nZ7LxSraIqYOhn7BufGRt0af/JY"
        "kwWW+OA/iQcjnAr8hN8ztaq16HRkxCJqnIfGoME7E9l6OlPA9lyXJHX51JFWdmvAY+JSh5AAvxcvZIef2j2QSOxwpCO9Lcrd"
        "yso84OjhhyjXd9aFcdHwoDvvCqyzsg8DD/RrGlR9ugcpofw6Bnug8bDfTxY7A/R6liuUOovpSvRWeCOPTWvxGIH/JYF/AKNg"
        "G0MjDBkWAAAAAElFTkSuQmCC"
    ),
    "disc": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAHGklEQVR42tWafexVcxzHX+ece36/npBRSbP0QGPJQ9TaTLFV"
        "HrMfKpFS0x9oaDYio4zFloQ8TmH+QUlDbKn9PM5EEomGSIo8tKbU7+Gee/zz/ubzO+45597f7xfrbHf33nO/5/P9PLw/j9/r"
        "LZoVczBfPgf5VWhnZTiFxECU+D0APH0u6fW/C+CJ6bgCpqIyzwa6H//XAjjGI8PYscAQYDBwPNAPqDEa/w7YDHwKrAU2AEVj"
        "nVJrBCm0EiolMd4BuByYAJwJdMp47oSENdYALwPPADuNINGBdGKnqQCYBqwXA6PEfCPQlKLJGGjWGg8YBsyTJe4Cuor54EAJ"
        "4LQzCHgXeEpQaRJjALWCTROwFdik12YxHmqNg18j0BOYDXwCnK/7vnH4doFQQXidDDwKdBbTnsH5RuB1CbcB+BXYp99CoIf8"
        "4izgPFnAWbSo31ZImDmi7eX5hVdBInPM3wvcrntNhvG3gAV6b67CosOA64ErDc1AryXyLQe9uLUQcszfI+YjMVkDbNcmo4A3"
        "dL8gBpIQcFEr0BoP+BCYCJwNrBNN5ydjJUQpkT+qEiAQ8xOBWfocCw6rgKHAi0ZrntZEZUJibCKXo+MEelsRbJGE8yXEJcD9"
        "Wh9UK4Bz2IFyVpdsCsArwGjgJ32PWpmMSibq7AWuAe4zymgGbgHqsoTwU5KUY3Yx0FEbhUC9zGst1NYr0p4hcJuCRMEI+STQ"
        "TZ+9SgRwiWoScIY0EQI7BCe3YUT7XbHR8o1KcqHudQPuNLDLFMAT87XAHQYWHjBdjluogPnA4Nk3zu3lCOEsMlVRye01Deht"
        "ckSqAIEIjQf6GO3XA0srgI1nrFM0BV7R+ImfA6cC8CXwhHHoWlmGPAFcNTnZMIScixwN+iZmj1AEeRNYDSxUVHHw9HOc2wMe"
        "UCJ0+Wa8/LFo+bCJzBHvDXytB32VAieZ8JdV4HWX5upS1n0seGwwz2RFwWWi5ZAwGlhpiz6/jDWGqsps0vflIhDkhOIjVUbU"
        "pWTkRgWF94FTcizhoLjEQMtZtgUSyhEYnAin9QknSzP7YmCAKdr+AF4Cnge2CMdNwGFKgF1E00uhFytbOxh5wKkJqLcQwDE4"
        "QO810uRXGQK4YmwEcJGYr5WZTxZuJykhPi6ajapip4pmkCIAEny74bNvlgAuNPYxFtihqjJNAKe9i03y+10F2jZZIgT2ANep"
        "G3M1z5gkMylB4Xuzf09Vtft5LwehDubzHqAhQwC3+Ymmx10lIUJZ0DmgJ+g4fPeXtUopMHL3/jT3akQrMxPHZYhU01c0ZDhm"
        "Q+KZSuh7Cd7iPAFKWRKnRKBvDPHhxn9CMeqq0QsNI1vkD35OgKgt49xlBXDO9IPZ5GjVInml90ppqkk+tED0mpU/isANwEit"
        "8ZTgsjJzlHBcD/hFfrlf0YUypvpW765x6adIUM7cRTHwmhz0NDF4rUYsywSbc8V8UXvuBB4ztVdaYjwK6GXC7VZTD5XSeuK1"
        "RkJfPex7OXhtBq5S3D5U0BhsckqyDZ0ibaaNURysTgcOkRJq1blZAVuYr2TSfWSwPyZDU1bQjcA5KhNqy6yrAX5Tpn41Zwbk"
        "/KkukZk/yGvqnZbXSHpXow+RZfyMTZ1WOkvDFygphhqr1Ku7257DvOPhcMG5q77vkj/sstOKQkof/IIEcOXtzZq+eTnlhA/8"
        "pepzoSkIG8oUanm9+DQJ4bL7CjHf4nk/xfMXqZZxXdFYjUGKOZMzl5RcM9Mk5n0T96OcsBzJeW81U4lYU7zcntjVJruAhwws"
        "Apm/YwUJLjbNjGf8p1hB4++YXSjtu6i1XGPMf1nPz4DCAuBHMyocqIY7qiKLxlVMK1zyuwm41JTwDWr2y07p0koJD9gtHGJa"
        "uynAXFPvVzWIzYBNQUqaDMw31go0k9qU1gBlZcFAGXaOcfYImAk8YhruAq07qnK+4uA1A3jWKLFG4/f5Zl1Vk7mSHpytzig0"
        "m00H3lFnVTR+EmRMlj1TsQbGV45RlTrf0A+Bz4CrjWPH1QoQG0tMkDZCMzUbBnykjfubCV0pMTq0DMdmXXdZcx0wzkwuQt0b"
        "qXKetgx3Y8PQOE0aAm3iSoMZwOcS8AoJE5jRYWSGYb3U/DytzD0XOMLMgEK1oSPUU/g5524Vjddt2IyBy4CH1R1hEo2tebYo"
        "gu02EaafBOiSaPRDMbpPE7h5yXqnPQ44YhN1lqommako1dEUdCUxe5xepEwn3MFIrWgvBe4GvqDlqWe7n5E5n/hZk7JBwIPq"
        "IdzxUbkOKk40KDXqtZ/TqGWsmK/6tNJr5V8NvERh10kz/uEaffRVMxQaQbYJVutVdq/mn9NJP6fBbzOE0iKUC5l7lTNWmjU9"
        "DP1YnVSUUjq0+tS+rSf1pYRFPDPQ3ZECWT9xYtOmq73+K1HuvxFeInpBO/5Hor0FaGsh1+rrbzw1P3ISXTA6AAAAAElFTkSu"
        "QmCC"
    ),
    "power": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAEvElEQVR42u2ZSYgcVRjHf/WqemIQo0GRKCpGUYMLXoKgIaIG"
        "PYiIO8QFESO4ooiHZGLEgxsoRkj0ZFBcCOpBQfRmNEqCC+hNdIREQVRccQhJtJfyMP8PPx4zXVWvq3UCKXhM95uu7/2/fXlZ"
        "eeMkY3pyoK/PARiM45AwJvCZwB8DLB0X+HExEIASuA/4GpgCntV+mO8MmKksAzYCh8mU7gQu0//yNg8sxmA6AEsEtnSgT41+"
        "My81UOrvFPC3k3bQ9wPKievszVsG/rPnIAMHGfgfGBin42fjBuNrmqxl8KVWaEK7CQOFwN8FvKHD2siqhWg9DzyjM0KTl+tW"
        "lj3gZmCz9h4BHoyqzpSKtQfcDdyqvb3ApLD12tCAATwfeFES6gLrgXv0vzwRfB+4Btgkml1gHXCHwOejMmC2uQh42dU2QQf0"
        "oxKiadmRic4vAhtEc6MKwn4VxlDTaZ8ETnCAc+B+4Dl9Tqn3TRBvAaudE5fAAmBLHRMPNVR8JnCbA1lIG5uAzgj2j97tAO8B"
        "a0XbtHIecJXOLVIYsFC2xhHNgZ/UrIQRwdvTE8CngE+cRkv5AsM0HIaA78n2V0eJ5mng94o+N2voC/ZscNoHWAmcMawRChWM"
        "nQscLUkXwB5gqwAOKqRaNtRCBmxXG5orIuXApcOEEiokeIGA2AEfAd/XYOAI1xvXjVK5mp43o3cuHEYjVKj1NBdKAXboexXj"
        "xymSdKW9OnWOnbEzwrbUOXxtBky6J0U2+aULdXO9lwEfq62cAA4B9gHvVmjOaH4jxi3yHCsznhVvUUFsYSTZP2pIMchXLlFW"
        "XaQaZ6qG6QFMu/CKNDmRWgulVJymhe+A22fJ6k2iUnIxZ4ftiYge1SA0BufIZYNsvVgma6XGPmD/XMxVhdFdkQOd3qDxGLh6"
        "qQ54o3mKzMcq0R+AX5syYMS+cpKwxNJEmimjmJVRINkVBZJGYXSbCHe0twI40ZlIm+D7ilhXRAxtS0lkxv2nUmFQaFsI3DQG"
        "BszmVwEnuyjUVfidsx4apgErHV6NHPte/p19hpakbwJ5VJ/N5z5QaRGaMuA53uIq0T5wpNpKK7BGbe6tJN8AnO0EkzEzlh+K"
        "s4qBXBLY7H7bA65Wkuq6TipF8h3VP5cDD7sisJDtv+26v6SOzKSxXim+cGH1MTUhPdd0ZDWB2ySiC1wHvOQSYCbTXVMn2lUx"
        "YCF0L3BDZDYD4HH5yBInvVwA82gVzll7wKF6/zXgcHdertHN7jrtah3V29ThM+BaJylztuuBL4AHXN9sCcwv21sM3KLua63o"
        "9Z0WJ6WRok7HlzW4pbQ5zZXA6+575pLMNPA+8KF852c31VimBmkVM5d/JpzSmeY64Im6M6GmDHgmVgAvKO2X7rBOgw6sdAHg"
        "N82YtjYBnzIbtXC6A1juwmnHhcO/tHqR+fj9Qr+3scpygc+bgE+dNJtPTEtq5yhe/6j9BVpF5MB+/0/gFeBimeS3qSPK1FvK"
        "vmstP9d6SDZ+EXAWcDwz16wo1u9WKN7uemsvxKQRzSjXrKUb/WUatbyjZcAmHLjuLPVPMvA2GIhLjswxM9DaH5lrcO+0MRRr"
        "9aK7jEBlszDaeh/R9k19cm+b+hzwl3z/ABXMYhlnRPJIAAAAAElFTkSuQmCC"
    ),
    "spinner": (
        "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"
    ),
    "rss": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAE6UlEQVR42u2ZWYgcVRSGv6rqniFG3BJ0BJcENSbBGPFBjAvG"
        "oBGiURgCIuKGgr4oUdxAEJEIgkSfFRUSJILgDm4hoKJECUENGpOJipIHw2QizlM03VXlg/+BQ3G7qmume+hAX7h0T9etqvPf"
        "s/z/uRPl29ZzPI+Y43wMAQwBDAEMAQwBzGo0Kq5HmkWwGZBrDjQAb2QWuJ4UAA0MgARIgTuBu4B/gAPAEeBn4Cfgd+BoAEw6"
        "CAAsbJYCawLXM+AgsAt4B9gBTLpQi+YKSFUIHQXaMiZx4BLgXM0N8sxHwGvAFw5I3/Mk7uJ6w+2q5UUqL6SaC4A7gM+BD4Fr"
        "XF4kg1BGmzKkoZm4HfagcuAmAXkLONt5L+oHgKhDPxDJmIXa3ROARcB5wDJgJXCxgBmATKAy3R8rLx4DtroNy+YiB2xnpzQB"
        "viusWQrcqBy4XLucO+PbwOnAFmAV8IhyKullgleFkBkTu/Ax0PuAzTJutWLf1qdalwvIA8BnwKm6Fs8VAAuNTIbY9AkeqfLc"
        "rOT90iVurjVt4CrgG2CJnpfMZRLTgQvartIkMn418DjQKnijLeO3A6f1yhO9cmVa4IoXgGuBX13MG4hzgA+AEwtaq285kBR4"
        "oApIrur0NXAF8L2e0RaIFnAl8EoBdN9yIHWk5ImtbLS0bhK4XiAaelZT128D7hewpNcAbLcXSQstA05ycZ85z3QaZtgUsFZV"
        "K9G9BmYzsHg2+RCXqFGA+yTUfgD26/sTwPnOM0lFSDWAw8CtUrVeG80HXq0RorVD6Jhj2DF543lgD/A6cJGMLEtGi/09wEbn"
        "BcuLNcB6B7YvPNB24q0NzAPuAXYDTznVGVeAeBn4xFUmkyxPz1RmVAGYrxePurWxY9gmsAl4W7U9K3mmhc5DSuLIGX2piDCr"
        "64W4hKQAdgJv6HO6oEJNYbaAceXHghJPWMk8ALzpSM7AbSxpXWur0dA4E7gaeFjiDbfjLXnjU2CdgIX6ZAO/RIVhpABwhapV"
        "1+HUbUMTAX9K468Cbgf+ci+y2n4D8FxJWTTA+wU2cizeAG6pqxCqFnq941l5m8TZwQKINvCkPNSJZa1ibQkc3YzXTeZupESo"
        "lWzqdOI618xnbu0zhcQNyY0dIjnfra0EzqooBpUAooIczgMtocX8BHB3oUJlCqXLOhCdPW9a6hVXokfFLcwUQOR2GjUgDbdr"
        "UUDvfKzaHrveAfEEHQjOPPttoMxeMtMy6o8QH5UAm9Ah1kvAKQEQ9vemQjuJwqvpGqAQL/wYALmiJPw69sSRe/n7KoU2Fqrs"
        "rZXGP+x2O3U7+QtwgSufizUnAolp3/9w2suAnlEHQOwekIlM1jkNZFLiX2A58GLAC/bynfpsaVq9D4WRGTepcpw6mTImfsi7"
        "EXhxQTXeW5DK5pUR/T6uF6SBh//mZMeIvi8vyQMcuye6r6GOLakTQpa4J4tt48DNZsA89QiHnBSwtbuA91wBSIC9XYRDUUcd"
        "KcmbjlIi0q7t0w6EKpSR2oU6me75IdVs+oFEcf6u0zb+2PCYfv9KiRcyPnLhkNQ4TkwCszYA0y7PygujLrTMO9PAg130z352"
        "E8dpYNYGYIz7tw6ntsrgSG3gdmmfvU5pDsRoBEhpkv//KzMmXTKlmGdQ4r7scDd3pHZI0xPdQBnf6XTa97eRI7OcARz/Ae1w"
        "hEEMFRAMAAAAAElFTkSuQmCC"
    ),
    "backup": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADC0lEQVR42u2Zz2vUQBTHP5PMtoiVKogIimAFKXgSPCiiB28i"
        "9OypKv4L7V08iv+BF8G/QATFo6Aggu61nkQqCnatFqXW7SbxsG9gHLLbyewkZe0+GJLNZibv+37Ne2/UudWHjDMljDlpj3eU"
        "DJvyhgRayAgCoGTBbKdFIlKZYFJ5XlQBoGRCBuwDTshvo4kPQDcy8wqYE57Mt9aAdYenHQGYF1vAXeC6ALBNaR54LxrKKzKZ"
        "lphJBkwDL4Bj8jsRAE+BZaBTBkIPsPcW8Ay4ElnKBdDz9AUFHAFuApeAy8AXV2i6ZGIG3BHmu/JO4phQiHkUwElg0XLOBHgO"
        "vHYcOBdNFcLDKeABcM3lQTsfyYAZ4JYsoq2F1YjRJQNOi3Bs+lMCQFnXaeHlqpjuiq2FsknHgaPyX+x9oism1AW25H7T0/QU"
        "cMYNt3rAy8WIEh9mSlqk52rYh3q+O3EdzMcSwP+VSuwGgMIZtedCsQVmNrPUShUaB6AtB8w9bVcB74ALTmT5JGupJgF0PHdU"
        "l9Yl5pfRz5AsNxTAPeB75JQ5BQ5VjYKhABabDpexAfRqYlw36cSTmngCYK90JZroRgQLVo+7xnwBmG1/CWgHFPNVys7DwCNg"
        "yqcuqQrg1ZBUIBbNVhFOVZOYkS1/qgbGW7L2bN1OnMn1PnBW7kN9w2i2I+nJdlXT1CN8+CJwPpL0N0KFMEpK8Eu0kY1QlBjt"
        "bexGRZZEqKqUs84klZgAmACIACBKv6Ym8jrgSD1r0twKo6Fkjo5819DDHhh0X4Ef1pY+CMwB/m1QhZCZe9CzyP/oasIFkALf"
        "gMfADfpt8KkBprckmWOMTvaWpBFlZrIteVKbfmMssTWmB+yMy/SPdebkeeb4hgJe1uiPxjTNcdcmcLss7xrUZFoTAE8sCaRy"
        "tdWvrWvIsNewedovzxLgjfBSWofoIRniZ2CB/rHOvPzXdpwvdkGDZKYLAmAVeGsBy31zIduuV2QMDWcRQ+Rv0bxrKXnVZK6w"
        "JieOL9RNJpTn1gjORvMGuxG2E++NVOIv/zm6Yie1HaUAAAAASUVORK5CYII="
    ),
    "restore": (
        "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"
    ),
    "puzzle": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAC8UlEQVR42u2av2sUQRTHPzN7d4miCVGJFoKdActoIVrZCFFQ"
        "EMHKxv/ARrBQa9HGWkULGyvbRLEQERURRBARUbELIiiKweRuZyx8A8Nytz9uZ/f24AaG3WWP2fd9877f995w6vklyzgPzZiP"
        "CYBRj1ZF60aA8p6NzMYDcEbHA0DFTQagACdpR4ElYBb4DDwA3knImiYCcJ6fAW4DpxPvrwAXgeuhQeiAADRwR4zvAj1vRsA1"
        "4JwYHzUJQCRGHQFOifFt2V03HYmvAluEC6opAJwhJ8RINQAkwA7gYMjdD5kHtmd41crclgBeC4l1xjsNfMowSsv7L9592rom"
        "5A6YlLkh15vAbwmXZIXoYv4p8Ep+381Yt/QOOF3fCtwT8qX9NhbFUX0AOEfNA49TpDQWBzwDLueR3Dwh1AaOFcwZasDzgsys"
        "0c3LkzxGWeAnMCf3eeI8LRTTGpCe2PQnNIkjL7ZVhapn5Ts61IKTfmACIBAAm0G+qobyZikAbVmkVxMQ5RWBNo3cOqf3v3tV"
        "pqoBRM+T1DlgWpKcSdqsMwwH+AXsB/YB54EfFYJwoTIrmfgt8BF4D9wC9iRBqCEOthaAR8BuAVGnEKxKq/rGlRm6gGc0MAV8"
        "AM7WYGyc4MAGsAu4L3WZBVQRFTLAupDpCfBCQMUVAYi80kQBHeHFXuC4I7YuIW0vE1ypaxjgUIhEphjdsGUAuJg8PCIgWkK4"
        "UDXqwqYtPFgCDoQ+IhnQxfm5oSPSuuL41yro9XVgEbhbcez3c0yH/6d8Z4A1AWBbOdVgp7SDJ4ELwOaKcoBrKR8CyyLX85JM"
        "V+Rc6ZvfaubpiWeA16LB/o6oCsm5BtyQOS07bz0OmKIk3uT1qrYG4kbi3Aj4K99syXfNMNVo7JG+DtWxQlpfQPpWwkVUaOSa"
        "P2kpmziK5AFTA4FNjrOjoQBM1bRbncQ1CAADfJUuqeodcG3kaggAfku5WLMSxYlrqR1wNdBYk3gUecCGBNDYv7SMfR74B8Eu"
        "xQlPQo1QAAAAAElFTkSuQmCC"
    ),
    "grid": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAABg0lEQVR42u2ZMU4DMRBF324WFIUSCii4A1IkDgAXoIOOc3Ap"
        "CgoK6JDSUsAB4BBUJGtTMJZWJsZZszbaaCxtk6zf5M9kx/OT6ujVMuZVM/I1egFN5P0KmPTgGbmKMZtIdQywSqiqKcVsIhv2"
        "gTNg1smev1wXWAEL4D0QMAdzrQB34wlwBxz3yNQHcA3cegFzML/Ve23UZeMAeAEOgWUgS6GKtsAp8CzfdZOB2Ya60ETKd94J"
        "tCOQTa6lMC69B3ZoZrSNziRo1fNhq2TftBAzKKBNCNQNaAoxgwJSA/22PwdTRwkVoAK2WUAOp2NLCUg5cNw+W5D5Y5hzh8UT"
        "8Ans9phb3AesgPs1wYdkBitg5LU34ErG2U3nFnffDfAgnDYTMziN+iP1HLgA9jqZCJW4lSCPnfklNzMoIOas/urIBmM2ES9a"
        "92y11i9xbmY9cNuzGVqpTf1VQk29mno19Wrq1dSrqVdHpgJUgJp6NfVq6tXUq6nfZlMf+6feJGasGFNP4v9eX1Ap9YWfe306"
        "AAAAAElFTkSuQmCC"
    ),
    "search": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAEoklEQVR42tWaS4gcVRSGv1vVk4lIUIIYAwoBH/gK6iagG0FR"
        "cKEYXSiC+EAQFRVFQjpLETMSstC4EB9IwOAL1I0IrnShgoJvRRFBUJIhPschKNP1cOF/4OSmuqu7qnqmc6GYqrq3657/nv+8"
        "7p2wuFRyPLeE47z1Wvw2aAFC9L7UVcwqgNQJmI8BsND4NQeQSBAT+hRgK3AOcJreLQHfAV8CB93YtAbs1AF4Aa4G7gcuAzYO"
        "Gb8MfA48A7yq36bT0EYYwwuZ8NuAx4CrXF8RCWW08c7hM+BR4C1nL+VqATDh7wP2AvNO4FICpdFvcteH698D9J1xl9MG0AMy"
        "4HFNbIYb3GXtT/09OXrvhU2BN4Cb3Ldag0hGrHwG3CPhBxWu8x3gNuAS4CxdFwLbgQPAijP8VM83AE9JS8m0NGCTXgx8pMnN"
        "AFPge+Bu4P2ab18APAlc6Yx4AMwBtwAvd+GdhgEogPeAyzWBrfwHwLWiTBoFLiJ6Zfr7ojSVu75Fud8jbe0hqaBOAVwRCR+A"
        "H4BrJHxPfXlk1BbcMn0rALeLbqmLI5uBuxy9OrMBW4lHoucA3CH/bsZd13Jn0HcqyJn9lMCDwPpoXCsAQSu4UUHKACTAu6JP"
        "OqbwHkRPlHnWCQ+wRUZftjHopOJ+K3CSc5kA+ytc57jNYsIBZ8yZ3l/qFq8TDZj3wE2WK7cpGxqb2ciPwG9unqDF6tSIATZF"
        "oP5WYkbDFNk0cAT4JRJ402oUNF3l9uU0MtIqAEvR8wbg1BZcNcM9Qe7Tf+evaQD4xvXlipznumDWBEAATlfdUDqNfN2lERtN"
        "vgL+cUEN4OYWRmypyfVajNwFuU+6NOJCzwdVjJRO/TcCZ7vJm9DngUgjvwOftnAOlRSy531uohJYBzwXBbdxhLeUY68o5GuF"
        "F+Them00MCyZS4AvgPOjuna/churF4ohyVziInZfNYXPqw4rDV90GUBnRmyZ5I6IWrmyyre1mpkD4LVVqG8D8LQTPnVjPwQO"
        "RXbWaUVmEXiPErsV0cgE+QN4HnhdWaq53hOBM4DrVAxtqbAbS1GekHZ6jlqdAQhuxV5TJZVFFZa1w8DPLrJudv25qy/SCoex"
        "G9jVBsSomjg4mu3TiuIKlXLEtkzVmCKibKa+ViCSmtBvE98L3Ar8pIlSl1UORLEV3Q/03VRjf9WWShLx3eqKvkD4IqizXKh0"
        "NvEScBHwsHhvbnJO9rFO93P67iFgQbX1dt0nUT1hIHbK2CcGESbYXvcF+LwE2wacF20tfgt8rGC4NGSLJovo15hOYcLzgeBc"
        "6rigi2irpg7EwiTeadLd6TLapQgVtTNDdq+tvNylcTsjEJ5O5biaaHo+0CS3Lx0I2+nrDwHR13MtiNU+oSkjTeyu2OWYyDut"
        "xRFTDGJhBIha77RWZ2Qxneo0MRTEWh7yNaVTMisAmtLpqORwFo5Zx6XTQP07PIgwQwfdoSbYFS77PVN1e6tz4mnTyYLdwKX2"
        "KOeyMjTMEoBRwc63V1RLp0A+awA8iFSaWOb/E6F54E3gIV9Hhxn/Zw+rIdYrTV/uKhdarWal6L+6jjksn3UAcPQJzjEJ5H/X"
        "37gh1WYYCgAAAABJRU5ErkJggg=="
    ),
}


# ------------------- إطارات اسم البانل المتحرك (موجة نيون) ------------------
TITLE_GLOW_B64 = (
    "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"
)
TITLE_FRAMES_B64 = [
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEVMwf/2bcywdv+IhP/WaP/mZPhTpv9Lx//0a9Kxdv9W"
        "nP9I0/91i//Uaf+Kg/9mkP/nZfZPuP9TqP9Zl/92i//8cLtH1f/7cL2bfv9Qsv+bfv9jkv91i//1bM+2dP/mZPpMw/9Wm/9T"
        "qP/2bM5H2P+td/9TqP9Lxf+td//Tav/1bM5Wmv+Mg//Uaf/2bcz0a9LmZPl3iv/Rav/nZfbSav/Waf/BcP/BcP9QtP+Mg/+I"
        "hP+Lg/+td//oZfRTqP9TqP/WaP+Ogv9Qsv9Lxv9Ylv9Ptf94iv+JhP+ydf/qZu9Wm/9Xl/9Rsv9Lxv/3bcr8cLxH2P9I1P92"
        "i/93iv95iv+ydf/8cLpYmP9UpP+afv/mZPpRsv9Rsf9LyP+afv+afv+afv/8cLtUpv9Nwv/7cL6Zf/+afv/BcP9ikv/8cLtH"
        "2f/9cbsAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAB3EQ7XAAABAHRSTlMA/Pz8/Pz8+gYG/fz8BQf6BQQFAwQGBPcE+vsMeHl3g4C8ubmAvIK9zy+D"
        "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"
        "4byJve3FxgAAAABJRU5ErkJggg=="
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEVI0v+wdv/rZuz2bM5TqP9LyP92i//pZvCLg/+xdv/W"
        "aP9al//8cLj2bM1kkf9Ptv9Qtf/Pa/9Lx/91i/9Tpv9YmP9lkf/CcP+KhP9I0f/9cLmcff/pZfNI0v/1bM9Ovf91i/+ud/9P"
        "tf/ZaP+vd/9LyP/Fb/+vdv/qZfD0a9LoZPf2bM1UpP+wdv+ud/9Ylf+wdv/BcP/2bc3pZfJUpP94iv91i/94iv/7cL5I1P+Z"
        "fv/3bctWnP+Ihf/rZux4iv/0a9LsZ+lZmf9kkf9jkf+Lg/9zjP+JhP9UpP+Lg/9Upf/Oa/9Wm/9Pt//9cbhalv9Ky/9I0/+d"
        "ff9Tqv9Ky/9Ky/9I0v9nkP+Qgv9I1/+cff+dff/Sav9Xmv9Vov9Lx/9kkf9ikv+Tgf9Ovv9I0/9lkf+cfv+afv/7cL77cL78"
        "cLpPuv+bfv8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAADjd1YUAAABAHRSTlMA/Pv8+/v8BvwG+/z7BfsG/AcHBAYFBvwF/AgEuoEvvYVwgHovu4BLeG9H"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEVRsP/Rav/sZ+tLyP/2bM6Og//pZvBkkf9Sqf9alv+b"
        "fv/Rav9vjf9Ptf/1bND8cLqMg/9I0f9yjP9Tp/9Lxv9Yl/9I1f+oef9kkf/8cLqhfP+afv/taObCcP9Lx//Pa//7cMBalf/S"
        "av+Ogv+ie//Na/9I1v9Sr//CcP9wjf9Pt/9Lx//Sav/qZfDrZu7Pa//2bM6KhP+Lg/+KhP/Sav/2bcyOg/+Lg//8cLtZlv9w"
        "jf/3bcn8cLlYmP9vjf+bfv9OvP9MxP/sZuzrZu5Zl/9Mxf9lkf/8cLtyjP/7cMBlkP/DcP/4bsZZl/9Tqf9Ovf+ifP+he//C"
        "cP/4bsbpZfNOvP/BcP/0a9P9cbdXmP9wjf9vjf9jkf+hfP/CcP/7cMBVof9Ovf9Lx/9I1P9lkf/9cbhSr/9Sqv9Ou/9Mxf9l"
        "kf+cfv+cfv+afv+ifP/8cLv7cMBVoP9okP+cfv/CcP/CcP/7cMCcfv/7cMD7cMD7cMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAD9Ky+OAAABAHRSTlMA/Pv8/PwF/Pr8/Af7/Ab8BPoFBwYFBgMHBPsIdwS5tv2Cc4eBSL2A+rt5"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEVikf/pZfGydv/2bcxTqP90i/+KhP/pZfJI1f+wdv/T"
        "af9Lxv9Qtf9lkP/1bM5zi/9LyP/Pa/9Tpv+Lg/9ZmP9PuP9H1f9XnP/BcP/8cLqcff+wdv/8cLlQs/9Tp/97if+Ehv/qZu+t"
        "d/+vd/9ikf/7cMDqZu7rZu3XaP/qZu+pef/7cL71bM9H2f/Oa//qZu5Ky//CcP/pZvGZf/+wd//1bM+Sgf9Xmv/0a9P2bcvK"
        "bf/7cMBUo/9Qtf/Uaf/Uaf9Uo/9TqP+ud/9zjP+Rgf/1bM5Zmf9Wm/9mkP9jkf/CcP/za9RZmP9Tqf9TqP99iP+Zf//Sav/9"
        "cbhWmv9Qtf9H1v9I0/9rj/9yjP/CcP9Qtv9I1f+Ehv9al/9Ou/9Ptv9Lx/9Kyv9Nwf+af//CcP/+cbdH1/9I1v9vjf9nkP/B"
        "cP/CcP9Mw/9LyP+MhP/+cbdpkP9pkP+Zf/+Zf//7cL4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAdPZJpAAABAHRSTlMA/Pz8/Pr7BvsF/Pv8/QYGCAUGBgQDBvr8BAWE+ry7gYAuuXeC/bBuddFG"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEWGhf+xdv/2bcyNg//WaP/mZfdTpv+wdv9Lxv9Xmf/1"
        "bM7Qa/9PuP9H1v9Ymf/oZfRkkf9Lxv9xjP91i/9Tpv9Pt/9I1P/CcP+afv/8cLqqeP/1bM6Hhf/WaP+xdv+1dP9lkf/7cL1e"
        "lP9Zlf9zjP9PuP+bfv/0bNFSqf/nZfaIhP+vd//Rav/BcP/7cMDmZPnUaf/0a9LmZPmwdv/WaP/1bM7XaP/mZPvoZfTnZfZ2"
        "i/91i//1bM+Lg/9okP+0df9I1P9H1v/1bNDPa/9Tqf9Lx/9I1f9Qs/96if+Fhf9Tpv9Sqv9Qs/9Lyf9Lyf9H1v+Mg//7cLz7"
        "cMBPtv9I1f9Zmv9Uo/9Pt/9Kyv9H1v+bfv+Sgf9alf9Pt/9MxP9Lxv94i//8cLxTqf/CcP/8cL17if9okP/7cL37cL37cMD7"
        "cMBWn/9qkP9qkP/7cL77cMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAwj2k3AAABAHRSTlMA/Pz7/Pz9Bvv6BgX8/AcE/Af7BAUFBf0IBYJ1gIZ3uAj5vYC8d/q1dy69"
        "K9ED+nMuSohIstJySrTPRYMverjRt82LSTDSLE59QYq4sXG7ciiwBJVQ0kQpKYy92HvWT5PE09gpSCHTK3M3sUxBgJZnAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAALYD/"
        "uAAACghJREFUeNrtm/tfG8cRwBfnxMkn4KogyQaBVGo7QhG2JJBAMnIAgR8FHGITB6ep69humjR9/f+/dfdu37d7DyGMk898"
        "4zjhdQi+N3M7s7MIAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAL9LChj4Lfz2pCn/BT4N3CiqNinifD/pah5De/8S5qUX"
        "wXAFn2G8ie7fv295oRYWFy0fWGCUAuxXKBaLlQDzx8oE6V3h5UoL8nf6Y8gi5yOEG/5z2NtwHGejt9rBv9YEa9L/T/LtZF9+"
        "coSnc5cKq7vibyjiXMlbYdsRDJpx5ogqr1vFdEeeqm7JEnGaXXJxv9km7Pg83OXwj0Scqu72ZSLOoi4m4oo84sqRiFtIF3Hf"
        "hGTXhmozOnsuus+99SRvTi63YzfnIa/av8FodBF6ybShpXdra2sPbkQYIU8ON+TvDHKMwXYhiHj5Ltq4deuW9ELrtRb5EYS2"
        "2z98pvH5M2RSt4D+epMyS3h/sn6EUNkQb8V8Pj9P2NfV4Y89zufnMKc8W5bQenC92VcLaIF+pz/d/EPI54y7/DU9oi9zAnHL"
        "EXEzTBx+sG04qricNeY81O0rUhojbIyJWzOL60ri8HXbw5yE42B1BUWco4gj1FvCHBb3WUTcrkXcHUUc4eQoaq6InjNx809Q"
        "xSCViJu7h3RxN4W4VxFxP/LXtDK5uFqMOLTq6OKGlgWKh6oRLf+k5lKJ81FzkMup4pyNjmTOKG5mpsbNGcWli7iQexFzRRJU"
        "VNz3dnFzF/QrTeLiIm7lKiKugDpORJwlWeJ4i2p5gB9sacVhb7lcRJzjSOYs4oS5TOLuGMTN6eaK6HWeizvQnnOyuNNPSxwL"
        "uN7h4TYTt2kW5/UN4l6gtOIM3kJxkjmbuJkWXaFcMlVicXMXytIeu3krxM1/axfHlKcT9+M0xe3VOTxV0idcj7zRoeKMudIX"
        "ATfudtka5cHaUmAO//0C82ujwez2GyFscYLLgKFFnMMLf6u4OtLF/fAl4+7DTOJOlZArhpmSidNypSJuLlyfxIn76i5jd5ri"
        "3GgJV6C/uk5Qf/dCcTnfEHI+GlMl1SD++lTc39n6hAWm/FnK10uryfbOzk57wMX1UETcclAMtOoiRbiquEdJP7cQF5QDR8dU"
        "3Jy8ssdq/paXxM1XFHOquFB5jLivTK9jGuL0Mo4/4jaItkJhNVZcgyoJq7MqFfcLX1jSOo6JU+s4KVEOm/SSzSF7srJkKcTV"
        "6Ocwc1t2cZY6ThIXvuOYinuqinuriFNzpSou/Mo4caY6bioR5+oR19kICG55Lm6YKI50UEgZXv3fLz8rEedJEeeZA27gs54X"
        "8ntayEni6B3WUpcnk0ccjjkqTl6ehGaIuP1Q3H5MxJFkWYqPuMUrjjhlT4DtC/BUOUTGZxwTN1Y7X3qJbhQnAk66K3yeqVnI"
        "yREXNE2QmyxuMVEc/mXjPyWTuGKYKfMHT0y5Uhd3ikopI2664pK2COJWleIZR+pu1mt+ubSUUlybipNrDR+xbtu2RZzrTiPi"
        "AnElozj0dSjuDB2E4s7ixOFkWbqGZ9wWQ2pFyAG3HVfH+XIZ1+h65i6zXRzLlFqTWc2VkVSJtmzPuJU/MxbNMaenSvRd9BnH"
        "M2X+SeV7XsrFiHtTihP3j38/pPwkXtM067g95Bo2CTrxnROtjgvceSnFiVpgoNwUQXYOVkfRiAtoWVeVgodJ4sK3j95TcRey"
        "uOeht8cVxHKl3PYS4u69Cc0dp6vjdq9GXD0qjjUt8e+2be5Vemik1dZjD71cSicO+TTgNpW7IlgPhcvawJwQV18m8GpgGdkL"
        "8ERxd44xJ6Y6jhZx+fxzVKkcREs5SdxFKG72CKUR9+xjiSuwHkoQcLZe5UjvnVRRumecENfWIo51bnRxeqfHvYQ4tQBXMuVr"
        "milfY1tn0baXJA6dh+Lel0qfUMQVCmyZELM5QKyMNXO/LqnmrkjcVlyvMpu4c2Vp8pZmymJF5MpvkUlcuRwky9nZ42uMOP0Z"
        "J7w5cdtxRMWoqkTdg/+ilOKGxlSJbKnS7O3y4s6lKYSiyJTBRupBpJSTIw49DcXNHn30iFsOqS1vIdeYJzHt2NEFso70RmPh"
        "Tm952VeVVNxQi7gNy+JEusuWXdN+3JcrIY9Wfsogbh2VDUUczpSEs0gpJ4srB8mSbOrZV5X/2Q14tvtwquKsQycF7m07Lt54"
        "Cwu74+JepBS3aSwH2K7Sqi5uT+pSqjvg2es4Ju5kvSR7kzNlEHFPIm0vRVy5HIpjXEevUvPWS+NNHRIasSbzuyXZnF3cDltW"
        "KgU4u2MOo+VATVtQook7J//6DnN0FAydSJ9Q5kWc1KtUc6UqjiTLeHFX1jlxTfHW2XDU/kXCXF7ozqPi1lKKY6sTsvjx2QAK"
        "38YtGArwPW0v7hKdE+OYV5lnSk2cKOXUVFlGp0kRd0W9SlP5hg757je+7QvWgUfeq+wH7rzwzbTipFyJzSH6TZqOminVAnzL"
        "sAa+TJNZn/Aqs3ZXRNyZRRxOltcjzpQr+WxeL37GUTSZu2GPuZ8lVWJVYv+7TSOunXO0nVS1V1mPLCon3dYxTeUpmVIVx9te"
        "qjj852naVGne1rlNcCeIuGi7RMwKrW7jf1Y3Nzfbm03jtk5VTNxhqpkWJ3KbmTS+8LcZiB3w7ehGKhHX4sOErnu5VGkW99wm"
        "judKTRz+9+Q6FieR0QU5T0rDQsZazudKbtxojMf9bOVAEHMDy+hCzzC6UCNzsPWYKa8MowsWcWVaxOW/xuwHHGgTDBFx5VKc"
        "uNjRBfKC/0LYQm5GcZFhoSzisIexYVjoXarOiW3oRGy/m8S5Lb3jNdmwkFFcGV3kWZ9ScMBzZdEkDv+1HicubliI8AVh+WOL"
        "87xGVNzPqcWRleXAIK5XMI3nkSCTWgeXGs+ziDtn1XeRj6BXzngpZxaHr3SSStxdu7haanG1qYgjUhq2gdg04oi5zYi41YJx"
        "IDYQx7dRZ1oxuwOJA7EmcXiF+IYmSnHoQ/Qr95FV3FFGcY8mFzediAtaleosc8ND6bZ1uDltltnpdZB5BD346cQ9t3eZuUqj"
        "OFxNs0wpTutUWK6crwTvjYoT23FZR9AnSJXWQx+4+CYrSRnrqpL2TLwum5zsj0fi0Ickrm8XF6prM3fDdkc7rqOLE1W4GF3I"
        "fOjjlVncORVXVMTxXMnEPdbFlUonEx36yBxxCcesshF2Kkfd4JSV8YRc3IlGRA9O+s3mTrNpOmWFCp0PHz60Wi2XDQu1KOIp"
        "p5N8zMr40XK5GKC+t8IQOwjawcZS1mNWEpnquKQJIRX7UVHuRelZZkdc3veTzzWiK+eTPdaYeJQ4c9TFhlTSh6k76+3BDjbq"
        "r91+tcSIQxkiDmkRN92jxNOLOAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgN8p/wetcLuhc6b9QgAAAABJRU5ErkJg"
        "gg=="
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEWqeP/Qa//rZuyMg/+xdv9Ouv9ujf9Lx//pZvBYmP/2"
        "bM1lkf+Lg//Sav90i/+bfv/8cLn1bNFLxv9Ptv9Zlv9kkf9I0f9Upf/8cLlI1P+JhP+bfv/DcP/Lbf/BcP/qZfDWaP+td/9n"
        "kP9Uof9Qtv/sZ+lYlv/rZu2ydf+Zfv/1bM9jkf+JhP/2bcyQgv/2bM71bNC4c//Tav/MbP/qZu/Qav/Vaf+Ng//0a9PoZfVb"
        "lP9Lx/9Lxv+bfv/2bcxblP9Lxv+0df/pZfJPuP9PuP9Lxv+Ghf+JhP+1df9Lyf9kkf/8cLhalf9Lx/9ikv/9cLlPt/9Ouf9I"
        "1P+bfv/9cLn8cLn8cLpI1P9I0//CcP/8cLpI0/+cfv+cfv9Ptf9I0/9zjP9lkf9Zlf9I0/9lkf+afv/CcP/CcP/BcP9Zlf9S"
        "rf9Vof/CcP9Srv+wd/8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAADwDPo9AAABAHRSTlMA/Pz8+/36+wX8/PwFBQj8/AUHBQUG/AcFBLkFBIL8eLmDeO6ChHm4LXpJ"
        "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"
        "7/PAYH/hJ+sAAAAASUVORK5CYII="
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEXMbP/rZu6ud/92i//Sav9Tpv+Qgv/1bM/qZvCwdv9Y"
        "mP9H1v+IhP/0a9JyjP9lkf9Ymf9Lx//8cLpQtf9TqP9Qs/+afv9I1f+vd/+afv9Kyv/9cLhkkf/pZfTrZ+t4iv9H2P/MbP/N"
        "bP/qZvCMg//BcP/3bcvsZ+u0df/sZ+pTp//1bM/8cLpPtv+seP+xdv+seP+zdf/Uaf9TqP/sZ+tQtP/1bNH1bNCLg//1bM9a"
        "l/9Ymf93iv9kkf+Ogv9Ymf9PuP/1bNBalv9Tpv9QtP+Qgv9Sq/+Pgv/9cbZxjf/8cLpblP9Sq/9LyP9LyP9zjP/Sav9alv9U"
        "pf91i/9mkf9kkf+Fhv/9cLf+cbVMw/9jkf9jkv+afv/DcP9Puf9KzP9Lx/9H2f+afv+afv/Uaf/CcP/7cL5jkf9Rsf9Lyf9J"
        "0f+cfv/CcP9I0/9vjv+eff+Yf//DcP8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAABTwDeSAAABAHRSTlMA/Pz7+/z8/AYF+/sGBAf8Bvz9BAb7Bwe6/AQDBYK2eYB6gHN2AoZKh9J2"
        "0YNJLkd0zL29MbtIsbJyK88pK9O3eipt0YSQizBFhXJMRjKPtiiQKtaq1lEpz3BOcjD6KEW3e3C4z0K0h9TaRsc23EZAjL4A"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABelg"
        "BwAACi1JREFUeNrtm/l3E0cSx9vxIo20M7JiyYoPSUDkIAsfktbC94GNgXDYDhhzeoEFlmySPf//X7bv6e7pHs3IsiF59X08"
        "EotRe6Y/U9VV1dUIgUAgEAgEAoFAIBAIBAKBQCAQCAQCgUAgEAgEAoFAIBDoD6kAC2bh9weN/ndmZgYm4yuSF5WOTbG4/uis"
        "Y5DPrVf/YPksx1Sp2L5Q0FSNXlAshyoxOe70O6lpIvcjkaGKRDH3o3zkc0WeSNUlmBv+s7I6n81m5z8vvMDoktgmIzjIr1Of"
        "qWJnp6parQ7rQZ3syr8jiwsUbsF6lmt8fPzzizhy5Gtes4HV7Hk6OgfGHwyTI9RySx2i/1To26v/ux+1OB1d8TwW50AXY3Hy"
        "TlAhYnGVZBb3E1N6bKgxYqoVoEByW80q4MbHf3STI5Dn5SD1ZugfPeS1/mTTX/+Jcqq5oVx78humqamPH/Czq+R85J+Mqjp9"
        "9mYbowuxoeLmlVATVLeRDd136G9/FvoW65f3rw4xOou9lclQeaxdEx3Gxe/nuFDwxT3OZqh2KqjCX0bxSKEm5SJxnc/EAOBq"
        "EXAjAhx2ffNZHdy40+YCtIIvVkap9wQ5DG7EDu7vCjj8f52ufLYpollfJYd/0LiNjmE920ZFBVw+Au7AAe6aBo7o/WGUXBnd"
        "FODyG6hoghN3chWZ4DIhuG4EXFeC+35wcI0YcOhG1gT30hGgBIj6VG0cQS4RuBxaUl9NCi6zc18hZwU3NvZGzqcVXDKLY3oV"
        "ubZcviPBPXGDG93i92kDF2dx31+ExQVoLxsB53CW2N6yEXAjPLpMAg5z056NgctkFHIOcGP7YkJTgbtmARchV0ZPr0hwm8Y6"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEXoZfT2bM2wdv/Uaf90i/9Tp//oZfKLg/+xdv/1bM9L"
        "x/9Xmf/Sav9QtP+Ng/9TqP+cfv91i/9PuP9alv9I1P9mkP/8cLtH1v9Lxv9lkf/Qa//0bNGpef/7cL3nZPabfv9Puf/3bch0"
        "jP+td/9Wnf9zjP/XaP/1bM/0bNF2i//mZfZTqP90i//Uaf/YaP/Taf9I1P+JhP+JhP/2bM1TqP/Vaf9H1/+Mg/9Tpv91i//B"
        "cP9Ptf9KzP/oZfRYmP9H1v+Ihf+wdv/1bNHkZPvjZPxSqv+ke//7cL37cL2KhP/7cLxTqP9H2v98if9mkP+Ihf+mev9UpP9Q"
        "sv/kZP37cL1Zmf9Kzf9lkP9mkP9nkP/8cLtYmf9Qsv9Lx/9lkf+oev9WnP9al/9Kzf9nkP9Rsv9Kzv/7cL5Rs/9H2v8AAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAABMoYgnAAABAHRSTlMA/Pv8/fz7+wcF+/sF+wYG/QUEBvv8BQULBbmCefqCBoG5L7l4ukhId3K4"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEX1bM/qZu+zdf9LyP+Ng//3bchalv/Tav/pZvCwdv9O"
        "u/9kkf+Mg/9wjf/Qa//BcP9Lxv/8cLtI0f9Pt/9Uo/+bff9YmP9I1P9zjP9jkf/9cbjqZfBTqP+bfv/rZu7BcP/1bM/7cMCI"
        "hf9MxP/1bM9Yl//rZu39cbfqZu+wdv+wdv/Rav/CcP9Mxf+wdv+wdv/qZu+vd/9Yl/9Mxf+Ng//qZu5xjf+Og//Kbf9yjP+x"
        "dv9ZmP+afv/0bNJOuv9I0/9yjP/3bcpKyv92i/9kkf9ZmP9OvP9MxP9lkf/Ibv/3bcpVov9Tpv9Ouv9Ouf9LyP9I1f9kkf9k"
        "kf+Pgv/Ibf/ObP/9cbf7cMBUpf9Upf9Ouv9vjf9tjv9jkf+cff+Ihf9Ylv9I1P+bfv+Ihf/LbP/8cLtI0/9jkf/1bM9Upf9I"
        "0/9I0v/CcP/DcP/CcP9Xm/+bfv+cfv9Tqv9Qt//DcP/Bcf/+cbf7cMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAD/dhzmAAABAHRSTlMA/Pz8+/r8+wQG+/sH/Af8Bvz6Bvz8BQYEBgW6BAeDBoD9eHi7gUWA0HDS"
        "d3e4Ty92q3OEvCku0LG1jTO8yUcqckUtSoa4vUUvTCmOzSd82G1LtCuP2HsIM7KDmNbR0ZFGRy5OKb3Xd31vka8pudDHc4RV"
        "30STX74AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAvczQ"
        "6QAACilJREFUeNrtm4tbE8cWwE+olaSEJeWVxBBCVWiCkBCehijSKFdbbalYbVFB9Hp9VW17n//+ndmZ2XnszGY3BKT9zu/r"
        "96k0H9nd356zc86cBUAQBEEQBEEQBEEQBEEQBEEQBEEQBEEQBEEQBEH+kqQJeBX+fNK0P5GzwQXKzxHalIjrri4jMH5eJmQN"
        "CoWC5TdMCmy/fswnJwh/IJ/PKfifdhwp/5Yio+A+JXqo9PDLrtOtVCrKjzyOnq50TiPcyH9zpWoqlaqWptf8f7upVDLKKfXy"
        "deQSqle228et7nrDfhdRb3/KiEtDeiklKa1FmaP3XaZeI9QbGV1d2RFxxsWi1ibby5Qjam1qyhZwWsTl83rAHSPiHOoiIi4T"
        "RJwXijgvXsR9x0iuDR59Sfjqc4XrqrdSSmPOba4ClYX5AUGzTs5LnB+UDycmJs4ZDA8Pr0NBDTco3t87L9hZJu5Uc2Mw9q8v"
        "KJ9xdhcvdYgsqQ3yr0Y/U6Af/gFs6iZhmX3LEONpa3sdoGCJtyw9VHL0E9fKRhLJQMY/35GRDxXhyYMrgz4PPX6l0mBcQsLl"
        "4He84de8B3Ffh8R9rtwqVfM7nTHnwb8/jgwoNBvCHBE3YRd3U7lWJNxeHwwNnVd4O6WaI+K+0MRRfr0hzRFxoyFxjx3iZjVx"
        "5FiGW+thc1m4KMRNvICMKW6AiRtZAFPcoBQXuoYpGRozvYt7FCEOpkPfWXU8Wj1YICcwoCHMxRJXgDt79BKq4sbv/aKYs4ob"
        "Hf0xMGcVFy/ihn22Q+ay2Y1A3B9ucSMvuTmbuKiImzmRiIO1VBh7svTg25GQuAG+uowjjnhjl1ATNz6umHOIk+YSiZu1iAuZ"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEX7cL3qZu33bcrSav+Mg/9TqP9Lxv/qZu+ydv/1bM7T"
        "av9H1/+LhP91i/+td/9PuP9lkP9Ptv+bfv9zi/9Tpv9Zl/9LyP9Xmf9H1f/CcP/1bM77cL3BcP+bfv/oZfbQav/yatj7cL7p"
        "ZfJkkf97iv9ikv9Lxf/Tav+Pgv+wdv/nZfWPgv9YmP9Upf9J0v/Oa/+Ng/9XmP9Tpv9Puf9Lx/+Ogv+wdv+Ogv9Puf9Lx//Q"
        "av/8cLuNg/+zdf9TqP9LyP+ydf/Oa//qZfHqZvFTpv/Oa/+reP9TqP9MxP+bfv+oef/CcP/lZflXmP9Ouv9Pt/9Xlv9Upf9H"
        "2P9zjP/DcP/5bsT4bsfxatqbfv/DcP/7cL1Puv9Lx/+bfv/2bc5Ouv97iv+bfv+afv/CcP/7cL39cbpYl/9J0f9wjf+bfv/B"
        "cP9J0v9I1v/DcP9gk/9ikv/8cbsAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAyW99NAAABAHRSTlMA+/z8/Pv8BvwFBfsG+gX8/Ab8BwYEBfsH/bz7AwZ5hICBugiAei7TMbhH"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEXuaOOtd//2bczpZvDWaP9zjP9Tp/9lkP+vd/9Qtf/R"
        "av9I1P/1bM5Ky/90i/9Tp/9PuP9Zl//7cL38cLtI1f9jkf9Lx/9Wnf+pef/oZvKdff/2bcz0bNJRsP+Bh//Sav9yjP9zjP91"
        "i/+vd/+vd//9cbuxdv+wdv91i//BcP/Tav9yjP+ydf/1bM9I1f/Qav/Rav/1bM/mZfjmZPhH1v9zi//pZvFUpf9Kyv9Kyv9I"
        "1P/nZfdLyP/Waf9UpP9I0//Vaf/1bNFPtv9WnP9TqP9QtP9kkf9Wm/9Kyv9Lyv9H1/9I0v9jkf/nZPlUpf9jkf/0bNFWnP9W"
        "nP9hkv+AiP9Pu/9hkv/8cL1WnP9Tp/9Qs/9lkP9WnP9TqP9Mxv+AiP+AiP9RsP+AiP8AAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAADPw/hBAAABAHRSTlMA/Pz7+/z7+wX7BvwF/AYHBwT5BgUJBPuDgQO5eXoDvHa6SUd1vSzShgLO"
        "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"
        "AAAASUVORK5CYII="
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEXcZv/Rav+Mg//sZ+r1bM+1dP9LyP9Yl/9TqP/1bM78"
        "cLrqZvCLg/+vdv9xjP9Ptv9YmP9Lxv9Ptv9kkf9Tpv93iv9I0/+bfv9I1P/sZ+n8cLqbfv9lkf/BcP/CcP/YaP+Lg//DcP+s"
        "eP/3bshJ0v+Ng/+Qgv/pZfLrZuz9cbZ0i/9hkv/oZfSpef9Tp/9Tp/9Mxf+Pgv/pZvFTqP9Tpv9Ptv/WaP/0a9FQtf9Ptv94"
        "iv/qZ+1YmP9TqP93iv+reP/Pa/9Lx/+Ogv/Vaf9Lx/92iv+bfv+bfv/0bNJZl/9Xmf9UpP/1bNBPtf94iv+afv/BcP9YmP9X"
        "mf9Ymf9H1/9lkf+IhP+ie//Oa/9Qs/9Lxv9Lx/9vjf+teP/0a9T8cLpQtf9lkf/0a9P7cLtH2f9mkf+bfv/Sav9Mxv+afv+Z"
        "f//8cLr8cblH2f9jkv+le//+cbZJ0v9mkf8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAADb6ukTAAABAHRSTlMA+/z8+/v7+/wG/QUGBvz8BgcF/AUE+/sFuwYEBoAEg4P9vHZ6dreHzHgq"
        "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"
        "AAAAAElFTkSuQmCC"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEW6c//qZvCzdf+Ng//1bM9Lx//WaP/oZfNkkf9alv90"
        "i/+KhP/1bM/8cLl0i/9Ou/+afv/Oa/9Lyf9UpP9Zl/9Puf/8cLpI1P9I0f9kkf+bfv9TqP/kZfe4c//Qa//mZPlMw/+Lg//z"
        "a9XrZuudff+0df/BcP/BcP+Hhf9jkf+zdf9Zl/+Og/+Ng/9Zlv/7cMBYlv9alf9wjf9Puf9vjf+Ng//NbP/2bcz7cMCMg/9L"
        "yP9Lx/91i/9jkf+cff/sZ+jsZ+n9cLlMxf9Mxf9kkf/Pa//2bc38cLpZmP9Zlv9Pt/9I0/9jkf+4c//1bM/0bNLoZvH8cLpU"
        "pf9Upv9Lxf9zjP9sjv/CcP/0bNFTp/9Ou/+1df9UpP9lkf+bfv/NbP/DcP/9cbhUpf9Pt/9Ouv9I0f9I0f9vjf+wd//CcP/8"
        "cLlPt/9I1P+bfv/BcP/9cbhI1P9mkf/Kbf9Upf/7cMBJ0/+cfv+cfv/Jbv/CcP/7cMD7cMD7cMD7cMAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAACnJQ9hAAABAHRSTlMA+/v8/Pz8Bvz9+wYG/AX8/AUH/AQEBQX6BAUFuoG7g3e4d3eBvfoFeIZ6"
        "LyyCc/lHhdS2iEeD0gXSs9MrcnIwSs4xT7dBurm3zEaxL0QpT9UssNKLR6xJkyzRKI7KKsl8b3QtbC9vctiDjI3TR7xQSE5+"
        "XK+WpschITJHf8QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJm9A"
        "rAAACk9JREFUeNrtm4tbE8cWwAeNNyFZIg15EAJCwFYgISIP5f0WQSkgIFqu1KsitFbba9v7au/93+/M7szsPDe7ISDtd36t"
        "bZPwbffjl3N2zpkzCAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB/SooY+C38wUin01ReFn4ZV4guQkpC1iZEXLauulyG"
        "orxfIGQEci6GK2QZli+R7UbN3Llzx/JJXMZ+CcdxpvIE82cuhusK73yhcQnhhv9+dnicSCSO14Yq+NcaaE0woakLRUnwla2f"
        "nUO5C4fVnfMHiriU4C19lkwmEx6tG5Ugc8RabrUPs7qCtWUKSsAZIk4JuRLxVakRRrNuoGsBp0ZcHXVRIs6iLiDiHB5xjn7d"
        "cBH3V48GxC20Y66LTKdQins7TAriWltH7eZyKHdydPMGZWYV62LaUOFDJ+aGwE2Xt0hQVyqh0uhGK2NjHmsrStGfHksmxRst"
        "D1bxN0+8ie+uyXz11d+QKTHF0UCLyG73wCJ5V483JxaL3W3DPFLV4c8exFzWebbk192N06vFUfdfVG7xexqm99mAuNuauOtM"
        "HP5+jyVlca3WmMuhx0dYha9m5h0zh8V1msU9FsThcHuz3yqQSGB1RUlcUhJHKFclc9c0cd9bxPW2qHQv6uYc1M/EtT1FeYNU"
        "l36kimvxxe1q4l7xe+ppXNxCgDg0kVTFbVoWKDl04qoQ3HQyc6HEldA3ex0dsrjE8ZZgziju+vUF0dy1BiPOY0Az57hB5Yl7"
        "bxcX26bmTOKCIq7nIiIujeaSmjhLssTxdlMT14mfa2HFYW8dHZq4RGILpeuIaxfNhRfX22I05yhutmNc3LLynBPFrV8tcTTg"
        "kmufPs0zcffM4nJHBnFPUFhx1JsuTjBnE9f+bVdXM1IlYVFa2mMbL3xxbT/ZxeFkGQ8v7lUzxU2XOTxVek+45CF5sUXFGXMl"
        "D7ibNw5WV/tmqbjOgmsO//MJYWZmlmqbnRl3YYuTUqm0bxGXYA0Au7h/IlXcd19SfvzxeSRx3VLIOV6mZOKUXCmJizneyjRA"
        "3C3O/WaKS+klXJoG3Jxbf6954lqzhpDLoR+ouD63iJul4v6OCtLPZai4PrV+Q3sdTNxGbXR0tLbBxR0iTdyIWwxUy1Rcu5Yq"
        "h+uWbVycu3Rf5BrFlT3+z52YIK4tL5mTxa2jOuJume6jGeLUMo4/4sbSWFuxOBQobpyK89omfVTcKV9Y0jqOiZPrOJYosbjN"
        "Cr1kZZOKS85Rc764QfozZSruo1WcrY4TxHlvsJc7srgXkjg5V8riYkvEVJA4Ux3XlIhLqRE3N+ZySFZ2XNxmXXEI/yFl+Onp"
        "6Tsp4jJCxOWMAdexkWU9L5Rdo+IOdXH0G1al4hbOG3E45ujLfkEcN3P3kSfuUUDExciVgiPuiwuOOKlRkaaPGJ4qN5HxGcfE"
        "HZBul6XdZRPnB9y+/63IoiIVx0JOjDi3aYJSdcXZGidixLmBEjeJc7xMGfvfU1OuVMV1o3jIiGuuuHr7OkGrSv8Zd2Nmxe1U"
        "Ygq0Gggh7g0V94tw8Syap+LOLOJSqWZEnCsubhSH1j0n/0XLnrjXQeJalkjX7NKfcZOMqp8zxYCbD6rjhFUl6XZlzF1muziW"
        "KZUmMxV3qImjqWHS9ozr+Zry/I5xUamlSrSkP+N8Mb/l37exUi5A3G48SNyrh4x/+/fUzDpuGunBVyTVQFDnRKnjXHeFkOJy"
        "rBbo2JO+FCQ7u+LG9IhzqVpXlX4d97yeOO/14i59uS2K6/eUPJhCLFeKbS9fXP8DV1xLb7g67v7FiCvr4nCiPKbiauZeZQ69"
        "VQrwgwxSMqVVHCrRgHtZksTh9ZAnLu2a88WVRwhlVsfdRl2Ni+sldJvqOIf1kPtRPr+sl3KCuG1PXMsiCiPu58sSly6iIdry"
        "2sxae5Vvj5TOySkK94zzxb1RIo6KS6rilAK8q+sc4mSWxIDb5o3IPHrdprW9BHGkbPD2BOJXKOLwU26e9SrtG3I5lPtBaXk9"
        "UVYnFyTuIzpPqpTolZYmL2imdKbyPFf+hEziSHDSC3y+iFOfcdxbInA7jqh4e3Ik9Sr/gUKK2zemSmRLlRIfA3cHIonrjccd"
        "td1FtJCN1GWtlBMjDu3EaLPz0iNuxGNwZBKpQycTbHegFji6QPoguZWDWV+c0vKyryqpuH0l4o4tixPhWzaSMu3HfdnjMfz9"
        "fyKIGxA3wXkRhzMl4bVWyonicHjSh6R9VXnf4+f7D5sqzjp0kp5g2zpB3vwWVmblgIt7ElLcS2M5sEXLgQlV3HTZ38iQd8Cj"
        "13F8WTIQl4YXhEzpRtxTre0liXMc5XqfoVepeDtk+3HzKMR8nlu+rbAm84eCaM4u7he2rJQK8CEq7pleDgxScSNKXo/eOVki"
        "LC56HWJLkcZ6lXKulMXxSvDyOycpU7zNjbGN1Pk6edIPOSqok+/r1BXHVicdFTYCiP+1xVpeaUMBPk3NVVPnjLi4eczLz5SK"
        "OFzKTZlSpYO660XcBfUqdXH48faM74B/QkX7wCPvVR65jcoMmokiTsiVrRU6WYlQhe0OTJh2Byb5Gvi84syDlbzdpYl7bRHH"
        "u2afrcksCDxjowtrwTOOfpN51esxz0ZJlahU4ts6rTUacTW2H5dkO6lyr5I95iZNi5NI2zpx4zSl2M6SxC3njeJQXE6Wl7it"
        "o8VbeoLPnAzN47/uYWr3KsZtnRPWqyQ9Zr4fF25xIrSZ3bk8/L/Z8HfAz/SNVCKuytaVQvndcJMZmae7jOJwrnRM4oiiz7E4"
        "0UYXWJ5UhoWMtRyuvnmTeebgYDZaOeDG3J5ldGHNMLowSOZgywFTXhFGFyziWBEXW8f8+ohAK7m29zZxUrKMNrrAb/jr8w8L"
        "RRHn7+tIBfiHUJ0TcehEE3dcTOvDQkRcioWc2PFqYFjIKM5vd/UL71Jzy1PeRJEqTp75izYsxOm5bHG53Lgu7l1ocWRluWcQ"
        "h5+thvE8kipTaISKu32u8TyLuBes+nb4CHqe1eC/W8RJyTLaeB5nOLS4haaII8ly3DYQG0YcMfdSEzdUNA7EuuK8bVR3PC9g"
        "d6DuQKxJnN/uWvebl36/8ldkFbcYUdxw4+KaE3Fuq/JEHkEvoHDbOtwc+mZPEre2hcwj6O4OeIpW4e3t/zrPXKVRHNpRZ8td"
        "czRX3vVGwXRxYrKMNoLeQKq0HvrAxffE2YTLkId9VUlblbnH47RTOXuwou+kZujcnlmcq65SY6c+NmtbynEdVRytwqXRhciH"
        "PnbN4limdCRxNFfe3WHiHqji4vHuhg59NBBxgcesouF1KldW3VNW0jErvyFmPvfIlyikgqtURisV0ykrlJ6bm6tiUmxYiLz4"
        "FmO9pRDHrIyfGk4sEnUeU47yU8Ihq6jHrC4ENuWVLnoEHBXlSxSpZxkd//LZbP1zjejCubLHGuseJY5KcEjV+5i6s3492MFG"
        "Zo7QJVXgkSMORYg4pETcFT5KDAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA8Gfk/0IT0MW1OXePAAAAAElFTkSuQmCC"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEWYfv+wdv/1bNDUaf9yjP+Mg/9Tpv/mZPjRav+vd//0"
        "bNHnZfVLyP9H1v+LhP91i/9TqP9Qs/9lkP9ZmP9PuP9lkf9H1v+0df9Lx/9Xmv/8cLrAcP/7cL3ya9Z4iv+Ugf/XaP/lY/xW"
        "nv+seP/7cMCxdv+ud/9kkf/1bM31bM9TqP95iv/bZ//2bcyMg/+Hhf/1bNCwdv/lZPlQtP9xjP+wdv9Tqv9Lx/90i//kZfpU"
        "pf/1bM5Lxv9LyP9Lxf9H1v91i/+Mg/+LhP9YmP9Zl/9PuP9Lx/9H1v/aZ//kZPtSqv9I1P9H1v9H1f9vjf9lkf/bZv/Taf/7"
        "cMBPtv9H1v9mkP9Xmf9Zmv9Ptv9QtP9Lyf/pZvH8cLtTp/9kkf/oZfP8cLtWnf9TqP9Rsv9lkf/Acf/8cLxmkf/ZZ//8cLr7"
        "cLyJhf/Acf/8cLzAcf/7cMD7cMD7cMD7cMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAADVFQ81AAABAHRSTlMA/Pz7/Pv8+wcGBgb8/AYFBvz7BQQFBboG+gQC/ISCg3h5eXf8KoW6us+D"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEVzi//qZvDPa/+vd/9Tpv+Pgv9vjf/pZvGwdv/Sav/9"
        "cLn2bM5LyP+LhP9I1f9QtP9TqP9Xm//0bNFPt/+afv9lkP9YmP9mkP/DcP/8cLqcff9Lx/9H1//BcP+Lg//LbP/qZu2bfv+w"
        "dv9XmP/pZvBzjP9zjP/9cLdTqf/pZfLVaf9I1f+KhP9Lx/+xdv/nZfXrZ+xSqf/za9XqZu6td/9Tp/9Tqf9Qtf/za9WMg/9P"
        "uP+vd/+wdv/0bNFTqP9Qs/9Mxf+KhP/Taf/za9TUaf/7cMBH2P9jkf/Vaf/2bMxXmP9TqP9I1f+wdv9al/9PuP9yjP+Ng/+M"
        "g/9LyP9LyP9H1/9H2P95iv+bfv/aZ/9Qtf/7cMBPuP+cff9Xm/9Xm/9Lx/9LyP9I0/9/iP/DcP/+cbdokP+bfv/CcP9Wnf+b"
        "fv/CcP/4bshzjP9pkP+fff/Bcf/CcP/CcP/7cL/8cL37cMD7cMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAABlP6I4AAABAHRSTlMA/Pz8/Pz9BgUG+/z9Bf37BvwEBfwHBfX4BwQEAwq5eLu8doFzeoCAuNAr"
        "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"
    ),
    (
        "iVBORw0KGgoAAAANSUhEUgAAAbgAAABUCAMAAADH5dLMAAADAFBMVEVWnv/qZu/Pa/+Ogv+vd/9Lxv/1bNBwjf/pZvGwdv9k"
        "kf9Upf+KhP/0bNHRav9Ou/9LyP9blP90i/9PuP9kkf9I1P/CcP/8cLtI0f/8cLmbfv9Sqf+bfv9zjP9Ou/9XnP/CcP/rZu3p"
        "ZfLza9VLx/+pef/Oa/+Yfv/Oa//Qa//rZu1Kyf9kkf+Rgf/Oa/+zdf/2bc6ydf/rZu1alf9kkf/Qa//rZuyzdf/8cLtkkf/9"
        "cLhOuv9I0v/rZu1clP9Kyf+Lg/+xdv9ZmP9PuP9I0v9Lxf9Lyf9I1P9wjf9xjf9kkf9kkf/8cbicfv+zdf9UpP9I0v/Tav/B"
        "cP/5b8L9cbVZlv9Puv9QtP9Puf9I1P9yjP9wjf9mkP+Kg/+bfv/CcP/2bc1alf9ujv/BcP/CcP/3bspSrf9Lxv9J0v+afv+U"
        "gP/CcP+VgP/BcP9Tqv+dfv/xat7+cbcAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAADW3kHCAAABAHRSTlMA+/z7+/z7/AYG/PsIBwX8BvwEBAYF/fv7BfsHBbmBggQsdoGDeLl5LsyK"
        "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"
    ),
]


# ------------------- صور تحديد السطر (إطار نيون سماوي) ----------------------
# كل صورة بحجم السطر بالضبط (دقة 1920 و 1280)
SEL_B64 = {
    "390x84": (
        "iVBORw0KGgoAAAANSUhEUgAAAYYAAABUCAMAAACx32BHAAAB4FBMVEVJ6P9J5/9D2fxB1/pC1fdB1fg3w+o0uuAWhLcSfrMX"
        "eaQSea4cdZgQea8QdasRcqgQcaQPcaQRbKIPa50ObZ8QZ58PZ5sOZ5gPYpkOYJQPXZQRW4IOWZASWn4PVY8NVYgOUYsNT4UO"
        "TIgNTIEOSYUOSIYOSIUOSIMOR4UOR4QOR4MORoQORoMORoINRoIORYMORYINSIAMSHsORYEMRX0ORIENRIENRIAMRHwORGYN"
        "RGYMRGYNRGUNQ4ANQ38NQ34NQn8NQn4NQn0NQnwNQX0NQXwNQHwMQnkNQHsNQHoMQHkLQXMOQ2QLQmQOQWIOQGEOQGAMQWIN"
        "P3oMP3oMP3kMPnkMP3cMPngMPnYMPXgMPXcMPXYMPHYMPHULPHUMO3ULPXQMO3QLO3MMOnMLOnQLOnMMPWgOPFwLOnILOmwL"
        "OXILOXELOXALOHELOHALOG8LN3ALN28LNm8LOG4LNm4LNm0KNm0KNW0KN2wKNWwLNmQKNGsKNGoKM2oKM2kKM2gKMmkKMmgK"
        "MmcJMmcKMWcJMWcKMWYKMGYJMGYJMGUNNFUNNFQNNFMMMlYNMVEMMVEMMFAJL2UJL2QJL2MJLmMJLmIJLWILLlcMLEwMK0sM"
        "K0oMKkoMKUkMKUgLIkALFzVoz3SjAAAJ/0lEQVR42u2d7VcT2R2AZ5I4M4FAgAQiSEBkEetSqlER0JbdBYuaEOa6iFv3RcVy"
        "Blpsa10re5YVXVitSQ5EwD2BGPxXe1/m3rlDJpCEBHva+xyIiH7hPvlNhg95ftIHnl1MTlBVyCnbDl7aKyGXzWTSiHVBxcEH"
        "m8lkiQpHDaaDdCqRMARVJJFIrqe37SIkzkJuO51MGHocgNjVq1eHBRUHHmsMgPikbiTSmRznQbIsZNNJYxLo4EpYUFWGJ3QQ"
        "hyLQRNg1wFHIrBlwDsI+TfW4jwmqh0dVa8ITUEQywzxIzELSiOknNI8kSS53hXG58APC9t3/U2RJcqs+APREmnqQTAvphB4b"
        "hhJciqrV+usPprZaeI8O7SOhKi5JVsMgnki/Jx4kcxYSkyCswn/zBgPBsmikf1YK/0HUH4q6OvRZQUp7AqhuSWnVY3QeiIZM"
        "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"
        "AAAAAElFTkSuQmCC"
    ),
    "770x100": (
        "iVBORw0KGgoAAAANSUhEUgAAAwIAAABkCAMAAAACJ3dQAAAB4FBMVEVJ6P9J5/9C2fxB1/pB1fg4xOs2wegim8kTf7QSeq4Q"
        "erAcdZgSd6kWc6MRdKoPdakPcaUQb6QObqEQaqEPaZwNbJ0PZpwPY5kPYZcPXZQRW4IPWJARWYAPU40NU4cOTokNTYMOSYYN"
        "SYEOSIcOSIYOSIUNSIAOR4UOR4QOR4IORoQORoMORoIORYMORYIORYENRYENRIENRoANRIANRH8NQ4ANQ38MRXwNQ34LRHgN"
        "RGYLQ3cNQ2UNQn8NQn4NQn0NQnwNQX0NQXwNQXsMQXsNQHwNQHsMQHsNP3sNQHoNP3oMP3oMP3kLQHYOQmQLQmQOQWIOQGEM"
        "QWIMP2AMPnkMPngMPnYMPXgMPXcMPXYMPHcMPHYMPHULPHUMO3ULPXQMO3QLO3MMOnMLOnQLOnMLPHELOnIOPl4OPFwLPmAN"
        "OmELOXMLOXILOXELOXALOHELOHALOG8LN3ALN28LNm8LN24LNm4LNm0KNm0KNW0KN2wKNWwLNmYKNGwKNGsKNGoKM2oKM2kK"
        "M2gKMmkKMmgKMmcJMmcKMWcJMWcKMWYKMGYJMGYJMGUNNFQJMGMNM1MNMVEMMVEMMFAJL2UJL2QJL2MJLmMJLmIJLWIJLWEM"
        "Lk4JLGAMK0sMKkoMKUgLHTuGJtC3AAAMEklEQVR42u3Z+1saVxrA8UEug+JjBB0uBQmyiY2tmyZuGhXT5tq0uUBgTNNrYrMb"
        "w/BsS9fdTdq6z8bWbmyycbyQxkQWyL+655wZ4MzMgQwKqPh+o4Cov8j7OWcO4V7rK0FQB2cYeM4w/8VCPp/P5XIbENRBoZFG"
        "g10oGhRwWgDFfG5NliUI6shkWd7IF7QIOBpAIY/GP5UQxcSZM2diENRBoZE+kxCTqbQk5zQIqgTQDoDmX8yIsRAEdWixGxkx"
        "SRAYCZQKa1JSzIRcvMNmtUFQR+bgXaEbMwhBvrIRlAmU0BaQyLzF2ziO67Lut7pw1UfldF8yn4EOVBaOs/IuMZGuGuAqAlKJ"
        "GALQ5eCd3b17pe59kxPaF/G8o4uz8CExKedUA1xFgBhycBaH0yMIHg+6MZNnt3PT9bejQ3s2UwtKvXWlZ7/WMAMrZ/dnEmgf"
        "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"
    ),
    "260x56": (
        "iVBORw0KGgoAAAANSUhEUgAAAQQAAAA4CAMAAAAsGXZaAAAB4FBMVEVK6v9J5/9J5v9G4f5F3P5F2/1E2/1E2/xC2/02weYs"
        "sNsrrdgrqtQfmckek8IdkcAdjrwUgLMPebEQdq4cdZgddZYQdawTc6kRcacOc6kOcaYRb6QQbaEUapsQap4PaJsNb6QNbKAM"
        "ap0MaJsRZp4PZpgLZpkQYpoPYZUPXZMOW5IPWpMOWZAOV44RV3oRV3kOVY0NVYUPUYwNUYUOT4kOTIgOS4cOSYYNTYQNTH8N"
        "SYEOSIYOSIUNSIAOR4UOR4QNR38ORoMORoIMRn0ORYIORYENRYENRIENRYANRIAMRH4LRHgNQ38NQ34NQn4NQn0NQnwMQnwN"
        "QX0NQXwMQnsNQHsNQHoMQHoMP3oMQXkMP3kLQHYMPnkMPngMPnYMPXgMPXcMPXYMPHYMPHUMO3ULPXMMO3QMO3MLO3IKPG0L"
        "PV4LPF4NPF0NPFwNO1wLPF0LOnMLOnILOXILOXELOXALOHELOHAKOW4LN28LN24KN20LOWAON1cNN1cLNm4LNm0KNm0KNmsK"
        "NW0KNWwKNWoJNWkKNGsKNGoKM2oKM2kKMmkKM2gKMmgLM2AKMWcKMWYJMWYKMWENMVEJMGYJMGUJMGQJL2UJL2QJL2MJLmMJ"
        "LmINL08JLWILLFULIUALFzUZ0sXKAAAGE0lEQVR42u3b/1MSeRzH8RWqZTkol4Q8YSBAAkQElDTUukqrw9UsT6vT6s4ru6Ba"
        "+mKnd8PeaXVZ0ZTDVSY49K/e+/P57MICy5cmm5s59jHblx/7PF3oh30t9UlUKBTySLYF4IPCgQvi2alSgmxa4Pm7LYHnhbSQ"
        "L1agxAb5tCAkuVAo1NcK4JzJlJCWMlCkQZZPhVg9vWffnl2yV7Lvv0A3spdm2vuSPLobxAiFvHAv0U5TOr3hC3zztei/Bkan"
        "0RpCfBpXoNB9IPAhhmLYwy63231Ezl2DS4mzkcONdSn4tjkWuYO1mQj2gL6N9qEKKAJ8Fu6FGO0Bp9Nmdzg8NTjqsNdka8ha"
        "V2dNh+qwWBoFgQYsa9qvo30pAW4FiJDnk4yWdVkdvp5gREk4EpYJKumt0NMDVxl/Tb6avM3pbo78Z2PttKAOOjrEZwsFqlBI"
        "p9qp/S6rpzcSGxvjyowpOYkcB7Fqw8P4j2O1DFSJRqPol0x/ubAi5R9CoBkoPJTrtLBsu1afhC9HCm6EEM1Ag2CMW1hKrMgk"
        "wDJyW7JUbUHZj2Vm5SaQYtIJedqTxcDYcJlRRIw5KDkqF63UX0M4GPB7rRbWZGgzC1mIkBVYinU6emNcYj2TyWxmSjY24Np4"
        "JlmX/FEk9VqWeYBBsgdSuGK8ReJ6mWugmOsyIfa6ePECMoVNEJOT38ucxU5jp06d+k4yKhoiBmVwrv5wwGuFT8Q+QzKdp/Lp"
        "pF532OaLcIm/3219RLaQ9++ITeTt2zfYaySTeYm92MCeP3+OCj1F1tfW/kJ+x1ZXV3+TLD8iHuJC9wH0uYXdIH5ZXPwZLnCN"
        "hAHz8/NX4LoCWS5dmpub+4GYmbkwPT19/jxcU1OTk3BNxuNwxePnzqEsZ8bPjI+jKKiLmOYECTMyOjKCo0TDge5DrImhQwJE"
        "EDha77L3xBbW3+VyOzs7udw2gVtsffjwAbX4B0gpSIvXr169wi0AToHgFE+fPHmCUvwJcIrVYo7Hjx/jFICkACTFzZs3cQpA"
        "UqAa2NWrV+dRDYBLzBVrzMxMT+MaJAYWj5MYZ5DxcRKjmAJinMAthgb7e+FWMBm0fiFLwVfCHoPbERy7nfm4s9MqEUaHBo+G"
        "/baDJiN8KQgkwhFPZGylpSKMDB3tD9ghgsacggh3SQRuZXO71SJ0WyBCB0TI3u2TIuRaKsKgFOFOWo2gRlAjqBHUCGoENYIa"
        "QY2gRlAjqBHUCGoENYIaQY2gRlAjqBHUCGoENcLuRJA9fMm17MMX6TEct5LZbsnHcMUI6IFsorWeRZYeyPIQQQjRere9N7b0"
        "7H2ulZ5KR4Po0bxRY0aP5oUko3M6fQPweXj/cRsXEHcaW1tkpwHn33xbUeClONR4Ie400FJDLEB2Guj8YgFpqIHO/xAXEHca"
        "92//is9/i5z/Bg5ACvx0XQyAz48KXFYMMIUDSAlIgfjZUoCKAmS+MgJfi+groZM16fFIA+22NKzTE4wtrDzLbG6K2xQi8wat"
        "dl6ibcqGpHK9s7YmTnfQocVZCvHo0QOJfPVEhimLixXbndI4pTTbmZ0lJ8ajHXxm0YT0c68e7ZyWn/q7stWObLIT7Q94rQdZ"
        "VoeWW1QhL/RpDS6bLxLjllbgLOtVg6SS5fIdl8KYCx3nc1ZcsxcnJHjGRf5yskztGRc+XcUcqaklVzgY8NotLGukOvBwK59O"
        "GtpYp80XHIhxHFf8l3N1jNUi354dH44NVzlWV1SZ0v6spqB83ydN+yrHfX5vt+0QGjIyCR5N+PCGj+5y2jz+YCQyoCxST6OR"
        "ocLYU5p8Nr34rBp9er9o6Wm3dsJnwcRozHjMiafNPpphXTabw+Orw9OMz5/+NrUC3s3dL576oj0ry1BsCo2b0cA7n4YKWmOX"
        "y+Vy1+Wq5UuG3V11fNaou8G221SBNeo0bIrPF0gEqJAK6SkdY2zfNQeasn+3GZum11GMmTQg7zvA/xB80mygtW3/bxryO2jT"
        "0voOTnzdQXrzpZBNC0nObzZ3tAazOZQU+Gxe9voPvhmygsDzqdSdFpBK8QIvZItvglHyNwKhg5BuAXDMbL70MtynfwEbXCSe"
        "zHeI4gAAAABJRU5ErkJggg=="
    ),
    "513x67": (
        "iVBORw0KGgoAAAANSUhEUgAAAgEAAABDCAMAAAAyNyYdAAAB4FBMVEVK6v9J5/9I5f9F3P5F2/1E2/1E2/xC2/0zu+Qsr9sr"
        "rNcrqtQfmMkelMQdkL8XhbccdZgddZYSdq0Tc6kPdq4Oc6kQcaYQb6QNb6QObKEQap4PaJsMapwQZZ4PZZcMZpgPYJgPX5MP"
        "W5UOW5APWJINWIwRV3oRV3kOVY0NVIYOUYwOTYkNUIQNTIQOS4cOSYcOSYYNSoQMSn4OSIYOSIUNSIAOR4UOR4QOR4IORoMO"
        "RoINRoEORYIORYENRYENRIENRoANRIANRH8NQ38MRX4NQ34MRXsLRHgNQn4NQn0NQnwNQX0NQXwNQXsMQXsNQHsMQHsMQnkN"
        "QHoMP3oMP3kMPnkMQHgMPngLP3UMPXgMPXcMPXYMPHYMPHUMPHQLPHQMO3UMO3QLO3QLOnQLPHMLOnMLOnIKO3ALPV4LPF4N"
        "PF0NPFwNO1sLO1wLOXILOXELOXALOHELOHALOG8KOG8LN28KOW4LN24LNm4LNm0KNm0LOGYON1cNN1cNNlcNNlYKNW0KNWwK"
        "NWsKNGsKNGoKM2oKM2kKMmkJM2gKMmgKMmcJMmcKMWcLM10KMWYJMWYJMWUNMlENMVEJMGYJMGUJMGQJL2UJL2QJL2MJLmMJ"
        "LmAJLWIJLWEMLUwJLGALHTz0PozFAAAG70lEQVR42u2d/VtSZxzGkepwHMQRZTIQSUQk7cWiluZshi3PdLXSapm1Ws0F1jmt"
        "VXNbFydWuUbbLg1Wa1109F/d8zzn7TkIiryt5PsRHpXfPPeHF3+5b8uqjozIAg0ACtqI3WLkn0lKgnAL2OoIgpRMGQ5YtPxT"
        "gpjgI5FIL7DFQSEnRCmZlWkD5KwgRrhmZtuObe802/PY0SAwVWU7wzp7E0JKNgyQU7cTTsZiY+114YN3jubGgrVZrfaImJQ1"
        "A+SUGGEtLOfx+3eVjr9WeCvkoxryYT1w1xzO2dzEBBUFkAFy5naEtTrRpfd1dARKpqOK+CpgE254yqO9OrSVRWsN4DjOvdPG"
        "BG/hNwJsgJBgrZzf0xEMhfvKJBxGt8oJVUowGEJfFdJVOWufMJ31YP1nik97HrQTCWxMRMhiA9B7gNPi9HsCob5odJxfl/GN"
        "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"
        "9i66upZtxSoAAAAASUVORK5CYII="
    ),
}


# ------------------------- لوجو E2 مع توهج نيون ------------------------------
# اللوجو + 5 إطارات لتوهجه (نبض) - ألوان التوهج مأخوذة من اللوجو نفسه
LOGO_B64 = (
    "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"
)
LOGO_GLOW_B64 = [
    (
        "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"
    ),
    (
        "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"
    ),
    (
        "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"
        "U5LOnCQAAAAASUVORK5CYII="
    ),
    (
        "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"
        "/wEvKNIJ2l77ygAAAABJRU5ErkJggg=="
    ),
    (
        "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"
        "dDTjUGEb2AFpH7DLZptq7MdggnoMfG/YaDC4YlhTnWezBUtpKHXN4BtZ2Vgu17ZagA+6rj+I1V4/rfWpY1/+pOhf8R2budVX"
        "eckvdhn7Fi8F3/Zv8PVoONglMv9Ogcn/JfBj4PvXR/tqubJ3Yk4/HEm3pWSladhHGY7Jxk2xbbhvwa6TdFtMt8DTgFsXt9V0"
        "lYgN+BBESkEyw2svQLJENVNg1aFkxWpmS8GOg+KY8asKezfbB9qG7EFiU1ybgu9HGFdjn4LBYAzIImXTMhxTXjZeF1/HNRP+"
        "EaRNpX7kaX3PdvFE+O+m2/r66RzvDFd84cPC73ALHPyr3MUvdhn7Ft/2xhZdssX+XYKSP6mT/9Yt/lePi7+ukRclf0vy9/OQ"
        "bkrNyfM4RN3IbZPl12G6FnEz4Dcr3AC3GV2H4trluZiyB9lNKcC7e2nW35OEBCpGyWIVsS3mR4etKbbItwnfhmlj2N6khwmb"
        "qtk0SlM19tX8IGPIUQ9BnsFyRM0lMx/MU7FYV6PerDvbWK6j4V/QwZ661d9S9g+fzvHOAJ98uI/vc+tf5SX/lBdc8158i5f6"
        "xtnbU/y7Zkte6739h/Xad9zwBS32++OUrktNT7ykhI8ZxsV9GsKm6rFNEdfVuHbpJsluhF2BXwtGmbIrhmSWor90lwAhGYYw"
        "sAqWxViNMWAaFJOwjeGbYto4sUE+JbRdzTcJbSq2kTGh2AxKu5D2mI/F4pAtHa0qy0jYvJpNs1laj5mUPdYPF+q1ZXsf9y+q"
        "1huT/ZDK0+fYkIp+50Ps5Cb/Iu/FL/FrNDf5234Byr8TYOynfuqjm6/uXw33ZZMizdNVKeMHtmzeKXb14OW6YLdPpGcr8VaK"
        "eLvA26b6TlDfIuL5Qjwx1a1JQ6gOQu4KhPDOfFMLJo6wLgCNOcbQpcyxSDBLfkxwDLO94/uAXTLfVdgN8p2b7YQ/uNle2L6Y"
        "HzahY7V8yKa5ms031eZisc42LNcW695T2XpebZ7rtVE+ceoTo76bqL9uUzz1Of7TT/b65xfV/qn38qJnY9/gG/E55+9PHRj7"
        "iZ/47u1Xl016vu6G76V1ui51XKxuA79KtdxWt5uC3vaItzK8HcS7kt6RyluSnlXVG1MdpZgqYScwLPotwtVuk4QBgUgyzCAh"
        "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"
        "wV2nVBootDzYL6SsnopMax7ZgE2VGLIxumwM15RgGhUbM21Bm0TdXJk2E7Zx1xjYmP31YDoc0HHI0iHxMIduU9FH6wgzkJJ8"
        "HY/Z5pullnVM+aNl9WcRvt7Y/PBQlxV79g56+O3PsoV/iH/7ZxtbLiRMnxdD7LOg9FhCeMJIyFtNZ1atFRkSdgai1yCn01rP"
        "0nIq+dQzL1HsdJXYWdjc3ox+9HgRGKk/VzlZLadMDdQDfulXVmOMTFgy2GAazTQNMIZpymii1Skbs5gSsUmmcSQ2pg822Otd"
        "8ru9+4/G5PMhaT94ejXbVUkoFt9EWseaxodc4tla1qjuWyv2Ec67+PU1dfiIQmfL9CtNsh5+kvje+9jXf/kzbLFPJ5s97V1c"
        "vgEOl6A4JFC1GcjI+/9znSce1a/QFhHCQJ0p+nQnwR5P9Em0wk4ZVwvop2wqzDo43YI8SVSPNfV88u3NYGWwAkNLl92bml6J"
        "GIBpQGM2TSFNI9psPDbXxHTFw85YNq4YZbsJbC97PcLDkNCYb5QJsq+WNFu2XNcYYq37wdPdamzDD771/OODvXoLyx9RlxXL"
        "f43Kezi/0V7m9yC+/sutbvn6m57Y+UydJStiNanaa8K258S1niZ5eihoMmUm4lxoiLAeoPWYOXm/qsNEOp30flW3+9YKyM7d"
        "FSP1OsSwllHZ5UR4A6bqEYzTxeDWcuba35DO7MEyYYgxmbLQOKBpMI3ZmLZoukYbs93GfbcxXk1m+437PLnl0Xw3OHZQVU7B"
        "6NcMWMy22GxzSjkVq2XwGJayxco+bezq4yNl29iy+xDWGc0/iR1+E737ux2Uz8nCTnHlDIgz88njtXuey52BhGxB1uXCKlir"
        "sk9+bus69WZUq8KtV+I9ezrVF4HhGMV0DtTRZUudCTInGSev+Jz+Wo8xI0b02NOShwbG40+efm87BpMlIiU0JdMwKsYNsRmd"
        "acM6GfsJHjZu8yal/cbtOBllMmeyUZNZGm0q+0hlGFZyPI1s1Lkq3J01obXc4ZsNptgwbY51vgPehvUlMQH8jUcJOzPls8H+"
        "s0EdYAdsOKWfJ3DESph3Q+Rkf/hFXIqLaBQXlmFcXAPW44j1x6fYUL0F/DAjdaMy9e97IycBZDVgx1NaZ29W+qKxJXU34JRx"
        "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"
    ),
]
