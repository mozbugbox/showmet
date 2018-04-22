#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et

from __future__ import print_function, unicode_literals, absolute_import, division
import sys
import os
import io
import time
import requests
import subprocess
import termios
import logging as log
from gi.repository import GLib

NATIVE=sys.getfilesystemencoding()

# DASH format got: HTTP error 400 Bad Request
#YOUTUBE_FORMAT = "bestvideo[height<720][vcodec=?vp9]+bestaudio[ext=webm]/best"
#YOUTUBE_FORMAT = "96/95/94/best"
YOUTUBE_FORMAT = "95/94/96/best"

def get_bin_path(bin_name):
    """Find the full path of command
    @bin_name: a executable string or a list of executables
    """
    pathes = os.environ["PATH"].split(":")

    src_dir = os.path.dirname(__file__)
    pathes.extend([src_dir, os.path.join(src_dir, 'bin')])

    if isinstance(bin_name, str):
        bin_name = [bin_name]
    for p in pathes:
        for bname in bin_name:
            full_path = os.path.join(p, bname)
            if os.path.exists(full_path):
                return full_path
    pstr = ", ".join(bin_name)
    raise ValueError("Failed to find one of commands: {}".format(pstr))

class TTYStat:
    """Save/restore tty state since mpv might failed to restore"""
    def __init__(self):
        self.tty_stat = self.save()

    def save(self):
        stat = None
        if sys.stdin.isatty():
            fd = sys.stdin.fileno()
            stat = termios.tcgetattr(fd)
        return stat

    def restore(self, stat=None):
        if stat is None:
            stat = self.tty_stat

        if stat is not None:
            fd = sys.stdin.fileno()
            termios.tcsetattr(fd, termios.TCSANOW, stat)

def setup_request_session(retry=3):
    """Setup a requests session"""
    rs = requests.Session()
    #return rs
    a = requests.adapters.HTTPAdapter(max_retries=retry)
    rs.mount("http://", a)
    rs.mount("https://", a)
    return rs
rsession = setup_request_session()

class VideoPlayer:
    """Video Player Class"""
    bin_list = ["mpv", "mplayer"]
    def __init__(self, app=None):
        self.app = app
        self.player = get_bin_path(self.bin_list)
        self.ts_player = None
        try:
            self.ts_player = get_bin_path(["ts-player", "ts-player.py"])
        except ValueError:
            pass
        self.proc = None
        self.proc_list = []
        self.youtube_format = YOUTUBE_FORMAT
        # FIXME: 30 is really too big for video streaming
        self.network_timeout = 30

        self.ttys = TTYStat()

    def log(self, *args):
        if self.app is not None and hasattr(self.app, "log"):
            self.app.log(*args)

    def url_is_ts(self, url):
        self.log("Checking for .ts: {}".format(url))
        resp = rsession.get(url, timeout=3.05, stream=True)
        #print(resp.url, resp.headers, resp.status_code)
        resp.close()
        content_type = resp.headers["content-type"].lower()
        ts_mime = "video/mp2t"
        ret = ts_mime in content_type
        if not ret:
            self.log("Not {}: {}: {}".format(ts_mime,
                content_type, resp.url))
        return ret

    def check_proc_list(self):
        """clean up state of process in the process list"""
        running = []
        for title, proc in self.proc_list:
            proc.poll()
            if proc.returncode is not None:
                self.log('({}) Stopped "{}" [{}]'.format(
                    proc.pid, title, proc.returncode))
            else:
                running.append((title, proc))
        self.proc_list = running
        return True

    def gen_ts_cmd(self, url, title):
        """return list of cmd to play url using ts-player.py"""
        cmd = None
        if self.ts_player:
            cmd = [self.ts_player]
            cmd += ["--title", title]
            cmd += [url]
        return cmd

    def gen_player_cmd(self, url, title):
        """return list of cmd to play url using player"""
        if url.startswith("rtmp://$OPT:rtmp-raw="):
            prefix, _, url = url.partition("=")

        cmd = None
        # prefer ts-player for .ts
        is_ts = False
        if url.endswith(".ts") and self.url_is_ts(url):
            is_ts = True
            cmd = self.gen_ts_cmd(url, title)
        if cmd:
            return cmd

        if "mpv" in self.player:
            cmd = [self.player,
                    "--cache-secs", "16",
                    "--network-timeout", str(self.network_timeout),
                    "--hls-bitrate", "2500000",
                    "--force-window=yes",
                  ]
            if "youtube." in url:
                cmd.extend(["--ytdl-format", self.youtube_format])

            # hack to keep .ts stream reloading
            if is_ts:
                cmd.extend(["--loop=inf"])

            cmd.extend(["--title", title, url])
        else:
            cmd = [self.player, "-cache-secs", "16"]
            cmd.extend(["-title", title, url])
        return cmd

    def play_url(self, url, title):
        """start to play a url"""
        self.stop()

        DETACHED_PROCESS = 0x00000008

        cmd = self.gen_player_cmd(url, title)
        cmd_str = " ".join(cmd)
        log.debug("cmd: {}".format(cmd_str))

        if sys.platform == "win32":
            p = subprocess.Popen(cmd,
                    #stdout=subprocess.DEVNULL,
                    creationflags=DETACHED_PROCESS)
        else:
            p = subprocess.Popen(cmd,
                    #stdout=subprocess.DEVNULL,
                    )
        self.log('({}) Play "{}"'.format(p.pid, title))
        self.log(cmd_str)
        self.proc = p
        self.proc_list.append((title, p))

    def stop(self, wait=False):
        """Stop current running player process"""
        if self.proc is not None:
            proc = self.proc
            try:
                proc.poll()
                if proc.returncode is None:
                    proc.terminate()
                time.sleep(0.1)
                proc.poll()
                if proc.returncode is None:
                    proc.kill()
                if wait:
                    print("Waiting process to stop")
                    proc.wait()
            except Exception as e:
                print("Exception: {}".format(e))
            finally:
                self.proc = None
                self.ttys.restore()
        self.check_proc_list()

    def start_proc_monitor(self):
        """Monitor running subprocesses"""
        GLib.timeout_add_seconds(1, self.check_proc_list)

def main():
    def set_stdio_encoding(enc=NATIVE):
        import codecs; stdio = ["stdin", "stdout", "stderr"]
        for x in stdio:
            obj = getattr(sys, x)
            if not obj.encoding: setattr(sys,  x, codecs.getwriter(enc)(obj))
    set_stdio_encoding()

    log_level = log.INFO
    log.basicConfig(format="%(levelname)s>> %(message)s", level=log_level)

if __name__ == '__main__':
    main()

