#!/usr/bin/python3 -I
"""fi-osk — a Windows-style on-screen keyboard for KDE Plasma (Wayland), Finnish layout.

Security model:
  * Keystrokes are injected only through the XDG RemoteDesktop portal, which makes
    Plasma ask the user for permission. No root, no /dev/uinput, no background daemon.
  * The keyboard is a layer-shell surface with keyboard interactivity NONE: it can never
    receive keyboard focus, so it never sees what you type on the physical keyboard.
  * Nothing is logged, nothing touches the network. The only file written is the
    portal "restore token" (mode 0600) so permission is remembered; use --no-remember
    to disable that.

Usage:  fi-osk            toggle the keyboard (starts it if not running)
        fi-osk --quit     quit the running keyboard
"""
import os
import sys

# gtk4-layer-shell must be loaded before libwayland; re-exec with LD_PRELOAD if needed.
LAYER_LIB = "libgtk4-layer-shell.so.0"
if LAYER_LIB not in os.environ.get("LD_PRELOAD", ""):
    env = dict(os.environ)
    env["LD_PRELOAD"] = (LAYER_LIB + " " + env.get("LD_PRELOAD", "")).strip()
    os.execve(sys.executable, [sys.executable, "-I", os.path.abspath(__file__)] + sys.argv[1:], env)

import secrets

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
try:
    gi.require_version("Gtk4LayerShell", "1.0")
except ValueError:
    sys.exit("fi-osk: gtk4-layer-shell is missing. Install it with: sudo dnf install gtk4-layer-shell")
gi.require_foreign("cairo")
import cairo  # noqa: E402
from gi.repository import Gdk, Gio, GLib, Graphene, Gtk, Gtk4LayerShell as LayerShell  # noqa: E402

APP_ID = "io.github.fiosk.Keyboard"
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "fi-osk")
TOKEN_FILE = os.path.join(STATE_DIR, "restore-token")

# ---------------------------------------------------------------------------
# Layout: Finnish (fi, winkeys). Each key: (evdev keycode, width in key units,
# base, shift, altgr). The compositor applies your real keymap, so the labels
# below are only for display; Finnish characters come out exactly as on a
# physical Finnish keyboard (including dead keys ´ ` ¨ ^ ~).
# ---------------------------------------------------------------------------
L = lambda code, base, shift=None, altgr=None, w=1.0: (code, w, base, shift if shift is not None else base.upper(), altgr)  # noqa: E731

KEY_LSHIFT, KEY_RSHIFT, KEY_LCTRL, KEY_RCTRL = 42, 54, 29, 97
KEY_LALT, KEY_ALTGR, KEY_META, KEY_CAPS = 56, 100, 125, 58
MODIFIERS = {KEY_LSHIFT: "shift", KEY_RSHIFT: "shift", KEY_LCTRL: "ctrl", KEY_RCTRL: "ctrl",
             KEY_LALT: "alt", KEY_ALTGR: "altgr", KEY_META: "meta"}
MOD_KEYCODE = {"shift": KEY_LSHIFT, "ctrl": KEY_LCTRL, "alt": KEY_LALT, "altgr": KEY_ALTGR, "meta": KEY_META}

FUNCTION_ROW = [L(1, "Esc", "Esc")] + [L(c, f"F{i}", f"F{i}") for i, c in
                                       enumerate([59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 87, 88], 1)]

MAIN_ROWS = [
    [L(41, "§", "½"), L(2, "1", "!"), L(3, "2", '"', "@"), L(4, "3", "#", "£"), L(5, "4", "¤", "$"),
     L(6, "5", "%", "€"), L(7, "6", "&"), L(8, "7", "/", "{"), L(9, "8", "(", "["), L(10, "9", ")", "]"),
     L(11, "0", "=", "}"), L(12, "+", "?", "\\"), L(13, "´", "`"), L(14, "⌫ Backspace", "⌫ Backspace", w=2)],
    [L(15, "⇥ Tab", "⇥ Tab", w=1.5), L(16, "q"), L(17, "w"), L(18, "e", altgr="€"), L(19, "r"), L(20, "t"),
     L(21, "y"), L(22, "u"), L(23, "i"), L(24, "o"), L(25, "p"), L(26, "å"), L(27, "¨", "^", "~")],
    [L(KEY_CAPS, "Caps", "Caps", w=1.5), L(30, "a"), L(31, "s"), L(32, "d"), L(33, "f"), L(34, "g"),
     L(35, "h"), L(36, "j"), L(37, "k"), L(38, "l"), L(39, "ö"), L(40, "ä"), L(43, "'", "*")],
    [L(KEY_LSHIFT, "⇧ Shift", "⇧ Shift", w=1.25), L(86, "<", ">", "|"), L(44, "z"), L(45, "x"), L(46, "c"),
     L(47, "v"), L(48, "b"), L(49, "n"), L(50, "m", altgr="µ"), L(51, ",", ";"), L(52, ".", ":"),
     L(53, "-", "_"), L(KEY_RSHIFT, "⇧ Shift", "⇧ Shift", w=2.75)],
    [L(KEY_LCTRL, "Ctrl", "Ctrl", w=1.5), L(KEY_META, "⊞ Meta", "⊞ Meta", w=1.25), L(KEY_LALT, "Alt", "Alt", w=1.25),
     L(57, " ", " ", w=7), L(KEY_ALTGR, "AltGr", "AltGr", w=1.25), L(127, "☰", "☰", w=1.25),
     L(KEY_RCTRL, "Ctrl", "Ctrl", w=1.5)],
]
ENTER = L(28, "↵ Enter", "↵ Enter", w=1.5)  # ISO Enter, spans rows 2-3

# Navigation cluster: (row, col, key)
NAV_KEYS = [
    (0, 0, L(110, "Ins", "Ins")), (0, 1, L(102, "Home", "Home")), (0, 2, L(104, "PgUp", "PgUp")),
    (1, 0, L(111, "Del", "Del")), (1, 1, L(107, "End", "End")), (1, 2, L(109, "PgDn", "PgDn")),
    (3, 1, L(103, "↑", "↑")),
    (4, 0, L(105, "←", "←")), (4, 1, L(108, "↓", "↓")), (4, 2, L(106, "→", "→")),
]

CSS = """
window.fiosk { background: transparent; }
.panel { background: rgba(28, 30, 34, 0.94); border-radius: 12px; padding: 6px;
         border: 1px solid rgba(255,255,255,0.08); }
.key { background: #3a3d44; border-radius: 6px; margin: 2px; color: #f2f2f2; }
.key:hover { background: #4a4e57; }
.key.down { background: #2f6fd6; }
.key.latched { background: #2b5797; }
.key.locked { background: #2f6fd6; box-shadow: inset 0 -3px #9cc3ff; }
.key .main { font-size: 1.15em; }
.key .hint { font-size: 0.7em; color: #9aa3b0; margin: 2px 5px 0 0; }
.key.wide .main { font-size: 0.9em; }
.titlebar { margin-bottom: 2px; }
.title { color: #9aa3b0; font-size: 0.85em; margin: 0 8px; }
.ctl { background: #2a2c31; border-radius: 6px; margin: 2px; color: #cfd3da; min-width: 0; min-height: 0; padding: 0; }
.ctl:hover { background: #3e4149; }
.ctl.close:hover { background: #c42b1c; color: white; }
.status { color: #ffb454; font-size: 0.85em; margin: 0 8px; }
"""


class Portal:
    """Minimal client for org.freedesktop.portal.RemoteDesktop (keyboard only)."""

    BUS = "org.freedesktop.portal.Desktop"
    PATH = "/org/freedesktop/portal/desktop"
    IFACE = "org.freedesktop.portal.RemoteDesktop"

    def __init__(self, remember, on_state):
        self.remember = remember
        self.on_state = on_state  # callback(str|None): status message, None when ready
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.session = None
        self.ready = False
        self.starting = False

    # -- helpers --
    def _token(self):
        return "fiosk_" + secrets.token_hex(8)

    def _request(self, method, build_params, callback):
        token = self._token()
        path = f"{self.PATH}/request/{self.sender}/{token}"
        sub = None

        def on_response(_conn, _sender, _path, _iface, _sig, params):
            self.bus.signal_unsubscribe(sub)
            response, results = params.unpack()
            callback(response, results)

        sub = self.bus.signal_subscribe(self.BUS, "org.freedesktop.portal.Request", "Response", path,
                                        None, Gio.DBusSignalFlags.NO_MATCH_RULE, on_response)

        def on_called(conn, res):
            try:
                conn.call_finish(res)
            except GLib.Error as e:
                self.bus.signal_unsubscribe(sub)
                self._fail(f"Portal error: {e.message}")

        self.bus.call(self.BUS, self.PATH, self.IFACE, method, build_params(token), None,
                      Gio.DBusCallFlags.NONE, -1, None, on_called)

    def _fail(self, msg):
        self.starting = False
        self.ready = False
        self.on_state(msg)

    # -- session setup: CreateSession -> SelectDevices -> Start --
    def start(self):
        if self.ready or self.starting:
            return
        self.starting = True
        self.on_state("Waiting for permission…")
        self._request("CreateSession",
                      lambda t: GLib.Variant("(a{sv})", ({"handle_token": GLib.Variant("s", t),
                                                          "session_handle_token": GLib.Variant("s", self._token())},)),
                      self._on_created)

    def _on_created(self, response, results):
        if response != 0:
            return self._fail("Could not create portal session")
        self.session = results["session_handle"]
        self.bus.signal_subscribe(self.BUS, "org.freedesktop.portal.Session", "Closed", self.session,
                                  None, Gio.DBusSignalFlags.NO_MATCH_RULE, self._on_closed)

        def params(t):
            opts = {"handle_token": GLib.Variant("s", t), "types": GLib.Variant("u", 1)}  # 1 = keyboard
            if self.remember:
                opts["persist_mode"] = GLib.Variant("u", 2)  # remember until revoked
                token = self._load_token()
                if token:
                    opts["restore_token"] = GLib.Variant("s", token)
            return GLib.Variant("(oa{sv})", (self.session, opts))

        self._request("SelectDevices", params, self._on_selected)

    def _on_selected(self, response, _results):
        if response != 0:
            return self._fail("Keyboard access not granted")
        self._request("Start",
                      lambda t: GLib.Variant("(osa{sv})", (self.session, "", {"handle_token": GLib.Variant("s", t)})),
                      self._on_started)

    def _on_started(self, response, results):
        if response != 0:
            return self._fail("Permission denied — click a key to ask again")
        if self.remember and results.get("restore_token"):
            self._save_token(results["restore_token"])
        self.starting = False
        self.ready = True
        self.on_state(None)

    def _on_closed(self, *_):
        self.session = None
        self._fail("Session closed — click a key to reconnect")

    def close(self):
        if self.session:
            self.bus.call_sync(self.BUS, self.session, "org.freedesktop.portal.Session", "Close",
                               None, None, Gio.DBusCallFlags.NONE, 1000, None)
            self.session = None
        self.ready = False

    # -- restore token (only secret-ish data we store; 0600, in user state dir) --
    def _load_token(self):
        try:
            with open(TOKEN_FILE, encoding="ascii") as f:
                return f.read().strip() or None
        except OSError:
            return None

    def _save_token(self, token):
        try:
            os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
            fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(token)
        except OSError:
            pass

    # -- key events --
    def key(self, code, pressed):
        if not self.ready:
            self.start()
            return False
        self.bus.call(self.BUS, self.PATH, self.IFACE, "NotifyKeyboardKeycode",
                      GLib.Variant("(oa{sv}iu)", (self.session, {}, code, 1 if pressed else 0)),
                      None, Gio.DBusCallFlags.NONE, -1, None, None)
        return True


class Key(Gtk.Box):
    def __init__(self, kb, spec):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.kb = kb
        self.code, self.width, self.base, self.shift, self.altgr = spec
        self.add_css_class("key")
        if len(self.base) > 1:
            self.add_css_class("wide")
        self.hint = Gtk.Label(xalign=1, css_classes=["hint"])
        self.main = Gtk.Label(vexpand=True, css_classes=["main"])
        self.append(self.hint)
        self.append(self.main)
        self.is_down = False

        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self._pressed)
        click.connect("end", self._released)
        self.add_controller(click)
        self.refresh()

    def refresh(self):
        mods = self.kb.mods
        if mods["altgr"] and self.altgr:
            text = self.altgr
        else:
            upper = bool(mods["shift"])
            if self.base.isalpha() and len(self.base) == 1 and self.kb.caps:
                upper = not upper
            text = self.shift if upper else self.base
        self.main.set_label(text)
        self.hint.set_label(self.altgr if self.altgr and not mods["altgr"] else "")
        mod = MODIFIERS.get(self.code)
        for cls in ("latched", "locked"):
            self.remove_css_class(cls)
        if mod and mods[mod]:
            self.add_css_class(mods[mod])
        if self.code == KEY_CAPS and self.kb.caps:
            self.add_css_class("locked")

    def _pressed(self, _gesture, n_press, _x, _y):
        if self.code in MODIFIERS:
            self.kb.toggle_modifier(MODIFIERS[self.code], n_press)
            return
        if self.kb.press(self.code):
            self.is_down = True
            self.add_css_class("down")

    def _released(self, _gesture, _seq):
        if self.is_down:
            self.is_down = False
            self.remove_css_class("down")
            self.kb.release(self.code)


class Keyboard(Gtk.ApplicationWindow):
    def __init__(self, app, remember):
        super().__init__(application=app, title="On-screen keyboard", css_classes=["fiosk"])
        self.mods = {m: None for m in MOD_KEYCODE}  # None | "latched" | "locked"
        self.caps = False
        self.held = set()
        self.unit = 50
        self.at_top = False
        self.pos = None    # None = docked (centered top/bottom), else (x, y) of the top-left corner
        self.area = None   # (width, height) of the usable screen area
        self.grab = None   # drag in progress: grabbed point in panel coordinates
        self.input_rect = None
        self.keys = []

        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "fi-osk")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)  # never takes focus
        # The surface covers the whole usable screen area and is fully transparent; only the
        # keyboard panel accepts pointer input (see _update_input_region), so clicks elsewhere go
        # to the windows below. Moving the keyboard is then just moving the panel inside the
        # surface, which needs no compositor round trip.
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self, edge, True)

        self.portal = Portal(remember, self._set_status)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["panel"],
                        halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.panel = panel
        # The panel is an overlay child so its position (margins) never affects the window's size
        # request; the surface size comes only from the compositor.
        overlay = Gtk.Overlay(child=Gtk.Box())
        overlay.add_overlay(panel)
        self.set_child(overlay)
        self.connect("realize", self._on_realize)

        # Top bar: drag handle + status + window controls
        top = Gtk.Box(css_classes=["titlebar"], cursor=Gdk.Cursor.new_from_name("grab"))
        self.top = top
        top.append(Gtk.Label(label="⠿  On-screen keyboard", css_classes=["title"]))
        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        top.add_controller(drag)
        self.status = Gtk.Label(hexpand=True, css_classes=["status"], xalign=1)
        top.append(self.status)
        for icon, tip, cb, extra in [("go-up-symbolic", "Move to top / bottom", self._toggle_pos, None),
                                     ("zoom-out-symbolic", "Smaller", lambda *_: self._resize(-6), None),
                                     ("zoom-in-symbolic", "Bigger", lambda *_: self._resize(6), None),
                                     ("window-close-symbolic", "Hide keyboard", lambda *_: self.hide_keyboard(), "close")]:
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["ctl"] + ([extra] if extra else []),
                           focus_on_click=False, can_focus=False)
            b.connect("clicked", cb)
            if icon == "go-up-symbolic":
                self.pos_button = b
            top.append(b)
        self.ctl_buttons = [w for w in self._children(top) if isinstance(w, Gtk.Button)]
        panel.append(top)

        # Main block + navigation cluster
        body = Gtk.Box(spacing=int(self.unit * 0.3))
        self.body = body
        main = self._grid()
        # Function row: Esc, gap, F1-F4, gap, F5-F8, gap, F9-F12 (columns are quarter key units)
        for i, spec in enumerate(FUNCTION_ROW):
            self._place(main, spec, 0 if i == 0 else 4 * i + 2 * ((i - 1) // 4) + 2, 0)
        for r, row in enumerate(MAIN_ROWS, 1):
            col = 0
            for spec in row:
                self._place(main, spec, col, r)
                col += int(spec[1] * 4)
            if r == 2:
                self._place(main, ENTER, col, 2, height=2)
        body.append(main)
        nav = self._grid()
        for r, c, spec in NAV_KEYS:
            self._place(nav, spec, c * 4, r + 1)
        for empty_row in (0, 3):  # keep rows aligned with the main block
            nav.attach(Gtk.Box(), 0, empty_row, 1, 1)
        body.append(nav)
        panel.append(body)
        self._resize(0)

    # -- construction helpers --
    @staticmethod
    def _children(w):
        c = w.get_first_child()
        while c:
            yield c
            c = c.get_next_sibling()

    def _grid(self):
        return Gtk.Grid(row_homogeneous=True, column_homogeneous=True)

    def _place(self, grid, spec, col, row, height=1):
        k = Key(self, spec)
        grid.attach(k, col, row, int(spec[1] * 4), height)
        self.keys.append(k)

    def _on_realize(self, *_):
        surface = self.get_surface()
        self.input_rect = None
        surface.set_input_region(cairo.Region())  # click-through until the panel is placed
        surface.connect("layout", self._on_layout)
        surface.get_frame_clock().connect("after-paint", self._update_input_region)

    def _on_layout(self, _surface, width, height):
        if self.area != (width, height):
            self.area = (width, height)
            GLib.idle_add(self._place_panel)  # not during GTK's own layout pass

    def _update_input_region(self, *_):
        ok, b = self.panel.compute_bounds(self)
        if not ok:
            return
        tx, ty = self.get_surface_transform()
        rect = (int(b.origin.x + tx), int(b.origin.y + ty), int(b.size.width + 0.999), int(b.size.height + 0.999))
        if rect != self.input_rect:
            self.input_rect = rect
            self.get_surface().set_input_region(cairo.Region(cairo.RectangleInt(*rect)))
            self.queue_draw()  # the region is only sent to the compositor with the next frame

    def _place_panel(self):
        if not self.area:
            return
        w, h = self._panel_size()
        if self.pos is None:  # docked: centered at the top or bottom edge
            x, y = (self.area[0] - w) // 2, 8 if self.at_top else self.area[1] - h - 8
        else:
            x, y = self.pos
        x, y = self._clamp(x, y, w, h)
        self.panel.set_margin_start(x)
        self.panel.set_margin_top(y)
        return GLib.SOURCE_REMOVE

    def _panel_size(self):
        # The preferred size includes the margins we use for positioning; leave those out.
        size = self.panel.get_preferred_size()[1]
        return size.width - self.panel.get_margin_start(), size.height - self.panel.get_margin_top()

    def _clamp(self, x, y, w, h):  # keep it fully on screen
        return max(0, min(int(x), self.area[0] - w)), max(0, min(int(y), self.area[1] - h))

    # -- dragging (by the title bar) --
    def _drag_begin(self, gesture, x, y):
        w = self.top.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not self.top:
            if isinstance(w, Gtk.Button):
                gesture.set_state(Gtk.EventSequenceState.DENIED)
                return
            w = w.get_parent()
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.grab = self._point(self.top, self.panel, x, y)
        self.top.set_cursor_from_name("grabbing")

    def _drag_update(self, gesture, dx, dy):
        if self.grab is None:
            return
        _, sx, sy = gesture.get_start_point()
        px, py = self._point(self.top, self, sx + dx, sy + dy)  # pointer in surface coordinates
        self.pos = self._clamp(px - self.grab[0], py - self.grab[1], *self._panel_size())
        self._place_panel()

    def _drag_end(self, *_):
        if self.grab is not None:
            self.grab = None
            self.top.set_cursor_from_name("grab")

    @staticmethod
    def _point(src, dest, x, y):
        ok, p = src.compute_point(dest, Graphene.Point().init(x, y))
        return (p.x, p.y) if ok else (x, y)

    def _toggle_pos(self, *_):
        self.pos = None  # back to docked
        self.at_top = not self.at_top
        self.pos_button.set_icon_name("go-down-symbolic" if self.at_top else "go-up-symbolic")
        self._place_panel()

    def _resize(self, delta):
        self.unit = max(30, min(110, self.unit + delta))
        for k in self.keys:
            k.set_size_request(int(k.width * self.unit), self.unit)
        for b in self.ctl_buttons:
            b.set_size_request(int(self.unit * 0.8), int(self.unit * 0.8))
        self.body.set_spacing(int(self.unit * 0.3))
        self._place_panel()

    def _set_status(self, msg):
        self.status.set_label(msg or "")

    # -- key logic --
    def refresh(self):
        for k in self.keys:
            k.refresh()

    def press(self, code):
        if not self.portal.key(code, True):
            return False
        self.held.add(code)
        if code == KEY_CAPS:
            self.caps = not self.caps
            self.refresh()
        return True

    def release(self, code):
        if code in self.held:
            self.held.discard(code)
            self.portal.key(code, False)
        # one-shot (latched) modifiers are released after a normal key
        changed = False
        for m, state in self.mods.items():
            if state == "latched":
                self.portal.key(MOD_KEYCODE[m], False)
                self.mods[m] = None
                changed = True
        if changed:
            self.refresh()

    def toggle_modifier(self, mod, n_press):
        state = self.mods[mod]
        if state is None:
            if not self.portal.key(MOD_KEYCODE[mod], True):
                return
            self.mods[mod] = "latched"           # single click: next key only
        elif state == "latched" and n_press >= 2:
            self.mods[mod] = "locked"            # double click: lock
        else:
            self.portal.key(MOD_KEYCODE[mod], False)
            self.mods[mod] = None
        self.refresh()

    def release_all(self):
        for code in list(self.held):
            self.portal.key(code, False)
        self.held.clear()
        for m, state in self.mods.items():
            if state:
                self.portal.key(MOD_KEYCODE[m], False)
                self.mods[m] = None
        for k in self.keys:
            k.is_down = False
            k.remove_css_class("down")
        self.refresh()

    def show_keyboard(self):
        self.set_visible(True)
        self.portal.start()

    def hide_keyboard(self):
        self.release_all()
        self.set_visible(False)


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.hold()  # stay resident while hidden, so permission is asked only once

    def do_command_line(self, cmd):
        args = cmd.get_arguments()[1:]
        if "--help" in args or "-h" in args:
            cmd.print_literal(__doc__.split("Usage:")[1].strip() + "\n        fi-osk --no-remember  do not store the portal permission\n")
            return 0
        if "--quit" in args:
            self.shutdown_keyboard()
            return 0
        if self.win is None:
            self.win = Keyboard(self, remember="--no-remember" not in args)
            self.win.show_keyboard()
        elif self.win.get_visible():
            self.win.hide_keyboard()
        else:
            self.win.show_keyboard()
        return 0

    def shutdown_keyboard(self):
        if self.win:
            self.win.release_all()
            self.win.portal.close()
        self.release()
        self.quit()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
