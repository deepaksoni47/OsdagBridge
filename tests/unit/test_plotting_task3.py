"""
Unit and Integration tests for Task III: Result Plotting for Transverse Members
Tests:
1. Element tag disjointness between longitudinal and transverse members.
2. OutputDock member dropdown population ('End Diaphragms', 'Intermediate Cross Bracings').
3. Data extraction for all 9 quantities (Fx, Vy, Vz, Tx, My, Mz, Dx, Dy, Dz) across load cases.
4. Matplotlib 3D figure generation for all 9 quantities across transverse and longitudinal selections.
5. SummaryOverlay HUD and extreme value reporting for transverse members.
"""

import os
import sys

# On Windows, ensure conda Library\bin is added to DLL search path for OpenBLAS/LAPACK
dll_path = os.path.join(sys.prefix, "Library", "bin")
if os.path.exists(dll_path) and hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(dll_path)
    except Exception:
        pass
if os.path.exists(dll_path) and dll_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] = dll_path + os.pathsep + os.environ.get("PATH", "")

import faulthandler
faulthandler.enable()

import unittest
import numpy as np
import xarray as xr
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication, QComboBox

from osdagbridge.core.utils.common import (
    KEY_ANALYSIS_MEMBER,
    KEY_OUTPUT_DOCK_MEMBER_ID,
    KEY_TS_NO_OF_GIRDERS,
)
from osdagbridge.core.bridge_types.plate_girder.results_data import (
    extract_transverse_structure_from_mesh,
    get_transverse_polylines,
    get_end_diaphragms,
    get_intermediate_cross_bracings,
    get_longitudinal_members,
    get_transverse_members,
)
from osdagbridge.core.bridge_types.plate_girder.results_data_post_processing import (
    build_end_diaphragms,
    build_intermediate_cross_bracings,
)
from osdagbridge.core.bridge_types.plate_girder.plot_generator import (
    build_figure_sfd,
    build_figure_bmd,
    build_figure_deflection,
    build_figure_grillage,
    FORCE_MAP,
    DISP_MAP,
    _is_transverse_selection,
)
from osdagbridge.desktop.ui.mpl_plot_widget import MplPlotWidget, SummaryOverlay
from osdagbridge.desktop.ui.docks.output_dock import OutputDock

# Ensure single QApplication exists for headless test execution
app = QApplication.instance() or QApplication(sys.argv)


def create_sample_bridge_mesh_and_results():
    """
    Construct a synthetic 3-girder bridge mesh with:
    - 3 longitudinal girders (G1 at z=0, G2 at z=2.5, G3 at z=5.0)
    - 3 transverse stations (x=0: End Diaphragm, x=10: Cross Bracing, x=20: End Diaphragm)
    - Fully populated xarray Dataset containing all 12 force components and 6 displacement components.
    """
    nodes = {
        1: [0.0, 0.0, 0.0], 2: [10.0, 0.0, 0.0], 3: [20.0, 0.0, 0.0],
        4: [0.0, 0.0, 2.5], 5: [10.0, 0.0, 2.5], 6: [20.0, 0.0, 2.5],
        7: [0.0, 0.0, 5.0], 8: [10.0, 0.0, 5.0], 9: [20.0, 0.0, 5.0],
    }
    members = {
        # Longitudinal members (G1, G2, G3)
        101: [1, 2], 102: [2, 3],
        103: [4, 5], 104: [5, 6],
        105: [7, 8], 106: [8, 9],
        # Transverse members at x=0 (End Diaphragm start)
        201: [1, 4], 202: [4, 7],
        # Transverse members at x=10 (Intermediate Cross Bracing)
        203: [2, 5], 204: [5, 8],
        # Transverse members at x=20 (End Diaphragm end)
        205: [3, 6], 206: [6, 9],
    }

    ed, icb, long_tags, trans_tags = extract_transverse_structure_from_mesh(nodes, members)

    elems = list(members.keys())
    nids = list(nodes.keys())
    lcs = ["1.0 DL", "1.0 LL", "Envelope ULS"]
    fc = ["Vx_i", "Vx_j", "Vy_i", "Vy_j", "Vz_i", "Vz_j", "Mx_i", "Mx_j", "My_i", "My_j", "Mz_i", "Mz_j"]
    dc = ["dx", "dy", "dz", "rx", "ry", "rz"]

    n_lcs = len(lcs)
    n_elems = len(elems)
    n_nodes = len(nids)

    # Assign distinct forces and displacements per component
    f_data = np.zeros((n_lcs, n_elems, len(fc)), dtype=float)
    for c_idx in range(len(fc)):
        f_data[:, :, c_idx] = (c_idx + 1) * 10.0

    d_data = np.zeros((n_lcs, n_nodes, len(dc)), dtype=float)
    for c_idx in range(len(dc)):
        d_data[:, :, c_idx] = -(c_idx + 1) * 0.002

    da_f = xr.DataArray(
        data=f_data,
        dims=["Loadcase", "Element", "Component"],
        coords={"Loadcase": lcs, "Element": elems, "Component": fc},
    )
    da_d = xr.DataArray(
        data=d_data,
        dims=["Loadcase", "Node", "Component"],
        coords={"Loadcase": lcs, "Node": nids, "Component": dc},
    )
    ds = xr.Dataset({"forces": da_f, "displacements": da_d})

    res_dict = {
        "end_diaphragms": ed,
        "intermediate_cross_bracings": icb,
        "longitudinal_element_tags": long_tags,
        "transverse_element_tags": trans_tags,
        "nodes": nodes,
        "members": members,
        "loadcases": lcs,
        "groups": {
            "start_edge": [201, 202],
            "end_edge": [205, 206],
            "transverse_slab": [203, 204],
        },
    }

    return nodes, members, ds, res_dict


class TestPlottingTask3(unittest.TestCase):
    """Automated test suite verifying Task III requirements."""

    def setUp(self):
        self.nodes, self.members, self.ds, self.res_dict = create_sample_bridge_mesh_and_results()

    def test_element_tag_disjointness(self):
        """Requirement 1: Verify longitudinal and transverse element tags have zero intersection."""
        long_tags = self.res_dict["longitudinal_element_tags"]
        trans_tags = self.res_dict["transverse_element_tags"]

        self.assertIsInstance(long_tags, set)
        self.assertIsInstance(trans_tags, set)
        self.assertGreater(len(long_tags), 0, "Longitudinal elements set must not be empty")
        self.assertGreater(len(trans_tags), 0, "Transverse elements set must not be empty")

        # Strict disjointness
        self.assertTrue(
            long_tags.isdisjoint(trans_tags),
            f"Longitudinal and transverse tag sets must be mutually exclusive! Overlap: {long_tags & trans_tags}",
        )
        self.assertEqual(len(long_tags & trans_tags), 0)

        # Verify geometric categorization
        for tag in long_tags:
            n1, n2 = self.members[tag]
            c1, c2 = self.nodes[n1], self.nodes[n2]
            dx = abs(c1[0] - c2[0])
            dz = abs(c1[2] - c2[2])
            self.assertGreater(dx, dz, f"Element {tag} classified as longitudinal must span along X")

        for tag in trans_tags:
            n1, n2 = self.members[tag]
            c1, c2 = self.nodes[n1], self.nodes[n2]
            dx = abs(c1[0] - c2[0])
            dz = abs(c1[2] - c2[2])
            self.assertGreater(dz, dx, f"Element {tag} classified as transverse must span along Z")

    def test_transverse_grouping_end_diaphragms_and_cross_bracings(self):
        """Requirement 1: Verify End Diaphragms and Cross Bracings are separated and ordered."""
        ed = self.res_dict["end_diaphragms"]
        icb = self.res_dict["intermediate_cross_bracings"]

        self.assertEqual(len(ed), 2, "Expected 2 end diaphragms (start and end)")
        self.assertEqual(len(icb), 1, "Expected 1 intermediate cross bracing station")

        ed_lines = get_transverse_polylines(self.res_dict, "End Diaphragms", nodes=self.nodes, members=self.members)
        self.assertEqual(len(ed_lines), 2)
        self.assertEqual(ed_lines[0]["station_x"], 0.0)
        self.assertEqual(ed_lines[1]["station_x"], 20.0)
        self.assertEqual(ed_lines[0]["members"], [201, 202])

        icb_lines = get_transverse_polylines(self.res_dict, "Intermediate Cross Bracings", nodes=self.nodes, members=self.members)
        self.assertEqual(len(icb_lines), 1)
        self.assertEqual(icb_lines[0]["station_x"], 10.0)
        self.assertEqual(icb_lines[0]["members"], [203, 204])

    def test_selection_helper_transverse(self):
        """Verify _is_transverse_selection correctly recognizes transverse categories."""
        self.assertTrue(_is_transverse_selection("End Diaphragms"))
        self.assertTrue(_is_transverse_selection("Intermediate Cross Bracings"))
        self.assertTrue(_is_transverse_selection("end diaphragm"))
        self.assertTrue(_is_transverse_selection("cross bracing"))

        self.assertFalse(_is_transverse_selection("All"))
        self.assertFalse(_is_transverse_selection("G1"))
        self.assertFalse(_is_transverse_selection("G2"))
        self.assertFalse(_is_transverse_selection("G3"))

    def test_output_dock_member_dropdown_population(self):
        """Requirement 2: Verify Member dropdown in OutputDock includes Transverse Members."""
        from osdagbridge.core.bridge_types.plate_girder.ui_fields import FrontendData
        mock_backend = MagicMock()
        mock_backend.input_dict = {KEY_TS_NO_OF_GIRDERS: 3}
        mock_backend.get_available_loadcases.return_value = ["1.0 DL", "1.0 LL"]
        mock_backend.output_values = FrontendData().output_values

        dock = OutputDock(backend=mock_backend)
        dock.refresh_member_dropdown()

        combo_analysis = dock._w(KEY_ANALYSIS_MEMBER)
        self.assertIsNotNone(combo_analysis, "analysis.member dropdown must exist in OutputDock")

        items = [combo_analysis.itemText(i) for i in range(combo_analysis.count())]

        self.assertIn("All", items)
        self.assertIn("G1", items)
        self.assertIn("G2", items)
        self.assertIn("G3", items)
        self.assertIn("End Diaphragms", items, "Member dropdown must include 'End Diaphragms'")
        self.assertIn("Intermediate Cross Bracings", items, "Member dropdown must include 'Intermediate Cross Bracings'")

        # Ensure order has All first and transverse options at bottom
        self.assertEqual(items[0], "All")
        self.assertEqual(items[-2], "End Diaphragms")
        self.assertEqual(items[-1], "Intermediate Cross Bracings")

    def test_data_extraction_all_nine_quantities(self):
        """Requirement 3: Verify data extraction for all 9 quantities across load cases."""
        ds_case = self.ds.sel(Loadcase="1.0 DL")

        # 1. Shear and Axial Forces (Fx, Vy, Vz)
        for fk in ["Fx", "Fy", "Fz"]:
            comp_i, comp_j = FORCE_MAP[fk]
            val_i = float(ds_case["forces"].sel(Element=201, Component=comp_i).values)
            val_j = float(ds_case["forces"].sel(Element=201, Component=comp_j).values)
            self.assertIsNotNone(val_i)
            self.assertIsNotNone(val_j)

        # 2. Moments and Torsion (Tx, My, Mz)
        for mk in ["Mx", "My", "Mz"]:
            comp_i, comp_j = FORCE_MAP[mk]
            val_i = float(ds_case["forces"].sel(Element=203, Component=comp_i).values)
            val_j = float(ds_case["forces"].sel(Element=203, Component=comp_j).values)
            self.assertIsNotNone(val_i)
            self.assertIsNotNone(val_j)

        # 3. Displacements (Dx, Dy, Dz)
        for dk in ["Dx", "Dy", "Dz"]:
            comp_name = DISP_MAP[dk]
            val = float(ds_case["displacements"].sel(Node=5, Component=comp_name).values)
            self.assertIsNotNone(val)

    def test_matplotlib_3d_figure_generation_sfd(self):
        """Requirement 4: Verify 3D figure generation for Shear and Axial forces."""
        ds_case = self.ds.sel(Loadcase="1.0 DL")

        for member_sel in ["End Diaphragms", "Intermediate Cross Bracings", "All"]:
            for fk in ["Fx", "Fy", "Fz"]:
                fig, summary = build_figure_sfd(
                    ds_case, fk, self.nodes, self.members,
                    selected_girder=member_sel, result_data=self.res_dict
                )
                self.assertIsNotNone(fig)
                self.assertGreater(len(fig.axes), 0, f"Axes3D missing for SFD {fk} ({member_sel})")
                self.assertIsInstance(summary, dict)
                self.assertGreater(len(summary), 0, f"Summary missing for SFD {fk} ({member_sel})")

    def test_matplotlib_3d_figure_generation_bmd(self):
        """Requirement 4: Verify 3D figure generation for Moments and Torsion."""
        ds_case = self.ds.sel(Loadcase="1.0 DL")

        for member_sel in ["End Diaphragms", "Intermediate Cross Bracings", "All"]:
            for mk in ["Mx", "My", "Mz"]:
                fig, summary = build_figure_bmd(
                    ds_case, mk, self.nodes, self.members,
                    selected_girder=member_sel, result_data=self.res_dict
                )
                self.assertIsNotNone(fig)
                self.assertGreater(len(fig.axes), 0, f"Axes3D missing for BMD {mk} ({member_sel})")
                self.assertIsInstance(summary, dict)
                self.assertGreater(len(summary), 0, f"Summary missing for BMD {mk} ({member_sel})")

    def test_matplotlib_3d_figure_generation_deflection(self):
        """Requirement 4: Verify 3D figure generation for Displacements."""
        ds_case = self.ds.sel(Loadcase="1.0 DL")

        for member_sel in ["End Diaphragms", "Intermediate Cross Bracings", "All"]:
            for dk in ["Dx", "Dy", "Dz"]:
                fig, summary = build_figure_deflection(
                    ds_case, dk, self.nodes, self.members,
                    selected_girder=member_sel, result_data=self.res_dict
                )
                self.assertIsNotNone(fig)
                self.assertGreater(len(fig.axes), 0, f"Axes3D missing for Deflection {dk} ({member_sel})")
                self.assertIsInstance(summary, dict)
                self.assertGreater(len(summary), 0, f"Summary missing for Deflection {dk} ({member_sel})")

    def test_matplotlib_3d_grillage_transverse_selection(self):
        """Verify build_figure_grillage functions cleanly with transverse member selection."""
        fig_ed = build_figure_grillage(self.nodes, self.members, selected_girder="End Diaphragms", result_data=self.res_dict)
        self.assertIsNotNone(fig_ed)
        self.assertGreater(len(fig_ed.axes), 0)

        fig_icb = build_figure_grillage(self.nodes, self.members, selected_girder="Intermediate Cross Bracings", result_data=self.res_dict)
        self.assertIsNotNone(fig_icb)
        self.assertGreater(len(fig_icb.axes), 0)

    def test_summary_overlay_hud_formatting(self):
        """Verify SummaryOverlay HUD formats transverse member summaries cleanly."""
        overlay = SummaryOverlay()

        # 1. End Diaphragm summary (2 stations)
        ed_summary = {
            "ED (x=0.00m)": {"max": 45.2, "min": -12.1},
            "ED (x=20.00m)": {"max": 44.8, "min": -11.9},
        }
        overlay.update_data(ed_summary, unit="kN")
        html_ed = overlay.text_label.text().replace("&nbsp;", " ")
        self.assertIn("ED (x=0.00m)", html_ed)
        self.assertIn("45.20", html_ed)
        self.assertIn("-12.10", html_ed)

        # 2. Intermediate Cross Bracings (many stations)
        icb_summary = {
            f"CB-{i} (x={i*1.5:.2f}m)": {"max": 10.0 + i, "min": -5.0 - i}
            for i in range(1, 15)
        }
        overlay.update_data(icb_summary, unit="kNm")
        html_icb = overlay.text_label.text().replace("&nbsp;", " ")
        self.assertIn("Overall", html_icb, "Should display overall governing summary when > 8 members")
        self.assertIn("kNm", html_icb)

    def test_mpl_plot_widget_integration(self):
        """Verify MplPlotWidget setup and dynamic member selection integration."""
        widget = MplPlotWidget()
        widget.setup(
            self.ds, ["1.0 DL", "1.0 LL"], self.nodes, self.members,
            edge_dist=0.0, result_data=self.res_dict
        )
        self.assertEqual(widget._result_data, self.res_dict)

        mock_dock = MagicMock()
        mock_output_widget = MagicMock()
        mock_dock.output_widget = mock_output_widget

        combo_lc = QComboBox()
        combo_lc.setObjectName("analysis.load_combination")
        combo_lc.addItems(["1.0 DL", "1.0 LL"])

        combo_member = QComboBox()
        combo_member.setObjectName("analysis.member")
        combo_member.addItems(["All", "G1", "G2", "G3", "End Diaphragms", "Intermediate Cross Bracings"])

        def find_child_side_effect(cls, name):
            if name == "analysis.load_combination":
                return combo_lc
            if name == "analysis.member":
                return combo_member
            return None

        mock_output_widget.findChild.side_effect = find_child_side_effect
        mock_output_widget.findChildren.return_value = []

        widget._output_dock = mock_dock

        # Switch to End Diaphragms and trigger plot
        combo_member.setCurrentText("End Diaphragms")
        widget.update_plot()
        self.assertIsNotNone(widget._fig)
        self.assertGreater(len(widget._fig.axes), 0)

        # Switch to Intermediate Cross Bracings
        combo_member.setCurrentText("Intermediate Cross Bracings")
        widget.update_plot()
        self.assertIsNotNone(widget._fig)
        self.assertGreater(len(widget._fig.axes), 0)


if __name__ == "__main__":
    unittest.main()

