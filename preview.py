"""Render the model offscreen to a PNG at a fixed angle.

Usage:
    python preview.py 0        # front
    python preview.py 90       # side
    python preview.py 180      # back

Writes out/preview_<angle>.png. Useful for checking texture / UV / camera work
without a visible window.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PySide6 import QtCore, QtGui, QtWidgets

from pet import GLView

angle = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
SIZE = (640, 900)

app = QtWidgets.QApplication(sys.argv)
fmt = QtGui.QSurfaceFormat()
fmt.setVersion(3, 3)
fmt.setAlphaBufferSize(8)
fmt.setDepthBufferSize(24)
QtGui.QSurfaceFormat.setDefaultFormat(fmt)

view = GLView()
view.angle = angle / 180.0 * 3.141592653589793
view.resize(*SIZE)
view.show()
app.processEvents()


def shot():
    view.update()
    app.processEvents()
    pm = view.grabFramebuffer()
    out = ROOT / "out" / f"preview_{int(angle)}.png"
    out.parent.mkdir(exist_ok=True)
    pm.save(str(out))
    print("saved", out, pm.width(), "x", pm.height())
    app.quit()


QtCore.QTimer.singleShot(900, shot)
sys.exit(app.exec())
