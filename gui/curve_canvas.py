"""
Interactive native QPainter temperature-vs-PWM curve editor widget.
Supports dragging control points directly on the graph, critical temperature
failsafe markers, gradient area fill, and live operating-point tracking.
"""

from typing import List, Optional
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QWidget

from core.models import (
    CurvePoint,
    TEMP_MAX_C,
    TEMP_MIN_C,
)


class CurveCanvasWidget(QWidget):
    """High-DPI interactive fan curve visualizer and control-point editor."""

    points_changed = pyqtSignal(list)
    point_selected = pyqtSignal(int)

    MARGIN_LEFT = 46
    MARGIN_RIGHT = 20
    MARGIN_TOP = 24
    MARGIN_BOTTOM = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 290)
        self.setMouseTracking(True)

        self._points: List[CurvePoint] = []
        self._editable: bool = True
        self._line_color = QColor("#3FB950")
        self._mode_caption: str = "自定义温控曲线（可拖拽节点）"
        self._critical_temp_c: int = 90
        self._live_temp_c: Optional[float] = None
        self._live_speed_pct: Optional[int] = None

        self._hover_idx: Optional[int] = None
        self._drag_idx: Optional[int] = None
        self._selected_idx: Optional[int] = None

    def set_curve_state(
        self,
        points: List[CurvePoint],
        editable: bool,
        line_color: str,
        caption: str,
        critical_temp_c: int = 90,
    ) -> None:
        self._points = [CurvePoint(p.temp_c, p.speed_pct) for p in points]
        self._editable = editable
        self._line_color = QColor(line_color)
        self._mode_caption = caption
        self._critical_temp_c = critical_temp_c
        if not editable:
            self._drag_idx = None
            self._hover_idx = None
        elif self._selected_idx is not None and self._selected_idx >= len(self._points):
            self._selected_idx = None
        self.update()

    def set_live_point(self, temp_c: Optional[float], speed_pct: Optional[int]) -> None:
        self._live_temp_c = temp_c
        self._live_speed_pct = speed_pct
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self.MARGIN_LEFT,
            self.MARGIN_TOP,
            max(60.0, self.width() - self.MARGIN_LEFT - self.MARGIN_RIGHT),
            max(60.0, self.height() - self.MARGIN_TOP - self.MARGIN_BOTTOM),
        )

    def _to_canvas(self, temp_c: float, speed_pct: float, rect: QRectF) -> QPointF:
        x_ratio = (temp_c - TEMP_MIN_C) / float(TEMP_MAX_C - TEMP_MIN_C)
        y_ratio = max(0.0, min(100.0, speed_pct)) / 100.0
        x = rect.left() + x_ratio * rect.width()
        y = rect.bottom() - y_ratio * rect.height()
        return QPointF(x, y)

    def _from_canvas(self, pos: QPointF, rect: QRectF) -> tuple[int, int]:
        x_ratio = (pos.x() - rect.left()) / max(1.0, rect.width())
        y_ratio = (rect.bottom() - pos.y()) / max(1.0, rect.height())
        t = int(round(TEMP_MIN_C + x_ratio * (TEMP_MAX_C - TEMP_MIN_C)))
        s = int(round(y_ratio * 100.0))
        return max(TEMP_MIN_C, min(TEMP_MAX_C, t)), max(0, min(100, s))

    def _hit_test(self, pos: QPointF) -> Optional[int]:
        if not self._editable or not self._points:
            return None
        rect = self._plot_rect()
        best_idx = None
        best_dist2 = 14.0 * 14.0
        for idx, pt in enumerate(self._points):
            c = self._to_canvas(pt.temp_c, pt.speed_pct, rect)
            dx = pos.x() - c.x()
            dy = pos.y() - c.y()
            d2 = dx * dx + dy * dy
            if d2 <= best_dist2:
                best_dist2 = d2
                best_idx = idx
        return best_idx

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._editable:
            idx = self._hit_test(event.position())
            if idx is not None:
                self._drag_idx = idx
                self._selected_idx = idx
                self.point_selected.emit(idx)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._drag_idx is not None and self._editable and 0 <= self._drag_idx < len(self._points):
            rect = self._plot_rect()
            t, s = self._from_canvas(pos, rect)
            min_t = (self._points[self._drag_idx - 1].temp_c + 1) if self._drag_idx > 0 else TEMP_MIN_C
            max_t = (self._points[self._drag_idx + 1].temp_c - 1) if self._drag_idx + 1 < len(self._points) else TEMP_MAX_C
            t = max(min_t, min(max_t, t))
            if self._points[self._drag_idx].temp_c != t or self._points[self._drag_idx].speed_pct != s:
                self._points[self._drag_idx] = CurvePoint(t, s)
                self.points_changed.emit([CurvePoint(p.temp_c, p.speed_pct) for p in self._points])
                self.update()
            return

        hit = self._hit_test(pos)
        if hit != self._hover_idx:
            self._hover_idx = hit
            self.setCursor(Qt.CursorShape.OpenHandCursor if hit is not None else Qt.CursorShape.ArrowCursor)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_idx is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_idx = None
            hit = self._hit_test(event.position())
            self.setCursor(Qt.CursorShape.OpenHandCursor if hit is not None else Qt.CursorShape.ArrowCursor)
            self.update()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._plot_rect()

        # Background frame
        painter.setPen(QPen(QColor("#30363D"), 1))
        painter.setBrush(QColor("#0D1117"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)

        # High-temperature critical failsafe shaded band
        if self._editable and TEMP_MIN_C <= self._critical_temp_c <= TEMP_MAX_C:
            crit_x = self._to_canvas(self._critical_temp_c, 0, rect).x()
            crit_rect = QRectF(crit_x, rect.top(), max(0.0, rect.right() - crit_x), rect.height())
            painter.fillRect(crit_rect, QColor(248, 81, 73, 22))
            crit_pen = QPen(QColor("#F85149"), 1.2, Qt.PenStyle.DashLine)
            painter.setPen(crit_pen)
            painter.drawLine(QPointF(crit_x, rect.top()), QPointF(crit_x, rect.bottom()))

            painter.setFont(QFont("sans-serif", 9, QFont.Weight.DemiBold))
            painter.setPen(QColor("#F85149"))
            crit_lbl = f"≥{self._critical_temp_c}°C 满转"
            lbl_rect = QRectF(
                max(rect.left() + 6, crit_x - 116),
                rect.bottom() - 24,
                min(110.0, max(40.0, crit_x - rect.left() - 6)),
                18,
            )
            painter.drawText(lbl_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, crit_lbl)

        # Grid lines and axis labels
        grid_pen = QPen(QColor("#21262D"), 1)
        label_font = QFont("sans-serif", 8)
        painter.setFont(label_font)

        for pct in range(0, 101, 20):
            p = self._to_canvas(TEMP_MIN_C, pct, rect)
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(rect.left(), p.y()), QPointF(rect.right(), p.y()))
            painter.setPen(QColor("#8B949E"))
            painter.drawText(
                QRectF(4, p.y() - 9, self.MARGIN_LEFT - 10, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{pct}%",
            )

        for temp in range(TEMP_MIN_C, TEMP_MAX_C + 1, 10):
            p = self._to_canvas(temp, 0, rect)
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(p.x(), rect.top()), QPointF(p.x(), rect.bottom()))
            painter.setPen(QColor("#8B949E"))
            painter.drawText(
                QRectF(p.x() - 18, rect.bottom() + 6, 36, 18),
                Qt.AlignmentFlag.AlignCenter,
                f"{temp}°",
            )

        # Plot border
        painter.setPen(QPen(QColor("#30363D"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Caption badge top-left inside plot
        painter.setFont(QFont("sans-serif", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor("#8B949E"))
        painter.drawText(
            QRectF(rect.left() + 8, rect.top() + 4, rect.width() - 16, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._mode_caption,
        )

        # Curve polyline & gradient fill
        if self._points:
            line_pts: List[QPointF] = []
            # Flat extension to left edge
            first = self._points[0]
            if first.temp_c > TEMP_MIN_C:
                line_pts.append(self._to_canvas(TEMP_MIN_C, first.speed_pct, rect))
            for pt in self._points:
                line_pts.append(self._to_canvas(pt.temp_c, pt.speed_pct, rect))
            # Flat extension to right edge
            last = self._points[-1]
            if last.temp_c < TEMP_MAX_C:
                line_pts.append(self._to_canvas(TEMP_MAX_C, last.speed_pct, rect))

            poly_path = QPainterPath()
            poly_path.moveTo(line_pts[0])
            for p in line_pts[1:]:
                poly_path.lineTo(p)

            fill_poly = QPolygonF(line_pts)
            fill_poly.append(QPointF(line_pts[-1].x(), rect.bottom()))
            fill_poly.append(QPointF(line_pts[0].x(), rect.bottom()))
            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            c_top = QColor(self._line_color)
            c_top.setAlpha(68)
            c_bot = QColor(self._line_color)
            c_bot.setAlpha(5)
            grad.setColorAt(0.0, c_top)
            grad.setColorAt(1.0, c_bot)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawPolygon(fill_poly)

            curve_pen = QPen(self._line_color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(curve_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(poly_path)

            # Control nodes
            if self._editable:
                for idx, pt in enumerate(self._points):
                    cp = self._to_canvas(pt.temp_c, pt.speed_pct, rect)
                    is_active = idx in (self._drag_idx, self._hover_idx, self._selected_idx)
                    radius = 7.0 if is_active else 5.5
                    if is_active:
                        halo = QColor(self._line_color)
                        halo.setAlpha(60)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(halo)
                        painter.drawEllipse(cp, radius + 5, radius + 5)

                    painter.setPen(QPen(QColor("#F0F6FC"), 2.0))
                    painter.setBrush(self._line_color if is_active else QColor("#161B22"))
                    painter.drawEllipse(cp, radius, radius)

                active_idx = self._drag_idx if self._drag_idx is not None else self._hover_idx
                if active_idx is not None and 0 <= active_idx < len(self._points):
                    apt = self._points[active_idx]
                    cp = self._to_canvas(apt.temp_c, apt.speed_pct, rect)
                    txt = f"{apt.temp_c}°C · {apt.speed_pct}%"
                    box_w, box_h = 84, 22
                    bx = min(max(rect.left() + 4, cp.x() - box_w / 2), rect.right() - box_w - 4)
                    by = cp.y() - box_h - 12 if cp.y() - box_h - 12 >= rect.top() else cp.y() + 14
                    badge_rect = QRectF(bx, by, box_w, box_h)
                    painter.setPen(QPen(self._line_color, 1))
                    painter.setBrush(QColor("#161B22"))
                    painter.drawRoundedRect(badge_rect, 5, 5)
                    painter.setPen(QColor("#F0F6FC"))
                    painter.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
                    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, txt)

        # Live operating point crosshair
        if self._live_temp_c is not None and self._live_speed_pct is not None:
            clamped_t = max(TEMP_MIN_C, min(TEMP_MAX_C, self._live_temp_c))
            lp = self._to_canvas(clamped_t, self._live_speed_pct, rect)
            cross_pen = QPen(QColor("#58A6FF"), 1.0, Qt.PenStyle.DotLine)
            painter.setPen(cross_pen)
            painter.drawLine(QPointF(lp.x(), rect.top()), QPointF(lp.x(), rect.bottom()))
            painter.drawLine(QPointF(rect.left(), lp.y()), QPointF(rect.right(), lp.y()))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(88, 166, 255, 70))
            painter.drawEllipse(lp, 9, 9)
            painter.setPen(QPen(QColor("#FFFFFF"), 1.8))
            painter.setBrush(QColor("#58A6FF"))
            painter.drawEllipse(lp, 4.8, 4.8)
