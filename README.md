# showmet
Play list of videos from mpv with a GUI

## Depends
* mpv
* Python3
* Gtk+3
* Python GObject binding
* Python `Requests` Package

## Windows/Win32
* Install msys2: https://www.msys2.org/
* Install mpv: https://mpv.io/installation/
* Install Python3 Gtk+ binding: https://pygobject.readthedocs.io/en/latest/getting_started.html#windows-getting-started
* Install `python3-requests` package
* Add msys2 BIN path (for python3.exe) and mpv path to %PATH% environment
* Run `python3 showmet.py`

* Hide console: [pywrun.vbs](https://gist.github.com/mozbugbox/03d1ee3a8c2f48c29cd7a6a65aee8e8e)
* Update showmet from git: [update-showmet-git.sh](https://gist.github.com/mozbugbox/5d6234c3815dee869f2f6c4c0b019af0)

## Files

* User defined Channels: $USERDATA/showmet/showmet-user-list.tvlist

  $USERDATA:

  * Windows: %LOCALAPPDATA%
  * Linux: $HOME/.local/share

  Format: `channel_name|http://host/channel.m3u8`

* Channel Cache:

  * Windows: %LOCALAPPDATA%/showmet/showmet-list.js
  * Linux: $HOME/.cache/showmet/showmet-list.js

