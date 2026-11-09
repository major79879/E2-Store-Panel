# -*- coding: utf-8 -*-
"""Parser for LinuxCommands.lst  (no Enigma2 dependencies, can be tested anywhere).

Format:
## ====== +++ Category Name +++ ====== ##
## === # Plugin Name - Author # = # Arabic / English description # === ##
<command line(s)>
"""
import re

CAT_RE = re.compile(r'^##\s*=+\s*\+{3}\s*(.+?)\s*\+{3}\s*=+\s*##\s*$')
ITEM_RE = re.compile(r'^##\s*=+\s*#\s*(.+?)\s*#\s*=\s*#\s*(.*?)\s*#\s*=+\s*[#\s]*$')
ITEM_RE_NODESC = re.compile(r'^##\s*=+\s*#\s*(.+?)\s*#\s*=+\s*[#\s]*$')


def parse_commands(text):
    """Return [(category, [ {name, author, desc, cmd, cat}, ... ]), ...]"""
    text = text.lstrip(u"\ufeff")
    cats = []          # ordered list of [name, items]
    index = {}
    cur_cat = "Others"
    pending = None

    def flush():
        nonlocal pending
        if pending and pending["lines"]:
            pending["cmd"] = " ; ".join(pending["lines"])
            del pending["lines"]
            if cur_cat not in index:
                index[cur_cat] = len(cats)
                cats.append([cur_cat, []])
            pending["cat"] = cur_cat
            cats[index[cur_cat]][1].append(pending)
        pending = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = CAT_RE.match(line)
        if m:
            flush()
            cur_cat = m.group(1).strip()
            continue
        m = ITEM_RE.match(line)
        desc = None
        if m:
            title, desc = m.group(1), m.group(2)
        else:
            m = ITEM_RE_NODESC.match(line)
            if m:
                title, desc = m.group(1), ""
        if m:
            flush()
            if " - " in title:
                name, author = title.rsplit(" - ", 1)
            else:
                name, author = title, ""
            pending = {"name": name.strip(), "author": author.strip(),
                       "desc": desc.strip(), "lines": []}
            continue
        if line.startswith("#"):
            continue            # ordinary comment
        if pending is not None:
            pending["lines"].append(line)
    flush()
    return [(n, items) for n, items in cats if items]


if __name__ == "__main__":
    import sys
    data = open(sys.argv[1], encoding="utf-8").read()
    res = parse_commands(data)
    total = 0
    for n, items in res:
        total += len(items)
        print("%-20s %d" % (n, len(items)))
    print("TOTAL", total)
