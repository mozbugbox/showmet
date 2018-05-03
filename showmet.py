#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et
"""
Play media playlist with mpv player
"""

from __future__ import print_function, unicode_literals, absolute_import, division
import sys
import os
import io
import logging

import re
import time
import pathlib
import threading
import collections

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, GObject, Gtk, Gio

import videoplayer

__version__ = "0.1"

APPNAME_FULL = "ShowMeT"
APPNAME = APPNAME_FULL.lower()
APPID = "{}.{}.{}".format("org", "mozbugbox", APPNAME )

NATIVE=sys.getfilesystemencoding()
CACHE_NAME = "{}-list.js".format(APPNAME)
USER_CHAN_NAME = "{}-user-list.tvlist".format(APPNAME)
CACHE_LIFE = 24 * 60 * 60

import platform
if platform.system() == "Windows":
    APPDATA_PATH = pathlib.Path(os.getenv("LOCALAPPDATA"))/APPNAME
else:
    HOME = pathlib.Path.home()
    APPDATA_PATH = HOME/".local/share"/APPNAME
CHANNEL_PATH = APPDATA_PATH/CACHE_NAME
USER_CHAN_PATH = APPDATA_PATH/USER_CHAN_NAME

LIVE_CHANNEL_URL = "https://raw.githubusercontent.com/mozbugbox/showmet/master/showmet-list.js"

GMARGIN = 2
COL_CH_NAME, COL_CH_URL = range(2)

def checksum_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()

def sec2str(seconds):
    h, s = divmod(seconds, 3600)
    m, s = divmod(s, 60)
    res = []
    if int(h) > 0:
        res.append("{:02d}".format(int(h)))
    res.append("{:02d}".format(int(m)))
    res.append("{:05.2f}".format(s))
    return ":".join(res)

class ChannelInfo(collections.OrderedDict):
    """Hold a list of unique urls for a channel"""
    def __init__(self, channel_name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = channel_name
        self._index = 0

    @property
    def url(self):
        return self[self._index]

    @property
    def pos(self):
        """Position of current index"""
        return self._index

    def find(self, url):
        """Find the position of the given url"""
        res = list(keys()).find(url)
        return res

    def next(self):
        self._index += 1
        if self._index >= len(self):
            self._index = 0
        return self.url

    def __getitem__(self, key):
        if not isinstance(key, int):
            raise ValueError("key need to be int")
        v = list(self.keys())[self._index]
        self._index = key
        return v

    def append(self, val):
        super().__setitem__(val, 1)

class StationDict(collections.OrderedDict):
    """defaultdict calls default_factory with key"""
    def __init__(self, name, default_factory, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name
        self.default_factory = default_factory
        self.current_channel = None

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        v = self.default_factory(key)
        self[key] = v
        return v

class OrderedDefaultDict(collections.OrderedDict):
    def __init__(self, default_factory, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_factory = default_factory

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        v = self.default_factory()
        self[key] = v
        return v

PROVINCES = [
        "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
        "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
        "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
        "甘肃", "青海", "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆",
        "香港", "澳门", "台湾"
        ]
province_pat = re.compile("({})".format("|".join(PROVINCES)))

class StationManager(GObject.GObject):
    __gsignals__ = {
            "added": (GObject.SIGNAL_RUN_FIRST, None, (str,))
            }

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.stations = collections.OrderedDict()
        self.file_checksum = {}

    def log(self, msg):
        self.app.log(msg)

    @property
    def channel_path(self):
        path = CHANNEL_PATH
        return path

    def add_station(self, station):
        if station.name not in self.stations:
            self.emit("added", station.name)
        self.stations[station.name] = station

    def import_channel_list(self, name, channel_list):
        """Import channel_list into a StationDict"""
        station = StationDict(name, ChannelInfo)
        for k, v in channel_list:
            k = k.strip()
            station[k].append(v.strip())
        return station

    def load_user_channels(self):
        # Always load user channels first
        ch_path = USER_CHAN_PATH
        try:
            with io.open(ch_path, encoding="UTF-8") as fh:
                lines = fh.readlines()
            import tvlist2json
            channel_list = tvlist2json.parse_tvlist(lines)
            station = self.import_channel_list("User", channel_list)
            self.log("Loaded user channels from {}".format(ch_path))
            self.add_station(station)
        except IOError as e:
            log.warn("File: {}\n  {}".format(ch_path, e))
            import traceback
            log.debug("{}".format(traceback.format_exc()))
            #raise

    def categorize(self, name, channel_list):
        stations = OrderedDefaultDict(list)
        for k in [name, "CCTV", "卫视"]:
            stations[k] = list()
        for data in channel_list:
            k = data[0].lower()
            if k.startswith(("cctv", "cetv", "cgtn")):
                stations["CCTV"].append(data)
            elif k.endswith(("卫视", "卫视hd")):
                stations["卫视"].append(data)
            else:
                m = province_pat.search(k)
                if m is not None:
                    prov = m.group(1)
                    stations[prov].append(data)
                else:
                    stations[name].append(data)
        return stations

    def load_channels_from_file(self, fname, station_name):
        json_head_re = re.compile(r"(^[^\[]*|[^\]]*$)")

        try:
            with io.open(fname, "rb") as fh:
                content = fh.read()

            checksum = checksum_bytes(content)
            self.file_checksum[fname] = checksum
            content = content.decode("UTF-8").strip()

            import json
            content = json_head_re.sub("", content)
            channel_list = json.loads(content)
            channel_list_grouped = self.categorize(station_name, channel_list)
            for k, data in channel_list_grouped.items():
                station = self.import_channel_list(k, data)
                self.add_station(station)
            self.log("Loaded channels from {}".format(fname))
        except (IOError, ValueError) as e:
            log.warn("File: {}\n  {}".format(fname, e))
            import traceback
            log.debug("{}".format(traceback.format_exc()))
            #raise

    def load_channels(self):
        self.load_user_channels()

        do_update = False
        if self.channel_path.exists():
            path = self.channel_path
            mtime = path.stat().st_mtime
            delta = time.time() - mtime
            log.debug("Cache life: {}".format(sec2str(delta)))
            if (delta) >= CACHE_LIFE:
                do_update = True
        else:
            path = pathlib.Path(sys.argv[0]).absolute().with_name(CACHE_NAME)
            self.channel_path.parent.mkdir(mode=0o700,
                    parents=True, exist_ok=True)
            import shutil
            shutil.copy(path, self.channel_path)
            do_update = True

        self.load_channels_from_file(path, "General")

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
            content = req.content
            if content:
                checksum = checksum_bytes(content)
                if checksum == self.file_checksum.get(self.channel_path, -1):
                    self.log("Live channel unchanged.")
                    return

                with io.open(self.channel_path, "wb") as fhw:
                    fhw.write(content)
                defer(self.load_channels_from_file,
                        self.channel_path, "General")
            else:
                self.log(f"Failed to get Channel data: {r.status_code}")
        t = threading.Thread(target=_fetch_channel)
        t.daemon = True
        t.start()

defer = GLib.idle_add

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

class AppWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_ui()
        defer(self.load_rest)

    def load_rest(self):
        """delay load"""
        self.station_man = StationManager(self)
        self.station_man.connect("added", self.on_station_added)
        self.station_man.load_channels()
        self.combobox_station.set_active(0)
        self.install_actions()

        self.player = videoplayer.VideoPlayer(self)
        self.player.start_proc_monitor()

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

        combobox_station = Gtk.ComboBoxText()
        combobox_station.props.hexpand = True
        hid = combobox_station.connect("changed",
                self.on_combobox_station_changed)
        combobox_station.changed_hid = hid

        chan_grid = Gtk.Grid()
        chan_grid.attach(combobox_station, 0, 0, 1, 1)
        chan_grid.attach(sw_channel, 0, 1, 1, 1)

        logger = Logger()
        logger.props.can_focus = False
        logger.props.margin = GMARGIN

        paned1 = Gtk.HPaned()
        paned1.props.position = 160
        paned1.add1(chan_grid)
        paned1.add2(logger)
        grid.attach(paned1, 0, 0, 1, 1)
        grid.show_all()
        self.add(grid)

        hb = self.setup_header_bar()
        self.set_titlebar(hb)
        self.load_accels()

        self.tree_channel = tree
        self.combobox_station = combobox_station
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
        cbox_source.props.tooltip_text = "Switch Source <Ctrl+\u2192>"
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

    def install_actions(self):
        actions = ["move_down", "move_up"]
        for a_name in actions:
            action = Gio.SimpleAction.new(a_name, None)
            action.connect("activate", getattr(self, f"on_{a_name}"))
            self.add_action(action)

    def load_accels(self):
        """Load shortcut/hotkeys"""
        accel_maps = [
                ["win.move_down", ["j", "n"]],
                ["win.move_up", ["k", "b"]],
                ["app.player_stop", ["<Control>s"]],
                ["app.play_next_source", ["<Control>Right"]],
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

    @property
    def current_station(self):
        station_name = self.combobox_station.get_active_text()
        station = None
        if station_name is not None:
            station = self.station_man.stations[station_name]
        return station

    @property
    def current_channel(self):
        return self.current_station.current_channel

    @current_channel.setter
    def current_channel(self, v):
        self.current_station.current_channel = v

    def on_move_down(self, action, param):
        self.tree_channel.emit("move-cursor",
                Gtk.MovementStep.DISPLAY_LINES, 1)

    def on_move_up(self, action, param):
        self.tree_channel.emit("move-cursor",
                Gtk.MovementStep.DISPLAY_LINES, -1)

    def on_combobox_source_changed(self, cbox):
        idx = cbox.get_active()
        current_idx = self.current_channel.pos
        if idx != current_idx:
            self.play_nth_source(idx)

    def channel_at(self, cursor):
        model = self.tree_channel.get_model()
        row = model[cursor]
        chan_id = row[COL_CH_NAME]
        ch = self.current_station[chan_id]
        return ch

    def on_tree_row_activated(self, tree, path, col):
        if path is None:
            return

        ch = self.channel_at(path)
        self.current_channel = ch
        cbox = self.combobox_source
        cbox.handler_block(cbox.changed_hid)
        cbox.remove_all()
        for i in range(len(ch)):
            cbox.append(None, str(i+1))
        cbox.handler_unblock(cbox.changed_hid)

        self.play_channel(ch)

    def play_channel(self, ch, idx=None):
        """@ch: a ChannelInfo"""
        try:
            chan_url = ch.url if idx is None else ch[idx]
            self.player.play_url(chan_url, ch.name)

            cbox = self.combobox_source
            cbox.handler_block(cbox.changed_hid)
            cbox.set_active(ch.pos)
            cbox.handler_unblock(cbox.changed_hid)
        except KeyError:
            pass

    def on_station_added(self, station_man, name):
        cbox = self.combobox_station
        cbox.handler_block(cbox.changed_hid)
        cbox.append(None, name)
        cbox.handler_unblock(cbox.changed_hid)

        if cbox.get_active_text() == name:
            cbox.emit("changed")

    def on_combobox_station_changed(self, cbox):
        if self.current_station is not None:
            self.fill_channel_tree(self.current_station.keys())

    def fill_channel_tree(self, channel_names):
        model = self.tree_channel.get_model()
        path, col = self.tree_channel.get_cursor()
        if path:
            chname = model[path][COL_CH_NAME]

        self.tree_channel.freeze_child_notify()
        model.clear()
        for cid in channel_names:
            model.append([cid,])
        self.tree_channel.thaw_child_notify()

        # reset cursor
        if path and chname == model[path][COL_CH_NAME]:
            self.tree_channel.set_cursor(path, None, False)
        else:
            path = "0"
            if self.current_channel:
                chname = self.current_channel.name
                for row in model:
                    if row[COL_CH_NAME] == chname:
                        path = row.path
                        break
            self.tree_channel.set_cursor(path, None, False)

    def player_stop(self):
        self.player.stop()

    def play_next_source(self):
        ch = self.current_channel
        try:
            if ch.url != ch.next():
                self.play_channel(self.current_channel)
        except IndexError:
            pass

    def play_nth_source(self, nth):
        self.play_channel(self.current_channel, nth)

    def update_live_channel(self):
        self.station_man.update_live_channel()

    def close(self):
        self.player.ttys.restore()

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

        self.install_actions()
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

    def do_shutdown(self):
        log.debug("shutdown")
        self.window.close()
        Gtk.Application.do_shutdown(self)

    def install_actions(self):
        actions = ["player_stop", "play_next_source", "refresh_channel",
                "about", "quit"]
        for a_name in actions:
            action = Gio.SimpleAction.new(a_name, None)
            action.connect("activate", getattr(self, f"on_{a_name}"))
            self.add_action(action)

    def on_about(self, action, param):
        dlg = Gtk.AboutDialog(transient_for=self.window, modal=True)
        dlg.props.version = __version__
        dlg.props.authors = ["mozbugbox"]
        dlg.props.comments = __doc__.strip()
        dlg.props.license_type = Gtk.License.GPL_3_0
        dlg.props.copyright = (
            "Copyright 2014-2018 mozbugbox <mozbugbox@yahoo.com.au>"
            )
        dlg.connect("response", lambda x, resp: x.destroy())

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
    try:
        main()
    except KeyboardInterrupt:
        log.info("User interrupt")

