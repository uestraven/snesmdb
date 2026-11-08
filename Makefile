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
# The suite needs pytest, which is the project's ONLY Python dependency. It
# lives in a venv here rather than being assumed present: the system python3
# on this machine has no pytest, so a bare `python3 -m pytest` fails -- which
# meant `make test` did not work while the tests were being reported as
# passing, because they were being run through a venv in /tmp that no longer
# exists after a reboot. `make venv` creates it; `make test` says so if it is
# missing instead of failing with ModuleNotFoundError.
VENV    ?= .venv
PYTEST  := $(VENV)/bin/pytest
PYTHON  ?= python3
SPC_DIR ?= data/spc
OUT_DIR ?= data/out
DIST_DIR ?= $(HOME)/snesmdb-corpus/dist
JOBS    ?= 8

.PHONY: all clean test venv corpus extract performance publish verify audit \
        check-data check-history hooks help

all: $(BUILD)/spc_dump

$(BUILD)/spc_dump: tools/spc_dump.cpp $(SRCS) src/hook.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(HOOK) -o $@ tools/spc_dump.cpp $(SRCS)

# INSTRUMENTED BUILD. Same sources, plus the sample hook that captures the
# directory entry the DSP actually consumed. Built separately so the ordinary
# extractor binary stays free of the extra output, and so the two can be
# compared for bit-identical audio.
EVT_HOOK = -DSPC_DSP_SAMPLE_HOOK\(v,a,s,l\)=snesmdb_log_sample_start\(v,a,s,l\)

$(BUILD)/spc_dump_evt: tools/spc_dump.cpp $(SRCS) src/hook.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(HOOK) $(EVT_HOOK) -o $@ tools/spc_dump.cpp $(SRCS)

# The instrumentation must not change what the chip produces.
verify-instrumentation: $(BUILD)/spc_dump $(BUILD)/spc_dump_evt
	@$(PYTHON) -I tools/verify_instrumentation.py

# The one documented modification to the vendored tree.
verify-vendor:
	@diff -u /tmp/SPC_DSP.cpp.orig vendor/snes_spc/snes_spc/SPC_DSP.cpp || true

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)

test: check-data | $(PYTEST)
	$(PYTEST) -q

# Refuse source or derived corpus data in the tracked tree. Runs before the
# suite, because a leak is worse than a failing test.
check-data:
	@$(PYTHON) -I tools/check_no_derived_data.py

# The only check that sees data already committed. A clean working tree says
# nothing about what the repository still carries in its history.
check-history:
	@$(PYTHON) -I tools/check_no_derived_data.py --history

# Install the pre-commit hook. .gitignore is a default, not enforcement.
hooks:
	git config core.hooksPath .githooks
	@echo "pre-commit hook active: .githooks/pre-commit"

venv: $(PYTEST)

$(PYTEST):
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -q --upgrade pip
	$(VENV)/bin/python -m pip install -q pytest
	@echo "created $(VENV) with pytest"

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

# RELEASE AUDIT. `verify` samples 26 of 1,316 published scores, which is the
# right trade for a gate that runs on every build and misses an isolated
# corrupted artifact. This opens all of them. Run it before publishing.
audit:
	@echo "== exhaustive release audit =="
	@$(PYTHON) -I tools/verify_corpus.py $(OUT_DIR) $(DIST_DIR) --exhaustive

# RELEASE FREEZE. Pin the tree so an evaluation names one exact artifact.
# Refuses a dirty working tree: a pin whose commit does not contain the code
# that built the corpus cannot be reproduced.
LABEL ?= rc1
freeze:
	@$(PYTHON) -I tools/freeze_release.py $(DIST_DIR) --label $(LABEL)

# RESEARCH REPLICATION, distinct from the engineering audit: `audit` checks
# that the artifact is self-consistent, this checks that the numbers in the
# documentation are true of it, using independently written methods that
# import nothing from this project.
replicate:
	@$(PYTHON) -I tools/replicate.py $(DIST_DIR) --claims docs/claims.json

check-freeze:
	@$(PYTHON) -I tools/freeze_release.py $(DIST_DIR) --verify

# The three dist-only research workflows, over the published tree.
workflows:
	@$(PYTHON) -I examples/workflows.py $(DIST_DIR) discover --game Actraiser
	@$(PYTHON) -I examples/workflows.py $(DIST_DIR) pitch --game Actraiser
	@$(PYTHON) -I examples/workflows.py $(DIST_DIR) samples --game Actraiser

help:
	@echo "make                 build build/spc_dump"
	@echo "make test            run the test suite (creates $(VENV) if needed)"
	@echo "make venv            just create $(VENV) with pytest"
	@echo "make corpus          full rebuild: extract -> performance -> publish -> verify"
	@echo "make verify          check an existing corpus and dist tree (sampled)"
	@echo "make audit           release audit: opens EVERY published score"
	@echo "make freeze          pin the published tree (LABEL=rc1)"
	@echo "make check-freeze    re-hash the tree against its pin"
	@echo "make workflows       run the three dist-only research workflows"
	@echo "make replicate       recompute the documented claims from dist"
	@echo "make check-data      refuse derived corpus data in the tracked tree"
	@echo "make check-history   same, across all git history (slow)"
	@echo "make hooks           install the pre-commit data guard"
	@echo
	@echo "variables: SPC_DIR=$(SPC_DIR) OUT_DIR=$(OUT_DIR) DIST_DIR=$(DIST_DIR) JOBS=$(JOBS)"
