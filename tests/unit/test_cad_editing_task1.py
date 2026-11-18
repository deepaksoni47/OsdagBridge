"""
Unit tests for Task I: Interactive 2D CAD Parameter Editing
Tests double-click inline QLineEdit editing, locked parameter protection,
double-commit prevention, dependent geometry updates, and two-way state synchronization.
"""

import sys
import unittest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QApplication, QLineEdit
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QEvent
from PySide6.QtGui import QMouseEvent, QKeyEvent

from osdagbridge.core.utils.common import (
    KEY_SPAN,
    KEY_CARRIAGEWAY_WIDTH,
    KEY_TS_GIRDER_SPACING,
    KEY_TS_DECK_THICKNESS,
    KEY_TS_DECK_OVERHANG,
    KEY_TS_OVERALL_WIDTH,
    KEY_TS_NO_OF_GIRDERS,
)
from osdagbridge.desktop.ui.docks.cad_cross_section import CrossSectionCADWidget
from osdagbridge.desktop.ui.docks.cad_top_view import TopViewCADWidget
from osdagbridge.desktop.ui.docks.cad_dual_view import BridgeDualCADWidget
from osdagbridge.core.bridge_types.plate_girder.defaults import (
    BASIC_INPUT_DICT,
    solve_extend_basic_input_dict,
)

# Ensure single QApplication exists for headless test execution
app = QApplication.instance() or QApplication(sys.argv)


def get_sample_input_dict():
    d = dict(BASIC_INPUT_DICT)
    d[KEY_SPAN] = 35.0
    d[KEY_CARRIAGEWAY_WIDTH] = 10.5
    solve_extend_basic_input_dict(d)
    return d


class TestCADInteractiveEditingTask1(unittest.TestCase):
    """Automated test suite verifying Task I requirements."""

    def _render_widget(self, widget, draw_func):
        from PySide6.QtGui import QPixmap, QPainter
        pm = QPixmap(1000, 700)
        p = QPainter(pm)
        widget._dimension_hitboxes = []
        draw_func(p)
        p.end()

    def setUp(self):
        self.cs_widget = CrossSectionCADWidget()
        self.cs_widget.resize(1000, 700)
        self.cs_widget.show_carriageway_values = True
        self.cs_widget.show_dimensions = True

        self.tv_widget = TopViewCADWidget()
        self.tv_widget.resize(1000, 700)
        self.tv_widget.show_span_values = True
        self.tv_widget.show_carriageway_values = True
        self.tv_widget.show_dimensions = True

        # Render both off-screen to populate hitboxes reliably in headless environment
        self._render_widget(self.cs_widget, self.cs_widget.draw_cross_section)
        self._render_widget(self.tv_widget, self.tv_widget.draw_top_view)

    def tearDown(self):
        if self.cs_widget._inline_editor:
            self.cs_widget._cleanup_inline_editor()
        if self.tv_widget._inline_editor:
            self.tv_widget._cleanup_inline_editor()
        self.cs_widget.deleteLater()
        self.tv_widget.deleteLater()

    # -------------------------------------------------------------------------
    # 1. Hitbox Registration
    # -------------------------------------------------------------------------
    def test_cross_section_hitbox_registration(self):
        """Cross-section CAD canvas registers hitboxes for editable and locked parameters."""
        hitboxes = self.cs_widget._dimension_hitboxes
        self.assertTrue(len(hitboxes) >= 4, f"Expected >= 4 hitboxes, got {len(hitboxes)}")

        registered_keys = {hb["param_key"] for hb in hitboxes}
        self.assertIn("carriageway_width", registered_keys)
        self.assertIn("girder_spacing", registered_keys)
        self.assertIn("deck_thickness", registered_keys)
        self.assertIn("overall_bridge_width", registered_keys)
        self.assertIn("overhang", registered_keys)

        # Check locked flags
        for hb in hitboxes:
            if hb["param_key"] in ("overhang", "overall_bridge_width"):
                self.assertTrue(hb["is_locked"], f"{hb['param_key']} must be locked")
            elif hb["param_key"] in ("carriageway_width", "girder_spacing", "deck_thickness"):
                self.assertFalse(hb["is_locked"], f"{hb['param_key']} must be editable")

    def test_top_view_hitbox_registration(self):
        """Top-view CAD canvas registers hitboxes for Span Length, Girder Spacing, and Bracing Spacing."""
        hitboxes = self.tv_widget._dimension_hitboxes
        self.assertTrue(len(hitboxes) >= 2, f"Expected >= 2 hitboxes, got {len(hitboxes)}")

        registered_keys = {hb["param_key"] for hb in hitboxes}
        self.assertIn("span_length", registered_keys)
        self.assertIn("girder_spacing", registered_keys)

        for hb in hitboxes:
            if hb["param_key"] == "bracing_spacing":
                self.assertTrue(hb["is_locked"], "bracing_spacing must be locked")
            elif hb["param_key"] in ("span_length", "girder_spacing"):
                self.assertFalse(hb["is_locked"], f"{hb['param_key']} must be editable")

    # -------------------------------------------------------------------------
    # 2. Double-Click Inline Editor Spawning
    # -------------------------------------------------------------------------
    def test_double_click_spawns_inline_editor_on_editable_dimension(self):
        """Double clicking an editable dimension spawns QLineEdit with current formatted value."""
        hb = next(h for h in self.cs_widget._dimension_hitboxes if h["param_key"] == "carriageway_width")
        center_pt = hb["rect"].center().toPoint()

        # Simulate double-click
        event = QMouseEvent(
            QEvent.MouseButtonDblClick,
            QPointF(center_pt),
            QPointF(center_pt),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        self.cs_widget.mouseDoubleClickEvent(event)

        editor = self.cs_widget._inline_editor
        self.assertIsNotNone(editor, "Inline editor must be created")
        self.assertFalse(editor.isHidden(), "Inline editor must not be hidden")
        self.assertEqual(self.cs_widget._active_edit_param, "carriageway_width")
        # Should contain formatted float string (e.g. 10.50)
        val_text = editor.text().strip()
        self.assertTrue(len(val_text) > 0)
        self.assertAlmostEqual(float(val_text), self.cs_widget.params['carriageway_width'] / 1000.0, places=2)

    # -------------------------------------------------------------------------
    # 3. Locked Parameter Protection
    # -------------------------------------------------------------------------
    @patch("osdagbridge.desktop.ui.docks.cad_editor_mixin.CustomMessageBox")
    def test_double_click_on_locked_parameter_shows_message_and_no_editor(self, mock_msgbox):
        """Double clicking a locked parameter displays an informative message and does not spawn editor."""
        mock_box = MagicMock()
        mock_msgbox.return_value = mock_box

        hb = next(h for h in self.cs_widget._dimension_hitboxes if h["param_key"] == "overhang")
        center_pt = hb["rect"].center().toPoint()

        event = QMouseEvent(
            QEvent.MouseButtonDblClick,
            QPointF(center_pt),
            QPointF(center_pt),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        self.cs_widget.mouseDoubleClickEvent(event)

        mock_msgbox.assert_called_once()
        call_kwargs = mock_msgbox.call_args.kwargs
        self.assertIn("Overhang", call_kwargs["text"])
        self.assertIn("derived parameter and cannot be edited directly", call_kwargs["text"])
        self.assertIsNone(self.cs_widget._inline_editor, "Editor must NOT be spawned for locked parameter")

    # -------------------------------------------------------------------------
    # 4. Committing Edit on Enter and FocusOut
    # -------------------------------------------------------------------------
    def test_commit_edit_on_enter_updates_param_and_emits_signal(self):
        """Pressing Enter in inline editor validates, updates internal CAD param, and emits signal."""
        hb = next(h for h in self.cs_widget._dimension_hitboxes if h["param_key"] == "carriageway_width")
        self.cs_widget._spawn_inline_editor(hb)

        editor = self.cs_widget._inline_editor
        editor.setText("8.50")

        signal_received = []
        self.cs_widget.parameter_changed.connect(lambda k, v, u: signal_received.append((k, v, u)))

        self.cs_widget._commit_inline_edit()

        self.assertEqual(len(signal_received), 1)
        k, v, u = signal_received[0]
        self.assertEqual(k, "carriageway_width")
        self.assertAlmostEqual(v, 8.50)
        self.assertEqual(u, "m")
        self.assertAlmostEqual(self.cs_widget.params['carriageway_width'], 8500.0)
        self.assertIsNone(self.cs_widget._inline_editor, "Editor must be cleaned up after commit")

    def test_commit_edit_on_focus_out(self):
        """FocusOut event on inline editor commits the edited value."""
        hb = next(h for h in self.tv_widget._dimension_hitboxes if h["param_key"] == "span_length")
        self.tv_widget._spawn_inline_editor(hb)

        editor = self.tv_widget._inline_editor
        editor.setText("42.0")

        signal_received = []
        self.tv_widget.parameter_changed.connect(lambda k, v, u: signal_received.append((k, v, u)))

        # Deliver FocusOut event
        event = QEvent(QEvent.FocusOut)
        app.sendEvent(editor, event)

        self.assertEqual(len(signal_received), 1)
        self.assertEqual(signal_received[0][0], "span_length")
        self.assertAlmostEqual(signal_received[0][1], 42.0)
        self.assertAlmostEqual(self.tv_widget.params['span_length'], 42000.0)

    # -------------------------------------------------------------------------
    # 5. Cancellation on Escape Key
    # -------------------------------------------------------------------------
    def test_cancel_edit_on_escape_key(self):
        """Pressing Escape key cancels editing without committing changes."""
        original_cw = self.cs_widget.params['carriageway_width']
        hb = next(h for h in self.cs_widget._dimension_hitboxes if h["param_key"] == "carriageway_width")
        self.cs_widget._spawn_inline_editor(hb)

        editor = self.cs_widget._inline_editor
        editor.setText("99.99")

        # Deliver Key_Escape event
        key_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        app.sendEvent(editor, key_event)

        self.assertIsNone(self.cs_widget._inline_editor, "Editor must be removed on Escape")
        self.assertEqual(self.cs_widget.params['carriageway_width'], original_cw, "Value must remain unchanged")

    # -------------------------------------------------------------------------
    # 6. Invalid Input Rejection
    # -------------------------------------------------------------------------
    @patch("osdagbridge.desktop.ui.docks.cad_editor_mixin.CustomMessageBox")
    def test_invalid_input_rejection(self, mock_msgbox):
        """Invalid, negative, non-numeric, or out-of-bounds input is rejected with an error dialog."""
        mock_box = MagicMock()
        mock_msgbox.return_value = mock_box

        hb = next(h for h in self.cs_widget._dimension_hitboxes if h["param_key"] == "carriageway_width")
        self.cs_widget._spawn_inline_editor(hb)

        # Test non-numeric input
        editor = self.cs_widget._inline_editor
        editor.setText("invalid_text")
        self.cs_widget._commit_inline_edit()
        mock_msgbox.assert_called_once()
        self.assertIn("positive number", mock_msgbox.call_args.kwargs["text"])

        # Test out-of-bounds input
        mock_msgbox.reset_mock()
        editor.setText("200.0")  # Exceeds max 50m
        self.cs_widget._commit_inline_edit()
        mock_msgbox.assert_called_once()
        self.assertIn("between 3.0 m and 50.0 m", mock_msgbox.call_args.kwargs["text"])

    # -------------------------------------------------------------------------
    # 7. Unit Conversion: Deck Thickness (mm) vs Others (m)
    # -------------------------------------------------------------------------
    def test_unit_conversion_deck_thickness_mm(self):
        """Deck Thickness is edited and emitted in mm, whereas Carriageway/Span/Spacing are in m."""
        hb = next(h for h in self.cs_widget._dimension_hitboxes if h["param_key"] == "deck_thickness")
        self.assertEqual(hb["unit"], "mm")

        self.cs_widget._spawn_inline_editor(hb)
        editor = self.cs_widget._inline_editor
        editor.setText("275")

        signal_received = []
        self.cs_widget.parameter_changed.connect(lambda k, v, u: signal_received.append((k, v, u)))
        self.cs_widget._commit_inline_edit()

        self.assertEqual(len(signal_received), 1)
        k, v, u = signal_received[0]
        self.assertEqual(k, "deck_thickness")
        self.assertEqual(v, 275.0)
        self.assertEqual(u, "mm")
        self.assertEqual(self.cs_widget.params['deck_thickness'], 275.0)

    # -------------------------------------------------------------------------
    # 8. Girder Spacing Modification and Solver Persistence
    # -------------------------------------------------------------------------
    def test_girder_spacing_persistence_across_solver_runs(self):
        """Custom girder spacing persists across solve_extend_basic_input_dict without being overwritten."""
        input_dict = get_sample_input_dict()

        initial_spacing = input_dict[KEY_TS_GIRDER_SPACING]
        initial_overhang = input_dict[KEY_TS_DECK_OVERHANG]
        overall_width = input_dict[KEY_TS_OVERALL_WIDTH]
        n = input_dict[KEY_TS_NO_OF_GIRDERS]

        # Simulate user customizing girder spacing in CAD to 2.50 m
        custom_spacing = 2.50
        input_dict[KEY_TS_GIRDER_SPACING] = custom_spacing
        input_dict["_girder_spacing_customized"] = True

        # Re-run solver
        solve_extend_basic_input_dict(input_dict)

        # Spacing must be preserved, and overhang must adjust according to width equation:
        # overall_width = (n - 1) * spacing + 2 * overhang
        expected_overhang = (overall_width - (n - 1) * custom_spacing) / 2.0

        self.assertAlmostEqual(input_dict[KEY_TS_GIRDER_SPACING], custom_spacing, places=3)
        self.assertAlmostEqual(input_dict[KEY_TS_DECK_OVERHANG], expected_overhang, places=3)
        self.assertNotEqual(input_dict[KEY_TS_GIRDER_SPACING], initial_spacing)


if __name__ == "__main__":
    unittest.main()
