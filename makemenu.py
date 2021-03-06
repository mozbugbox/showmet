#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et

from __future__ import unicode_literals, absolute_import, division
import sys
import os
import io
import logging

from xml.sax import saxutils
NATIVE = sys.getfilesystemencoding()

def fix_headerbar_menu(headerbar):
    """Show accelerators in Application on HeaderBar

    Gtk3 default to set use_popover for the MenuButton of the Application
    Menu. However use_popover will hide action accelerators. Try to fixit!
    """
    from gi.repository import Gtk, GLib
    timeout = 500
    res = True

    def _foreach(child):
        nonlocal res
        if not isinstance(child, Gtk.Container):
            return

        for kid in child.get_children():
            aname = kid.get_accessible().props.accessible_name
            if aname is not None and aname.lower() == "application menu":
                kid.props.use_popover = False
                res = False

    def _on_fix_timeout(wid):
        # has to call forall since the boxes in hb are internal
        log.debug("Fixing headerbar menu.")
        wid.forall(_foreach)
        return res

    # keep trying as menu might not be added to headerbar yet
    GLib.timeout_add(timeout, _on_fix_timeout, headerbar)

class MenuItem:
    """Menu item class for Gtk Builder UI interface"""
    def __init__(self, label, action, target=None, accel=None):
        self.action = saxutils.escape(action)
        self.label = saxutils.escape(label)
        self.target = None if target is None else saxutils.escape(target)
        self.accel = None if accel is None else saxutils.escape(accel)

    def __str__(self):
        res = ["<item>"]
        res.append(f'  <attribute name="action">{self.action}</attribute>')
        res.append(f'  <attribute name="label" translatable="yes">'
                f'{self.label}</attribute>')
        if self.target is not None:
            res.append(f'  <attribute name="target">{self.target}'
                    f'</attribute>')
        if self.accel is not None:
            res.append(f'  <attribute name="accel">{self.accel}</attribute>')
        res.append("</item>")
        return "\n".join(res)

class MenuSection:
    """Menu section class for Gtk Builder UI interface"""
    _header = ["<section>"]
    _tailer = ["</section>"]
    _indent = 2
    def __init__(self, label=None):
        self.label = None if label is None else saxutils.escape(label)
        self.subitems = []

    def append(self, item):
        """Append sub item to the section"""
        self.subitems.append(item)

    def do_label(self, res):
        """Handle the section label attribute"""
        if self.label is not None:
            res.append(f'  <attribute name="label" translatable="yes">'
                    f'{self.label}</attribute>')
        return res

    def __str__(self):
        res = [] + self._header
        self.do_label(res)

        for item in self.subitems:
            lines = str(item).splitlines()
            res += [" " * self._indent + line for line in lines]
        res = res + self._tailer
        return "\n".join(res)

class MenuUI(MenuSection):
    """Menu class for Gtk Builder UI interface"""
    _header = ['<?xml version="1.0" encoding="UTF-8"?>', "<interface>"]
    _tailer = ["  </menu>", "</interface>"]
    _indent = 4
    def do_label(self, res):
        """Handle the menu id attribute """
        label = "app-menu" if self.label is None else self.label
        res.append(f'  <menu id="{label}">')
        return res

def setup_app_menu_by_actions(action_names, parent=None):
    """Add actions to GtkApplication menu
    action_names = [action_fullname, ...]
    parent: can be GtkApplication, MenuButton or HeaderBar
    """
    menu_name = "app-menu"
    menu = MenuUI(menu_name)
    section = MenuSection()
    menu.append(section)
    for act in action_names:
        _, _, title = act.partition(".")
        label = title.replace("-", " ").title()
        item = MenuItem(label, act)
        section.append(item)

    if parent is not None:
        from gi.repository import Gtk
        builder = Gtk.Builder.new_from_string(str(menu), -1)
        menu_model = builder.get_object(menu_name)
        if isinstance(parent, Gtk.Application):
            parent.set_app_menu(menu_model)
        elif isinstance(parent, Gtk.MenuButton):
            parent.set_menu_model(menu_model)
        elif isinstance(parent, Gtk.HeaderBar):
            button = Gtk.MenuButton()
            button.props.valign = Gtk.Align.CENTER
            button.props.can_focus = False
            button.props.use_popover = False
            button.set_menu_model(menu_model)
            button.get_style_context().add_class("titlebutton")
            image = Gtk.Image.new_from_icon_name(
                    "open-menu-symbolic", Gtk.IconSize.MENU);
            button.add(image)
            button.show_all()
            parent.pack_end(button)

    return str(menu)

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

    menu = MenuUI()
    section = MenuSection("Section Top")
    menu.append(section)
    for i in range(10):
        item = MenuItem(f"menu{i}", f"win.action_menu{i}")
        section.append(item)

    print(menu)

if __name__ == '__main__':
    main()

