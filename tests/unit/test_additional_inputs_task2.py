import os
import unittest
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QLineEdit, QComboBox, QCheckBox
from PySide6.QtGui import QCloseEvent

# Ensure singleton QApplication
app = QApplication.instance()
if app is None:
    app = QApplication([])

from osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs import AdditionalInputs
from osdagbridge.core.bridge_types.plate_girder.defaults import solve_extend_basic_input_dict, BASIC_INPUT_DICT
from osdagbridge.core.utils.common import *


def get_sample_input_dict():
    d = dict(BASIC_INPUT_DICT)
    d[KEY_SPAN] = 35.0
    d[KEY_CARRIAGEWAY_WIDTH] = 10.5
    solve_extend_basic_input_dict(d)
    return d


class TestAdditionalInputsCustomValidation(unittest.TestCase):
    """Test suite for Custom-field pre-save validation."""

    def setUp(self):
        self.dlg = AdditionalInputs()
        self.base_dict = get_sample_input_dict()
        self.dlg.set_input_dictionary(self.base_dict)

    def test_non_custom_mode_passes_validation(self):
        """When fields are in default/non-custom mode, validation must pass."""
        is_valid, err = self.dlg.validate_custom_fields()
        self.assertTrue(is_valid)
        self.assertIsNone(err)

    def test_mode_line_custom_empty_blocks_save(self):
        """Custom mode with an empty value must block save and identify the field."""
        mode_w = self.dlg.findChild(QComboBox, KEY_LL_FOOTPATH_PRESSURE + ".mode")
        val_w = self.dlg.findChild(QLineEdit, KEY_LL_FOOTPATH_PRESSURE + ".value")
        self.assertIsNotNone(mode_w)
        self.assertIsNotNone(val_w)

        mode_w.setCurrentText("Custom")
        val_w.setText("")

        is_valid, err = self.dlg.validate_custom_fields()
        self.assertFalse(is_valid)
        self.assertIn("Footpath Pressure", err)
        self.assertTrue(err.startswith("Error: The custom value for '"))
        self.assertTrue(err.endswith("' cannot be empty."))

    def test_mode_line_custom_whitespace_blocks_save(self):
        """Custom mode with whitespace-only value must block save."""
        mode_w = self.dlg.findChild(QComboBox, KEY_WL_GUST_FACTOR + ".mode")
        val_w = self.dlg.findChild(QLineEdit, KEY_WL_GUST_FACTOR + ".value")
        self.assertIsNotNone(mode_w)
        self.assertIsNotNone(val_w)

        mode_w.setCurrentText("Custom")
        val_w.setText("    ")

        is_valid, err = self.dlg.validate_custom_fields()
        self.assertFalse(is_valid)
        self.assertIn("Gust Factor", err)

    def test_mode_line_custom_valid_value_passes(self):
        """Custom mode with a valid numerical value must pass validation."""
        mode_w = self.dlg.findChild(QComboBox, KEY_LL_FOOTPATH_PRESSURE + ".mode")
        val_w = self.dlg.findChild(QLineEdit, KEY_LL_FOOTPATH_PRESSURE + ".value")

        mode_w.setCurrentText("Custom")
        val_w.setText("4.5")

        is_valid, err = self.dlg.validate_custom_fields()
        self.assertTrue(is_valid)
        self.assertIsNone(err)

    def test_typical_section_custom_crash_barrier_empty_blocks_save(self):
        """Crash barrier set to Custom with empty field must block save."""
        cb_type_w = self.dlg.findChild(QComboBox, KEY_CB_TYPE)
        cb_w = self.dlg.findChild(QLineEdit, KEY_CB_WIDTH)
        self.assertIsNotNone(cb_type_w)
        self.assertIsNotNone(cb_w)

        cb_type_w.setCurrentText("Custom")
        cb_w.setText("")

        is_valid, err = self.dlg.validate_custom_fields()
        self.assertFalse(is_valid)
        self.assertIn("Crash Barrier Width", err)

    def test_typical_section_custom_wearing_course_whitespace_blocks_save(self):
        """Wearing course set to Custom with whitespace-only density must block save."""
        wc_mat_w = self.dlg.findChild(QComboBox, KEY_WC_MATERIAL)
        wc_den_w = self.dlg.findChild(QLineEdit, KEY_WC_DENSITY)
        self.assertIsNotNone(wc_mat_w)
        self.assertIsNotNone(wc_den_w)

        wc_mat_w.setCurrentText("Custom")
        wc_den_w.setText("   ")

        is_valid, err = self.dlg.validate_custom_fields()
        self.assertFalse(is_valid)
        self.assertIn("Wearing Course Density", err)

    def test_multiple_missing_fields_identified_sequentially(self):
        """When multiple fields are missing, the first is reported, and fixing it reports the next."""
        fp_mode = self.dlg.findChild(QComboBox, KEY_LL_FOOTPATH_PRESSURE + ".mode")
        fp_val = self.dlg.findChild(QLineEdit, KEY_LL_FOOTPATH_PRESSURE + ".value")
        gust_mode = self.dlg.findChild(QComboBox, KEY_WL_GUST_FACTOR + ".mode")
        gust_val = self.dlg.findChild(QLineEdit, KEY_WL_GUST_FACTOR + ".value")

        fp_mode.setCurrentText("Custom")
        fp_val.setText("")

        gust_mode.setCurrentText("Custom")
        gust_val.setText("")

        # First missing field reported
        is_valid1, err1 = self.dlg.validate_custom_fields()
        self.assertFalse(is_valid1)
        self.assertIn("Footpath Pressure", err1)

        # Fix first field
        fp_val.setText("5.0")

        # Second missing field reported
        is_valid2, err2 = self.dlg.validate_custom_fields()
        self.assertFalse(is_valid2)
        self.assertIn("Gust Factor", err2)

        # Fix second field -> now valid
        gust_val.setText("1.2")
        is_valid3, err3 = self.dlg.validate_custom_fields()
        self.assertTrue(is_valid3)
        self.assertIsNone(err3)

    @patch("osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs.CustomMessageBox")
    def test_failed_validation_does_not_mutate_default_dict(self, mock_msgbox):
        """Failed Custom validation must NOT mutate default_input_dict or clear is_modified."""
        mock_instance = MagicMock()
        mock_msgbox.return_value = mock_instance

        mode_w = self.dlg.findChild(QComboBox, KEY_LL_FOOTPATH_PRESSURE + ".mode")
        val_w = self.dlg.findChild(QLineEdit, KEY_LL_FOOTPATH_PRESSURE + ".value")

        mode_w.setCurrentText("Custom")
        val_w.setText("")  # empty custom value

        self.assertTrue(self.dlg.is_modified)
        original_default = dict(self.dlg.default_input_dict)

        self.dlg._save_inputs()

        # Must have shown error dialog
        mock_msgbox.assert_called()
        # Default dictionary must not be mutated
        self.assertEqual(self.dlg.default_input_dict, original_default)
        # Dialog must remain modified
        self.assertTrue(self.dlg.is_modified)


class TestAdditionalInputsModificationTracking(unittest.TestCase):
    """Test suite for self.is_modified state management."""

    def setUp(self):
        self.dlg = AdditionalInputs()
        self.base_dict = get_sample_input_dict()
        self.dlg.set_input_dictionary(self.base_dict)

    def test_initially_clean_dialog(self):
        """Freshly loaded dialog must have is_modified == False."""
        self.assertFalse(self.dlg.is_modified)

    def test_editing_line_edit_marks_modified(self):
        """Modifying a line edit must set is_modified == True."""
        w = self.dlg.findChild(QLineEdit, KEY_TS_FOOTPATH_WIDTH)
        self.assertIsNotNone(w)
        original = w.text()

        w.setText(original + "5")
        self.assertTrue(self.dlg.is_modified)

    def test_changing_combo_box_marks_modified(self):
        """Changing a combobox must set is_modified == True."""
        combo = self.dlg.findChild(QComboBox, KEY_CB_TYPE)
        self.assertIsNotNone(combo)
        original = combo.currentText()

        # Switch to another item
        for i in range(combo.count()):
            text = combo.itemText(i)
            if text != original:
                combo.setCurrentText(text)
                break

        self.assertTrue(self.dlg.is_modified)

    def test_reverting_all_changes_restores_clean_state(self):
        """Reverting modified fields back to saved baseline must restore is_modified == False."""
        w = self.dlg.findChild(QLineEdit, KEY_TS_FOOTPATH_WIDTH)
        original = w.text()

        # Modify
        w.setText("99.99")
        self.assertTrue(self.dlg.is_modified)

        # Revert
        w.setText(original)
        self.assertFalse(self.dlg.is_modified)

    @patch("osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs.CustomMessageBox")
    def test_successful_save_resets_is_modified(self, mock_msgbox):
        """A valid save must set is_modified == False and update saved state."""
        mock_instance = MagicMock()
        mock_msgbox.return_value = mock_instance

        w = self.dlg.findChild(QLineEdit, KEY_TS_FOOTPATH_WIDTH)
        w.setText("2.50")
        self.assertTrue(self.dlg.is_modified)

        self.dlg._save_inputs()

        self.assertFalse(self.dlg.is_modified)
        self.assertEqual(str(self.dlg.default_input_dict.get(KEY_TS_FOOTPATH_WIDTH)), "2.5")


class TestAdditionalInputsDialogClosing(unittest.TestCase):
    """Test suite for closeEvent and unsaved changes confirmation."""

    def setUp(self):
        self.dlg = AdditionalInputs()
        self.base_dict = get_sample_input_dict()
        self.dlg.set_input_dictionary(self.base_dict)

    @patch("osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs.CustomMessageBox")
    def test_clean_dialog_closes_without_warning(self, mock_msgbox):
        """Clean dialog (is_modified == False) must accept close without warning."""
        event = QCloseEvent()
        self.dlg.closeEvent(event)

        mock_msgbox.assert_not_called()
        self.assertTrue(event.isAccepted())

    @patch("osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs.CustomMessageBox")
    def test_modified_dialog_discard_reverts_and_closes(self, mock_msgbox):
        """Modified dialog when user selects 'Discard' must revert changes and close."""
        mock_box = MagicMock()
        mock_box.exec.return_value = "Discard"
        mock_msgbox.return_value = mock_box

        w = self.dlg.findChild(QLineEdit, KEY_TS_FOOTPATH_WIDTH)
        orig_val = w.text()
        w.setText("9.99")
        self.assertTrue(self.dlg.is_modified)

        event = QCloseEvent()
        self.dlg.closeEvent(event)

        mock_msgbox.assert_called_once()
        _, kwargs = mock_msgbox.call_args
        self.assertEqual(
            kwargs.get("text"),
            "You have unsaved changes. Closing this window will discard them. Do you want to proceed?",
        )
        self.assertEqual(kwargs.get("buttons"), ["Discard", "Cancel"])
        self.assertTrue(event.isAccepted())
        # Working dict and widget must have reverted
        self.assertEqual(w.text(), orig_val)
        self.assertFalse(self.dlg.is_modified)

    @patch("osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs.CustomMessageBox")
    def test_modified_dialog_cancel_preserves_values_and_stays_open(self, mock_msgbox):
        """Modified dialog when user selects 'Cancel' must ignore close and preserve values."""
        mock_box = MagicMock()
        mock_box.exec.return_value = "Cancel"
        mock_msgbox.return_value = mock_box

        w = self.dlg.findChild(QLineEdit, KEY_TS_FOOTPATH_WIDTH)
        w.setText("9.99")
        self.assertTrue(self.dlg.is_modified)

        event = QCloseEvent()
        self.dlg.closeEvent(event)

        mock_msgbox.assert_called_once()
        self.assertFalse(event.isAccepted())  # Event ignored
        self.assertEqual(w.text(), "9.99")   # Value preserved
        self.assertTrue(self.dlg.is_modified)

    @patch("osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs.CustomMessageBox")
    def test_custom_titlebar_close_button_routes_to_close_event(self, mock_msgbox):
        """Clicking title bar close button triggers closeEvent."""
        mock_box = MagicMock()
        mock_box.exec.return_value = "Cancel"
        mock_msgbox.return_value = mock_box

        w = self.dlg.findChild(QLineEdit, KEY_TS_FOOTPATH_WIDTH)
        w.setText("9.99")
        self.assertTrue(self.dlg.is_modified)

        # Trigger titlebar close button
        self.dlg.title_bar.btn_close.click()

        mock_msgbox.assert_called_once()
        self.assertTrue(self.dlg.is_modified)

    @patch("osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs.CustomMessageBox")
    def test_discard_and_reopen_shows_baseline_and_clean_state(self, mock_msgbox):
        """When user modifies a field, discards on close, and re-opens, baseline is restored and is_modified is False."""
        mock_box = MagicMock()
        mock_box.exec.return_value = "Discard"
        mock_msgbox.return_value = mock_box

        w = self.dlg.findChild(QLineEdit, KEY_TS_FOOTPATH_WIDTH)
        original_val = w.text()
        w.setText("12.34")
        self.assertTrue(self.dlg.is_modified)

        event = QCloseEvent()
        self.dlg.closeEvent(event)
        self.assertTrue(event.isAccepted())

        # Verify working_input_dict reverted to default baseline and is_modified is False
        self.assertEqual(
            self.dlg.working_input_dict[KEY_TS_FOOTPATH_WIDTH],
            self.dlg.default_input_dict[KEY_TS_FOOTPATH_WIDTH]
        )
        self.assertFalse(self.dlg.is_modified)

        # Also create a re-opened instance with base_dict to simulate full application re-open
        new_dlg = AdditionalInputs()
        new_dlg.set_input_dictionary(self.base_dict)
        new_w = new_dlg.findChild(QLineEdit, KEY_TS_FOOTPATH_WIDTH)
        self.assertFalse(new_dlg.is_modified)
        self.assertEqual(new_w.text(), original_val)
        self.assertNotEqual(new_w.text(), "12.34")


if __name__ == "__main__":
    unittest.main()
