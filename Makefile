# Build the SPC logger.
#
# The vendored snes_spc tree is NEVER patched. The DSP-write hook is enabled
# purely through the macro upstream already provides, defined here on the
# command line, with src/hook.h force-included so the declaration is visible
# wherever the macro expands.

VENDOR  := vendor/snes_spc/snes_spc
BUILD   := build
CXX     ?= g++
CXXFLAGS += -O2 -std=c++11 -I$(VENDOR) -Isrc
HOOK    := -DSPC_DSP_WRITE_HOOK\(t,a,d\)=snesmdb_log_dsp_write\(t,a,d\) -include src/hook.h

SRCS := $(VENDOR)/SNES_SPC.cpp $(VENDOR)/SNES_SPC_misc.cpp \
        $(VENDOR)/SNES_SPC_state.cpp $(VENDOR)/SPC_DSP.cpp \
        $(VENDOR)/SPC_Filter.cpp $(VENDOR)/spc.cpp

.PHONY: all clean
all: $(BUILD)/spc_dump

$(BUILD)/spc_dump: tools/spc_dump.cpp $(SRCS) src/hook.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(HOOK) -o $@ tools/spc_dump.cpp $(SRCS)

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)
