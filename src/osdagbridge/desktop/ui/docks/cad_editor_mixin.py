"""
Interactive 2D CAD Dimension Editor Mixin for OsdagBridge.
Provides in-place QLineEdit editing on double-click over dimension annotations
with bounds validation, locked parameter protection, and two-way state synchronization.
"""

import math
from PySide6.QtWidgets import QWidget, QLineEdit, QToolTip
from PySide6.QtCore import Qt, QEvent, QRectF, Signal
from osdagbridge.desktop.ui.dialogs.custom_messagebox import CustomMessageBox, MessageBoxType


class CADDimensionEditorMixin:
    """
    Mixin class providing interactive 2D CAD dimension in-place editing capabilities.
    Bound to double-click events on registered dimension text hitboxes.
    """

    def _init_dimension_editor(self):
        """Initialize dimension hitboxes and inline editor tracking."""
        self._dimension_hitboxes = []
        self._inline_editor = None
        self._active_edit_param = None
        self._active_hb = None
        self._is_committing_edit = False

    def _show_locked_param_message(self, display_name: str):
        """Show information dialog that the selected parameter is derived/locked."""
        msg = f"Parameter '{display_name}' is a derived parameter and cannot be edited directly."
        CustomMessageBox(
            title="Locked Parameter",
            text=msg,
            buttons=["OK"],
            dialogType=MessageBoxType.Information,
        ).exec()

    def _spawn_inline_editor(self, hb: dict):
        """Spawn in-place QLineEdit exactly over the dimension text hitbox."""
        if self._inline_editor:
            self._cleanup_inline_editor()

        self._active_edit_param = hb["param_key"]
        self._active_hb = hb
        self._is_committing_edit = False

        self._inline_editor = QLineEdit(self)
        self._inline_editor.setObjectName(f"inline_editor_{hb['param_key']}")

        val = hb.get("value")
        unit = hb.get("unit", "m")
        if unit == "mm":
            text_val = f"{val:.0f}" if isinstance(val, (int, float)) else str(val)
        else:
            text_val = f"{val:.2f}" if isinstance(val, (int, float)) else str(val)

        self._inline_editor.setText(text_val)

        # Geometry: centered over hb["rect"]
        r = hb["rect"]
        edit_w = max(int(r.width()) + 16, 90)
        edit_h = max(int(r.height()) + 8, 26)
        edit_x = int(r.center().x() - edit_w / 2)
        edit_y = int(r.center().y() - edit_h / 2)
        self._inline_editor.setGeometry(edit_x, edit_y, edit_w, edit_h)

        self._inline_editor.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                color: #000000;
                border: 2px solid #007acc;
                border-radius: 3px;
                padding: 2px 4px;
                font-family: Arial;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        self._inline_editor.setAlignment(Qt.AlignCenter)
        self._inline_editor.installEventFilter(self)
        self._inline_editor.returnPressed.connect(self._commit_inline_edit)

        self._inline_editor.show()
        self._inline_editor.selectAll()
        self._inline_editor.setFocus()
        self.update()

    def eventFilter(self, watched, event):
        """Handle Escape key to cancel and FocusOut to commit."""
        if hasattr(self, "_inline_editor") and watched == self._inline_editor:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._cancel_inline_edit()
                return True
            elif event.type() == QEvent.FocusOut:
                if not self._is_committing_edit:
                    self._commit_inline_edit()
                return False
        return super().eventFilter(watched, event)

    def _commit_inline_edit(self):
        """Validate input and apply parameter modification with double-commit protection."""
        if self._is_committing_edit or not self._inline_editor:
            return
        self._is_committing_edit = True
        raw_text = self._inline_editor.text().strip()
        hb = self._active_hb
        if not hb:
            self._cleanup_inline_editor()
            return

        param_key = hb["param_key"]
        display_name = hb["display_name"]
        unit = hb.get("unit", "m")

        try:
            new_val = float(raw_text)
            if new_val <= 0 or math.isnan(new_val) or math.isinf(new_val):
                raise ValueError("Value must be a positive number.")
        except ValueError:
            CustomMessageBox(
                title="Error",
                text=f"Error: Invalid value '{raw_text}' for '{display_name}'. Value must be a positive number.",
                buttons=["OK"],
                dialogType=MessageBoxType.Critical,
            ).exec()
            self._is_committing_edit = False
            if self._inline_editor:
                self._inline_editor.selectAll()
                self._inline_editor.setFocus()
            return

        is_valid, err_msg = self._validate_param_bounds(param_key, new_val, unit)
        if not is_valid:
            CustomMessageBox(
                title="Error",
                text=err_msg or f"Error: Invalid value for '{display_name}'.",
                buttons=["OK"],
                dialogType=MessageBoxType.Critical,
            ).exec()
            self._is_committing_edit = False
            if self._inline_editor:
                self._inline_editor.selectAll()
                self._inline_editor.setFocus()
            return

        # Clean up editor widget
        self._cleanup_inline_editor()

        # Apply change and notify
        self._apply_parameter_edit(param_key, new_val, unit)

    def _validate_param_bounds(self, param_key: str, new_val: float, unit: str) -> tuple[bool, str | None]:
        """Validate reasonable engineering bounds for editable parameters."""
        if param_key == "carriageway_width":
            if new_val < 3.0 or new_val > 50.0:
                return False, f"Error: Carriageway Width must be between 3.0 m and 50.0 m (got {new_val:.2f} m)."
        elif param_key == "span_length":
            if new_val < 5.0 or new_val > 200.0:
                return False, f"Error: Span Length must be between 5.0 m and 200.0 m (got {new_val:.1f} m)."
        elif param_key == "deck_thickness":
            if new_val < 100.0 or new_val > 2000.0:
                return False, f"Error: Deck Thickness must be between 100 mm and 2000 mm (got {new_val:.0f} mm)."
        elif param_key == "girder_spacing":
            n = int(self.params.get('num_girders', 4))
            min_width_needed = (n - 1) * new_val
            total_deck_w = (self.params.get('deck_overhang', 1000) * 2 + (n - 1) * self.params.get('girder_spacing', 2750)) / 1000.0
            if total_deck_w > 0 and min_width_needed >= total_deck_w:
                return False, f"Error: Girder Spacing of {new_val:.2f} m exceeds overall bridge deck width for {n} girders."
            if new_val < 1.0 or new_val > 10.0:
                return False, f"Error: Girder Spacing must be between 1.0 m and 10.0 m (got {new_val:.2f} m)."
        return True, None

    def _cancel_inline_edit(self):
        """Cancel inline edit without saving."""
        self._cleanup_inline_editor()
        self.update()

    def _cleanup_inline_editor(self):
        """Remove inline editor and reset active editing parameter."""
        self._active_edit_param = None
        self._active_hb = None
        if self._inline_editor:
            editor = self._inline_editor
            self._inline_editor = None
            editor.removeEventFilter(self)
            editor.hide()
            editor.setParent(None)
            editor.deleteLater()
        self._is_committing_edit = False
        self.update()
        self.repaint()

    def handle_double_click_hit(self, pos) -> bool:
        """
        Check if double-click hit any registered dimension annotation.
        Returns True if handled, False otherwise.
        """
        for hb in self._dimension_hitboxes:
            if hb["rect"].contains(pos):
                if hb.get("is_locked"):
                    self._show_locked_param_message(hb["display_name"])
                    return True
                else:
                    self._spawn_inline_editor(hb)
                    return True
        return False

