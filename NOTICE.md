# Licences in this repository

Original work in this repository is under the MIT licence (`LICENSE`).

The files below come from other projects and stay under the Apache License 2.0
(`LICENSES/Apache-2.0.txt`). Their copyright and licence notices are kept.

| File | Origin | Changes |
|---|---|---|
| `.github/workflows/*`, `.devcontainer/*`, `.vscode/*`, `.gitignore`, `test/requirements.txt` | Tiny Tapeout template, github.com/TinyTapeout/ttihp-verilog-template, commit 4b1204a | None |
| `info.yaml`, `test/Makefile`, `test/tb.v` | Same template | Filled in for this project; memory-block models added to the test build |
| `src/config.json` | Same template | Clock period, power-grid numbers, memory-block entries and checks. The memory-block settings follow the walkthrough and configuration in github.com/kdp1965/ihp-um-janestreet-prism, commit 05a68dc |
| `src/pdn_cfg.tcl` | LibreLane's `pdn_cfg.tcl` as modified in ihp-um-janestreet-prism, commit 05a68dc | None |
| `odb_stripes.py` | ihp-um-janestreet-prism, commit 05a68dc | None |
| `librelane_plugin_jsasic_pdn.py` | Derived from `librelane_plugin_prism_pdn.py` in ihp-um-janestreet-prism, commit 05a68dc | Reduced to the one step this project uses |
| `test/ihp_sram/*.v` | IHP-Open-PDK, github.com/IHP-GmbH/IHP-Open-PDK, commit 2bbec755 (`ihp-sg13g2/libs.ref/sg13g2_sram/verilog`); the 512 x 32 model from the PDK version the layout flow installs (89d42ee6, `ihp-sg13cmos5l/libs.ref/sg13cmos5l_sram/verilog`) | None |
