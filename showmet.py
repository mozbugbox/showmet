#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et

from __future__ import print_function, unicode_literals, absolute_import, division
import sys
import os
import io
import logging
import pathlib
import threading
import datetime
import time

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gio

import videoplayer

NATIVE=sys.getfilesystemencoding()

CACHE_LIFE = 24 * 60 * 60
CACHE_NAME = "showmet-list.js"
import platform
if platform.system() == "Windows":
    CACHE_PATH = pathlib.Path(os.getenv("LOCALAPPDATA")) / CACHE_NAME
else:
    CACHE_PATH = pathlib.Path.home() /".cache"/"showmet"/ CACHE_NAME

LIVE_CHANNEL_URL = ""

COL_CH_NAME, COL_CH_URL = range(2)

class AppWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_ui()
        self.defer(self.load_rest)

    def load_rest(self):
        self.load_channels()
        self.player = videoplayer.VideoPlayer(self)
        self.player.start_proc_monitor()

    def defer(self, *args, **kwargs):
        GLib.idle_add(*args, **kwargs)

    def setup_ui(self):
        self.resize(200, 800)
        grid = self.grid_main = Gtk.Grid()
        self.add(grid)

        store = Gtk.ListStore(str, str)
        self.tree_channel = tree = Gtk.TreeView(store)
        sw_channel = Gtk.ScrolledWindow()
        sw_channel.add(tree)
        sw_channel.props.expand = True

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Channel", renderer, text=COL_CH_NAME)
        tree.append_column(column)

        tree.connect("row-activated", self.on_tree_row_activated)

        """
        select = tree.get_selection()
        select.connect("changed", self.on_tree_selection_changed)
        """


        grid.attach(sw_channel, 0, 0, 1, 1)
        grid.show_all()

    def on_tree_selection_changed(self, sel):
        model, treeiter = sel.get_selected()
        if treeiter is not None:
            chan_id, chan_src = model[treeiter]
            self.player.play_url(chan_src, chan_id)

    def on_tree_row_activated(self, tree, path, col):
        model = tree.get_model()
        if path is not None:
            row = model[path]
            chan_src = row[COL_CH_URL]
            chan_id = row[COL_CH_NAME]
            self.player.play_url(chan_src, chan_id)

    @property
    def cache_path(self):
        path = CACHE_PATH
        return path

    def load_channels(self):
        do_update = False
        if self.cache_path.exists():
            path = self.cache_path
            mtime = path.stat().st_mtime
            if (time.time() - mtime) >= CACHE_LIFE:
                do_update = True
        else:
            path = pathlib.Path(sys.argv[0]).absolute().with_name(CACHE_NAME)
            self.cache_path.parent.mkdir(mode=0o700,
                    parents=True, exist_ok=True)
            import shutil
            shutil.copy(path, self.cache_path)
            do_update = True
        self.load_channels_from_file(path)
        if do_update:
            self.update_live_channel()

    def update_live_channel(self):
        def _fetch_channel():
            time.sleep(.01)
            import requests
            req = requests.get(LIVE_CHANNEL_URL, timeout=30)
            if req.content:
                with io.open(self.cache_path, "w") as fhw:
                    fhw.write(req.content)
                self.defer(self.load_channels_from_file, self.cache_path)
        t = threading.Thread(target=_fetch_channel)
        t.daemon = True
        t.start()

    def load_channels_from_file(self, fname):
        with io.open(fname) as fh:
            content = fh.read().strip()
            try:
                tag = " = "
                idx = content.index(" = ")
                import json
                content = content[idx+len(tag):].strip(";")
                channel_list = json.loads(content)
                self.load_channel_list(channel_list)
            except ValueError as e:
                log.warn("{}".format(e))
                import traceback
                log.debug("{}".format(traceback.format_exc()))
                #raise

    def load_channel_list(self, channel_list):
        model = self.tree_channel.get_model()
        model.clear()
        for cid, src in channel_list:
            model.append([cid, src])


class Application(Gtk.Application):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, application_id="org.mozbugbox.showmet",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
                         **kwargs)
        self.window = None

        self.add_main_option("debug", ord("D"), GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, "Debug mode", None)

    def do_startup(self):
        Gtk.Application.do_startup(self)

        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.on_about)
        self.add_action(action)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)

        #builder = Gtk.Builder.new_from_string(MENU_XML, -1)
        #self.set_app_menu(builder.get_object("app-menu"))

    def do_activate(self):
        # We only allow a single window and raise any existing ones
        if not self.window:
            # Windows are associated with the application
            # when the last one is closed the application shuts down
            self.window = AppWindow(application=self, title="Show Me T")

        self.window.present()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()

        if options.contains("debug"):
            # This is printed on the main instance
            setup_log(logging.DEBUG)

        self.activate()
        return 0

    def on_about(self, action, param):
        about_dialog = Gtk.AboutDialog(transient_for=self.window, modal=True)
        about_dialog.present()

    def on_quit(self, action, param):
        self.quit()

def setup_log(log_level=None):
    global log
    rlog = logging.getLogger()
    if __name__ == "__main__" and not rlog.hasHandlers():
        # setup root logger
        ch = logging.StreamHandler()
        formatter = logging.Formatter(
                "%(levelname)s:%(name)s@%(lineno)s:: %(message)s")
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

    app = Application()
    app.run(sys.argv)

if __name__ == '__main__':
    import signal; signal.signal(signal.SIGINT, signal.SIG_DFL)
    main()

