# Build the SPC logger, and rebuild the corpus.
#
# The vendored snes_spc tree is NEVER patched. The DSP-write hook is enabled
# purely through the macro upstream already provides, defined here on the
# command line, with src/hook.h force-included so the declaration is visible
# wherever the macro expands.
#
# THE CORPUS TARGETS EXIST BECAUSE THE PROSE RECIPE WAS WRONG. docs/DATASET.md
# listed the rebuild as commands to type and omitted the step that derived the
# row clock, so following it produced a corpus with ZERO scored tracks,
# silently. A recipe that executes cannot drift from the recipe that is
# documented, so the ordering lives here and the docs point at it.
#
# That step is now gone: the clock is decided inside extraction, so there is
# one pass over the corpus and nothing to forget.

VENDOR  := vendor/snes_spc/snes_spc
BUILD   := build
CXX     ?= g++
CXXFLAGS += -O2 -std=c++11 -I$(VENDOR) -Isrc
HOOK    := -DSPC_DSP_WRITE_HOOK\(t,a,d\)=snesmdb_log_dsp_write\(t,a,d\) -include src/hook.h

SRCS := $(VENDOR)/SNES_SPC.cpp $(VENDOR)/SNES_SPC_misc.cpp \
        $(VENDOR)/SNES_SPC_state.cpp $(VENDOR)/SPC_DSP.cpp \
        $(VENDOR)/SPC_Filter.cpp $(VENDOR)/spc.cpp

# Overridable, so a rebuild can be pointed at a different corpus or a scratch
# tree without editing this file.
PYTHON  ?= python3
SPC_DIR ?= data/spc
OUT_DIR ?= data/out
DIST_DIR ?= $(HOME)/snesmdb-corpus/dist
JOBS    ?= 8

.PHONY: all clean test corpus extract performance publish verify help

all: $(BUILD)/spc_dump

$(BUILD)/spc_dump: tools/spc_dump.cpp $(SRCS) src/hook.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(HOOK) -o $@ tools/spc_dump.cpp $(SRCS)

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)

test:
	$(PYTHON) -m pytest -q

# ---------------------------------------------------------------------------
# Corpus rebuild. Each step is separately invokable for iteration, but the
# ORDER IS LOAD-BEARING and `corpus` is the only entry point that guarantees
# it. Roughly 80 minutes end to end on 8 jobs.
# ---------------------------------------------------------------------------

corpus: extract performance publish verify
	@echo
	@echo "corpus rebuilt: $(DIST_DIR)"
	@echo "provenance:     $(DIST_DIR)/provenance.json"

# ~50 min, and now the only step that touches the corpus. Emulates every SPC,
# logs DSP writes, recovers notes and pitch, decides the row clock from the
# SPC's own timer register, and writes the manifest, records and scores.
#
# A second pass used to run after this and was easy to forget -- the shipped
# rebuild recipe omitted it, which produced a corpus with zero scored tracks,
# silently. It existed because the per-game tick consensus needed every row of
# a game before it could settle any one of them. The register read is per
# track, so there is nothing left for a second pass to do.
extract: $(BUILD)/spc_dump
	@echo "== extract ($(SPC_DIR) -> $(OUT_DIR)) =="
	$(PYTHON) -I tools/extract.py $(SPC_DIR) $(OUT_DIR) --jobs $(JOBS)

# The §7 analysis, reported twice: over everything, and over music only, so
# the figures say how much the jingles and effects were moving them.
performance:
	@echo "== performance conventions =="
	$(PYTHON) -I tools/performance.py $(OUT_DIR) $(OUT_DIR)/performance.json
	$(PYTHON) -I tools/performance.py $(OUT_DIR) \
		$(OUT_DIR)/performance_music.json --track-class music

# ~18 min. Refuses to write inside a git work tree: the corpus is derived from
# research-only SPCs and must not be committed.
publish:
	@echo "== publish ($(OUT_DIR) -> $(DIST_DIR)) =="
	$(PYTHON) -I tools/publish.py $(OUT_DIR) $(DIST_DIR)

# Fails loudly on the defects that have actually shipped from this pipeline:
# a missing clock block, scores covering only part of the corpus, polyphony
# above the hardware limit, and derived audio leaking into the artifact.
verify:
	@echo "== verify =="
	@$(PYTHON) -I tools/verify_corpus.py $(OUT_DIR) $(DIST_DIR)

help:
	@echo "make                 build build/spc_dump"
	@echo "make test            run the test suite"
	@echo "make corpus          full rebuild: extract -> performance -> publish -> verify"
	@echo "make verify          check an existing corpus and dist tree"
	@echo
	@echo "variables: SPC_DIR=$(SPC_DIR) OUT_DIR=$(OUT_DIR) DIST_DIR=$(DIST_DIR) JOBS=$(JOBS)"
