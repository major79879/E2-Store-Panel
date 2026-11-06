# -*- coding: utf-8 -*-
"""E2 Store Panel for Enigma2."""
import os
import re
import ssl
import time
from urllib.request import Request, urlopen

from enigma import (eConsoleAppContainer, eListboxPythonMultiContent, getDesktop,
                    gFont, eSize, eTimer, RT_HALIGN_LEFT, RT_HALIGN_RIGHT,
                    RT_VALIGN_CENTER)
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

TITLE = "E2 Store Panel"
COMMANDS_URL = "https://raw.githubusercontent.com/major79879/E2-Store-Panel/refs/heads/main/E2Store_Commands.lst"
INSTALLER_URL = "https://raw.githubusercontent.com/major79879/E2-Store-Panel/refs/heads/main/installer.sh"
UPDATE_CMD = 'wget -q --no-check-certificate -O - "%s" | /bin/sh -s norestart' % INSTALLER_URL
C_BG, C_CARD, C_LINE = "#0E1117", "#161B22", "#30363D"
C_TEXT, C_MUTED = "#E6EDF3", "#8B949E"
C_ACCENT, C_GREEN, C_RED, C_YELLOW = "#1F6FEB", "#238636", "#DA3633", "#D29922"
W = max(getDesktop(0).size().width(), 1280)
H = max(getDesktop(0).size().height(), 720)
SCALE = W / 1920.0


def s(value):
    return int(round(value * SCALE))


def rect(x, y, width, height):
    return 'position="%d,%d" size="%d,%d"' % (s(x), s(y), s(width), s(height))


def fetch_commands():
    ctx = ssl._create_unverified_context()
    req = Request(COMMANDS_URL + "?t=%d" % int(time.time()),
                  headers={"User-Agent": "E2Store/1.0", "Cache-Control": "no-cache"})
    text = urlopen(req, timeout=20, context=ctx).read().decode("utf-8", "ignore")
    if "+++" not in text:
        raise ValueError("Invalid commands list")
    return text


def read_meminfo():
    values = {}
    try:
        with open("/proc/meminfo", "r") as stream:
            for line in stream:
                key, _, value = line.partition(":")
                try:
                    values[key] = int(value.split()[0])
                except (ValueError, IndexError):
                    pass
    except IOError:
        return 0, 0
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable")
    if available is None:
        available = values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0)
    return max(total - available, 0) / 1024.0, total / 1024.0


def external_disk():
    """Return the first local block filesystem mounted below /media, if any."""
    found = []
    try:
        with open("/proc/mounts", "r") as stream:
            for line in stream:
                fields = line.split()
                if len(fields) < 3:
                    continue
                source, mountpoint, fstype = fields[:3]
                mountpoint = re.sub(r"\\([0-7]{3})",
                                    lambda match: chr(int(match.group(1), 8)), mountpoint)
                if (not mountpoint.startswith("/media/")
                        or mountpoint.startswith("/media/net/")
                        or not source.startswith("/dev/")
                        or fstype in ("nfs", "nfs4", "cifs", "smbfs")):
                    continue
                try:
                    stats = os.statvfs(mountpoint)
                    total = stats.f_blocks * stats.f_frsize
                    free = stats.f_bavail * stats.f_frsize
                    if total > 0:
                        found.append((mountpoint, total - free, total))
                except OSError:
                    pass
    except IOError:
        return None
    if not found:
        return None
    found.sort(key=lambda item: (0 if item[0] == "/media/hdd" else
                                 1 if os.path.basename(item[0]).lower().startswith("usb") else 2))
    return found[0]


def human_size(size):
    gb = size / float(1024 ** 3)
    return "%.1f GB" % gb if gb >= 1 else "%d MB" % (size / (1024 ** 2))


def main_skin():
    return '''
<screen name="E2Store" position="0,0" size="%(W)d,%(H)d" flags="wfNoBorder" backgroundColor="%(bg)s">
  <eLabel position="0,0" size="%(W)d,%(hh)d" backgroundColor="%(card)s" zPosition="0"/>
  <eLabel position="0,%(hl)d" size="%(W)d,%(lw)d" backgroundColor="%(acc)s" zPosition="1"/>
  <widget name="title" %(title)s font="Regular;%(f46)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <widget name="byline" %(byline)s font="Regular;%(f24)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <widget name="source" %(source)s font="Regular;%(f22)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="right" valign="center" zPosition="2"/>
  <eLabel %(catcard)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="cats" %(cats)s backgroundColor="%(card)s" backgroundColorSelected="%(acc)s" foregroundColor="%(text)s" foregroundColorSelected="#FFFFFF" scrollbarMode="showNever" zPosition="2"/>
  <eLabel %(itemcard)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="items" %(items)s backgroundColor="%(card)s" backgroundColorSelected="%(acc)s" foregroundColor="%(text)s" foregroundColorSelected="#FFFFFF" scrollbarMode="showOnDemand" zPosition="2"/>
  <eLabel %(detailcard)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="d_cat" %(dcat)s font="Regular;%(f26)d" foregroundColor="#58A6FF" backgroundColor="%(card)s" transparent="1" zPosition="2"/>
  <widget name="d_count" %(dcount)s font="Regular;%(f24)d" foregroundColor="%(muted)s" backgroundColor="%(card)s" transparent="1" halign="right" zPosition="2"/>
  <widget name="d_name" %(dname)s font="Regular;%(f38)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="top" zPosition="2"/>
  <widget name="d_author" %(dauthor)s font="Regular;%(f26)d" foregroundColor="#3FB950" backgroundColor="%(card)s" transparent="1" zPosition="2"/>
  <eLabel %(sep)s backgroundColor="%(line)s" zPosition="2"/>
  <widget name="d_desc" %(ddesc)s font="Regular;%(f28)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="right" valign="top" zPosition="2"/>
  <eLabel %(syscard)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="b_model" %(model)s font="Regular;%(f28)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="b_ram" %(ram)s font="Regular;%(f22)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <eLabel %(ramtrack)s backgroundColor="%(line)s" zPosition="2"/>
  <widget name="ram_fill" %(ramfill)s backgroundColor="%(acc)s" zPosition="3"/>
  <widget name="b_disk" %(disk)s font="Regular;%(f22)d" foregroundColor="%(text)s" backgroundColor="%(card)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <eLabel %(disktrack)s backgroundColor="%(line)s" zPosition="2"/>
  <widget name="disk_fill" %(diskfill)s backgroundColor="%(acc)s" zPosition="3"/>
  <widget name="key_red" %(redkey)s font="Regular;%(f26)d" foregroundColor="#FFFFFF" backgroundColor="%(red)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_green" %(greenkey)s font="Regular;%(f26)d" foregroundColor="#FFFFFF" backgroundColor="%(green)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_yellow" %(yellowkey)s font="Regular;%(f26)d" foregroundColor="#FFFFFF" backgroundColor="%(yellow)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_blue" %(bluekey)s font="Regular;%(f26)d" foregroundColor="#FFFFFF" backgroundColor="%(acc)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="hint" %(hint)s font="Regular;%(f20)d" foregroundColor="%(muted)s" backgroundColor="%(bg)s" transparent="1" halign="center" valign="center" zPosition="2"/>
</screen>''' % dict(
        W=W, H=H, bg=C_BG, card=C_CARD, line=C_LINE, text=C_TEXT, muted=C_MUTED,
        acc=C_ACCENT, red=C_RED, green=C_GREEN, yellow=C_YELLOW,
        hh=s(110), hl=s(106), lw=max(2, s(4)), cr=s(24), cr2=s(14),
        f20=s(20), f22=s(22), f24=s(24), f26=s(26), f28=s(28), f38=s(38), f46=s(46),
        title=rect(50, 18, 470, 72), byline=rect(530, 20, 560, 68),
        source=rect(1100, 20, 770, 68),
        catcard=rect(40, 135, 420, 800), cats=rect(55, 150, 390, 770),
        itemcard=rect(485, 135, 800, 800), items=rect(500, 150, 770, 770),
        detailcard=rect(1310, 135, 570, 430),
        dcat=rect(1340, 153, 340, 40), dcount=rect(1690, 153, 160, 40),
        dname=rect(1340, 198, 510, 100), dauthor=rect(1340, 302, 510, 40),
        sep=rect(1340, 352, 510, 2), ddesc=rect(1340, 370, 510, 180),
        syscard=rect(1310, 585, 570, 350), model=rect(1340, 600, 510, 46),
        ram=rect(1340, 680, 510, 36), ramtrack=rect(1340, 720, 510, 12),
        ramfill=rect(1340, 720, 4, 12), disk=rect(1340, 778, 510, 36),
        disktrack=rect(1340, 818, 510, 12), diskfill=rect(1340, 818, 4, 12),
        redkey=rect(40, 955, 440, 66), greenkey=rect(500, 955, 440, 66),
        yellowkey=rect(960, 955, 440, 66), bluekey=rect(1420, 955, 460, 66),
        hint=rect(40, 1030, 1840, 40))


class E2Store(Screen):
    def __init__(self, session):
        self.skin = main_skin()
        Screen.__init__(self, session)
        self.setTitle(TITLE)
        self["title"] = Label(TITLE)
        self["byline"] = Label("By John Kamel & Robin John")
        self["source"] = Label("Server ...  •  Category 0  •  Order 0")
        self["cats"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        self["items"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        for name, font_size, height in (("cats", 28, 84), ("items", 32, 96)):
            self[name].l.setFont(0, gFont("Regular", s(font_size)))
            self[name].l.setItemHeight(s(height))
        self["d_cat"] = Label("")
        self["d_count"] = Label("")
        self["d_name"] = Label("")
        self["d_author"] = Label("")
        self["d_desc"] = Label("")
        self["b_model"] = Label("Enigma2")
        self["b_ram"] = Label("")
        self["ram_fill"] = Label("")
        self["b_disk"] = Label("")
        self["disk_fill"] = Label("")
        self["key_red"] = Label("Exit")
        self["key_green"] = Label("Install")
        self["key_yellow"] = Label("Search")
        self["key_blue"] = Label("Update panel")
        self["hint"] = Label("LEFT/RIGHT: category   UP/DOWN: select   OK: install   MENU: refresh")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "EPGSelectActions", "MenuActions"],
            {"ok": self.askInstall, "green": self.askInstall, "cancel": self.close,
             "red": self.close, "yellow": self.search, "blue": self.askUpdate,
             "info": self.askUpdate, "menu": self.refresh,
             "left": lambda: self.move_category(-1), "right": lambda: self.move_category(1),
             "up": self.move_item_up, "down": self.move_item_down}, -1)
        self.allcats = []
        self.cats = []
        self.cat_index = 0
        self.query = ""
        self.online = None
        self["items"].onSelectionChanged.append(self.update_details)
        self.stats_timer = eTimer()
        try:
            self.stats_timer.callback.append(self.update_stats)
        except AttributeError:
            self.stats_timer.timeout.connect(self.update_stats)
        self.onClose.append(self.stats_timer.stop)
        self.onLayoutFinish.append(self.start)

    def start(self):
        self.stats_timer.start(3000, False)
        self.update_stats()
        self.refresh()

    def update_header(self):
        status = "Online" if self.online is True else "Offline" if self.online is False else "Connecting"
        count_categories = len(self.allcats)
        count_items = sum(len(items) for _, items in self.allcats)
        self["source"].setText("Server %s  •  Category %d  •  Order %d" %
                                (status, count_categories, count_items))

    def refresh(self):
        self.update_header()
        deferred = deferToThread(fetch_commands)
        deferred.addCallback(self.online_ok)
        deferred.addErrback(self.online_fail)

    def online_ok(self, text):
        try:
            data = parse_commands(text)
        except Exception as error:
            self["source"].setText("Parse error: %s" % error)
            return
        keep = self.cats[self.cat_index][0] if self.cats and self.cat_index < len(self.cats) else None
        self.allcats = data
        self.online = True
        self.update_header()
        self.build_view(keep)

    def online_fail(self, failure):
        self.online = False
        self.update_header()

    def update_stats(self):
        try:
            used, total = read_meminfo()
            if total:
                pct = min(100.0, used * 100.0 / total)
                self["b_ram"].setText("RAM   %d / %d MB   (%d%%)" % (used, total, pct))
                self["ram_fill"].instance.resize(eSize(max(s(4), int(s(510) * pct / 100)), s(12)))
                color = C_GREEN if pct < 75 else C_YELLOW if pct < 90 else C_RED
                self["ram_fill"].instance.setBackgroundColor(parseColor(color))
        except Exception:
            pass
        try:
            disk = external_disk()
            fill = self["disk_fill"].instance
            if disk:
                mountpoint, used, total = disk
                pct = min(100.0, used * 100.0 / total)
                label = os.path.basename(mountpoint) or mountpoint
                self["b_disk"].setText("External disk %s   %s / %s   (%d%%)" %
                                       (label, human_size(used), human_size(total), round(pct)))
                if fill:
                    fill.resize(eSize(max(s(4), int(s(510) * pct / 100)), s(12)))
                    color = C_GREEN if pct < 75 else C_YELLOW if pct < 90 else C_RED
                    fill.setBackgroundColor(parseColor(color))
            else:
                self["b_disk"].setText("External disk   N/A")
                if fill:
                    fill.resize(eSize(s(4), s(12)))
        except Exception:
            self["b_disk"].setText("External disk   N/A")

    def build_view(self, keep=None):
        if self.query:
            q = self.query.lower()
            matches = [(category, item) for category, items in self.allcats for item in items
                       if q in ("%s %s %s %s" % (item["name"], item["author"], item["desc"], category)).lower()]
            self.cats = [("Search: %s" % self.query, [item for _, item in matches])]
        else:
            self.cats = self.allcats
        self.cat_index = 0
        if keep:
            for index, (name, _) in enumerate(self.cats):
                if name == keep:
                    self.cat_index = index
                    break
        cat_rows = [[name, MultiContentEntryText(pos=(s(18), 0), size=(s(350), s(84)),
                    font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text="%s  (%d)" % (name, len(items)),
                    color=0xE6EDF3, color_sel=0xFFFFFF)] for name, items in self.cats]
        self["cats"].setList(cat_rows)
        self["cats"].moveToIndex(self.cat_index)
        self.fill_items()

    def fill_items(self):
        items = self.cats[self.cat_index][1] if self.cats and self.cat_index < len(self.cats) else []
        rows = []
        for item in items:
            rows.append([item,
                MultiContentEntryText(pos=(s(24), s(4)), size=(s(720), s(48)), font=0,
                    flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=item["name"],
                    color=0xE6EDF3, color_sel=0xFFFFFF),
                MultiContentEntryText(pos=(s(24), s(52)), size=(s(720), s(36)), font=0,
                    flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=item["author"] or item["cat"],
                    color=0x3FB950, color_sel=0xDDEEFF)])
        self["items"].setList(rows)
        if rows:
            self["items"].moveToIndex(0)
        self.update_details()

    def current_item(self):
        current = self["items"].getCurrent()
        return current[0] if current else None

    def update_details(self):
        item = self.current_item()
        if not item:
            for key in ("d_cat", "d_count", "d_name", "d_author"):
                self[key].setText("")
            self["d_desc"].setText("No results" if self.query else "")
            return
        total = len(self.cats[self.cat_index][1])
        self["d_cat"].setText(item["cat"])
        self["d_count"].setText("%d / %d" % (self["items"].getSelectionIndex() + 1, total))
        self["d_name"].setText(item["name"])
        self["d_author"].setText("by " + item["author"] if item["author"] else "")
        self["d_desc"].setText(item["desc"] or "—")

    def move_category(self, step):
        if len(self.cats) < 2:
            return
        self.cat_index = (self.cat_index + step) % len(self.cats)
        self["cats"].moveToIndex(self.cat_index)
        self.fill_items()

    def move_item_up(self):
        self["items"].up()
        self.update_details()

    def move_item_down(self):
        self["items"].down()
        self.update_details()

    def search(self):
        self.session.openWithCallback(self.search_done, VirtualKeyBoard,
                                      title="Search (leave empty to clear)", text=self.query)

    def search_done(self, text=None):
        if text is not None:
            self.query = text.strip()
            self.build_view()

    def askInstall(self):
        item = self.current_item()
        if item:
            self.session.openWithCallback(self.confirm_install, MessageBox,
                "%s\n\nInstall this item now?" % item["name"], MessageBox.TYPE_YESNO)

    def confirm_install(self, answer):
        item = self.current_item()
        if answer and item:
            self.session.open(RunScreen, item)

    def askUpdate(self):
        self.session.openWithCallback(self.confirm_update, MessageBox,
            "Update / reinstall the whole panel now?", MessageBox.TYPE_YESNO)

    def confirm_update(self, answer):
        if answer:
            self.session.open(RunScreen, {"name": "Update E2 Store Panel", "cmd": UPDATE_CMD})


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
URL_RE = re.compile(r"(?:https?|ftps?)://[^\s'\"<>]+", re.I)


class RunScreen(Screen):
    skin = '''
<screen name="E2StoreRun" position="0,0" size="%(W)d,%(H)d" flags="wfNoBorder" backgroundColor="%(bg)s">
  <eLabel position="0,0" size="%(W)d,%(hh)d" backgroundColor="%(card)s" zPosition="0"/>
  <eLabel position="0,%(hl)d" size="%(W)d,%(lw)d" backgroundColor="%(acc)s" zPosition="1"/>
  <widget name="title" %(title)s font="Regular;%(f38)d" foregroundColor="#FFFFFF" backgroundColor="%(card)s" transparent="1" valign="center" zPosition="2"/>
  <eLabel %(cardpos)s backgroundColor="%(card)s" cornerRadius="%(cr)d" zPosition="0"/>
  <widget name="log" %(logpos)s font="Regular;%(f22)d" foregroundColor="#C9D1D9" backgroundColor="%(card)s" scrollbarMode="showOnDemand" zPosition="2"/>
  <widget name="status" %(status)s font="Regular;%(f30)d" foregroundColor="%(yellow)s" backgroundColor="%(bg)s" transparent="1" halign="center" valign="center" zPosition="2"/>
  <widget name="key_red" %(red)s font="Regular;%(f26)d" foregroundColor="#FFFFFF" backgroundColor="%(redc)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
  <widget name="key_green" %(green)s font="Regular;%(f26)d" foregroundColor="#FFFFFF" backgroundColor="%(greenc)s" cornerRadius="%(cr2)d" halign="center" valign="center" zPosition="2"/>
</screen>''' % dict(
        W=W, H=H, bg=C_BG, card=C_CARD, acc=C_ACCENT, yellow=C_YELLOW,
        redc=C_RED, greenc=C_GREEN, hh=s(110), hl=s(106), lw=max(2, s(4)),
        cr=s(24), cr2=s(16), f22=s(22), f26=s(26), f30=s(30), f38=s(38),
        title=rect(60, 20, 1800, 70), cardpos=rect(40, 135, 1840, 715),
        logpos=rect(65, 155, 1790, 675), status=rect(40, 865, 1840, 70),
        red=rect(40, 955, 900, 66), green=rect(980, 955, 900, 66))

    def __init__(self, session, item):
        Screen.__init__(self, session)
        self.item = item
        self.lines = []
        self.partial = ""
        self.pending_cr = False
        self.done = False
        self["title"] = Label(item.get("name", "Running operation"))
        self["log"] = ScrollLabel("")
        self["status"] = Label("Running...")
        self["key_red"] = Label("Stop")
        self["key_green"] = Label("")
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"],
            {"red": self.stop, "cancel": self.stop, "green": self.restart,
             "ok": self.restart, "up": self["log"].pageUp, "down": self["log"].pageDown,
             "left": self["log"].pageUp, "right": self["log"].pageDown}, -1)
        self.container = eConsoleAppContainer()
        self.connections = []
        for signal_name, callback in (("appClosed", self.finished), ("dataAvail", self.on_data),
                                      ("stderrAvail", self.on_data)):
            try:
                signal = getattr(self.container, signal_name)
                try:
                    signal.append(callback)
                except AttributeError:
                    self.connections.append(signal.connect(callback))
            except AttributeError:
                pass
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def feed(self, text):
        text = ANSI_RE.sub("", text)
        for part in re.split(r"(\r\n|\n|\r)", text):
            if not part:
                continue
            if part == "\r":
                self.pending_cr = True
            elif part in ("\n", "\r\n"):
                self.lines.append(self.partial)
                self.partial = ""
                self.pending_cr = False
            else:
                if self.pending_cr:
                    self.partial = ""
                    self.pending_cr = False
                self.partial += part
        if len(self.lines) > 400:
            del self.lines[:-400]

    def render(self):
        # Show terminal output, but never print the command being launched.
        text = "\n".join(self.lines + [self.partial])
        text = URL_RE.sub("[link hidden]", text)
        self["log"].setText(text)
        try:
            self["log"].lastPage()
        except Exception:
            pass

    def start(self):
        self.feed("Running selected operation...\n\n")
        self.render()
        self.container.execute("exec 2>&1; " + self.item["cmd"])

    def on_data(self, data):
        if isinstance(data, bytes):
            data = data.decode("utf-8", "ignore")
        self.feed(data)
        self.render()

    def finished(self, code):
        if self.done:
            return
        self.done = True
        self.feed("\n\n--- finished (exit code %s) ---\n" % code)
        self.render()
        self["key_red"].setText("Close")
        if code == 0:
            self["status"].setText("Finished successfully")
            self["status"].instance.setForegroundColor(parseColor("#3FB950"))
            self["key_green"].setText("Restart GUI")
        else:
            self["status"].setText("Finished with code %s" % code)
            self["status"].instance.setForegroundColor(parseColor("#F85149"))

    def stop(self):
        if self.done:
            self.close()
        else:
            try:
                self.container.kill()
            except Exception:
                pass
            self.finished(-1)

    def restart(self):
        if self.done and self["key_green"].getText():
            self.session.openWithCallback(self.restart_answer, MessageBox,
                "Restart GUI now?", MessageBox.TYPE_YESNO)

    def restart_answer(self, answer):
        if answer:
            self.session.open(TryQuitMainloop, 3)

    def cleanup(self):
        if not self.done:
            try:
                self.container.kill()
            except Exception:
                pass
        for signal_name in ("appClosed", "dataAvail", "stderrAvail"):
            try:
                del getattr(self.container, signal_name)[:]
            except Exception:
                pass


def main(session, **kwargs):
    session.open(E2Store)


def Plugins(**kwargs):
    return [PluginDescriptor(name=TITLE, description="Modern Linux commands panel",
                             where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main),
            PluginDescriptor(name=TITLE, description="Modern Linux commands panel",
                             where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main)]
