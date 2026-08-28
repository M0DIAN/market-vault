import QtQuick
import "../theme" as Theme

Canvas {
    id: root
    property string glyph: "info"
    property color color: Theme.PixelTheme.ink
    property color accentColor: color
    implicitWidth: 18
    implicitHeight: 18
    antialiasing: false
    renderTarget: Canvas.Image

    onGlyphChanged: requestPaint()
    onColorChanged: requestPaint()
    onAccentColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    function pixelsFor(name) {
        const glyphs = {
            "home": [[2,5,1,1],[3,4,1,1],[4,3,4,1],[8,4,1,1],[9,5,1,1],[3,6,6,1],[3,7,1,3],[8,7,1,3],[4,9,4,1],[5,7,2,3]],
            "history": [[2,3,8,1],[2,4,1,6],[3,9,7,1],[4,7,1,2],[6,5,1,4],[8,3,1,6]],
            "calendar": [[2,3,8,7],[3,2,1,3],[8,2,1,3],[3,5,6,1],[4,7,1,1],[6,7,1,1],[8,7,1,1]],
            "chart": [[2,9,8,1],[2,7,1,2],[4,6,1,3],[6,3,1,6],[8,5,1,4],[9,2,1,7]],
            "inventory": [[2,3,8,2],[3,5,6,5],[4,6,4,1],[5,8,2,1]],
            "audit": [[2,3,5,1],[2,4,1,6],[3,9,6,1],[8,6,2,1],[7,7,1,1],[6,8,1,1],[4,6,1,1]],
            "pulse": [[1,7,2,1],[3,5,1,2],[4,3,1,5],[5,7,2,1],[7,5,1,2],[8,4,1,2],[9,6,2,1]],
            "runs": [[3,2,6,1],[2,3,8,7],[3,4,1,1],[8,4,1,1],[5,4,1,3],[6,6,2,1]],
            "storage": [[2,3,8,2],[3,5,6,5],[4,6,4,1],[5,8,2,1],[8,1,1,2],[9,2,1,1]],
            "previous": [[6,3,1,1],[5,4,1,1],[4,5,1,1],[3,6,1,1],[4,7,1,1],[5,8,1,1],[6,9,1,1]],
            "next": [[5,3,1,1],[6,4,1,1],[7,5,1,1],[8,6,1,1],[7,7,1,1],[6,8,1,1],[5,9,1,1]],
            "refresh": [[3,3,5,1],[2,4,1,3],[8,2,1,3],[7,3,2,1],[4,9,5,1],[9,6,1,3],[3,8,2,1],[3,7,1,2]],
            "export": [[5,2,2,5],[3,4,2,1],[7,4,2,1],[4,3,1,1],[7,3,1,1],[2,7,1,3],[3,9,7,1],[9,7,1,3]],
            "download": [[5,2,2,5],[3,5,2,1],[7,5,2,1],[4,6,1,1],[7,6,1,1],[5,7,2,1],[2,9,8,1]],
            "check": [[2,6,1,2],[3,8,2,1],[5,7,1,1],[6,6,1,1],[7,5,1,1],[8,4,1,1],[9,3,1,1]],
            "warning": [[5,2,2,1],[4,3,4,1],[3,4,6,4],[2,8,8,2],[5,5,2,2],[5,8,2,1]],
            "info": [[5,2,2,2],[5,5,2,5],[4,5,1,1],[4,9,4,1]],
            "close": [[3,3,1,1],[8,3,1,1],[4,4,1,1],[7,4,1,1],[5,5,2,2],[4,7,1,1],[7,7,1,1],[3,8,1,1],[8,8,1,1]],
            "language": [[4,2,4,1],[3,3,6,1],[2,4,2,4],[8,4,2,4],[3,8,6,1],[4,9,4,1],[5,3,1,6],[7,3,1,6],[3,5,6,1]],
            "network": [[2,5,2,2],[8,5,2,2],[5,2,2,2],[5,8,2,2],[4,4,4,1],[4,7,4,1]],
            "lock": [[4,2,4,1],[3,3,1,3],[8,3,1,3],[3,6,6,4],[5,7,2,2]]
        }
        return glyphs[name] || glyphs.info
    }

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        ctx.imageSmoothingEnabled = false
        const unit = Math.max(1, Math.floor(Math.min(width, height) / 12))
        const offsetX = Math.floor((width - 12 * unit) / 2)
        const offsetY = Math.floor((height - 12 * unit) / 2)
        ctx.fillStyle = root.color
        const pixels = pixelsFor(root.glyph)
        for (let i = 0; i < pixels.length; ++i) {
            const p = pixels[i]
            ctx.fillRect(offsetX + p[0] * unit, offsetY + p[1] * unit,
                         p[2] * unit, p[3] * unit)
        }
    }
}
