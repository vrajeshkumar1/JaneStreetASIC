# One-time setup

This folder holds everything except ten files that could not be written to this
computer remotely: the GitHub workflow files, the editor and container settings,
and `test/Makefile`. Nine of them are unchanged from the Tiny Tapeout template,
so they come from the template itself. The tenth is here under another name.

1. On GitHub, open https://github.com/TinyTapeout/ttihp-verilog-template and
   choose "Use this template" to create a repository named `JaneStreetASIC`
   under `vrajeshkumar1`. It can be private until submission.
2. Clone that repository to this computer.
3. Copy the contents of this folder into the clone, replacing files with the
   same name.
4. In the clone:
   - delete `src/project.v` (the template's example design);
   - delete `test/Makefile` and rename `test/Makefile.project` to `test/Makefile`;
   - move the template's `LICENSE` to `LICENSES/Apache-2.0.txt` if asked to
     replace it; the `LICENSE` in this folder (MIT) is the one to keep at the
     top level.
5. Commit and push. Three workflows start:
   - `test` runs the simulation (about a minute);
   - `gds` builds the layout and runs the Tiny Tapeout checks;
   - `docs` checks `info.yaml` and `docs/info.md`.
6. If `gds` fails, send the failing step's log. The layout settings have not
   been run yet; this first run is what tests them.

To delete this file afterwards is fine; nothing depends on it.
