# SPDX-License-Identifier: Apache-2.0
#
# LibreLane plugin: one extra flow step that runs the tile's Metal4 power
# stripes across the IHP memory blocks so they are powered.
#
# Derived from librelane_plugin_prism_pdn.py in
# https://github.com/kdp1965/ihp-um-janestreet-prism (commit 05a68dc,
# Apache-2.0). Only the ExtendPowerStripes step is kept; the class body and its
# option list are unchanged from that file. The script it runs, odb_stripes.py,
# is an unmodified copy from the same repository. See NOTICE.md.
#
# LibreLane imports every module on the Python path whose name starts with
# "librelane_plugin_". The Tiny Tapeout GDS action and a local run both start
# LibreLane from the repository root, so this file is found without installing
# anything. src/config.json inserts the step after the power-grid generator:
#
#   "meta": { "substituting_steps": { "+OpenROAD.GeneratePDN": "Project.ExtendPowerStripes" } }
import os

from librelane.steps import Step
from librelane.steps.odb import OdbpyStep
from librelane.config import Variable
from typing import Optional
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))


@Step.factory.register()
class ExtendPowerStripes(OdbpyStep):
    id = "Project.ExtendPowerStripes"
    name = "Extend Power Stripes Over Macros"

    def get_script_path(self):
        return os.path.join(HERE, "odb_stripes.py")

    config_vars = [
        Variable("EXTEND_STRIPES_LAYER", str, "The tile's vertical single-layer PDN layer (Metal4 on the CMOS5L tile, TopMetal1 on the sg13g2 tile).", default="Metal4"),
        Variable("EXTEND_STRIPES_SRAM_LAYER", Optional[str], "Layer of the IHP SRAM power columns when it differs from the stripe layer; the column stripes then get via stacks down to it.", default=None),
        Variable("EXTEND_STRIPES_CLEARANCE", Decimal, "Spacing kept between a drawn stripe and the other net's macro rails or tile pins on the stripe layer.", units="µm", default=Decimal("0.24")),
        Variable("EXTEND_STRIPES_STACK_PITCH", Decimal, "Spacing of the via stacks along an SRAM power column.", units="µm", default=Decimal("10")),
        Variable("EXTEND_STRIPES_PIN_FACE_MARGIN", Decimal, "No rail via stack within this distance of a macro edge that carries pins (the stack would block the pins' escape); 0 leaves pdngen's stacks alone.", units="µm", default=Decimal("3")),
        Variable("EXTEND_STRIPES_SRAM_ALL_COLUMNS", bool, "Put a stripe on every legal supply column of an IHP SRAM rather than only the ones the tile grid and the per-region minimum need.", default=False),
        Variable("EXTEND_STRIPES_SRAM_ARRAY_EVERY_OTHER", bool, "In each bit-cell array of an IHP SRAM, add a VPWR/VGND stripe pair on every other available pair position (the grid's pairs stay; the macro's standard-cell band is left as the grid gives it).  Not with EXTEND_STRIPES_SRAM_ALL_COLUMNS.", default=False),
    ]

    def get_command(self):
        cmd = super().get_command() + [
            "--layer", self.config["EXTEND_STRIPES_LAYER"],
            "--clearance", str(self.config["EXTEND_STRIPES_CLEARANCE"]),
            "--stack-pitch", str(self.config["EXTEND_STRIPES_STACK_PITCH"]),
            "--pin-face-margin", str(self.config["EXTEND_STRIPES_PIN_FACE_MARGIN"]),
        ]
        if self.config.get("EXTEND_STRIPES_SRAM_LAYER"):
            cmd += ["--sram-layer", self.config["EXTEND_STRIPES_SRAM_LAYER"]]
        cmd += ["--sram-all-columns" if self.config["EXTEND_STRIPES_SRAM_ALL_COLUMNS"] else "--sram-grid-columns"]
        if self.config["EXTEND_STRIPES_SRAM_ARRAY_EVERY_OTHER"]:
            cmd += ["--sram-array-every-other"]
        return cmd
