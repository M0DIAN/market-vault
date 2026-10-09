# Adaptive desktop window geometry

This change keeps Qt 6 in charge of native high-DPI coordinates and Windows
chrome. The **1440×900 Qt-logical client area** is a *preferred* design size,
not a requirement. At startup, the sole QML `ApplicationWindow` uses one
`QScreen.availableGeometry()` rectangle and the native window's frame margins
to fit on the chosen display (including a taskbar's reserved area). Ordinary
minimum design size is **1024×600**, dynamically reduced if the current work
area cannot contain that client size and its frame. A compact 64-DIP navigation
rail appears at window widths below 1060 DIPs; the existing full sidebar is
retained at larger widths.

The existing `desktop-preferences.json` (`market-vault-desktop-preferences-v1`)
keeps the language field and adds an optional `window` object with `x`, `y`,
`width`, `height`, `maximized` and `screen`. Geometry is always Qt logical, not
physical display pixels. Window and language writes preserve one another.
Invalid, missing, or obsolete saved geometry falls back to a calculated default.+A saved normal rectangle is retained across maximize/minimize. Disconnected
screens or changed work areas cause a visible recovery without immediately
persisting a temporary fallback over the user's saved normal size.

The renderer uses Qt's existing DPI handling. There is no `QT_SCALE_FACTOR`
production override, system-wide font scale, widget framework, custom Win32
non-client hit testing, or new independent preference store.

## Verification boundaries

The focused pure-Python and Qt-interface-substitute tests check window fit,
logical coordinates, offscreen recovery, state preservation, and language/
window preference independence. They do **not** substitute for a genuine
PySide6/Windows launch or multiple physical monitors.

Before the PR can be independently accepted, verify from an actual source and
Windows frozen launch that common desktop resolutions, 100/125/150/175/200%
Windows DPI, restore/restart, maximize, taskbar placement, monitor disconnect
and mixed-DPI dragging work without clipped titlebar or inaccessible critical
controls. In particular, re-check the quant research and intraday settings
panels and the minimum-size TEST overview at 1024×600 or smaller available
work areas. Any reproducible clipping should be addressed by a narrowly
scoped form/dialog scroll or layout adjustment rather than whole-window
scaling. Record real Windows/DPI outcomes separately from offscreen Qt tests.
