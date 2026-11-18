# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
#
# Build the PYNQ-Z2 bitstream without a Vivado project:
#     vivado -mode batch -source fpga/build.tcl
# Output in fpga/build/: pynq_z2_top.bit and timing and utilisation reports.
#
# The design's sources are read from src/ unchanged, except pe_fifo.sv: a copy
# without its pe_clkgate and pe_lmem modules is written to fpga/build/, and
# fpga/pe_lmem_ff.sv supplies a flip-flop pe_lmem instead. fpga/fpga_ram.v
# replaces the IHP memory blocks (src/sram_bb.v is not read).

set root  [file normalize [file join [file dirname [info script]] ..]]
set build [file join $root fpga build]
set part  xc7z020clg400-1
file mkdir $build

set f [open [file join $root src pe_fifo.sv]]
set text [read $f]
close $f
foreach m {pe_clkgate pe_lmem} {
    set start [string first "module $m " $text]
    if {$start < 0} {
        error "module $m not found in src/pe_fifo.sv"
    }
    set stop [string first "endmodule" $text $start]
    set text [string replace $text $start [expr {$stop + 8}] ""]
}
set f [open [file join $build pe_fifo_fpga.sv] w]
puts $f $text
close $f

read_verilog -sv [list \
    [file join $root src project.sv] \
    [file join $root src pe_pins.sv] \
    [file join $root src pe_spi.sv] \
    [file join $root src pe_regs.sv] \
    [file join $root src pe_engine.sv] \
    [file join $build pe_fifo_fpga.sv] \
    [file join $root fpga pe_lmem_ff.sv] \
    [file join $root fpga fpga_ram.v] \
    [file join $root fpga pynq_z2_top.v]]
read_xdc [file join $root fpga pynq_z2.xdc]

synth_design -top pynq_z2_top -part $part
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -file [file join $build timing.rpt]
report_utilization    -file [file join $build utilization.rpt]
write_bitstream -force [file join $build pynq_z2_top.bit]
