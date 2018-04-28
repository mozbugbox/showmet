#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et

from __future__ import print_function, unicode_literals, absolute_import, division
import sys
import os
import io
import logging
import pathlib
import json

NATIVE=sys.getfilesystemencoding()

def parse_tvlist(lines):
    result = []
    separation = list("|,，;；")
    for line in lines:
        if line.startswith("#"): continue
        line = line.strip()
        if len(line) == 0: continue
        for sep in separation:
            cid, s, src = line.partition(sep)
            if s: break
        if s:
            result.append([cid.strip(), src.strip()])

    return result

def setup_log(log_level=None):
    global log
    rlog = logging.getLogger()
    if __name__ == "__main__" and not rlog.hasHandlers():
        # setup root logger
        ch = logging.StreamHandler()
        formatter = logging.Formatter("%(levelname)s:%(name)s:: %(message)s")
        ch.setFormatter(formatter)
        rlog.addHandler(ch)

    log = logging.getLogger(__name__)

    if log_level is not None:
        log.setLevel(log_level)
        rlog.setLevel(log_level)
setup_log()

def main():
    def set_stdio_encoding(enc=NATIVE):
        import codecs; stdio = ["stdin", "stdout", "stderr"]
        for x in stdio:
            obj = getattr(sys, x)
            if not obj.encoding: setattr(sys, x, codecs.getwriter(enc)(obj))
    set_stdio_encoding()

    log_level = logging.INFO
    setup_log(log_level)

    fname = sys.argv[1]
    with io.open(fname, encoding="UTF-8") as fh:
        lines = fh.readlines()

    result = parse_tvlist(lines)

    if len(result) > 0:
        outpath = pathlib.Path(fname).with_suffix(".js")
        log.info("Write result to {}".format(outpath))
        with io.open(outpath, "w", encoding="UTF-8") as fhw:
            fhw.write("watchlist_data = ")
            fhw.write(json.dumps(result, indent=2, ensure_ascii=False))
            fhw.write(";")

if __name__ == '__main__':
    main()

