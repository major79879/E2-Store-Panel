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
C_BG, C_CARD, C_LINE = "#0E1117", "#161B22", "#30363D"
C_TEXT, C_MUTED = "#E6EDF3", "#8B949E"
C_ACCENT, C_GREEN, C_RED, C_YELLOW = "#1F6FEB", "#238636", "#DA3633", "#9E6A03"
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
        if not os.path.isfile(path):
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


TEMP_PATHS = ["/proc/stb/fp/temp_sensor_avs", "/proc/stb/fp/temp_sensor",
              "/proc/stb/sensors/temp0/value", "/proc/stb/sensors/temp/value"]
TEMP_GLOBS = ["/sys/class/thermal/thermal_zone*/temp", "/sys/class/hwmon/hwmon*/temp1_input",
              "/sys/devices/virtual/thermal/thermal_zone*/temp"]


def get_temp():
    paths = list(TEMP_PATHS)
    for g in TEMP_GLOBS:
        paths.extend(sorted(glob.glob(g)))
    for p in paths:
        m = re.search(r"-?\d+(?:\.\d+)?", read_file(p))
        if not m:
            continue
        t = float(m.group())
        if t > 1000:
            t /= 1000.0
        if 1 < t < 130:
            return t
    return None


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
        if not os.path.isfile(path):
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
def main_skin():
    return u'''
<screen name="E2Store" position="0,0" size="%(W)d,%(H)d" flags="wfNoBorder" backgroundColor="%(bg)s">
  <eLabel position="0,0" size="%(W)d,%(hh)d" backgroundColor="%(card)s" zPosition="0"/>
  <eLabel position="0,%(hl)d" size="%(W)d,%(lw)d" backgroundColor="%(acc)s" zPosition="1"/>
  <widget name="title" %(r_title)s font="Regular;%(f46)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <widget name="source" %(r_source)s font="Regular;%(f28)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" halign="right" valign="center" zPosition="2"/>

  <eLabel %(r_card1)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="cats" %(r_cats)s backgroundColor="%(card)s" backgroundColorSelected="%(acc)s" foregroundColor="%(text)s" foregroundColorSelected="#FFFFFF" scrollbarMode="showNever" transparent="0" zPosition="2"/>

  <eLabel %(r_card2)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="items" %(r_items)s backgroundColor="%(card)s" backgroundColorSelected="%(acc)s" foregroundColor="%(text)s" foregroundColorSelected="#FFFFFF" scrollbarMode="showOnDemand" transparent="0" zPosition="2"/>

  <eLabel %(r_card3)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="d_cat" %(r_dcat)s font="Regular;%(f26)d" foregroundColor="#58A6FF" backgroundColor="%(card)s" transparent="1" zPosition="2"/>
  <widget name="d_count" %(r_dcount)s font="Regular;%(f26)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" halign="right" zPosition="2"/>
  <widget name="d_name" %(r_dname)s font="Regular;%(f38)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="top" zPosition="2"/>
  <widget name="d_author" %(r_dauthor)s font="Regular;%(f28)d" foregroundColor="#3FB950" backgroundColor="%(card)s" transparent="1" zPosition="2"/>
  <eLabel %(r_sep)s backgroundColor="%(line)s" zPosition="2"/>
  <widget name="d_desc_h" %(r_ddeschd)s font="Regular;%(f24)d" foregroundColor="#58A6FF" backgroundColor="%(card)s" transparent="1" halign="right" zPosition="2"/>
  <widget name="d_desc" %(r_ddesc)s font="Regular;%(f32)d" foregroundColor="#E6EDF3" backgroundColor="%(card)s" transparent="1" halign="right" valign="top" zPosition="2"/>

  <eLabel %(r_card4)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="b_model" %(r_bmodel)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="box_pic" %(r_bpic)s alphatest="blend" scale="1" zPosition="2"/>
  <widget name="b_image" %(r_bimage)s font="Regular;%(f24)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="b_ram" %(r_bram)s font="Regular;%(f24)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <eLabel %(r_track)s backgroundColor="%(line)s" cornerRadius="%(cr3)d" zPosition="2"/>
  <widget name="ram_fill" %(r_fill)s font="Regular;%(f22)d" backgroundColor="%(acc)s" cornerRadius="%(cr3)d" transparent="0" zPosition="3"/>
  <widget name="b_temp" %(r_btemp)s font="Regular;%(f28)d" foregroundColor="#3FB950" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>

  <widget name="key_red" %(r_b1)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(red)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_green" %(r_b2)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(green)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_yellow" %(r_b3)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(yellow)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_blue" %(r_b4)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(acc)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="hint" %(r_hint)s font="Regular;%(f22)d" foregroundColor="%(muted)s" backgroundColor="%(bg)s" transparent="1" halign="center" valign="center" zPosition="2"/>
</screen>''' % dict(
        W=_W, H=_H, bg=C_BG, card=C_CARD, line=C_LINE, text=C_TEXT, muted=C_MUTED, acc=C_ACCENT,
        red=C_RED, green=C_GREEN, yellow=C_YELLOW,
        hh=s(110), hl=s(106), lw=max(2, s(4)), cr=s(24), cr2=s(16), cr3=s(6),
        f22=s(22), f24=s(24), f26=s(26), f28=s(28), f30=s(30), f32=s(32), f38=s(38), f46=s(46),
        r_title=rect(60, 20, 900, 70), r_source=rect(960, 20, 900, 70),
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
        r_bmodel=rect(1340, 598, 510, 42), r_bpic=rect(1340, 645, 510, 115),
        r_bimage=rect(1340, 766, 510, 34), r_bram=rect(1340, 806, 510, 34),
        r_track=rect(1340, 844, 510, 12), r_fill=rect(1340, 844, 4, 12),
        r_btemp=rect(1340, 866, 510, 42),
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
        self["source"] = Label("")
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
        self["b_ram"] = Label("")
        self["ram_fill"] = Label("")
        self["b_temp"] = Label("")

        self["key_red"] = Label(u"خروج | Exit")
        self["key_green"] = Label(u"تثبيت | Install")
        self["key_yellow"] = Label(u"بحث | Search")
        self["key_blue"] = Label(u"تحديث البانل | Update")
        self["hint"] = Label("LEFT / RIGHT : category     UP / DOWN : select     OK : install     "
                             "BLUE / INFO : update panel     MENU : refresh list")

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
        self.srcInfo = ""

        self.statTimer = eTimer()
        try:
            self.statTimer.callback.append(self.updateStats)
        except AttributeError:
            self._statConn = self.statTimer.timeout.connect(self.updateStats)
        self.onClose.append(self.statTimer.stop)
        self.onLayoutFinish.append(self.start)

    # ----------------------------- تحميل ------------------------------------
    def start(self):
        self.showBoxInfo()
        self.updateStats()
        self.statTimer.start(3000, False)
        remove_old_cache()
        self["source"].setText(u"جارٍ الاتصال بسيرفر البانل... | Connecting...")
        self.refresh()

    def refresh(self):
        self["source"].setText(self.srcInfo + u"   (… جارٍ التحديث)" if self.srcInfo else u"… جارٍ التحديث")
        d = deferToThread(load_online)
        d.addCallback(self.onlineOK)
        d.addErrback(self.onlineFail)

    def onlineOK(self, result):
        text, src = result
        self.setData(text, src)

    def onlineFail(self, failure):
        if not self.allcats:
            self["source"].setText(u"تعذّر الاتصال بسيرفر البانل - تحقق من الإنترنت | Cannot connect to panel server")
        else:
            self["source"].setText(self.srcInfo + u"   (offline)")

    def setData(self, text, src):
        try:
            data = parse_commands(text)
        except Exception as e:
            self["source"].setText("Parse error: %s" % e)
            return
        keepCat = self.cats[self.catIdx][0] if self.cats else None
        self.allcats = data
        total = sum(len(i) for _, i in data)
        self.srcInfo = u"%s  •  %d %s  •  %d %s" % (
            "Server",
            len(data), u"أقسام", total, u"أمر")
        self["source"].setText(self.srcInfo)
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
        maxw, maxh = s(510), s(115)
        size = png_size(path) or (maxw, maxh)
        ratio = min(maxw / float(size[0]), maxh / float(size[1]))
        w, h = max(1, int(size[0] * ratio)), max(1, int(size[1] * ratio))
        try:
            inst.setScale(1)
        except Exception:
            pass
        inst.resize(eSize(w, h))
        inst.move(ePoint(s(1340) + (maxw - w) // 2, s(645) + (maxh - h) // 2))
        inst.setPixmap(ptr)
        inst.show()

    def updateStats(self):
        try:
            used, total = get_meminfo()
            if total:
                pct = used * 100.0 / total
                self["b_ram"].setText("RAM   %d / %d MB   (%d%%)" % (used, total, pct))
                inst = self["ram_fill"].instance
                if inst:
                    inst.resize(eSize(max(s(4), int(s(510) * pct / 100.0)), s(12)))
                    color = C_GREEN if pct < 75 else (C_YELLOW if pct < 90 else C_RED)
                    inst.setBackgroundColor(parseColor(color))
            t = get_temp()
            if t is None:
                self["b_temp"].setText("Temperature   N/A")
                setColor(self["b_temp"], C_MUTED)
            else:
                self["b_temp"].setText(u"Temperature   %d \u00b0C" % round(t))
                setColor(self["b_temp"], "#3FB950" if t < 55 else ("#D29922" if t < 70 else "#F85149"))
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
                                             color=0xE6EDF3, color_sel=0xFFFFFF))
            row.append(MultiContentEntryText(pos=(s(316), 0), size=(s(62), s(84)), font=1,
                                             flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER,
                                             text=str(len(items)),
                                             color=0x8B949E, color_sel=0xFFFFFF))
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
                                               color=0xE6EDF3, color_sel=0xFFFFFF),
                         MultiContentEntryText(pos=(s(24), s(56)), size=(s(720), s(36)), font=1,
                                               flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
                                               text=it["author"] or it["cat"],
                                               color=0x3FB950, color_sel=0xDDEEFF)])
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
def run_skin():
    return u'''
<screen name="E2StoreRun" position="0,0" size="%(W)d,%(H)d" flags="wfNoBorder" backgroundColor="%(bg)s">
  <eLabel position="0,0" size="%(W)d,%(hh)d" backgroundColor="%(card)s" zPosition="0"/>
  <eLabel position="0,%(hl)d" size="%(W)d,%(lw)d" backgroundColor="%(acc)s" zPosition="1"/>
  <widget name="title" %(r_title)s font="Regular;%(f46)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <eLabel %(r_card)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="log" %(r_log)s font="Regular;%(f26)d" foregroundColor="#C9D1D9" backgroundColor="%(card)s" scrollbarMode="showOnDemand" zPosition="2"/>
  <widget name="status" %(r_status)s font="Regular;%(f34)d" foregroundColor="#D29922" backgroundColor="%(bg)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="key_red" %(r_b1)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(red)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_green" %(r_b2)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(green)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
</screen>''' % dict(
        W=_W, H=_H, bg=C_BG, card=C_CARD, acc=C_ACCENT, red=C_RED, green=C_GREEN,
        hh=s(110), hl=s(106), lw=max(2, s(4)), cr=s(24), cr2=s(16),
        f26=s(26), f30=s(30), f34=s(34), f46=s(46),
        r_title=rect(60, 20, 1800, 70),
        r_card=rect(40, 135, 1840, 715), r_log=rect(65, 155, 1790, 675),
        r_status=rect(40, 865, 1840, 70),
        r_b1=rect(40, 955, 900, 66), r_b2=rect(980, 955, 900, 66))


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
URL_RE = re.compile(r"(?:https?|ftps?)://[^\s'\"<>]+", re.I)
LINK_MASK = u"[link hidden]"
MAX_LINES = 400


class RunScreen(Screen):
    def __init__(self, session, item):
        self.skin = run_skin()
        Screen.__init__(self, session)
        self.item = item
        self.lines = []         # finished lines (raw)
        self.partial = ""       # current unfinished line
        self.cr = False         # last char was a bare carriage return (progress bars)
        self.done = False

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

        self.container = eConsoleAppContainer()
        self._conns = []
        # stdout + stderr كلاهما يصل إلى الشاشة حتى تظهر كل عمليات التثبيت
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
        text = ANSI_RE.sub("", text)
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
                if self.cr:             # شريط تقدم: استبدل السطر الحالي
                    self.partial = ""
                    self.cr = False
                self.partial += part
        if len(self.lines) > MAX_LINES:
            del self.lines[:-MAX_LINES]

    def render(self):
        text = "\n".join(self.lines + [self.partial])
        text = URL_RE.sub(LINK_MASK, text)          # لا تُعرض أي روابط
        self["log"].setText(text)
        try:
            self["log"].lastPage()
        except Exception:
            pass

    def start(self):
        setColor(self["status"], "#D29922")
        self.feed(u"Starting installation...\n\n")
        self.render()
        # دمج stderr داخل stdout ليظهر كل ما يطبعه التثبيت
        self.container.execute("exec 2>&1; " + self.item["cmd"])

    def onData(self, data):
        if isinstance(data, bytes):
            data = data.decode("utf-8", "ignore")
        self.feed(data)
        self.render()

    def finished(self, retval):
        if self.done:
            return
        self.done = True
        self.feed(u"\n\n--- finished (exit code %s) ---\n" % retval)
        self.render()
        self["key_red"].setText(u"إغلاق | Close")
        if retval == 0:
            self["status"].setText(u"تم بنجاح | Finished successfully")
            setColor(self["status"], "#3FB950")
            self["key_green"].setText(u"إعادة تشغيل الواجهة | Restart GUI")
        else:
            self["status"].setText(u"انتهى برمز خطأ %s | Finished with code %s" % (retval, retval))
            setColor(self["status"], "#F85149")

    def onRed(self):
        if not self.done:
            try:
                self.container.kill()
            except Exception:
                pass
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
        try:
            if not self.done:
                self.container.kill()
        except Exception:
            pass
        for sig in ("appClosed", "dataAvail", "stderrAvail"):
            try:
                del getattr(self.container, sig)[:]
            except Exception:
                pass


# --------------------------------- التسجيل -----------------------------------
def main(session, **kwargs):
    session.open(E2Store)


def Plugins(**kwargs):
    icon = "plugin.png" if os.path.isfile(os.path.join(PLUGIN_DIR, "plugin.png")) else None
    kw = {"icon": icon} if icon else {}
    return [
        PluginDescriptor(name=TITLE, description="Modern Linux commands panel",
                         where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main, **kw),
        PluginDescriptor(name=TITLE, description="Modern Linux commands panel",
                         where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main),
    ]


# ------------------------- بيانات الأيقونات المدمجة ---------------------------
# أيقونات PNG بحجم 48x48 (مدمجة حتى يبقى المجلد على GitHub بنفس الملفات الأربعة)
ICONS_B64 = {
    "bolt": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADF0lEQVR42tWau4vUUBSHv5tkfBSCuoLNamGjIhY+UAvRQkRE"
        "OxHdxspCBVGs9A9QKwsRBHFB0bXW2laxEHwMLK7YiAiCxdr4WtlJYrHnwiHMI5ucm525EJgJmXPPL+e7v5zcXfdt9iejPKIl"
        "mNONsgAH5JbzRg1XOwe2AkfkXDwqApwcMTAJ/LIKnDQkIAY6wC1gF/BazmejUAGf/FHgCvAC+KeQGmoBkdzlDcADSfiV5dxR"
        "A9znwBSwXr63R8VGYyAFbgIHBKMMmLbiP6QAz/0x4CowL4bxFfgi1+TDKkBz/6iQ6AfLBRxCgJOYTrhfK2J8+/DOet4oEDrX"
        "FfexEvBmmJs5n/xx4b6jWoVY1oHpArYU4LkfBx6qhs2pZD/LMXQCnDqeAGOSYFRIdlqqEFsilBiio/2+W9w20CqsiV4jLetS"
        "SQDukx5t9HOpwLyp7dV4pfSJjQNvxTJ7YZkCd4FZtV66jQxYDtwBvqtWxLwCTi3QKWCdJBn3qdTFkrGfAj9UKxIEobLc69EZ"
        "wHwiD7qT8t2FWgPFPqdTMk6va3JJdg44I8lHZa02qsB9sc+pa8UevfPAjAjNFpNQFb9/rPqcOgJ89SYlZjIAtVoIRXK3bgAH"
        "VYucV9z/8dy3ZYGXWrRVBfjgJ4Brcq414Dd5HxFe9G/gtPBfqcUuK8AzOQPs7nOHvW+vBJ4JZt2E+Lt/AfhYBZ3FCsjVC0mZ"
        "sR1Y3SN5z/19MYLKyVex0WgA2z6ZQ3Jt0WI195eqcl9HQFbSFvf0qeIfYAL4KwJqvVpav5FlktSOLvG9359Tfp/WndBSgHeR"
        "TXLo+LX9vikBsLD3uUzdXRO/b3JbZa9iXvv9hPh9brWlYi3Ad5D71TOhVp/TpAD/ABsDNqsFHYT7ULsSADuBVdIntUJxH6oC"
        "mv9in2PKvfWuhH7A7ZPPLeBs3T6nyX2hTKxzm8S8Z9HnNCXAx9gCbATeA5dDch+iAoh95sAp4Z5Q3FsL8EkeZuGPeJ+s+pym"
        "BKTAGuAlcFvtWjQynNE/e6yQpNOm0LG20TmWaFj2Qm4pBPwHaOzcPEoIplwAAAAASUVORK5CYII="
    ),
    "panel": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAACrklEQVR42u2Zu4sUQRCHv97bVVGREz3EJyia+ALBWMFERP0D"
        "NDAS1EgTUVAUES8zExMFY00MjE1ExHdooCCiIJygh9zh43Znx8BfS18zszOzOzfjsV0w3HJbM1NfVXV3Va35/HWK+SwN5rkE"
        "gAAw7ADNnJB1gcZAV38LAzR0s73qzpRuEQD3ht3ANn02FXoe4CPwGGinQSQBGCluBm4De2v2/hvgFPAoCcJ4J3FD9GuAF8Bq"
        "oAOM6PsoAbpTYD0VlTbQ0nv3AE9kS5QWAev96zJ+BlgATOu7JcA3R3cGWCXoCemWJS1gqQNxC9jpR6DpGR8BY8ABfW4B94Gr"
        "wANgEfAcOCbPHwfGBXAZuOd7aIBF2wLOA6cFsVXr8Zn7Dh8gBlYCy6RgZOB3YK30tgOTAtjoPGOD/l+mjAMnBRMD6wRgei3i"
        "SMpWaRR4BVwE9gOXpDMCXAHWA7+Udg1vFxkkArFS0tpinPWWuQsZzwgDXNPlnuATwOGEk33Q7dZ4TiTtuXl2jh8J+2/awVbW"
        "gWefMz1IKWFpbyi3TUp6mJLSJikCC7006gtg139Qs0VDWY3asN0E3vYqqOaweBsFLjiVQF8Ad4CXNTl4MXCul515dqHl0ivj"
        "hC0agbGsLbmZcwF1FJGqATqhJw4AASAABIAAMPQAhuoGWln2xXlKCf+m315fWoXY9/z0jG/micCUmnRLe1RTAVsPVXHZmuuI"
        "urKOoCb9SCRN5rrAQ2CfM1R6p9GKKbl1zGondzjjnS/AJjn3H0TaVOIs8FTGt4EtNa0B60CAM0qpWWV9I2EaYIDXwCHgk/OA"
        "OqSlycQJ4K7snVXSm5SfWW0qrQAOOo19VYvYOvI9f0eaH9JaWtPjd+IqO7AsSbWlmdGJmV4NdYXRiPptKeM8bV0oJQJAAAgA"
        "fcsfgM/Dm/ggkMwAAAAASUVORK5CYII="
    ),
    "tools": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADqElEQVR42u2ZO2gUURSGv7k76wMxkHSCFrbxUQgWJlqlUBHF"
        "BATRIrH1gUEIWNnE1s6kEtQUEQxIRMFGxEJTWEhQEURBFIwoKJigxM3urEXOhcNkZvbusncmogMLO8ydmf8/9zz+cyaY+7bA"
        "33yEBb/fAIE6j4D6aicQACWgKoDTrtdcyORNwAKryvlmYKvgqADvgTl13a4vnIB1k5qAPgUcAbYB69W6n8BLYBq4AXwRN4tS"
        "H5xDEAfKFUaAi0BXzO/tOh0PX4FR4GrCc3IjYAGtBW4BR+W8qgJYg67LL1LecQc4IS5GnEToGbyRF04D+4EleWeYcY+9rwKs"
        "AeaFUJDkSsZziqwBlwV8BSjHLJ52LAn4MYmXalpG8uVCNnvsBGblf6kJ8GXx/XNyX2p9MJ4DeESBbjt4XwQCsXgXcEjtiCv4"
        "MVfwvghYsLuBThWAWUdNWf6sK3jfLtStUmLWEQng8WYsnweBTkfLG+A2cEYyTxZ4kyeBqqMBI2AP0CupttRgbZAXgXcO2ccW"
        "ri3AA6BHiIcJmi0C+oE+jd0HAevzs+IKxiFrRcBGIdEbI1GW84PAJPDB9w5E8tw3wIxKqy6u1BHbiXWSXvuAu8Az4K1WqL5c"
        "KBTQj5MEWAMSdif2AovAAQFfBq7EDe+DQFmCcQAYVmmSJkh0APekkk8BG8QY92VN1ZcWKsuWD0hqLIn1gyafE7/nO7AL+BhX"
        "pcYjeJNShWsOxa2u9P8P4LAE7wpJbTyAn1J9gEmpupZcNeFnk8Aa4LnEwoyq0G0vZBZ8v1g+SAFvq+5DyVBGNTf6ZyTTXJBs"
        "9CqruQ89uE0SeKs0J4BBaeT3SQXulmuLwGux9lPgd6wxantTH3eboAH4m8CQy6hEqdqGoi707DZx8DqwTcKkIVAK1oVkSwRa"
        "cZshta6uYiK32ahR1mvFbeLg21ryXRt0m8IGWnAbL+BdCOjpwmlJa9sdwE/kAb4RAZu+jgPXRI+klfrcLd+IgH35DuC6krWl"
        "hHFgYeCzKrEFcF6BL7Pyg4SVB7m6jQsBK1d7BEgpo3kJWB6FD+YN3kULhRlS2AZxRXQ7pIzAiyBgLf4i1ufGrR+x/FVlvpFm"
        "KWoHxmPjwnqs1BsZBVbwP2dtioCdJj8CLsl/nYGsXp+UcaBxnAPlugOWxChwDHgCLAC/ZGQyDJxUgVvI4SKn9Ue2TXL+qaig"
        "bUULRUqbf06QGax2Alr6BsrqhYNvpR+oF+0yPpr6/wT+aQJ/ABPbN0Oti+bIAAAAAElFTkSuQmCC"
    ),
    "key": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAD0UlEQVR42u2ZTYhWVRjHf/e87zhDMhrOJJIyjSJ9iDggDi4G"
        "CVrYok1thELENkGMSXujFuHKhZtRIiQYaqGQUBuhRYsSscyPisAiwRbNlDPMlEVDvh/3uvk/8HS878f4zrw5cg8c7jvnnHvO"
        "//+c5/mf59xJpuf+ZiWXwAovBYGCQEGgIFAQKAis6FJe5PhENSaeAameDySBBCgBNQe20Xz1bhIpt+lmqcAHYAcwAgyr/3fg"
        "e+A7YEFtJRH53wkYkFXAIeCAwOeVX4DTwHFgplskkibptAEYBU7J8lZqzk3MvRL9PQ0cBs52g0RoAX4v8KXA19RmrtSjamOt"
        "73HgY2BcbaVuEwhaeCfwKdDngJTkdgG4Dfwhy5fV5+NlAnh5uUmEHLVBoD904IP6KsB7wHPAk8BWYDdwFJhz85VE5H1gSL9D"
        "N2KgLOu9qWA0dwnATeAV4KsGc20W6TEBTjXfJHBQQtBpPNwj4Z5A4kh8CzyjwWb5PcBlByR175U15jHgmuLArL6gXZhfbhk1"
        "338a2Ca2mdxh0oGv5Filor5Z4F25mfWtVkBf6ECVMhlqFvjBtf1nB8x9XgU+cO6TyPoX9bveJJ4yYD3wM9AfSe1SlHPAC94Q"
        "eYH1hGMYgL+An5xfNyrWNwPccG2Je/d+a8W5bX8rGU1ygNUWud21BsHXrGZOMIKTZOSeAM9L2uuGM4/ALbf1GbBGCpO0kEIj"
        "/qjGE8lquUUtNYhRv2aP5s8NYgN9xSlLXc+XpC6hSQyUgarOiEF3fgB8IRkOOW6YaO21WscH7Vm59C6Hr9ZMRjPgEeBHYJOT"
        "wnklcVPazmoUoAa+B/hGqYe9WwO2AL+2cL0NwG/ObQMwoNN8ArgD9EoNRw1viHagLN3+yBHKNNEZLVKJwGcC36ekbyTq/9wR"
        "z3Mda1+XQ2qdDJo2ujTFPm3BYSlxcBYZA74GXtfuGOlBYJ90/oCbw8gf0dOSvUY1zzXrLqB79VzV7D5gB9cs8BrwiSa33GYI"
        "OAkck9bXFLAD0YJVLfQWcLWDA8ySxinnQlPt3AdswXH5H+5gy3IUox4FZdB7b7QB3gL7KeB6FAOjuun1ujlSnw00kkVLgU8A"
        "+4E/I0mrapKKC+iSI/a2wIcWh1/eBwN/QTIRWAD+Va20eyPzOzEMvAO8GOuwK1XgM+VCl9xutXvB7wO2RzJ6Hfgn53DN2iUQ"
        "X9A3As9Kl/2l/hpwXvLb1Ut90ua/mEKLRC52yfQ+8ZRy0phsKb4LpQ5giLYxcWPSDg266F1b7Je5pQBZfBstCBQECgIFgYJA"
        "QeChIXAXnB1GhwfQTKkAAAAASUVORK5CYII="
    ),
    "audio": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADyElEQVR42u2ZW4jMURzHP/+Z2d1CK8qDFSkkCXkQ4gG5JClK"
        "KZeQUG7Ji1vJlgcevKwdiTx4wJNyKRJa5V6SJA8o5FLIg9vOYv5zPPieOo2ZnfNf8x8zmVOnzvxv5/f9Xb+/M8Hbj1+o5ZGg"
        "xkcdQB1AHUDlR1DLABKAqUUAgWYOGFxOKyQqqHUD7AXSWidrAUBKWu8DHAd2AaGnxZK+G8QpfBYYCpwEJguMTwwYT6CxWCBw"
        "hJ8F3JTwXdov8MhQ/YF1joxBpQDY72WBDcBFoEXaTHmCBzgEHAaOyGrJSgBIarMUcBBo1/dznv5s398NLAYywBpgixSSjBNA"
        "SloeBFwCNjo+nPDUfELzKvAaaAJ+AAeACfpe0heA9WPfmdUm14DpjsZ8870Bfur5m8ASJ9gTQJu+Z3wBGAnhO1cAHcBw/U5F"
        "CHiAZmCntNwAXAf2A42ywiRgjuOiRdOo9dmpwGqtEx4ZY77WuYipOZCy2qSE4do3oaK3TJXbKB4u5FuhGIDRwMoIgpgexFQK"
        "+A6sl/AZYBXwQIAywAlgh2SaCQwAPjjAi27YJVfo8nCf0OE6UUZO79wBXshdQmC7KncAnNVztppPdDJW2YK4p5zGuud9WcGm"
        "0YHADGn4EfBO+xhgXLU1NBbEZeClAtiocgN0As8cpY7Ic9l/DsBIsCzw0BF0pHP/g/N8v2ptKQPVAfJ9vEiyqBoAtskBGOUI"
        "+cK53+w8n6k2ALbZGS+3yUrou7rf6Pg9wJP8vjpVgo/nPHh50ENFWO23qEuzQn0Crmg9QvzK8qDHvg1Ng17wTZFhD9JpUhpf"
        "IqrQCfQCjgLv9cxchyj+AG452asgABsk74B7JQSz1bCvNGUiHpuEstwhYB4wTRxoj+Nayx1XuwG8cthCQQDWXc5r+owmoBXY"
        "lpfbfelHp6jEPmCtAjWn9RhpvhE4lkd3fmurm+P1KFQYYKm6qD5FGKm9dgZYKMuGLq9xxjBV6F4S+Dkw1slCXoXMeE5LO04A"
        "s5UCbY8QpZjZmBsCnFL6tG62VZb642CsHGnUONq9DUwRNbAgTAQQIbBJzdE3uWcaOOdYLLY6YLuwt8oeaceNchGCulWK6K0m"
        "abND9GI/lQidINsobWZ1LfSMpa8K6jSwQNeLnifFUYlzTp5vVyv4Ru4QerwbAE+lgM/FOFDcVMI4Z0EdyvF3ivlxN0EdlIqh"
        "uLmQDe5nalJOF6LE3SigZAJIEf+wMZABFqlZCXzPPksSqgr+TxxQ5j83Kk2nzV8w13/qQoWqe01aILaOqA6gDuB/BvAL0EIa"
        "HgdZv/sAAAAASUVORK5CYII="
    ),
    "cc": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADrUlEQVR42u2ZO2gUURSGv5mdJCrxGbQQCwOCDxAxUVEbQSSN"
        "pY9CfDXaCAHFTsQHFoIK2liIxkJEQhSLEFKoWAhB0SgIEQQbNSiCQSSIJtndsflvuN7MxJ3ZyW4Ce2HY2btz5p7/vO5/z3pf"
        "hoaZycNnho8agBqAGoAZPoL//O4BuSrrWNSVGEAOKAD5aWBoo0vJAIzAQmAnsAWYU2Gl88AroBf4pHCf4AkvYic2yu8CrgLL"
        "qmz9YeA8cDnKE36M8vuA+1J+tIrK54G5wCXggnTz4zzgAyHQDAwA9fqeA94B3/RcOMVKe/qcB7TqfgyoA9qAR7YnAscbeeAo"
        "MEuWzwFHgFsVUDxq7AC6gEatf1IAwqgQMrG1XQ/UA93ATVnFd66crNKgq05zfglXKbIB8Fh5aAzdCsxXMnuuBwyqBZYb+60X"
        "jzneKsSUNn+yup1A1gB9bf3eqND6KR3DqDJacMpswQJkJ3ogb23Won3AU93HgUgqW3CMPGFTCyZJoqiENdZbB3QALc7vfcAh"
        "4EMEiKSyUTp45XAho9BaJVKLU2JHga3AM8VqaL2/HNlMyJxBPhvoBBZr0XrgIzCoe5SUSy25tLKZstGcLLgfWA2MaNHrwEpg"
        "FXAX6JGVu60YTitbzIKN4rzsgFVi3wLHND8iBaOqSTmymQEYAxbJQiY07ukzcBirZylg7tPIZgogBJZojzCbSL/mi06lcKtG"
        "WtnMT2ReBNGqhGxmVegH8MuaWyN5z0r0XFStLlM2EwCB2Oh7a5E9zrZv6IFdw03IpJHNHEAIPJASo8A2oF3hUAROARetsmlb"
        "N61sZkmc10tvAMeBJs1d05HTcBvDZtuBF5Z108pm5gHj2u/AYX0PZM02LTyiZzfqLB1aVSiNbOZVyOyqPcBuYMiiAIYGfNUh"
        "pNeyflrZTHZiLwbEQ3UM9oqEFUXEOpWwUW2QpLJ+HANNQqfHIrxkXv4ZuKIrinLHeTGJrB+xU3txAEy8/rbmVshCQQTYwGoE"
        "2DSgWEJoliIbAH+A5ZbciObGd+3AYZx54LkOHXnFa4dcXI2WSjNwwqpkAyoG4zlit1VM7G0AXlqtjFFR3MEKAzBdwSZZvgE4"
        "CNyxSaDbmTMgzgBnLbJVzQavMWSXEv+fCuXHVIpzwOlpoDxS/ra6hb67R3gx/1IalOsluElHQq/COfBGFOSJU2j+C2DSlnYV"
        "hrF8mGQjK1hdsmKVWouGCBbS7sTFpEe8KQijzLjQtBw1ADUANQAzfPwF+vZJvaQxD0MAAAAASUVORK5CYII="
    ),
    "epg": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAEAElEQVR42u2ZTYgURxSAv67pMSpG3YCBCBpBkWySQxACEUQS"
        "ELzl6CEgCMJ6DHrwIIiQgzcvEoIh1yB6EIRcAkJITopIclASIRCIQkB2112icc1ud4+HfQWPZ9VMdffMjqsWNFVd/fp1vf+f"
        "zv6ZfcRqHo5VPlyL97LAuu7oRNbJI2/44SqyrjvKyHpkEvDwB4BbwB/A98CbIoWsBh4HnAXuAneAo03OlNU04gzoAb8Dk2p/"
        "CvhOJFokqE0JfAJcV/tLwFZgRn2nsQp1BnCzI6qzCHSBjYIrT9T7DNgkOErZK4ANwLxIwapmL6RmeYJuhkah1KAD/Ct7RQIB"
        "HuahvN9TajOdiCNKgBfdQeAdWYck8ZbR109FBVyCUXuYSfVNf5YpYM6okD/DE+CKZa61AY/8JvDxC+byHwNvAwuawJgKzYso"
        "y4h/tjZSNXCnWQB3GTDeShj7MGTY/Yw4j3ykn1tsOzqRmONi53hlU4nXBLwm4GUhICX0+xCenJ8MYWQmQrciIGuRdg9jVG0I"
        "yIB7wK9jksBO4MM2BDjgR+DYmLh/DLjQVoXeUJG5WEHbLID1ozBiF9HTKqGeKAbkQqgaoUzJr/IGBpWStJWJjCnauve85uH3"
        "Se1aqdTbAReBa6pcPAPsUM+RfP4k8J/cT8q9z/c97DXg0qgI+AA4Enh2Vz7shIAvgN0Bjp9WBGyL4FoShoykrfJUlY65mp8Y"
        "uDlVT/i+0Zxxw0sC4znvcT0eZV9IBzU9uz71hIsEQ7+n1Syvm940MWJdvBeRaFkGJFBEjFhLoHajrC4B60z7xM/rA0W/bbNs"
        "Ma51jXnu1xtGRYADfgPOq1rZzzcM974Ftst9proKTxW+vwSX90Ie1y+J3Y1GBNyUa5D/P5eA70/gyz7nqkahQmtZ7oOGWh4L"
        "6n4igLsHzCpP1AU2B3AtGEkNjYACOAR8HXCjpyTp6op7vAJ8ZIx4HtgjM8Be4GrAjV4QfIxKAhMR49ZjcwAuN0bcjeCqZcSu"
        "gRvtCZf1XAWkpd2kh7Uq1VPNrCUiDdy2BGSBe3uRANMELhuGCi2qzltuOmgdhcdfvcBzHZ1tDHERXD35dmMCvH/epdLoGfE4"
        "1ohnTISeEzhrxNMK/7TAWCOeVXjeM+r2XElru9P+UF9J5rgoEfMyy39TtgDvKuL8fB94oPbeD0TnEritDrfRZKwe1zTwtzBu"
        "Sva6wA/A5yqABgnwPxy2S9SdEOPqjqkmLlVC+BnwsyXABbyMEw4cZvnPy7gO7+3CAcfl8I4BPzj0i6Wowglgv/L12Qoc3LvT"
        "W8A3wE+W84MIwCRUqT/whk3E/4ahtbxQZXL5Ykwq1LdJMIir1QqqTaPuRl5DnC/kWPXt9Wd6Ki3+GZQl6QAAAABJRU5ErkJg"
        "gg=="
    ),
    "tv": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAACxklEQVR42u2ZO2sVQRTHf3N3Ba+YwoCKBiwsokUQxEpFRNRv"
        "IhZiYSEWYiPaKOgHiJXiA7+DrbWFjUYR8RFEiaImscg+LO4ZnTvZHXbm5t7dwAwMe3fv2Z3zP4+ZOf9Ri0u/2cytxyZvEUDb"
        "LXX8p4zediuA0gdAz/VSSy0B8iYAtPIKOARMGx6ZZNPGWwFeAn8M3WoBaIFTwB3gcEes/w64DjywQaQVLjoBPBPBvAM5UAL7"
        "gfvAVmDeDCdlLGRK/ngBzAFrwJaOeEDn4yowC3wRfcvUsv6c9FyUvwk8rIq9CU3xBXBMrA4wBZwRnRIgs3NgpyDVYTMPfGzZ"
        "+q+BG8CM6LbLlcSZdo3cbxdLtOEBrUffepa5AKiK2CuM320AyF06xr1QBBABRAARQAQQAUQAkZVYX4eaANtiJ1SNkUsXgMS6"
        "X6nZEU6yqF+1dsKJC8Cy9fJp4EkdpTGhiuyIFFq56LE85CapibW7+sACsEdAJMDnlsN8txh6TUAdBN5qgKlh8UTcdQV4ZFRo"
        "Mx0o6Aup0W+J8v8iwkyQXO4fAxeAH7ipx6ZMgnkNDaUMuA1ctctbVXE+oAX2AiftIrpBCbgNuCbX0niugLvAB88a+xfwXEJ7"
        "/aA1BxyjJu0SA0rSBjALvAn8ZmNu1Awnn4VOK7rDsWZMy5i+Birq5NMGyeOyyEYtbsFrTWiSKseA36in5b9LQmbj2kr4hMpZ"
        "4Dj/qXiTiOrXvHsZWGT4/EEBr4CnhkfLcQHQsXsOuOexn9HX8w7Zo8Al3/xQgcesCwwo76wi0ZUjP7IK65byjRLYx4B5bjzN"
        "+m6ntfxXUTIRL5o9MRSze518CvxkcAqjfEKoFxD/Slz9XgZWI/ZEVv2LAqLnAyAkhLSFpoADDNPxIdOnAj5hHFp4KROYA+Og"
        "24O+GboO6Klzo0rSItQgo+w226rUIivRqfYX1ATDLpY4TM0AAAAASUVORK5CYII="
    ),
    "skin": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADYklEQVR42tWaS2sUQRRGT/f0BEE0QZQYFBeu4gMfJCQIChGi"
        "KG6M+FqIbgQX4g8R/AG6EOJKBDELF4oiiOhC8BFU0IUIKkZQfEBUNDPT5eaWXIvu6Z5J9UynYEimezJ9vrrfvXWrSDDzZZaF"
        "PKIFwBjKywCx/FwwAkKBjtW1QIsos4AK0ADWA+PAW+C6iPknoqwCqkANOA5cVJw3gIPAb3lvwhLDnwAuSSRqwBywFzgpUahY"
        "j5UVflJ5vyqsNWDUTZIy2mZSeT2Q+7F85l4ZBbi2ceFrQA9wTcSFkuClSOIk27jwVYE/rGxlyhCBLNskwf+3DoQlt42FP6Tu"
        "x2XIgby2mZKZN0nw3RLQim1SZ75bArzYplsCvNmmGwK82qZoAaHzvd5tU+R+QD84VP2LV9sUFYGKAKwGNgtEvQjbFBEBu/lY"
        "AdwSESPAppy2Me3A+xJg4ZcL/Dq5/hBYrKzlzTY+LRQq+NvAFrGNAZYqW3m1jS8B9qRgLXBXwUeq4TIJ/bw3eF9J3AusUVYh"
        "wTYW8jJwdL628SXAzuBTYDvwWeVD0mgA58RGFR/wPiJgbfEM2AN8TRERyPWbwA65H3ZTgAWyJwYAT4BtTUQgZbbfyY2OCQgk"
        "QW1lachrADgmZbEfGAK+KxFG7aAOAFf1nnbeS3/G4W6g/Ko9OwDsEqAxSWSkCo0BH4HHQJ+ABnIgNSWTUPfWu7RwOj0A7Ab2"
        "C2Sfk6CxwDWUiGlgiQidUo0dRQuw/lwG7AMmUqCtDQOnMsWSrLPABuCK75nPEmAfdh44lQGdVl7rwE7gQREzn5XEFnRYfp+T"
        "RLSVJ8ixQkdyijauar/3EaUAxMBKYFAeHLZZ9r4Bn9yznKIjYEEHpZuMW4Q3qswekUUu9LXytiJg1Olj8o66RO0McEdVJjol"
        "wIZ6pI3vq0vCXpACUEjlyRLQkAdvbHG1tn93Hzid0dgVJsC+X6Va5DCH561t3ovvY6eF6LiAYWBRwgwatVmvqwSPgD+y4s4U"
        "mbR598RbVSUxzjFJ4Aj/AbwDzgKPOuH7ZgLsrA0JaI9z/yfwBnghG5lp4JVYx4rsGLwrwPYwvbLD+gW8Bp47sB+a2DGmwyNK"
        "WQcmgJdNYCvOxt10Az5vO50EayjJSIuA/ueKBiUeUUpdLzW0Hn8Bxjk89VPoKt0AAAAASUVORK5CYII="
    ),
    "settings": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAACx0lEQVR42u2Yv4sTQRTHP5Pdi1qoYKFgZaOlqM3B6XnYWgiC"
        "CIpnIdfbWWrtXyBWInZ6FraihXB6/sJf4B+giFqcImdxkstmbd7AMEw2yczbzQXymoTJ7OZ933vz5jNjvv/6yyRbiwm3qYCp"
        "gETLE5/PACPfS6CYFAHW6aLPeLmVBRjHwQXguAhZAZ4H5jQuIDTmOlMAe4E7wGlv3jKwBKxLefmZ0bDC9SfkbHfAC2aA+xJ9"
        "f+45oA2cbWo95IHSWJLxn85YKRF9DRwR5zvirGubwBkpq2/AURGSkgHrw25gD3Ab2LCVkTtCusA14GbFy+aAeXlhq+LP5oCP"
        "wMMagn4MWJSAFr4T+wY83AG2DZhTypxOTVWz312XubMwDHBdPg94US5kbhtYBa726TL2mVfy+UgymyU6bf/rD3DDLUkTQaO7"
        "gLfAQYly5ohsA+9lDWyMo40acaiqh69Lt3kAHPJ25U/AeXE+q8Ff47fRmAy0gB6wE7gMnJSXPgPuAv+a3MhM5IHGihj1N3WO"
        "imWhXqDcbHp7Q5SBGkfliZ2hG1HDqhyVK4uiAY5KZqEUU+eoYVkoNQMpHNXSZKEU0+KoJBZKMS2OimKh1ANIKkepslCKqXNU"
        "DAulWCpHqbBQ6j2UKkdpCxiGbzQ4Sn3XNU56q/AhlaNqE2AP/rPS67cDL4EnMu6LiOEoVRbyI7oDuCV17dpT4ArwVfGeqJZF"
        "fA+4FIhqDrwDTtR1xHQFjMJClm8+S7l8EJbJveha5lkEHkt5dUfMgOq9kG8XZHMqnYUc6ioLInJ53PdCIb5pD+jbRuZsjvNe"
        "KLSQMonum4r+bTOzKpAWe09UKwvNSLeZ78M3P4DDwNpWuRcicBC5KPU96+3KX2SdrCndE9XCQrZL5LIPnJLO9EL45ncMIjTN"
        "QlUAVpvz2iihxjfjEKDKN6Py+UTbVMBUQKL9B3hyHvt0F2bTAAAAAElFTkSuQmCC"
    ),
    "media": (
        "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"
    ),
    "dish": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAELklEQVR42u2ZX4hVVRTGf+ecexOdGhIdCnwq7A9BoKC+qPlo"
        "UTBQ6gwIUk8RUaHgi28G6buP+iAjGilaEWpkUNCDhvQU/ZUI8kEKCyQ1Rufec3rwW7A4nP/3nHEGPHCYc8+9e+/17fWttb61"
        "J7j2z00W8xWyyK8HAO731VugdkVAoOcEGC4mAGGGwSEQLwYAZugWYDuwFDgPnJFHkvSAYAGlUTN+FzCT+u4gsC/LEwsFgBn2"
        "NPCzdnvgdr0PvAKcU3wMm2YhH1xtAwiATS4G+qJ4oM8v2qY3TaM2cdIBCNvpf/XXcz3Rxt0cpQ6Yi18ClmnStmpIBMwBE8Be"
        "gelrvYGeZ4EP9V1cF0CkQduUEY7pXRsgjM8rgS+ADTL2D83dA64Dk8APWQDKgth2/hngEjCuRU8D026yZATjJ2T8WnliB/Al"
        "8IJ2/5JAZNaCIgCB4/pXys0WAz3l5im9C2qC8MZfANbI+Gng44KNrBUDNminjB9o4Z6eXwM+AsZSYOvSZo3mM+P7mityWS+u"
        "K+Zs0BIVkDTfe8BdxcW7+m3UYOeNNlPO+Dmnf4Zlng0LFkpUPJ6VgWEqtfWBW8Bnehc3NH46ZXwrctpQ78rIyzjefwr86DLV"
        "KLSZa5LGwhz6DIFHlNaCDHoY309W4H9V2tAmAKRLHs+ovFYZ/wK+KdHrndCmKoDVOdy2z7+r9Oel0LAr2lQF8FxOkUocAHKy"
        "j6XglSpKrdKmakMzVjL2bokwW6EC+HzbtJmvjmwJ8ISep4BP2ja+DMDtkrEPFaTgALgGrJMnLjrV2fmphHH8p6wGwn1+0tWE"
        "PBC/FjTqnZ0LGYDfcn4TOgDjBQ2OyY+yItcZgCvAnxlp0grdY5K8QYEOirva+TIA1sJdzilUiQvOpGE/0OnRolHiWI5UMLH3"
        "qqjk1WpQcs8LABNrZ4FfMhoKk9vLgP1OrYbOI3l3OB8AbKE7wIGcpsJ0zk41NwMHannOPd52QDdpKaMMXXQDWK/i9TnwcAZl"
        "Yt27gRPpA6ouAKSb+ovAoxmeM/pc0anaZMmaF4CtOQAs5SajUsgbF6kgveU4HqfmSCS/J50B6dtaxVspL4euoA7rZrQqATXU"
        "AqeANwUoXVkDZ3hYkoWiVMDbARaKp611Dt2qZgQ7kTgMvC7OR3qfpM43q8wVyyORBN8e4DtgI/CtAzdyDGRpp4Gak0PA5hpj"
        "TXJcB77XXKvUON0G3gGOth3ERXo/At4G3nOyuW6hmgWOAO8Df6fmb70fCFyjc1hd1g13EFXHE1Yo/9PBwdfyzBvA1aKTuFE8"
        "YPT5QIddXVzngZfrAGjSkT2lHZx1u99U4yTOIz3XY3RCIZv0OPf+ATfWgQdm6jZAdYPYAmyLYiBuQWFa7biqpr9WEDfJQpX5"
        "2UTa1K3ETWLA5EXb2j5pIu6aHqt02ibWuf4HK0RiargeTTYAAAAASUVORK5CYII="
    ),
    "picon": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAEFUlEQVR42u2ZS4gUVxSGv7pd7ahJ3PiaERIF40Z84EJNoggK"
        "2SSLhBBwdmISggE1i+hC8YWCgpiFRA2K6CJgSMj7sYn4AHcuEiQLgyIS1BgXEsgIxpnuqizyXzjTVlVXTVc/DHOhqJ7q23P/"
        "/5xz/3PuqeCP+0M8ycPxhI9xAuME2kjAAWEPYKzoShxhxo/qQNQDBOoNmJoS8BMXAe8BK4AqEHQYeKz7L8Bp4GwSiaAhDzhZ"
        "fRA4CTzVQ+G+C9hnMD5GwIn1AuAyMBEYkfW7OSLhqgBvAF9bT4QN1q8B7xvwIfAZcLWR+RhGYEKjorUe6B7K21UB88bsB9bp"
        "+wjYDnxjwmsUgZruL2lCVeAH22jdhcBs4I5iPWn8DuwXgfnATOBPb9AwRT69ta7IWhPkkTJkexhYDpwSID9uAO8AF7We05pX"
        "jAcfk/ZmOt8nl44YD7UCvg7MAX4ApjUoylzge2AZ8JsJp74UdcqVieOSk2YMbBP4YZOkKvr7aWCP5gV5MHSylPAeXCFQYUJO"
        "ihVefXlDthu1UFBArXqKgLf4ZYGsJZQMAfAz8EgbuacIRAJ4ABgSwJq5qgK+t5seCDJCxBO4Brwq2QzNdRt4Tfkgd9IMSwYf"
        "5/CCAy4BS4DVktXbwAXgLwPedZKAX3QhsANYa2QzTiExBHyXUgkX3lhlhE0VOAG8ANwCtujZSEY4OXOvFQVf1h7wVvtQ4P8B"
        "PlARNpJhpNgcmobHWii6EqSxppDZpM++/DgJrNSzSgb5CHgFmNVEBEon4EviBToxRXrmQYTA58CAKZGTPLcY+FFlfFwUk2sh"
        "7gEmAZ/qbusXX7gNiETYYF0Pfi7wkz5vlCJFRXC5FuP+qDyQFCbeQyuBjzS/YhRrOvAVMEPfTdY+iouEkWsh7t8C1psTVdbc"
        "Dbr8XAd8q8ZBTVm5riPjy4Zs6QS8VZcCx3Mu5L31MbBGivMF8GIK+UPmCFkqAZ9ppwBnzMJ5qks/5xRwDHhdpMKUds7bZZfT"
        "gZG8E8DzTeQx7TAzW72mKOW3gb7bC0zNI6uuYNxvlubXxpDFA5O8XJOSZAawO+XgMyYCD4FVwOEiGyzDk832TAS8CzwL/N0K"
        "Ac9+OvCJaTL5eqYdF+Ywf1CbvlAxZ6vHR7LIl8BzDaTb2Sv13cBBQ8wlletpzV0/nlHo9Ks/0+l2eyzFCtIiJknGfgXmaaNu"
        "1D/ZmWaBNh/8+4GtCqcAuAncM2o1qrnrCawBzhm16HRbPWkMK1tvAo4YVRzlEq8u5/mvlV3JeUxsdwgh8GcE3tmORpDwnth7"
        "4k2VuItNNdlp8DFwXeX64aRjapDyott2BQbo7svAO1lNgzCje+ATyt0e2AOph/0sWazn6PV0KpTqrXQl4i5v5J5pLY4T+F8S"
        "+BfE/Sj3JGL4WAAAAABJRU5ErkJggg=="
    ),
    "disc": (
        "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"
        "AElFTkSuQmCC"
    ),
    "power": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAEtklEQVR42u2ZW8hlYxjHf+tde39mkmGQZoQMYXIszQ3TCFMu"
        "XDhTQ5JTESK5GMOUC6IINcOFTE5pwgVRrhiGZnK44MrhU/OlNAlDxjQfsw/LxfyfPN72t9d6116LmZpVq2/v99vreZ/j//0/"
        "z8q27/iDlq4cGOhzAIZtbBJaUj6T8ouBJW0p35YBASiAe4BvgWngGa03vl/WcApZqiwFvtZaoYhcCrwdpdbEV6eF1AFYJEMK"
        "/c2Bk6Pf7JMpVOjvNLBHits+e/a3Iq6yts8a8J9dBww4YMD/YECbhZ+1rYznNFnDyhe6Q4rsFAM6Uv4O4A1tljd0mBbA88DT"
        "2iOkPFyVWfaBG4D1WnsYeHBCamBy7wRu1tpuYI106zcRAVPwPOBFeagHPADcpf/lNZUfAFcB6ySzB9wP3C7l80kNsNxcALzi"
        "uE3QBoOIQqTSjkxyfpayQTKfEiEclOkYKhbt48BxTuEcuBd4Vp/r8H1zxFvAKlfEBXAQsKFKiocKIT4duNUp2VE01gHdCanx"
        "QDLeB1ZLtkXlXOAK7dupY4BB2S1OaA78qGYlNMTr+1LwCeBTF9FCtcC4CIcxyveV+6uig+ZJ4NeSPjdLrAW71rroA6wATnM9"
        "RWUDbP0c4Ch5ugPsAjZKwWGJV4vEKGTAZrWhuRApBy4e55RQ4sHzpYht8DHwQwUDDnO9cVWUytX0vBk9c8E4GaEkrKc4KAXY"
        "ou9lhh8jJOkpelV4ju2xNdJtiSv4ygaYd0+IcvIrB3VzPZcBn6itnALmAbPAuyWRM5nfyXBDnqOVxiP17ZQImx959rcKXgyq"
        "lYt0qi4Qx5mukHoAOx28okhO1eVCdRinReF74LYRp3oKKtUmc7bZrkjokQnQGFwhFwmn9UKlrFGNWeDPuYwrg9FtUQGdmtB4"
        "DB1fqqK8yTxJ6WNMdDvwS6oBJuwb5wk7WFK8WWcUsyICkm0RkCTB6CYJ7mptOXC8S5EmlR8IsS6LDNpU5yAz6z9TCIOgbT5w"
        "fQsGWM6vBE50KNQT/M7Jh8ZFwKjDq1Fh380/s8/QkPfNIY/os9Xch6IWIdUAb/EGx0QHwBFqK41gTdrcGyVfC5zlHJOxdyw/"
        "Vs8yA3J5YL37bR+4UodUz3VSdTzfFf+5BHjIkcCOcv8d1/2NFlLyfsAgcx7wpSDOiF0uIx5zZ8qgwkGUuWYe4BrgOeAQ9+ws"
        "cCYwU0LbSz1nELobuC5KmyHwqGpkkfNeLmPy6O64Yu0DB+v514BD3X65RjczVdrVKqG3qcPnwNWOKlixXQt8Adzn+mY7wPxt"
        "awuBG9V9rZa8gWsd1wAvu4iOD2fCKyab01wOvO6+Z+6Q2Ql8AHyk2vnJTTWWqkFayd6Xf7iUM0pjKVlpJpRqgDdiOfCCaqJw"
        "m3UTOrDCAcAOzZg2pihfZzZqcLoFWObgtOvg8C/d/Sh9/HpHv7exyjIpn6coXycC8cgF4GzgJo1AFld8/ndB5EvAeyNktm4A"
        "rrW0TQ9Xjl8InAEcK2hEWD+jbmuz6619FtQiiE28Jw6OjMXrU65YeyOiyKSzpSbeEw+jiNgZMXSNCPz7Tf2woaFYoy+6i0ip"
        "bIShjfcRTb+pr93bTpK/+/X1N/RlavcR7+YRAAAAAElFTkSuQmCC"
    ),
    "spinner": (
        "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"
    ),
    "rss": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAE10lEQVR42u2YW4gcRRiFv+ru3RAVb4m4gpd4i2twjfggGpVo"
        "iApRIyyCiHhDwTeJd0EQHyIIgr6qqGAQhYB38EIIqESiBMEEjcnGK0ENm6wafYhmprt9OQU/RXX3zGR2ncAUFNMz3VP9n6r/"
        "P+dUuV9n/uZwbgmHeRsCGAIYAhgCGAI4pJY13HfqIdgCKNUHGoANsojcTwNAAwMgBXLgNuB24B9gFzADfAt8A/wEHIiAyQcB"
        "gE+bcWBF5H4B7Aa2AG8CG4Fpk2puroA0pdABoK1gUgMuBU5Tv1Er8z7wEvCJATLrdZJ0cD8zs+rrItcq5OoLgFuBj4H3gOWm"
        "LtJBoNERBZKpp2aGLagSuE5A1gOnmNVzswHAVewHnIJZqNk9AlgEnAmcCywFzhcwD6AQqEL/T1QXDwHrzIQVcwGgkzYOXKsa"
        "uDig3US142vsOeB+1VTazwJvAlAlZO3gueXAA8D1hkpTk1oZsAlYDfzRz5VoqgGfGoWCbpvgfYE7Mc9qAfnUFG6pZ9rAZcDn"
        "wGKNl85lEVOhBW3DNKmCvwJ4GGhp/NyAWAxsAI7X78n/CcC2PNCKp4Erge9NznsQpwLvAkcFKTorAJyhTNchkFLs9BmwDPhK"
        "Y/iibgGXAi8EoGetBnIjSlbY6lpLz00DVwlEprFGdP9m4B4BS/vNQl4HFgFnAL8BvwB/BeatbGATnz4nqD7GjU4UMokTwI+9"
        "MlNS82KAu2XUtgI7df0IcJZZmbQhpTJgL3CTArbe6EjgxS5StOsUOmgUdkzO9ClgG/AycJ6CrCtGn/vbgDUCXJi6WCH9yDsw"
        "lz3rQNuYtzYwH7gT+BJ4LFDgOhDPAx+a1PKp+ni/U8gucQbMM896E9dWQa4F3hC3FzVj+tS5V0XsTNAXSgiLblchqREpgM3A"
        "q/rcH7hQ7zBbwKTqY0HNSnjK3AW8bkTOg1tTs3Xti5k7CbgcuM+YNz/jLa3GR8AqwzJlZMJKKfJWYDQAOAHs6CadOt3QOFHp"
        "euAS4Bbgd/Miz+3XAE/W2AQPeKfAOqPiGXBDtw6h6UHrd6wqvyZztjsA0QYe1QpVqaxnrFcijney22LuxErEtpIjOp1YaTbz"
        "hXn2iaBwY3ZjI7Av2K0tBU5uIINGAC6ww2VkS+hzfgq4I2CoQql0UYXQ+fH2S50xFD1P2kKvAJyZaYDjjIcpIyAy4ANxe2L2"
        "DkgnqBA4v7JfRGj2gl5p1O68HpQBm9Ih1rPAsREQ/vtac+3HXGnqokoXvo6AnKhJv8pzIWde/o6o0LeFor2r5fH3mtnOzUx+"
        "B5xt6PN09alIYfrrn4338kBP7AZAYgYoJCarjAfyVuJfYAnwTGQV/Ms367Ol7vk+lkY+uGnRcW5sypj0oezE4CWBa7zLFF5i"
        "VmVUv0/qBXlk8B+M7RjV9ZKaOsCoe6r/Zdqxpd2kkC/cY6S2SeTPPoD52iPsMVbAP7sFeNsQQAps7yAdQh81U1M3lVbCadZ2"
        "aAZiDOVF7RydTPf9kOpQ9gOp8vwt423sseFB/b5JhRcL3pl0SLs4TkwjnV5WwAFHqxjHA5r0+bpMCuwGYfbtCnjF/VOHU+sU"
        "sNM2cIO8z/ZBCj5mp51JnTH5kn3KeQYl72NCFiqrE9PsCYRuoIKnYvtm97fOiFnJALb/AKariVR3IKwTAAAAAElFTkSuQmCC"
    ),
    "backup": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADBElEQVR42u2azWoUQRDHfz3TmxCMREFEUAQjSMCTN0X0IF7E"
        "F/AUFV8huYtH8Q08+gQiKB4FBRE0Vz2JKApmEw2REDc7Mx5SDW07s+np7ZllzRY0szs73VP/+uqq6lVf1zYZZ0oYc9IezygZ"
        "NuUtCbSQEQRAyYLZXotEpDLBpHK/qANAyYQMmAFOynejiY9ALzLzCpgXnsy7VoF1h6c9AZgHO8A94IYAsE1pAfggGsprMpmW"
        "mEkGTAMvgOPyPREAT4FloFsGQlfYewd4BlyJLOUC6Hv6ggKOAreAS8Bl4JsrNF0yMQPuCvM9eSZxTCjEPArgFLBoOWcCPAde"
        "Ow6ci6YK4eE08BC47vKgnZdkwCxwWxbR1sJqyOiSAWdEODb9LgGgrOu08HJNTPe9rYWySSeAY/Jb7H2iJybUA7bl85an6Sng"
        "rBtudcXDxZASH2RKWqTnatiH+r47cRPMxxLA/5VKjAJA4YzGc6HYAjObWWqlCq0D0JYD5p62q4B3wAUnsnyRtVSbALqeO6pL"
        "6xLzy2gzJMsNBXAf+BE5ZU6Bw3WjYCiAxbbDZWwA/YYY12068aQmngDYL12JNroRwYLV464xXwBm218CVgKK+Tpl5xHgETDl"
        "U5fUBfBqQCoQi+bqCKeuSczKlj/VAOMdWXuuaSfO5PoAOCefQ33DaLYr6clOXdPUQ7z4InA+kvQ3QoUwTErwS7SRDVGUGO1t"
        "jKIiSyJUVcpZZ5JKTABMAEQAEKVf0xB5HXCknjVpboXRUDJHR75r6EE3DLrvwE9rS68Cc5C/G1QhZOYe8izyP7macAGkwBrw"
        "GLjJbht8qsL0liRzjNHJ3pY0osxMdiRPWmG3MZbYGtMVO+Myu8c683I/c3xDAS8b9Edjmua4awu4U5Z3VTWZVgXAE0sCqVxt"
        "9WvrGjLsNWyeDsi9BHgjvJTWIarirwb2aeCCDKQeWKXiyDNSQTMDXBUAn4G3FrB/MlU14L8Sqip0jSjc53WTucKanDi+0DSZ"
        "UJ5bIzgbzVvsRthOvD9SiT9DCrphuy0IzwAAAABJRU5ErkJggg=="
    ),
    "restore": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAFX0lEQVR42u2Za4gVZRjHf/PO2e2K5a5IFobdxAwLjMzsRli0"
        "Ri0hRFFSdP9U0YWiMAqE7taH2g9WpBJRFKZrUdEHKahMrez2wdKiEkoiw9Y23d1zZvryf+FhmJkzl1MgnBcO55yZd577+38u"
        "E/y6ey8H8nIc4KurQFeBrgLVV6BP3VWLjqvxXKxP3eXpuP9LgQYQAT1AXw0L+ucOAyaJZqNTCgRAmCF8EzgB2Ai8VsN63otD"
        "wFfAeaIddkKBGGjpfpAQfjGwCTgdWAgMaG8ZxqGemQcsAWYAG4B7ytJyGf8vBC6XW2OgV8JfB6wB+oH92j8EHKx9QcKLznwn"
        "DRQCz+rb03oSeERKNOoocDywFngeOBoYl+VXifiEhN4DPKFryUMdGwNEKQoEwDJgh2g1Rfd+YKn+N6qG0H4xuRnYCjwErDDM"
        "e4Avgfm63jTC+8PZBwwDnwAzE57wIfq2aAyLJqK1DLioyJlwOdcDYAyYCjwMTDGu3QosAr4T4zgR3zFwIzAInCWBkiEWi9Zu"
        "eXdtgtZqGSEXJFyBwxYbCwf6fROwS2ejlfHs4brXAn423rGraXgsAbZJiXFgmhSP8mDaFcTrhgkNB7wCXC1GUcZzHk1CYCSH"
        "vke7f4BrRdOj1K3ASWZP7UTmFZglJYaBU8QwSNlrPUkbJRrAFmCl9k/o+4Y8WauWEk1ZfhB4FzgmI0TKLB8qj8kbvbp+hcKq"
        "2QkFImOtFvAccA6w0xzMugr8BHwg2ZqC9LlZniyjgI/DEHhf6HIb8EsHCzuPfusMeATilerhogr4zLkduBK4GPg8I/azBHMF"
        "+cSqjWw9NrsOCnnLPqX653UjUCvH8vb6qKk2gzZhhMJoxGTiExP3S8NoADwN7NWBinLg068eKdgELgHmmAzfrkT4Sx+v7BFZ"
        "Z8wVsDyGSJCTuJJrpwmx84HNMkK/ie2wjeFoBw4uI/msB141JTTAoSnlQN5hX6VCz3vqIOBOlSHXm71p6xDDz9dmhRTwAv4J"
        "fGowHyWvIljvq89x4D5B4FvmuenAS8BHwFUGeWxnN0N1kFdwRxkYjQ0eW4FPqwCLIfCtEt6gfvu1QF5ebgo2H3InJ4z3fRkU"
        "8lD2BbDPZMSBNm7PCycnL5wB3A38bvacneAbA5cm5NuUdRaCjOGuUxh8CJxrBJkPfGYgtKw3/DPTVKLPBG6XZ/z9yco3k+WN"
        "XYLRUf2Pi/YDqGkPjAIPFDzIWd7wyPObKs0LgG+MULGye596kVieGzVldyEPeE2nAD+a2t6pU9qQQKgqIxWX0oJOVxa2Y5Z5"
        "qlLDNK+7NqXDH8AzYuiLrReVE8pOItKmHpE5wLHQ6UjTD6+X8Jkh69qkdQc8Li/0qkY/DnjZhFZVJWzx1hSfheLREIDc1S5c"
        "22XiwHRKXqEJ4DLgDRNajZKVbWAmfJF6gHtNSDrgDuAHAyiVijkv3Mdi0DD4vFgThwWmwXHaEyaSU5C4F5sJ33tKeE0zslwN"
        "vGD6jlqzUR+Py4FHxcB7Yo6gdkiQGGl/K4HrceLeURrVbFFp7i3fC7ypoUFYBKqDEi/5PMGlmhagcsEnun1Cp2Hga00i9pg6"
        "6lgpvEhC96XQWKlZVFS0wwtKvqX0SgwIjXwvPKZiza4Rld9o8tafuD9mvDmqDL3CHNpCHV5Q4TWrx/+pwIPALcaCTZMvelJC"
        "Me3eGnl1mwwUlWlPg4rviW18zgau0aGeVaJXeEeHdWMKTf5rBWw2bZkObC5wJnCq8sUkEy7bVVVuVnH2dwJIokpCdOBNvTMj"
        "kLJepIrVk/Fcd0WmzLAvRKKUoa9teFod4N0RBZL1TV4+6fjqvujuKlBz/QttAJ/LzhV6WwAAAABJRU5ErkJggg=="
    ),
    "puzzle": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAC80lEQVR42u2YPYsUQRCGn+7Z3TvF4ziV00AREw8MTwNRMBLh"
        "FDRQMDLxH5gIJuaiP0HRwMREU08xEBE0E0FFRMVEDvELv/C8nW4Dq6EZdmZndnt6dmEbmp3ZGWbqrar3rapRHz7/YJyXZszX"
        "BEDTq1XTcxNAeedG9sgDcEanOaDSUQagACvHh4ElYBZ4C9wGnkvKBo2ECiSjzvMzwFXgZOZ6FzgPXA4NQgf0vgauifFrYrTb"
        "CXAJOCPGJ6MUAZfbh4B7Ynw7c08qIL8AO4GfmZRrNAIufY6Jd1UOSIDNwL6Q0Q9ZBzblGO+Wlb0xAzyKCuk+1zTwpo9RWq6/"
        "846LnmtiqhDAdpHKDT08nEoaPQQOxqoDjmQzwA3PsLx7U1GcXuR0np4H7hdIqQP6CLhQRnLLpFAbOFKx6Kmc8wXZ/dZaWZ6U"
        "McoC34A5OS6T50V5XSSdXbHpV2gSJ7LtkOqhSzgrqaKOk3lgAiASABuibxmwTVFFvCsLoC0P6UYCokRgjOe8nuTWJb3/yesy"
        "VQQQXU9S54BpKXIma7PuYzjAd2APsBs4C3ytEYRLlVmpxM+A18BL4AqwIwtikF5oQfr+bQIiphCsyKj61LUZuoJnNDAFvAJO"
        "RzA2zXDgL7AVuCl9mQVUFRUywKqQ6QHwWEClNQFIvNZEAR3hxS7gqCO2HkLanmS4EmsZYH+IQqZobtlhALicPNAQEC0pXKkb"
        "dWnTFh4sAXtDfyLJ+ZLh14aOSOuy41+rotdXgUXges2538sxHf5/5TsF/BYAtlVSDbbIOHgcOAesr6kGuJHyLnBH5Hpeiuky"
        "cBH46I+aRYXMVds54IVosB+ROnLftQ+3gBPy37RE3nocMFVJvM6bVW0E4iYCJAH+yDtb8l4zSDeaeqSPoTpWouELSM9OuIoK"
        "Na75k5FyFFeVOmAiENiU+HY0EICpSNHqZH6DADDAe5mS6o6AqwMrIQD4I+ViZCVKM79DRcD1QGNN4ibqgA0JwI5qBMa+DvwD"
        "X7a9cbdM24kAAAAASUVORK5CYII="
    ),
    "grid": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAABhklEQVR42u2ZsU7DMBCGv6QBVWWEgYV3QELiAeAF2GDjOXgp"
        "BgYG2JBYGXgBmLoxwUQbm4GzFJkaNyY2SnWWokpp/F3/u+Zyf1vN394Z86oZ+Rq9gCbyfgVMevCMHMWYTaQ6BlgmVNWUYjaR"
        "DbvACTDrZM9fVl6XwCPwGgiYg7lSgLvwELgBDnpk6gO4BK69gDmY3+q9NuqysQc8A/vAIpClUEVb4Bh4ku+6ycBsQ11oIuU7"
        "7QTaEsg6x0IY594NOzQz2kZnErTqebNVsm9aiBkU0CYE6gY0hZhBAamBftufg6mjhApQAZsswGaIZ0sJSHnguH22IPPHMOce"
        "Fg/AJ7DdY25xH7ACblcEH5IZrICRcy/AhYyz684t7ror4E44bSZmcBr1R+oj4AzY6WQiVOJWgtx35pfczKCAmLP6qyMbjNlE"
        "vGjds9Vav8S5mfXAbc9maKU29VcJNfVq6tXUq6lXU6+mXh2ZClABaurV1KupV1Ovpn6TTX3sn3qTmLFiTH0S//f6AuPe+4K7"
        "oj40AAAAAElFTkSuQmCC"
    ),
    "search": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAEsklEQVR42tWaW4gcRRSGv+puk4gEIYgx4IMQFUWDChLQl4Ci"
        "oCAk+iKCeEGQGDQoZsnkUWR3FQVvD6KICRjU+KAvQfBJBRUUvBsUEQRlvYa4LiGSme72If+Bk0rP9sx0z+ykoNmprpqp89c5"
        "/7lUbVg4vMTp3BJO85Y1+G7QBoTofamnmFYAqRMwHwBgofkrDiCRICb0OcAm4GLgPL1bBL4HvgYW3Ny0BuzYAXgBbgQeBK4F"
        "1vWZvwR8CbwIvKnvpuPQRhjAC5nwm4HHgRvcWBEJZWbjncMXwGPAO44v5aS8kAm/A/hQwpvt9yRIBpyhJ9O7nubkwFXA28CT"
        "br0wCQCZBJgFXgBWOTNKNJ6qf0RPqXc2FhzgXcABvU/aApEss/M9YDvQAboVrvNd4C7t8IV6Lge2AfuB4474qfq3As8JUDIu"
        "DtiiVwKfaHEjYAr8ANwPfFDz25cBzwLXOxJ3ZWp3AK+34Z36ASiA94EtWsB2/iPgFplLGgUu05A9Pf19VZrK3djvcr9Hm5I6"
        "qTCdArguEj4APwI3SfjMkbSIoq8R3Dhwt8wtdXFkA3CfM6/WOGA78WjUD8A98u+ZBKxruSPqvQpyxp8S2AmsieY1AmAeY52C"
        "lAFIgPdkPumAwnsQmUzmJSc8wAUifdmE0EnF503A2QJjO7PPmdKwrdT39jsyWwy5pmlciDVg3gO3WK7cphyRbMaRn4C/3TpB"
        "m9UqiQHWR6D+VWLGiCmyaeAo8Gsk8PpJFDRt5fblODLSKgCLUX8tcG4DWzXinin36X/nn3EA+M6N5Yqcl7hgNgqAAJyvuqF0"
        "Gvm2TRKbmXwDHHNBDeD2BiS21GSrNiN3Qe6zNklcqL+gYqR06r8NuMgtPor5PBRp5DDweQPnUGlC1n/eLVQqlX45Cm6DCG8p"
        "x9MyodxtzCvycFmbbrSnd28Bh6L8ZQuw11VhWUVeH1ytUCr77Cgtt5QhBf4AnnHRv1USWyY5E5lWrqzyoHaz54KU11ahsbUq"
        "hGad6dncj4HfIp61BsAWOwg8JeJ1XVS+GfgKeAK4WmmHEfwseawZRe8dEW9M4K3AnIBmTbxQv6I+uB07oEqqF1VY1v4EfnGR"
        "dYMbz119kVY4jDlgj+NK2RYA75sTkXq740lwBX1Vq5pTRBq33W8EIqkJ/bbwA8CdwM+uYLessqt697g+d/W7Vtz/pSOVJLJ3"
        "qys6zpzSYc2pzh2WznZfA64AHlF1FtyRyio9drySiKTzqq236XMS1RMGYrfIPjSIMMTxui/AV0uwzcCl0dHiIeBTBcPFSNBZ"
        "7XgvMr+RzSkMeT8QnEsdFHQRHdXUgZjX+EAghj2dLqNTilBRO9Pn9NrKyz2atzsC4c2pHFQTo94PjJLblw5ER/1OHxAd9WtB"
        "TPqGpow0MVdxyjGUd1qJK6YYxPwyIGq900rdkcXmVKeJviBW8pJvVHNKpgXAqOZ0UlE1Ddesg5qT1RYzHkSYoovuUBPsCpf9"
        "blTd3uieeNzmZMGu61J7lHNZxRemCcBywc63N1RLp0A+bQA8iFSaWOLEjdBqTlwWPuxr6TDl/+xhNcQapelLbeVCk2pWiv6n"
        "55TL8mkHACff4JySQP4PQJGtvT+3Sk4AAAAASUVORK5CYII="
    ),
}
