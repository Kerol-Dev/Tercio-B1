# 6. KiCad as code

**Decision (Kerol, 2026-10-12): code owns everything.** The schematic,
footprints, placement, power-stage copper and routing are regenerated from
Python every spin. Nobody edits the generated KiCad files by hand. Review
happens in KiCad, and every change goes back into the code.

## 6.1 Toolchain on this Mac (checked 2026-10-12)

| Tool | State |
|---|---|
| KiCad | 10.0.6 at `/Applications/KiCad/KiCad.app` |
| `kicad-cli` | `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli` (not on PATH). It has `sch erc`, `sch export {netlist,pdf,svg,bom}`, `pcb drc --schematic-parity --refill-zones --exit-code-violations --format json`, `pcb export {gerbers,drill,pos,step,glb,ipc2581,odb}`, `pcb render`, `sch/pcb upgrade` and `jobset run` |
| `pcbnew` Python | KiCad's bundled Python 3.9 (`…/Python.framework/Versions/3.9/bin/python3`). `pcbnew.Version()` = 10.0.6, and `ExportSpecctraDSN` and `ImportSpecctraSES` are present |
| Java | OpenJDK 17 (Homebrew). Freerouting 2.x needs a newer Java (check its release notes) or pin Freerouting 1.9.x on Java 17 |
| `uv` | Installed, for the generator's own Python environment and `easyeda2kicad` |
| `easyeda2kicad` | Not installed: `uv tool install easyeda2kicad` |
| SKiDL | Not installed, and not needed (see 6.3) |

## 6.2 Repository layout (proposed)

```
Tercio-bldc/
  hardware/
    gen/                     Python package: the board as code
      parts.py               part catalogue: symbol, footprint, 3D, LCSC code, JLC rotation offset
      circuit/               one module per block (power_in, bridge, driver, mcu, encoder, can, aux, rails)
      schematic.py           Circuit → .kicad_sch (one sheet per block)
      board.py               Circuit → .kicad_pcb via pcbnew (outline, stackup, rules, placement)
      power_stage.py         hand-specified geometry: legs, pours, via arrays, Kelvin traces
      route.py               DSN export → Freerouting → SES import → zone fill
      checks.py              design checks beyond ERC/DRC (6.6)
      outputs.py             PDF, Gerbers, drill, BOM/CPL for JLC, renders, STEP
    lib/                     project symbol/footprint/3D libraries (KiCad library first, easyeda2kicad second)
    rules/tercio-b1.kicad_dru custom DRC rules (voltage clearances, encoder keepout, net classes)
    build/                   generated files only (git-ignored, or committed per release tag)
  Makefile                   make gen | check | outputs | review
```

## 6.3 Circuit description: one netlist, two outputs

A small in-house Python model holds everything (`Part`, `Pin`, `Net`, `Block`,
sheet placement hints). Both the schematic and the board are generated from it,
so parity is structural rather than checked after the fact.

**Why not SKiDL:** SKiDL produces netlists well, but its schematic
generation is the part this flow depends on most, and it is the least mature.
Its KiCad 10 library support would also have to be proven first. The model
the generator needs is small (parts, pins, nets, fields, placement hints). A
few hundred lines that you own are less risk than a dependency on the critical
path.

**Schematic output (`.kicad_sch`):**

- One hierarchical sheet per block, laid out on a grid given in code.
- Pins connect through short wire stubs and net labels (globals for power).
  No long wires to auto-route, so generated sheets stay readable.
- Symbols are copied from the project/KiCad libraries into `lib_symbols`, with
  fields Value, Footprint, LCSC, MPN, DNP.
- The writer emits a well-documented KiCad 8 S-expression format, then
  `kicad-cli sch upgrade` converts it to KiCad 10. The writer never has to
  track format changes.
- UUIDs are deterministic (`uuid5` of refdes/sheet), and output order is
  sorted, so `git diff` shows only real changes.

## 6.4 Board output (`.kicad_pcb`) via `pcbnew`

1. New board, 4-layer stackup ([05](05-bom-pcb.md) §5.2), net classes
   (POWER, PHASE, GATE, KELVIN, ANALOG, DIGITAL, CAN) and the custom
   `.kicad_dru` rules.
2. Footprints loaded from `lib/`, with the schematic path set on each
   (`SetPath` = sheet UUID / symbol UUID from 6.3). This makes
   `--schematic-parity` meaningful.
3. Placement: every part's position, rotation and side is code. Groups are
   positioned relative to anchors (board centre for the MT6835, edges for
   connectors).
4. **Power stage, hand-specified in `power_stage.py`:** a `leg(origin, angle)`
   function places high FET, low FET, shunt and MLCC pair. It draws the
   V_BUS/phase/GND zones as polygons with fixed priorities, via arrays under
   drain tabs, gate and Kelvin pairs as explicit tracks, and the MT6835
   keepout. Everything is parametric, so the checks in 6.6 can compute loop
   area and spacing. These items are locked.
5. **Freerouting for digital nets only:** export DSN, run Freerouting headless
   with a pinned version and fixed pass count, import SES, fill zones, save.
   Pre-routed power copper is locked, so Freerouting routes around it. CAN_H/L
   and the SPI clocks get explicit routes in code if the autorouter's result
   is poor.
6. Run `pcbnew` under KiCad's bundled Python (`make gen` calls it). The rest
   of the generator runs in a normal `uv` environment and talks to it through
   files.

**Known risk:** KiCad has deprecated the SWIG `pcbnew` bindings in favour of
the IPC API (`kicad-python`), which needs a running KiCad instance. Keep every
`pcbnew` call behind one adapter module (`board_io.py`), so the move to the
IPC API is one file when SWIG goes away.

## 6.5 Commands (what `make check` / `make outputs` run)

```bash
KICAD=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
$KICAD sch erc --severity-all --exit-code-violations --format json -o build/erc.json build/tercio-b1.kicad_sch
$KICAD pcb drc --schematic-parity --refill-zones --severity-all --exit-code-violations --format json -o build/drc.json build/tercio-b1.kicad_pcb
$KICAD sch export pdf -o build/tercio-b1-schematic.pdf build/tercio-b1.kicad_sch
$KICAD pcb export gerbers -o build/gerbers/ build/tercio-b1.kicad_pcb
$KICAD pcb export drill -o build/gerbers/ build/tercio-b1.kicad_pcb
$KICAD pcb export pos --format csv --units mm --side both -o build/pos.csv build/tercio-b1.kicad_pcb
$KICAD sch export bom --fields 'Reference,Value,Footprint,LCSC,${QUANTITY}' -o build/bom.csv build/tercio-b1.kicad_sch
$KICAD pcb render --side top --quality high --perspective -o build/render-top.png build/tercio-b1.kicad_pcb
$KICAD pcb export step --no-dnp -o build/tercio-b1.step build/tercio-b1.kicad_pcb
```

(Every flag above was checked against the 10.0.6 `--help` output on
2026-10-12.) `outputs.py` then
converts `pos.csv` and `bom.csv` to JLC's CPL/BOM formats, applying the
per-footprint rotation table from `parts.py`. JLC's rotation conventions
differ from KiCad's for many packages. Check the table once against JLC's
placement preview and keep it in code.

The STEP output also feeds the existing marketing pipeline
(`Tercio-web/tools/step-to-glb.mjs`, the demo-film renderer).

## 6.6 Checks beyond ERC/DRC (`checks.py`)

| Check | Why |
|---|---|
| Every part has an LCSC code, and `parts_lookup.py` shows JLC stock ≥ 2× the build quantity | No surprise "out of stock" at order time |
| Power-loop area per leg below a threshold (computed from the geometry in `power_stage.py`) | Switch-node ringing at 52 V |
| Kelvin nets touch only the shunt pads and the DRV pins | Current-sense accuracy |
| No copper or high-current path inside the encoder keepout; MT6835 centre = board centre ± 0.05 mm | Magnet alignment, stray fields |
| S1/FD lessons: BOOT0 pull-down, NRST 100 nF, VBAT tied, SWD has GND, DRV_EN pull-down, nothing on CAN connector pin 1, CAN_RX not on a BOOT pin | Repeat-bug prevention ([01](01-requirements.md) R14) |
| Clearance classes: V_BUS/phase 0.2 mm to everything, 0.6 mm on exposed copper | IPC-2221B |
| Test points on every rail and the CSA outputs | Bring-up ([08](08-bringup.md)) |
| Determinism: generating twice gives byte-identical files | Clean diffs, trust in the pipeline |

## 6.7 Review loop

1. `make gen check outputs`, all green (ERC, DRC with parity, custom checks).
2. `make review` builds a review packet in `build/review/`: schematic PDF,
   top/bottom/3D renders, DRC/ERC summaries, BOM with live stock, and a
   netlist diff against the previous tag.
3. Kerol opens `build/tercio-b1.kicad_pro` in KiCad to read the schematic and
   board. Findings are written as a list (issues or a `REVIEW.md`), not as
   edits. If something is quicker to show than describe, a throwaway copy of
   the board is fine as a sketch, and the change is then made in code.
4. Iterate. Tag `rev-a` when the order is placed, and commit the generated
   files for that tag so the exact ordered design is kept.

Mac resources: Freerouting runs with `-Xmx2g`. Never run it alongside a render
or another heavy job (16 GB RAM).

## 6.8 Effort estimate

The generator framework (model, schematic writer, `pcbnew` adapter, outputs,
checks) is about 2–3 weeks of evenings before the first B1 sheet. It is
reusable for later boards (S1 rev B, FD rev B, an "X" class B1). The B1 circuit
and power-stage geometry are another ~2 weeks. If the autorouter cannot finish
the dense 46 mm board, the fallback keeps "code owns everything": route the
remaining nets as explicit paths in code. It is not hand routing in KiCad.
