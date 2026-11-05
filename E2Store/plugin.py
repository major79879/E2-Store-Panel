# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
#  E2 Store  -  لوحة أوامر لينوكس بواجهة عصرية لـ Enigma2 (OpenATV 7.6 / 8)
#  Python 3 only.  يقرأ ملف LinuxCommands.lst من GitHub ويعرضه كأقسام وبطاقات.
# ---------------------------------------------------------------------------
import os
import re
import ssl
import time
from urllib.request import Request, urlopen

from enigma import (eConsoleAppContainer, eListboxPythonMultiContent, getDesktop,
                    gFont, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER)
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
from Components.ScrollLabel import ScrollLabel
from Plugins.Plugin import PluginDescriptor
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Standby import TryQuitMainloop
from Screens.VirtualKeyBoard import VirtualKeyBoard
from skin import parseColor
from twisted.internet.threads import deferToThread

from .lstparser import parse_commands

# ============================ الإعدادات / SETTINGS ===========================
# رابط ملف الأوامر على GitHub (عدّله لو اختلف المسار عندك)
COMMANDS_URL = "https://raw.githubusercontent.com/major79879/E2-Store-Panel/refs/heads/main/E2Store_Commands.lst"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = "/etc/enigma2/e2store_cache.lst"      # نسخة محفوظة تعمل بدون إنترنت
LOCAL_FILE = os.path.join(PLUGIN_DIR, "E2Store_Commands.lst")   # (اختياري) ملف مرفق مع البلجن
TITLE = "E2 Store Panel"

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


def _read(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def load_offline():
    for path, src in ((CACHE_FILE, "cache"), (LOCAL_FILE, "local")):
        if os.path.isfile(path):
            try:
                return _read(path), src
            except Exception:
                pass
    return None, None


def load_online():
    """Runs in a worker thread. Returns (text, 'online') or raises."""
    text = _fetch(COMMANDS_URL)
    if "+++" not in text:
        raise ValueError("bad file")
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    return text, "online"


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
  <widget name="d_name" %(r_dname)s font="Regular;%(f40)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="top" zPosition="2"/>
  <widget name="d_author" %(r_dauthor)s font="Regular;%(f28)d" foregroundColor="#3FB950" backgroundColor="%(card)s" transparent="1" zPosition="2"/>
  <eLabel %(r_sep)s backgroundColor="%(line)s" zPosition="2"/>
  <widget name="d_desc" %(r_ddesc)s font="Regular;%(f30)d" foregroundColor="#C9D1D9" backgroundColor="%(card)s" transparent="1" halign="right" scrollbarMode="showNever" zPosition="2"/>
  <widget name="d_cmd_h" %(r_dcmdh)s font="Regular;%(f24)d" foregroundColor="#58A6FF" backgroundColor="%(card)s" transparent="1" zPosition="2"/>
  <widget name="d_cmd" %(r_dcmd)s font="Regular;%(f22)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" zPosition="2"/>

  <widget name="key_red" %(r_b1)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(red)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_green" %(r_b2)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(green)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_yellow" %(r_b3)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(yellow)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_blue" %(r_b4)s font="Regular;%(f30)d" foregroundColor="#FFFFFF" backgroundColor="%(acc)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="hint" %(r_hint)s font="Regular;%(f22)d" foregroundColor="%(muted)s" backgroundColor="%(bg)s" transparent="1" halign="center" valign="center" zPosition="2"/>
</screen>''' % dict(
        W=_W, H=_H, bg=C_BG, card=C_CARD, line=C_LINE, text=C_TEXT, muted=C_MUTED, acc=C_ACCENT,
        red=C_RED, green=C_GREEN, yellow=C_YELLOW,
        hh=s(110), hl=s(106), lw=max(2, s(4)), cr=s(24), cr2=s(16),
        f22=s(22), f24=s(24), f26=s(26), f28=s(28), f30=s(30), f40=s(40), f46=s(46),
        r_title=rect(60, 20, 900, 70), r_source=rect(960, 20, 900, 70),
        r_card1=rect(40, 135, 420, 800), r_cats=rect(55, 150, 390, 770),
        r_card2=rect(485, 135, 800, 800), r_items=rect(500, 150, 770, 770),
        r_card3=rect(1310, 135, 570, 800),
        r_dcat=rect(1340, 155, 360, 40), r_dcount=rect(1700, 155, 150, 40),
        r_dname=rect(1340, 205, 510, 120), r_dauthor=rect(1340, 330, 510, 44),
        r_sep=rect(1340, 385, 510, 2),
        r_ddesc=rect(1340, 400, 510, 250),
        r_dcmdh=rect(1340, 665, 510, 36), r_dcmd=rect(1340, 705, 510, 215),
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
        for name, big, small, h in (("cats", 32, 26, 84), ("items", 34, 26, 100)):
            lst = self[name].l
            lst.setFont(0, gFont("Regular", s(big)))
            lst.setFont(1, gFont("Regular", s(small)))
            lst.setItemHeight(s(h))

        self["d_cat"] = Label("")
        self["d_count"] = Label("")
        self["d_name"] = Label("")
        self["d_author"] = Label("")
        self["d_desc"] = ScrollLabel("")
        self["d_cmd_h"] = Label("Command")
        self["d_cmd"] = Label("")
        self["key_red"] = Label(u"خروج | Exit")
        self["key_green"] = Label(u"تثبيت | Install")
        self["key_yellow"] = Label(u"بحث | Search")
        self["key_blue"] = Label(u"تحديث | Refresh")
        self["hint"] = Label("LEFT / RIGHT : category     UP / DOWN : select     OK : install     "
                             "INFO : full command")

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "EPGSelectActions"],
            {
                "ok": self.askInstall, "green": self.askInstall,
                "cancel": self.exit, "red": self.exit,
                "yellow": self.search, "blue": self.refresh,
                "left": self.prevCat, "right": self.nextCat,
                "up": self.up, "down": self.down,
                "info": self.showCommand,
            }, -1)

        self.allcats = []       # [(cat, [items])]
        self.cats = []          # current view (all or search results)
        self.catIdx = 0
        self.query = ""
        self.srcInfo = ""
        self.onLayoutFinish.append(self.start)

    # ----------------------------- تحميل ------------------------------------
    def start(self):
        text, src = load_offline()
        if text:
            self.setData(text, src)
        else:
            self["source"].setText(u"جارٍ التحميل... | Loading...")
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
            self["source"].setText(u"فشل التحميل - تحقق من الإنترنت | Download failed")
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
            {"online": "Online", "cache": "Cached", "local": "Local"}.get(src, src),
            len(data), u"أقسام", total, u"أمر")
        self["source"].setText(self.srcInfo)
        self.buildView(keepCat)

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
            rows.append([n,
                         MultiContentEntryText(pos=(s(20), 0), size=(s(280), s(84)), font=0,
                                               flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=n,
                                               color=0xE6EDF3, color_sel=0xFFFFFF),
                         MultiContentEntryText(pos=(s(300), 0), size=(s(70), s(84)), font=1,
                                               flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER,
                                               text=str(len(items)),
                                               color=0x8B949E, color_sel=0xFFFFFF)])
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
            for k in ("d_cat", "d_count", "d_name", "d_author", "d_cmd"):
                self[k].setText("")
            self["d_desc"].setText(u"لا توجد نتائج | No results" if self.query else "")
            return
        total = len(self.cats[self.catIdx][1])
        self["d_cat"].setText(it["cat"])
        self["d_count"].setText("%d / %d" % (self["items"].getSelectionIndex() + 1, total))
        self["d_name"].setText(it["name"])
        self["d_author"].setText((u"by " + it["author"]) if it["author"] else "")
        self["d_desc"].setText(it["desc"])
        cmd = it["cmd"]
        self["d_cmd"].setText(cmd if len(cmd) <= 230 else cmd[:227] + "...")

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
    def showCommand(self):
        it = self.current()
        if it:
            self.session.open(MessageBox, it["cmd"], MessageBox.TYPE_INFO)

    def askInstall(self):
        it = self.current()
        if not it:
            return
        self.session.openWithCallback(
            self.confirmed, MessageBox,
            u"%s\n\nتنفيذ هذا الأمر الآن؟\nRun this command now?" % it["name"],
            MessageBox.TYPE_YESNO)

    def confirmed(self, answer):
        it = self.current()
        if answer and it:
            self.session.open(RunScreen, it)

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
LOG_LIMIT = 14000


class RunScreen(Screen):
    def __init__(self, session, item):
        self.skin = run_skin()
        Screen.__init__(self, session)
        self.item = item
        self.log = ""
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
        try:
            self.container.appClosed.append(self.finished)
            self.container.dataAvail.append(self.onData)
        except AttributeError:
            self._c1 = self.container.appClosed.connect(self.finished)
            self._c2 = self.container.dataAvail.connect(self.onData)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def start(self):
        setColor(self["status"], "#D29922")
        self.container.execute(self.item["cmd"])

    def onData(self, data):
        if isinstance(data, bytes):
            data = data.decode("utf-8", "ignore")
        data = ANSI_RE.sub("", data).replace("\r\n", "\n").replace("\r", "\n")
        self.log = (self.log + data)[-LOG_LIMIT:]
        self["log"].setText(self.log)
        try:
            self["log"].lastPage()
        except Exception:
            pass

    def finished(self, retval):
        if self.done:
            return
        self.done = True
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
        try:
            del self.container.appClosed[:]
            del self.container.dataAvail[:]
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
