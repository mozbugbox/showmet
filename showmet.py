#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et

from __future__ import print_function, unicode_literals, absolute_import, division
import sys
import os
import io
import logging
import pathlib
import threading
import time
import collections

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gio

import videoplayer

__version__ = "0.1"

APPNAME_FULL = "ShowMeT"
APPNAME = APPNAME_FULL.lower()
APPID = "{}.{}.{}".format("org", "mozbugbox", APPNAME )

NATIVE=sys.getfilesystemencoding()
CACHE_NAME = "{}-list.js".format(APPNAME)
CACHE_LIFE = 24 * 60 * 60
import platform
if platform.system() == "Windows":
    CACHE_PATH = pathlib.Path(os.getenv("LOCALAPPDATA"))/APPNAME/CACHE_NAME
else:
    CACHE_PATH = pathlib.Path.home()/".cache"/APPNAME/CACHE_NAME

LIVE_CHANNEL_URL = "https://raw.githubusercontent.com/mozbugbox/showmet/master/showmet-list.js"

GMARGIN = 2
COL_CH_NAME, COL_CH_URL = range(2)

def _create_icon_image(icon_name, size=None):
    """Create Gtk image with stock icon"""
    if size is None:
        size = Gtk.IconSize.BUTTON
    icon = Gio.ThemedIcon(name=icon_name)
    image = Gtk.Image.new_from_gicon(icon, size)
    return image

def _create_icon_button(icon_name=None, tooltip=None, action=None,
        clicked=None):
    """Create Gtk button with stock icon"""
    bt = Gtk.Button()
    bt.props.can_focus = False
    if icon_name is not None:
        if isinstance(icon_name, Gtk.Image):
            image = icon_name
        else:
            image = _create_icon_image(icon_name)
        bt.set_image(image)
    if tooltip is not None:
        bt.props.tooltip_text = tooltip
    if action is not None:
        bt.props.action_name = action
    if clicked is not None:
        bt.connect("clicked", clicked)
    return bt

class Logger(Gtk.ScrolledWindow):
    def __init__(self, maxlen=64):
        """Logging Widget with a maxlen of line"""
        self.maxlen = maxlen

        Gtk.ScrolledWindow.__init__(self)
        self._textview = Gtk.TextView()
        self._textview.props.editable = False
        self._textview.props.can_focus = False
        self.add(self._textview)

        # need to get new size before we can scroll to the end.
        self._textview.connect("size-allocate", self._autoscroll)

    def log(self, text):
        """Add text to the log widget"""
        tbuf = self._textview.get_buffer()
        timestamp = time.strftime("%H:%M:%S")
        line = "[{}] {}".format(timestamp, text)

        # limit textbuffer size to maxlen
        line_count = tbuf.get_line_count()
        if  line_count >= self.maxlen:
            iter_start = tbuf.get_start_iter()
            iter_cut = tbuf.get_iter_at_line(line_count - self.maxlen + 1)
            tbuf.delete(iter_start, iter_cut)
        iter_end = tbuf.get_end_iter()
        tbuf.insert(iter_end, line + "\n")

    def _autoscroll(self, *args):
        """The actual scrolling method"""
        tv = self._textview
        tv.queue_draw()
        tbuf = tv.get_buffer()
        iter_end = tbuf.get_end_iter()
        tv.scroll_to_iter(iter_end, 0.0, True, 0.0, 1.0)
        return False

def sec2str(seconds):
    h, s = divmod(seconds, 3600)
    m, s = divmod(s, 60)
    res = []
    if int(h) > 0:
        res.append("{:02d}".format(int(h)))
    res.append("{:02d}".format(int(m)))
    res.append("{:05.2f}".format(s))
    return ":".join(res)

class ChannelURLs(list):
    """Hold a list of alternative urls for a channel"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._index = 0

    @property
    def url(self):
        return self[self._index]

    @property
    def index(self):
        return self._index

    def next(self):
        self._index += 1
        if self._index >= len(self):
            self._index = 0
        return self.url

    def __getitem__(self, key):
        v = super().__getitem__(key)
        self._index = key
        return v

class AppWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_channel_name = None
        self.channels = collections.defaultdict(ChannelURLs)
        self.setup_ui()
        self.defer(self.load_rest)

    def load_rest(self):
        """delay load"""
        self.load_channels()
        self.player = videoplayer.VideoPlayer(self)
        self.player.start_proc_monitor()

    def defer(self, *args, **kwargs):
        GLib.idle_add(*args, **kwargs)

    def setup_ui(self):
        self.resize(900, 800)
        theme = Gtk.IconTheme.get_default()
        logo_pixbuf = theme.load_icon("video-x-generic", 48, 0)
        self.set_default_icon(logo_pixbuf)

        grid = Gtk.Grid()

        store = Gtk.ListStore(str)
        tree = Gtk.TreeView(store)
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

        logger = Logger()
        logger.props.can_focus = False
        logger.props.margin = GMARGIN

        paned1 = Gtk.HPaned()
        paned1.props.position = 160
        paned1.add1(sw_channel)
        paned1.add2(logger)
        grid.attach(paned1, 0, 0, 1, 1)
        grid.show_all()
        self.add(grid)

        hb = self.setup_header_bar()
        self.set_titlebar(hb)
        self.load_accels()

        self.tree_channel = tree
        self.paned1 = paned1
        self.logger = logger

    def setup_header_bar(self):
        hb = Gtk.HeaderBar()
        hb.props.show_close_button = True
        hb.props.title = "ShowMeT"
        hb.props.has_subtitle = False

        button_player_stop = _create_icon_button(
                "media-playback-stop-symbolic", "Player Stop <Ctrl+s>",
                action="app.player_stop")
        button_refresh_channel = _create_icon_button(
                "view-refresh-symbolic", "Refresh Channel <Ctrl+r>",
                action="app.refresh_channel")
        button_about = _create_icon_button("help-about",
                "About", action="app.about")
        cbox_source = Gtk.ComboBoxText()
        cbox_source.props.tooltip_text = "Switch Source <Ctrl+n>"
        hid = cbox_source.connect("changed",
                self.on_combobox_source_changed)
        cbox_source.changed_hid = hid

        hb.pack_start(button_refresh_channel)
        hb.pack_start(button_player_stop)
        hb.pack_start(cbox_source)
        hb.pack_end(button_about)
        hb.show_all()
        self.combobox_source = cbox_source
        return hb

    def load_accels(self):
        """Load shortcut/hotkeys"""
        accel_maps = [
                ["app.player_stop", ["<Control>s"]],
                ["app.play_next_source", ["<Control>n"]],
                ["app.refresh_channel", ["<Control>r"]],
                ["app.help", ["F1"]],
                ["app.quit", ["<Control>q"]],
            ]

        gapp = self.get_application()
        for act, k in accel_maps:
            gapp.set_accels_for_action(act, k)

    def log(self, msg):
        """Log a message to the log window"""
        self.logger.log(msg)

    def on_tree_selection_changed(self, sel):
        model, treeiter = sel.get_selected()
        if treeiter is not None:
            chan_id, chan_src = model[treeiter]
            self.player.play_url(chan_src, chan_id)

    def on_combobox_source_changed(self, cbox):
        idx = cbox.get_active()
        current_idx = self.channels[self.current_channel_name].index
        if idx != current_idx:
            self.play_nth_source(idx)

    def on_tree_row_activated(self, tree, path, col):
        if path is None:
            return

        model = tree.get_model()
        row = model[path]
        chan_id = row[COL_CH_NAME]
        self.current_channel_name = chan_id

        ch = self.channels[chan_id]
        cbox = self.combobox_source
        cbox.handler_block(cbox.changed_hid)
        cbox.remove_all()
        for i in range(len(ch)):
            cbox.append(None, str(i+1))
        cbox.handler_unblock(cbox.changed_hid)

        self.play_channel(chan_id)

    def play_channel(self, name, idx=None):
        try:
            ch = self.channels[name]
            chan_url = ch.url if idx is None else ch[idx]
            self.player.play_url(chan_url, name)

            cbox = self.combobox_source
            cbox.handler_block(cbox.changed_hid)
            cbox.set_active(ch.index)
            cbox.handler_unblock(cbox.changed_hid)
        except KeyError:
            pass

    @property
    def cache_path(self):
        path = CACHE_PATH
        return path

    def load_channels(self):
        do_update = False
        if self.cache_path.exists():
            path = self.cache_path
            mtime = path.stat().st_mtime
            delta = time.time() - mtime
            log.debug("Cache life: {}".format(sec2str(delta)))
            if (delta) >= CACHE_LIFE:
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
        """Load channel from URL"""
        def _fetch_channel():
            time.sleep(.01)
            import requests
            url = LIVE_CHANNEL_URL
            self.log("Update Channel from {}...".format(url))
            req = requests.get(url, timeout=30)
            if req.text:
                with io.open(self.cache_path, "w", encoding="UTF-8") as fhw:
                    fhw.write(req.text)
                self.defer(self.load_channels_from_file, self.cache_path)
        t = threading.Thread(target=_fetch_channel)
        t.daemon = True
        t.start()

    def load_channels_from_file(self, fname):
        with io.open(fname, encoding="UTF-8") as fh:
            content = fh.read().strip()
            try:
                tag = " = "
                idx = content.index(" = ")
                import json
                content = content[idx+len(tag):].strip(";")
                channel_list = json.loads(content)
                self.channels.clear()
                channel_names = collections.OrderedDict()
                for k, v in channel_list:
                    k = k.strip()
                    self.channels[k].append(v.strip())
                    channel_names[k] = 1

                self.fill_channel_tree(channel_names.keys())
                self.log("Loaded channels from {}".format(fname))
            except ValueError as e:
                log.warn("{}".format(e))
                import traceback
                log.debug("{}".format(traceback.format_exc()))
                #raise

    def fill_channel_tree(self, channel_names):
        model = self.tree_channel.get_model()
        path, col = self.tree_channel.get_cursor()
        if path:
            chname = model[path][COL_CH_NAME]

        model.clear()
        for cid in channel_names:
            model.append([cid,])

        # reset cursor
        if path and chname == model[path][COL_CH_NAME]:
            self.tree_channel.set_cursor(path, None, False)
        else:
            self.tree_channel.set_cursor("0", None, False)

    def player_stop(self):
        self.player.stop()

    def play_next_source(self):
        ch = self.channels[self.current_channel_name]
        try:
            if ch.url != ch.next():
                self.play_channel(self.current_channel_name)
        except IndexError:
            pass

    def play_nth_source(self, nth):
        ch = self.channels[self.current_channel_name]
        self.play_channel(self.current_channel_name, nth)

class Application(Gtk.Application):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, application_id=APPID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
                         **kwargs)
        self.window = None

        self.add_main_option("debug", ord("D"), GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, "Debug mode", None)

    def do_startup(self):
        GLib.set_application_name(APPNAME_FULL)
        Gtk.Application.do_startup(self)

        actions = ["player_stop", "play_next_source", "refresh_channel",
                "about", "quit"]
        for a_name in actions:
            action = Gio.SimpleAction.new(a_name, None)
            action.connect("activate", getattr(self, f"on_{a_name}"))
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
        dlg = Gtk.AboutDialog(transient_for=self.window, modal=True)
        dlg.props.version = __version__
        dlg.props.authors = ["mozbugbox"]
        dlg.props.comments = "Play media playlist with mpv player"
        dlg.props.license_type = Gtk.License.GPL_3_0
        dlg.props.copyright = (
            "Copyright 2014-2018 mozbugbox <mozbugbox@yahoo.com.au>"
            )

        def _on_response(d, resp):
            d.destroy()
        dlg.connect("response", _on_response)

        dlg.present()

    def on_player_stop(self, action, param):
        self.window.player_stop()

    def on_play_next_source(self, action, param):
        self.window.play_next_source()

    def on_refresh_channel(self, action, param):
        self.window.update_live_channel()

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

