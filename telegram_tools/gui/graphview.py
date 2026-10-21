"""An interactive force-directed graph for the Nexus view.

Pure QGraphicsView/QGraphicsScene - no extra dependency. A small spring-electrical
simulation lays out the nodes: edges pull their endpoints together, every node
pushes every other apart, and the whole thing cools down to a stable picture.
Nodes are draggable (a dragged node is pinned), the wheel zooms, clicking selects
and highlights a node's neighbourhood, double-clicking activates it (the Nexus
page uses that to open the Investigateur on a subject).
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QLineF, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame, QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QInputDialog, QLabel,
    QMenu, QSlider, QToolButton, QWidget, QWidgetAction,
)

from ..core import graph as G
from . import theme
from .export import style_menu

# A small, distinct palette for recolouring nodes by hand.
PALETTE = ["#2D6CE0", "#1E9E5A", "#E0A52D", "#D64B42", "#8E5BE0",
           "#E05BA8", "#1FB6C4", "#E07B2D", "#6E6E73", "#333A44"]


class _Node(QGraphicsEllipseItem):
    def __init__(self, key: str, radius: float, view: "GraphView"):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.key = key
        self._view = view
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setZValue(2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        self._view._select(self.key)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        # Dropping a node pins it where you left it (physics stops moving it).
        self._view._fixed.add(self.key)
        self._view._pos[self.key] = self.pos()
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self._view.nodeActivated.emit(self.key)
        super().mouseDoubleClickEvent(e)


class GraphView(QGraphicsView):
    nodeClicked = pyqtSignal(str)
    nodeActivated = pyqtSignal(str)
    reclassify = pyqtSignal(str, str)   # (node key, new layer) - fix a misclassification
    styleChanged = pyqtSignal(str)      # (node key) - color/size/label edited; persist it

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)   # pan on empty space
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._nodes: dict = {}
        self._labels: dict = {}
        self._edges: list = []        # (item, src_key, dst_key)
        self._pos: dict = {}          # key -> QPointF
        self._fixed: set = set()
        self._selected = None
        self._graph = None
        self._temp = 0.0
        self._base_r: dict = {}       # key -> default radius (by degree)
        # Hand overrides (right-click menu); persist across re-renders by key.
        self._overrides: dict = {}    # key -> {"color": str, "size": float, "label": str}
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._step)

    # ---- public ----
    def set_graph(self, g) -> None:
        self._timer.stop()
        self._scene.clear()
        self._nodes, self._labels, self._edges, self._pos = {}, {}, [], {}
        self._fixed = set()
        self._selected = None
        self._graph = g
        if g is None or not g.entities:
            return
        # Colour by layer (people / groups / crypto / links / phones / ...), read
        # live so it tracks the theme.
        layer_color = {
            "users": theme.ACCENT, "groups": theme.SUCCESS, "crypto": "#E0A52D",
            "links": "#1FB6C4", "invites": "#2DB5C4", "mentions": "#8E5BE0",
            "emails": "#14A8B8", "phones": "#9AA0AD", "other": theme.TEXT_MUTED,
        }
        keys = list(g.entities)
        n = len(keys)
        # Seed on a circle (+ small jitter) so the simulation unfolds predictably.
        R = max(120.0, 24.0 * math.sqrt(n))
        for i, key in enumerate(keys):
            a = 2 * math.pi * i / max(n, 1)
            self._pos[key] = QPointF(R * math.cos(a) + random.uniform(-5, 5),
                                     R * math.sin(a) + random.uniform(-5, 5))
        # Edges first (under nodes).
        epen = QPen(QColor(theme.BORDER_STRONG)); epen.setCosmetic(True)
        for (src, dst, _etype), edge in g.edges.items():
            if src not in g.entities or dst not in g.entities:
                continue
            item = QGraphicsLineItem()
            w = min(1 + edge.weight * 0.35, 4.0)
            p = QPen(QColor(theme.BORDER_STRONG)); p.setWidthF(w); p.setCosmetic(True)
            item.setPen(p)
            item.setZValue(1)
            self._scene.addItem(item)
            self._edges.append((item, src, dst))
        # Nodes + labels.
        for key in keys:
            ent = g.entities[key]
            deg = g.degree(key)
            base_r = 5.0 + min(deg, 20) * 0.9
            self._base_r[key] = base_r
            ov = self._overrides.get(key, {})
            r = ov.get("size", base_r)
            layer = G.entity_layer(ent)
            name = ov.get("label") or ent.label
            node = _Node(key, r, self)
            node.setBrush(QBrush(QColor(ov.get("color") or layer_color.get(layer, theme.TEXT_MUTED))))
            node.setPen(QPen(QColor(theme.SURFACE), 1.5))
            node.setPos(self._pos[key])
            if ent.kind == G.INDICATOR:
                lbl_name = G.LAYER_LABELS.get(layer, "Indicator")
                node.setToolTip(f"{lbl_name}{' (possible)' if layer == 'phones' else ''}: {name}")
            else:
                node.setToolTip(f"{name}  ·  {G.LAYER_LABELS.get(layer, ent.kind)}  ·  {deg} links")
            self._scene.addItem(node)
            self._nodes[key] = node
            text = name
            # Label the meaningful nodes; long/noisy ones (urls, phones) stay to tooltip.
            show_label = (ent.kind in (G.USER, G.GROUP)
                          or layer in ("crypto", "mentions", "emails", "invites")
                          or "label" in ov)
            if show_label:
                lbl = QGraphicsSimpleTextItem(_short(text))
                f = QFont(); f.setPointSize(7); lbl.setFont(f)
                lbl.setBrush(QBrush(QColor(theme.TEXT_MUTED)))
                lbl.setZValue(3)
                self._scene.addItem(lbl)
                self._labels[key] = lbl
        self._sync_items()
        # Gentle settle: start cool and cool fast, so it doesn't bounce around.
        self._temp = min(R * 0.12, 28.0)
        self._timer.start()
        QTimer.singleShot(60, self.fit)

    def fit(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if not rect.isNull():
            self.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)

    def reset_layout(self) -> None:
        self._fixed = set()
        if self._graph is not None:
            self.set_graph(self._graph)

    # ---- interaction ----
    def wheelEvent(self, e):
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def _select(self, key) -> None:
        self._selected = key
        self.nodeClicked.emit(key)
        self._highlight()

    def _highlight(self) -> None:
        sel = self._selected
        nbrs = self._graph.neighbors(sel) | {sel} if (sel and self._graph) else set()
        for key, node in self._nodes.items():
            dim = bool(sel) and key not in nbrs
            node.setOpacity(0.25 if dim else 1.0)
            lbl = self._labels.get(key)
            if lbl:
                lbl.setOpacity(0.2 if dim else 1.0)
        for item, src, dst in self._edges:
            on = (not sel) or (src == sel or dst == sel)
            pen = item.pen()
            pen.setColor(QColor(theme.ACCENT if (sel and on) else theme.BORDER_STRONG))
            item.setPen(pen)
            item.setOpacity(1.0 if on else 0.15)

    # ---- physics ----
    def _step(self) -> None:
        if not self._nodes:
            self._timer.stop(); return
        keys = list(self._nodes)
        grabber = self.scene().mouseGrabberItem()
        if self._temp > 0.5:
            k = 85.0                      # ideal edge length-ish
            disp = {key: QPointF(0, 0) for key in keys}
            # Repulsion (O(n^2); fine for the capped sizes the Nexus page feeds).
            # The distance is floored so two near-overlapping nodes can't produce
            # a huge force spike - that spike is what made the graph bounce.
            for i in range(len(keys)):
                ki = keys[i]
                pi = self._pos[ki]
                for j in range(i + 1, len(keys)):
                    kj = keys[j]
                    d = pi - self._pos[kj]
                    dist2 = max(d.x() * d.x() + d.y() * d.y(), 100.0)
                    f = (k * k) / dist2
                    disp[ki] += d * f
                    disp[kj] -= d * f
            # Attraction along edges.
            for _item, src, dst in self._edges:
                d = self._pos[src] - self._pos[dst]
                dist = math.hypot(d.x(), d.y()) or 0.01
                f = (dist * dist) / k
                off = d / dist * f
                disp[src] -= off
                disp[dst] += off
            t = self._temp
            for key in keys:
                node = self._nodes[key]
                if key in self._fixed or node is grabber:
                    self._pos[key] = node.pos()
                    continue
                dsp = disp[key]
                dist = math.hypot(dsp.x(), dsp.y()) or 0.01
                step = min(dist, t)
                self._pos[key] += dsp / dist * step
                node.setPos(self._pos[key])
            self._temp *= 0.90            # cool fast so it settles in ~1s
        else:
            # Cooled: just keep positions synced (so dragging still moves edges).
            for key, node in self._nodes.items():
                if node is grabber or key in self._fixed:
                    self._pos[key] = node.pos()
        self._sync_edges_labels()

    def _sync_items(self) -> None:
        for key, node in self._nodes.items():
            node.setPos(self._pos[key])
        self._sync_edges_labels()

    def _sync_edges_labels(self) -> None:
        for item, src, dst in self._edges:
            a, b = self._pos.get(src), self._pos.get(dst)
            if a is not None and b is not None:
                item.setLine(QLineF(a, b))
        for key, lbl in self._labels.items():
            p = self._pos.get(key)
            if p is not None:
                lbl.setPos(p.x() + 7, p.y() - 6)

    # ---- right-click: rename / recolour / resize a node ----
    def contextMenuEvent(self, event):
        key = None
        for it in self.items(event.pos()):
            if isinstance(it, _Node):
                key = it.key
                break
        if key is None:
            return super().contextMenuEvent(event)
        ent = self._graph.entities.get(key) if self._graph else None
        cur = self._overrides.get(key, {}).get("label") or (ent.label if ent else str(key))
        menu = style_menu(QMenu(self))
        header = menu.addAction(_short(cur, 30))
        header.setEnabled(False)                      # just the name, up top
        menu.addSeparator()
        menu.addAction("Rename…", lambda: self._rename(key))
        # Reclassify (fix a wrong type from a too-broad filter), revealed on hover.
        cur_layer = G.entity_layer(ent) if ent else "other"
        tsub = style_menu(menu.addMenu("Type"))
        for layer in G.LAYERS:
            mark = "● " if layer == cur_layer else "     "
            act = tsub.addAction(mark + G.LAYER_LABELS[layer])
            act.triggered.connect(lambda _=False, L=layer: (self.reclassify.emit(key, L), menu.close()))
        # Appearance one hover deeper.
        sub = style_menu(menu.addMenu("Appearance"))
        sub.addAction(self._color_action(sub, menu, key))
        sub.addAction(self._size_action(sub, key))
        menu.exec(event.globalPos())

    def _rename(self, key) -> None:
        ent = self._graph.entities.get(key) if self._graph else None
        cur = self._overrides.get(key, {}).get("label") or (ent.label if ent else str(key))
        text, ok = QInputDialog.getText(self, "Rename node", "Name:", text=cur)
        if ok and text.strip():
            self.set_node_label(key, text.strip())

    def _color_action(self, parent, root, key) -> QWidgetAction:
        wa = QWidgetAction(parent)
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(8, 4, 8, 4); h.setSpacing(4)
        lab = QLabel("Color"); lab.setStyleSheet(f"color:{theme.TEXT};"); h.addWidget(lab)
        for c in PALETTE:
            b = QToolButton(); b.setFixedSize(18, 18); b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QToolButton{{background:{c}; border:1px solid {theme.BORDER}; "
                            "border-radius:9px;}")
            b.clicked.connect(lambda _=False, col=c: (self.set_node_color(key, col), root.close()))
            h.addWidget(b)
        wa.setDefaultWidget(w)
        return wa

    def _size_action(self, parent, key) -> QWidgetAction:
        wa = QWidgetAction(parent)
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(8, 4, 8, 8); h.setSpacing(6)
        lab = QLabel("Size"); lab.setStyleSheet(f"color:{theme.TEXT};"); h.addWidget(lab)
        s = QSlider(Qt.Orientation.Horizontal); s.setMinimum(4); s.setMaximum(32); s.setFixedWidth(150)
        s.setValue(int(self._overrides.get(key, {}).get("size", self._base_r.get(key, 8))))
        s.valueChanged.connect(lambda v: self.set_node_size(key, float(v)))
        h.addWidget(s)
        wa.setDefaultWidget(w)
        return wa

    def load_overrides(self, data: dict) -> None:
        """Restore saved per-node color/size/label (layer lives on the entities)."""
        self._overrides = {k: {kk: vv for kk, vv in v.items() if kk in ("color", "size", "label")}
                           for k, v in (data or {}).items() if isinstance(v, dict)}

    def overrides_for(self, key) -> dict:
        return dict(self._overrides.get(key, {}))

    def set_node_color(self, key, color) -> None:
        self._overrides.setdefault(key, {})["color"] = color
        node = self._nodes.get(key)
        if node:
            node.setBrush(QBrush(QColor(color)))
        self.styleChanged.emit(key)

    def set_node_size(self, key, r) -> None:
        self._overrides.setdefault(key, {})["size"] = r
        node = self._nodes.get(key)
        if node:
            node.setRect(-r, -r, 2 * r, 2 * r)
        self.styleChanged.emit(key)

    def set_node_label(self, key, text) -> None:
        self._overrides.setdefault(key, {})["label"] = text
        lbl = self._labels.get(key)
        if lbl is not None:
            lbl.setText(_short(text))
        else:
            lbl = QGraphicsSimpleTextItem(_short(text))
            f = QFont(); f.setPointSize(7); lbl.setFont(f)
            lbl.setBrush(QBrush(QColor(theme.TEXT_MUTED))); lbl.setZValue(3)
            self._scene.addItem(lbl); self._labels[key] = lbl
            p = self._pos.get(key)
            if p is not None:
                lbl.setPos(p.x() + 7, p.y() - 6)
        node = self._nodes.get(key)
        if node:
            node.setToolTip(text)
        self.styleChanged.emit(key)


def _short(text: str, n: int = 16) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"
