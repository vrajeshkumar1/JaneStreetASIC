# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info
# Derived from the Tiny Tapeout template (Apache-2.0); see NOTICE.md.

# defaults
SIM ?= icarus
FST ?= -fst # Use more efficient FST format
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = project.sv pe_pins.sv pe_spi.sv pe_regs.sv pe_engine.sv pe_fifo.sv sram_bb.v

# The PDK's behavioural models of the memory block, copied into ihp_sram/ so
# the GitHub jobs (which have no PDK checkout) can simulate it. The gate-level
# netlist keeps the memory block as a black box, so that build needs the
# models as well.
SRAM_MODEL_DIR ?= $(PWD)/ihp_sram
SRAM_MODELS = $(SRAM_MODEL_DIR)/RM_IHPSG13_1P_core_behavioral_bm_bist.v \
              $(SRAM_MODEL_DIR)/RM_IHPSG13_1P_256x32_c2_bm_bist.v

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD				= sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
VERILOG_SOURCES += $(SRAM_MODELS)
COMPILE_ARGS    += -DSIM
COMPILE_ARGS    += -DFUNCTIONAL

else

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DSIM
PDK ?= ihp-sg13cmos5l
PDK_CELL_PREFIX = $(patsubst ihp-%,%,$(PDK))
PDK_LIBS_REF = $(PDK_ROOT)/$(PDK)/libs.ref
VERILOG_SOURCES += $(PDK_LIBS_REF)/$(PDK_CELL_PREFIX)_io/verilog/$(PDK_CELL_PREFIX)_io.v
VERILOG_SOURCES += $(wildcard $(PDK_LIBS_REF)/$(PDK_CELL_PREFIX)_stdcell/verilog/$(PDK_CELL_PREFIX)_udp.v)
VERILOG_SOURCES += $(PDK_LIBS_REF)/$(PDK_CELL_PREFIX)_stdcell/verilog/$(PDK_CELL_PREFIX)_stdcell.v
VERILOG_SOURCES += $(SRAM_MODELS)

# this gets copied in by the GDS action workflow
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v

endif

# Allow sharing configuration between design and testbench via `include`:
COMPILE_ARGS 		+= -I$(SRC_DIR)

# Include the testbench sources:
VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb

# List test modules to run, separated by commas and without the .py suffix:
COCOTB_TEST_MODULES = test

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
