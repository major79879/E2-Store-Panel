# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
#  MAJOR ENIGMA PANEL (E2 Store) - لوحة أوامر لينوكس بواجهة عصرية لـ Enigma2
#  تمت إضافة ميزات: حالة السيرفر، عدد الأقسام والإضافات، اسم المطور بجوار العنوان،
#  قراءة حالة الهارد الخارجي بدلاً من الحرارة، وعرض خطوات التنفيذ (التيرمنال).
#  متوافق مع Python 3 و صور OpenATV 7.x / 8.x.
# ---------------------------------------------------------------------------
import glob
import os
import re
import ssl
import struct
import time
import base64
from urllib.request import Request, urlopen

from enigma import (eConsoleAppContainer, eListboxPythonMultiContent, getDesktop, gFont,
                    ePoint, eSize, eTimer, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER,
                    eEnv)
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryPixmapAlphaBlend, MultiContentEntryText
from Components.Pixmap import Pixmap
from Plugins.Plugin import PluginDescriptor
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Standby import TryQuitMainloop
from Screens.VirtualKeyBoard import VirtualKeyBoard
from skin import parseColor
from Tools.LoadPixmap import LoadPixmap
from twisted.internet.threads import deferToThread

# استيراد البارس الخاص بنا من نفس المجلد
try:
    from .lstparser import parse_commands
except ImportError:
    # في حالة التجربة خارج E2
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from lstparser import parse_commands

try:
    from enigma import BT_SCALE
except ImportError:
    BT_SCALE = 0

# ============================ الإعدادات / SETTINGS ===========================
# رابط ملف الأوامر على GitHub
COMMANDS_URL = "https://raw.githubusercontent.com/major79879/E2-Store-Panel/refs/heads/main/E2Store_Commands.lst"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
OLD_CACHE_FILES = ("/etc/enigma2/e2store_cache.lst", "/etc/enigma2/modernpanel_cache.lst")
TITLE = "Major Enigma Panel"
DEVELOPER = "By John Kamel"
# رابط ملف التحديث
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
    ctx = ssl._create_unverified_context()
    sep = "&" if "?" in url else "?"
    req = Request(url + sep + "t=%d" % int(time.time()),
                  headers={"User-Agent": "MajorEnigmaPanel/1.0", "Cache-Control": "no-cache"})
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
    image = distro
    if version:
        image += " " + version
    return title, image, [build_id, _boxinfo("model"), name, title]


# صورة ريسيفر عامة مدمجة
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
    path = "/tmp/majorpanel_default_box.png"
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


# ------------------------------ حالة الهارد ---------------------------------
def get_hdd_info():
    """Returns (used GB, total GB, percentage, mountpoint) for first external HDD."""
    mounts = []
    try:
        from os import statvfs
        # فحص sdb1, sdc1 إلخ كأقراص خارجية محتملة
        for dev in ("/dev/sdb1", "/dev/sdc1", "/dev/sdb", "/dev/sdc"):
            for line in read_file("/proc/mounts").splitlines():
                if line.startswith(dev):
                    mounts.append(line.split()[1])
        # فحص مجلدات الميديا الشائعة
        for p in ("/media/hdd", "/media/usb", "/mnt/hdd", "/mnt/usb"):
            if os.path.ismount(p) and p not in mounts:
                mounts.append(p)
    except Exception:
        pass

    for mp in mounts:
        # تأكد أنه ليس الروت إذا كان الروت مثبت على /dev/sda1 مثلاً
        if mp == "/":
            continue
        try:
            st = os.statvfs(mp)
            total = (st.f_blocks * st.f_frsize) / (1024 ** 3)  # GB
            avail = (st.f_bavail * st.f_frsize) / (1024 ** 3)
            used = total - avail
            if total > 1.0:  # يجب أن يكون حجمه أكبر من 1 جيجا لاعتباره هارد
                pct = int(used * 100.0 / total) if total > 0 else 0
                label = os.path.basename(mp).upper()
                return used, total, pct, label
        except Exception:
            pass
    return None


# ------------------------------ أيقونات الأقسام ------------------------------
ICON_RULES = (
    ("fast", "bolt"), ("panel", "panel"), ("tool", "tools"), ("cam", "key"),
    ("audio", "audio"), ("sub", "cc"), ("epg", "epg"), ("iptv", "tv"),
    ("skin", "skin"), ("setting", "settings"), ("media", "media"),
    ("channel", "dish"), ("picon", "picon"), ("boot", "power"), ("logo", "power"),
    ("image", "disc"), ("spinner", "spinner"), ("feed", "rss"),
    ("backup", "backup"), ("restore", "restore"), ("other", "puzzle"),
)
_icon_cache = {}


def get_icon(cat_name):
    n = cat_name.lower()
    key = "grid"
    if n.startswith("search:"):
        key = "search"
    else:
        for word, icon in ICON_RULES:
            if word in n:
                key = icon
                break
    
    if key not in _icon_cache:
        path = os.path.join(PLUGIN_DIR, "icons", key + ".png")
        if os.path.isfile(path):
            try:
                _icon_cache[key] = LoadPixmap(path)
            except Exception:
                _icon_cache[key] = None
        else:
            _icon_cache[key] = None
    return _icon_cache[key]


# --------------------------------- الشاشة الرئيسية ---------------------------
def main_skin():
    return u'''
<screen name="MajorEnigmaPanel" position="0,0" size="%(W)d,%(H)d" flags="wfNoBorder" backgroundColor="%(bg)s">
  <eLabel position="0,0" size="%(W)d,%(hh)d" backgroundColor="%(card)s" zPosition="0"/>
  <eLabel position="0,%(hl)d" size="%(W)d,%(lw)d" backgroundColor="%(acc)s" zPosition="1"/>
  <!-- العنوان الجديد واسم المطور -->
  <widget name="title" %(r_title)s font="Regular;%(f46)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <widget name="developer" %(r_dev)s font="Regular;%(f28)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <!-- حالة السيرفر والمعلومات الإجمالية -->
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
  
  <!-- RAM Progress -->
  <widget name="b_ram" %(r_bram)s font="Regular;%(f22)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <eLabel %(r_track)s backgroundColor="%(line)s" cornerRadius="%(cr3)d" zPosition="2"/>
  <widget name="ram_fill" %(r_fill)s font="Regular;%(f22)d" backgroundColor="%(acc)s" cornerRadius="%(cr3)d" transparent="0" zPosition="3"/>
  
  <!-- HDD Progress (بدلاً من الحرارة) -->
  <widget name="b_hdd" %(r_bhdd)s font="Regular;%(f22)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <eLabel %(r_track_hdd)s backgroundColor="%(line)s" cornerRadius="%(cr3)d" zPosition="2"/>
  <widget name="hdd_fill" %(r_fill_hdd)s font="Regular;%(f22)d" backgroundColor="%(acc)s" cornerRadius="%(cr3)d" transparent="0" zPosition="3"/>

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
        # تعديل قياسات الهيدر لتناسب العنوان الجديد والمطور
        r_title=rect(60, 20, 550, 70), r_dev=rect(610, 20, 350, 70), r_source=rect(960, 20, 900, 70),
        r_card1=rect(40, 135, 420, 800), r_cats=rect(55, 150, 390, 770),
        r_card2=rect(485, 135, 800, 800), r_items=rect(500, 150, 770, 770),
        # --- البطاقة العلوية: تفاصيل الإضافة ---
        r_card3=rect(1310, 135, 570, 430),
        r_dcat=rect(1340, 153, 360, 40), r_dcount=rect(1700, 153, 150, 40),
        r_dname=rect(1340, 198, 510, 100), r_dauthor=rect(1340, 302, 510, 40),
        r_sep=rect(1340, 352, 510, 2),
        r_ddeschd=rect(1340, 364, 510, 34), r_ddesc=rect(1340, 402, 510, 150),
        # --- البطاقة السفلية: معلومات الجهاز (تعديل لتناسب HDD) ---
        r_card4=rect(1310, 585, 570, 350),
        r_bmodel=rect(1340, 598, 510, 42), r_bpic=rect(1340, 645, 510, 115),
        r_bimage=rect(1340, 766, 510, 34),
        # RAM pos
        r_bram=rect(1340, 800, 510, 30), r_track=rect(1340, 832, 510, 10), r_fill=rect(1340, 832, 4, 10),
        # HDD pos
        r_bhdd=rect(1340, 855, 510, 30), r_track_hdd=rect(1340, 887, 510, 10), r_fill_hdd=rect(1340, 887, 4, 10),
        
        r_b1=rect(40, 955, 440, 66), r_b2=rect(500, 955, 440, 66),
        r_b3=rect(960, 955, 440, 66), r_b4=rect(1420, 955, 460, 66),
        r_hint=rect(40, 1030, 1840, 40),
    )


class MajorEnigmaPanel(Screen):
    def __init__(self, session):
        self.skin = main_skin()
        Screen.__init__(self, session)
        self.setTitle(TITLE)

        self["title"] = Label(TITLE)
        self["developer"] = Label(DEVELOPER)
        self["source"] = Label("") # سيعرض: Server [Online/Offline] Category [X] Order [Y]
        self["cats"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        self["items"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        for name, big, small, h in (("cats", 28, 24, 84), ("items", 34, 26, 100)):
            lst = self[name].l
            lst.setFont(0, gFont("Regular", s(big)))
            lst.setFont(1, gFont("Regular", s(small)))
            lst.setItemHeight(s(h))

        self["d_cat"] = Label("")
        self["d_count"] = Label("")
        self["d_name"] = Label("")
        self["d_author"] = Label("")
        self["d_desc_h"] = Label(u"شرح الإضافة")
        self["d_desc"] = Label("")
        
        self["b_model"] = Label("")
        self["box_pic"] = Pixmap()
        self["b_image"] = Label("")
        # RAM
        self["b_ram"] = Label("")
        self["ram_fill"] = Label("")
        # HDD
        self["b_hdd"] = Label("")
        self["hdd_fill"] = Label("")

        self["key_red"] = Label(u"خروج")
        self["key_green"] = Label(u"تثبيت")
        self["key_yellow"] = Label(u"بحث")
        self["key_blue"] = Label(u"تحديث البانل")
        self["hint"] = Label("LEFT/RIGHT: category  UP/DOWN: select  OK: install  BLUE: update panel  MENU: refresh")

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "EPGSelectActions", "MenuActions"],
            {
                "ok": self.askInstall, "green": self.askInstall,
                "cancel": self.exit, "red": self.exit,
                "yellow": self.search,
                "blue": self.askUpdate, "info": self.askUpdate,
                "menu": self.refresh,
                "left": self.prevCat, "right": self.nextCat,
                "up": self.up, "down": self.down,
            }, -1)

        self.allcats = []
        self.cats = []
        self.catIdx = 0
        self.query = ""
        self.is_online = False

        self.statTimer = eTimer()
        try:
            self.statTimer.callback.append(self.updateStats)
        except AttributeError:
            self._statConn = self.statTimer.timeout.connect(self.updateStats)
        self.onClose.append(self.statTimer.stop)
        self.onLayoutFinish.append(self.start)

    def start(self):
        self.showBoxInfo()
        self.updateStats()
        self.statTimer.start(5000, False)
        remove_old_cache()
        self.updateHeaderStatus(u"جارٍ الاتصال...")
        self.refresh()

    def refresh(self):
        self.updateHeaderStatus(u"جارٍ التحديث...")
        d = deferToThread(load_online)
        d.addCallback(self.onlineOK)
        d.addErrback(self.onlineFail)

    def onlineOK(self, result):
        self.is_online = True
        text, _ = result
        self.setData(text)

    def onlineFail(self, failure):
        self.is_online = False
        if not self.allcats:
            self.updateHeaderStatus(u"خطأ اتصال")
        else:
            self.updateSourceLabel() # لتحديث كلمة Online إلى Offline

    def setData(self, text):
        try:
            data = parse_commands(text)
        except Exception as e:
            self.updateHeaderStatus("Parse error")
            return
        keepCat = self.cats[self.catIdx][0] if self.cats else None
        self.allcats = data
        self.buildView(keepCat)

    def updateHeaderStatus(self, msg):
        """تحديث مؤقت للمعلومات في الهيدر أثناء التحميل"""
        self["source"].setText(u"Server [%s] • Major Enigma Panel" % msg)

    def updateSourceLabel(self):
        """تحديث السطر العلوي بالصيغة المطلوبة: Server Online/Offline Category [X] Order [Y]"""
        status = u"Online" if self.is_online else u"Offline"
        color = C_GREEN if self.is_online else C_RED
        
        total_items = sum(len(items) for _, items in self.allcats)
        
        text = u"Server %s  •  Category %d  •  Order %d" % (
            status, len(self.allcats), total_items)
        
        self["source"].setText(text)
        # لتلوين كلمة Online/Offline نحتاج ميزة skin srollable label أو تعديل skin engine
        # حالياً نغير لون النص بالكامل بناءً على الحالة
        setColor(self["source"], color if not self.is_online else C_MUTED)

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
            # RAM
            used, total = get_meminfo()
            if total:
                pct = used * 100.0 / total
                self["b_ram"].setText("RAM: %d / %d MB (%d%%)" % (used, total, pct))
                inst = self["ram_fill"].instance
                if inst:
                    inst.resize(eSize(max(s(4), int(s(510) * pct / 100.0)), s(10)))
                    color = C_GREEN if pct < 75 else (C_YELLOW if pct < 90 else C_RED)
                    inst.setBackgroundColor(parseColor(color))
            
            # HDD (بدلاً من الحرارة)
            hdd = get_hdd_info()
            inst_h = self["hdd_fill"].instance
            if hdd:
                used_g, total_g, pct_g, label = hdd
                self["b_hdd"].setText("%s: %d / %d GB (%d%%)" % (label, used_g, total_g, pct_g))
                if inst_h:
                    inst_h.resize(eSize(max(s(4), int(s(510) * pct_g / 100.0)), s(10)))
                    setColor(self["b_hdd"], C_TEXT)
                    inst_h.show()
            else:
                self["b_hdd"].setText(u"الهارد الخارجي: غير متصل")
                setColor(self["b_hdd"], C_MUTED)
                if inst_h:
                    inst_h.hide()
                    
        except Exception:
            pass

    def buildView(self, keepCat=None):
        if self.query:
            q = self.query.lower()
            hits = [it for c, items in self.allcats for it in items
                    if q in (u"%s %s %s %s" % (it["name"], it["author"], it["desc"], c)).lower()]
            self.cats = [(u"Search: %s" % self.query, hits)]
        else:
            self.cats = self.allcats
        
        self.updateSourceLabel() # تحديث العدادات العلوية
        
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
            self["d_desc"].setText(u"لا توجد نتائج" if self.query else "")
            return
        total = len(self.cats[self.catIdx][1])
        self["d_cat"].setText(it["cat"])
        self["d_count"].setText("%d / %d" % (self["items"].getSelectionIndex() + 1, total))
        self["d_name"].setText(it["name"])
        self["d_author"].setText((u"by " + it["author"]) if it["author"] else "")
        self["d_desc"].setText(it["desc"] or u"—")

    def prevCat(self): self.moveCat(-1)
    def nextCat(self): self.moveCat(1)
    def moveCat(self, step):
        if len(self.cats) < 2: return
        self.catIdx = (self.catIdx + step) % len(self.cats)
        self["cats"].moveToIndex(self.catIdx)
        self.fillItems()

    def up(self):
        self["items"].up()
        self.updateDetails()

    def down(self):
        self["items"].down()
        self.updateDetails()

    def search(self):
        self.session.openWithCallback(self.searchDone, VirtualKeyBoard,
                                      title=u"بحث (اتركه فارغاً للإلغاء)", text=self.query)

    def searchDone(self, text=None):
        if text is None: return
        self.query = text.strip()
        self.buildView()

    def askInstall(self):
        it = self.current()
        if not it: return
        self.session.openWithCallback(
            self.confirmed, MessageBox,
            u"%s\n\nتنفيذ التثبيت الآن؟" % it["name"],
            MessageBox.TYPE_YESNO)

    def confirmed(self, answer):
        it = self.current()
        if answer and it:
            self.session.open(RunScreen, it)

    def askUpdate(self):
        self.session.openWithCallback(
            self.confirmUpdate, MessageBox,
            u"تحديث Major Enigma Panel بالكامل؟",
            MessageBox.TYPE_YESNO)

    def confirmUpdate(self, answer):
        if answer:
            self.session.open(RunScreen, {"name": u"تحديث البانل",
                                          "cmd": UPDATE_CMD, "author": "", "desc": "", "cat": ""})

    def exit(self):
        self.close()


# --------------------------------- شاشة التنفيذ ------------------------------
def run_skin():
    return u'''
<screen name="MajorEnigmaRun" position="0,0" size="%(W)d,%(H)d" flags="wfNoBorder" backgroundColor="%(bg)s">
  <eLabel position="0,0" size="%(W)d,%(hh)d" backgroundColor="%(card)s" zPosition="0"/>
  <eLabel position="0,%(hl)d" size="%(W)d,%(lw)d" backgroundColor="%(acc)s" zPosition="1"/>
  <widget name="title" %(r_title)s font="Regular;%(f46)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <eLabel %(r_card)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <!-- Console log -->
  <widget name="log" %(r_log)s font="Console;%(f24)d" foregroundColor="#C9D1D9" backgroundColor="%(card)s" scrollbarMode="showOnDemand" zPosition="2"/>
  
  <widget name="status" %(r_status)s font="Regular;%(f34)d" foregroundColor="#D29922" backgroundColor="%(bg)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="key_red" %(r_b1)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(red)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_green" %(r_b2)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(green)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
</screen>''' % dict(
        W=_W, H=_H, bg=C_BG, card=C_CARD, acc=C_ACCENT, red=C_RED, green=C_GREEN,
        hh=s(110), hl=s(106), lw=max(2, s(4)), cr=s(24), cr2=s(16),
        f24=s(24), f26=s(26), f30=s(30), f34=s(34), f46=s(46),
        r_title=rect(60, 20, 1800, 70),
        r_card=rect(40, 135, 1840, 715), r_log=rect(65, 155, 1790, 675),
        r_status=rect(40, 865, 1840, 70),
        r_b1=rect(40, 955, 900, 66), r_b2=rect(980, 955, 900, 66))


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
MAX_LINES = 500


class RunScreen(Screen):
    def __init__(self, session, item):
        self.skin = run_skin()
        Screen.__init__(self, session)
        self.item = item
        self.lines = []
        self.partial = ""
        self.cr = False
        self.done = False

        self["title"] = Label(item["name"])
        self["log"] = ScrollLabel("")
        self["status"] = Label(u"جارٍ التنفيذ...")
        self["key_red"] = Label(u"إيقاف")
        self["key_green"] = Label("")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "red": self.onRed, "cancel": self.onRed,
                "green": self.onGreen, "ok": self.onGreen,
                "up": self["log"].pageUp, "down": self["log"].pageDown,
            }, -1)

        self.container = eConsoleAppContainer()
        self._conns = []
        # استقبال stdout و stderr لعرض كل المخرجات (التيرمنال)
        for sig, cb in (("appClosed", self.finished), ("dataAvail", self.onData),
                        ("stderrAvail", self.onData)):
            try:
                getattr(self.container, sig).append(cb)
            except AttributeError:
                # صور قديمة تستخدم connect
                self._conns.append(getattr(self.container, sig).connect(cb))
        
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def feed(self, text):
        # إزالة أكواد الألوان ANSI للحفاظ على نظافة السجل
        text = ANSI_RE.sub("", text)
        for part in re.split(r"(\r\n|\n|\r)", text):
            if part == "": continue
            if part == "\r":
                self.cr = True
            elif part in ("\n", "\r\n"):
                self.lines.append(self.partial)
                self.partial = ""
                self.cr = False
            else:
                if self.cr: # شريط تقدم: استبدل السطر الحالي
                    self.partial = ""
                    self.cr = False
                self.partial += part
        if len(self.lines) > MAX_LINES:
            del self.lines[:-MAX_LINES]

    def render(self):
        text = "\n".join(self.lines + [self.partial])
        self["log"].setText(text)
        try:
            self["log"].lastPage()
        except Exception:
            pass

    def start(self):
        setColor(self["status"], "#D29922")
        self.feed(u"Major Enigma Panel - Terminal\n---------------------------\n\n")
        self.render()
        # تنفيذ الأمر. مخرجات التيرمنال ستظهر عبر dataAvail
        self.container.execute(self.item["cmd"])

    def onData(self, data):
        if isinstance(data, bytes):
            data = data.decode("utf-8", "ignore")
        self.feed(data)
        self.render()

    def finished(self, retval):
        if self.done: return
        self.done = True
        self.feed(u"\n\n--- Finished (Exit code: %s) ---\n" % retval)
        self.render()
        self["key_red"].setText(u"إغلاق")
        if retval == 0:
            self["status"].setText(u"تم بنجاح")
            setColor(self["status"], "#3FB950")
            self["key_green"].setText(u"إعادة تشغيل الواجهة")
        else:
            self["status"].setText(u"انتهى بخلل")
            setColor(self["status"], "#F85149")

    def onRed(self):
        if not self.done:
            try: self.container.kill()
            except Exception: pass
            self.finished(-1)
        else:
            self.close()

    def onGreen(self):
        if self.done and self["key_green"].getText():
            self.session.openWithCallback(
                self.restartAnswer, MessageBox,
                u"إعادة تشغيل الواجهة الآن؟", MessageBox.TYPE_YESNO)

    def restartAnswer(self, answer):
        if answer:
            self.session.open(TryQuitMainloop, 3)

    def cleanup(self):
        try:
            if not self.done: self.container.kill()
        except Exception: pass
        for sig in ("appClosed", "dataAvail", "stderrAvail"):
            try: del getattr(self.container, sig)[:]
            except Exception: pass


# -------------------------- تعاريف السكرول ليبل -----------------------------
try:
    from Components.ScrollLabel import ScrollLabel
except ImportError:
    # لصور قديمة جداً لا تحتوي على ScrollLabel افتراضياً
    from Components.HTMLComponent import HTMLComponent
    from enigma import eLabel

    class ScrollLabel(HTMLComponent, eLabel):
        def __init__(self, text=""):
            HTMLComponent.__init__(self)
            eLabel.__init__(self, self.session)
            self.setText(text)
        def setText(self, text):
            eLabel.setText(self, text)
        def pageUp(self): pass
        def pageDown(self): pass
        def lastPage(self): pass


# --------------------------------- التسجيل -----------------------------------
def main(session, **kwargs):
    session.open(MajorEnigmaPanel)


def Plugins(**kwargs):
    # استخدام plugin.png إذا وجد، وإلا فلا أيقونة
    icon = "plugin.png" if os.path.isfile(os.path.join(PLUGIN_DIR, "plugin.png")) else None
    kw = {"icon": icon} if icon else {}
    
    # تحويل الوصف لعربية لملائمة الـ Menu في OpenATV
    desc = u"لوحة متطورة لأوامر لينوكس - By John Kamel"
    
    return [
        # WHERE_PLUGINMENU للعرض في قائمة البلجنات (الأخضر)
        PluginDescriptor(name=TITLE, description=desc,
                         where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main, **kw),
        # WHERE_MENU للعرض في قائمة Menu الرئيسية (المطلوب في الصورة)
        PluginDescriptor(name=TITLE, description=desc,
                         where=PluginDescriptor.WHERE_MENU, fnc=main_menu),
    ]

# -------------------------- الإظهار في القائمة الرئيسية -------------------------
def main_menu(menuid, **kwargs):
    # menuid == "mainmenu" هي القائمة الرئيسية في OpenATV
    if menuid == "mainmenu":
        # الإرجاع عبارة عن قائمة من التوبل: (الاسم، الفانكشن، المعرف الفريد، الترتيب)
        return [(TITLE, main_menu_open, "major_enigma_panel", 10)] # ترتيب 10 ليظهر في الأعلى قليلاً
    return []

def main_menu_open(session, **kwargs):
    session.open(MajorEnigmaPanel)
