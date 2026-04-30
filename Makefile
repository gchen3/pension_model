# Pension model dev workflow.
#
# Three core commands drive everything else:
#   make run plan=<p> scenario=<s>           run one cell, upsert long CSV
#   make run-all                             run the full matrix
#   make compare a=<p>/<s> b=<p>/<s>         pairwise diff between two cells
#
# Convenience targets wrap the test suite, term-vested CSV builds, and
# calibration. `make help` prints this list.

PYTHON ?= python

PLANS ?= frs txtrs txtrs-av
SCENARIOS ?= baseline low_return high_discount

# Default scenario for `make run` if user omits scenario= argument.
scenario ?= baseline

ALL_RUNS_CSV = output/all_runs.csv

.PHONY: help test r-match verify-cashflows build-cashflows \
        calibrate run run-all compare \
        compare-twin compare-txtrs-av-to-av all-checks

help:
	@echo "Core workflow commands:"
	@echo "  make run plan=<p> scenario=<s>      run one (plan, scenario), upsert $(ALL_RUNS_CSV)"
	@echo "  make run-all                        run every (plan, scenario) cell"
	@echo "  make compare a=<p>/<s> b=<p>/<s>    pairwise diff between two cells"
	@echo
	@echo "Tests:"
	@echo "  make test                           full pytest suite"
	@echo "  make r-match                        FRS/TXTRS R-baseline scenario tests"
	@echo
	@echo "Term-vested cashflow:"
	@echo "  make build-cashflows                rebuild all per-plan term-vested CSVs"
	@echo "  make verify-cashflows               NPV identity + bit-match check"
	@echo
	@echo "Calibration (calibrates AND rebuilds CSV - no footgun):"
	@echo "  make calibrate plan=<p>             $(PYTHON) -m pension_model calibrate <p> --write + build CSV"
	@echo
	@echo "Diagnostics:"
	@echo "  make compare-txtrs-av-to-av         TXTRS-AV vs published AV Table 2"
	@echo
	@echo "Aggregate:"
	@echo "  make all-checks                     test + r-match + verify-cashflows"
	@echo
	@echo "Variables:"
	@echo "  PLANS=$(PLANS)"
	@echo "  SCENARIOS=$(SCENARIOS)"

test:
	$(PYTHON) -m pytest tests/

r-match:
	$(PYTHON) -m pytest tests/test_pension_model/test_truth_table_scenarios.py -v

verify-cashflows:
	$(PYTHON) scripts/build/verify_term_vested_cashflow.py

build-cashflows:
	$(PYTHON) scripts/build/build_frs_term_vested_cashflow.py
	$(PYTHON) scripts/build/build_txtrs_term_vested_cashflow.py
	$(PYTHON) scripts/build/build_av_term_vested_cashflow.py txtrs-av

calibrate:
ifndef plan
	$(error plan=<name> is required, e.g. make calibrate plan=txtrs)
endif
	$(PYTHON) -m pension_model calibrate $(plan) --write
	@case "$(plan)" in \
		frs)       $(PYTHON) scripts/build/build_frs_term_vested_cashflow.py ;; \
		txtrs)     $(PYTHON) scripts/build/build_txtrs_term_vested_cashflow.py ;; \
		txtrs-av|frs-av) $(PYTHON) scripts/build/build_av_term_vested_cashflow.py $(plan) ;; \
		*) echo "WARNING: no term-vested build script known for plan=$(plan); update Makefile if needed" ;; \
	esac

run:
ifndef plan
	$(error plan=<name> is required, e.g. make run plan=txtrs scenario=baseline)
endif
	$(PYTHON) scripts/diagnostic/run_cell.py --plan $(plan) --scenario $(scenario)

run-all:
	@for p in $(PLANS); do \
		for s in $(SCENARIOS); do \
			echo "==> $$p / $$s"; \
			$(PYTHON) scripts/diagnostic/run_cell.py --plan $$p --scenario $$s || exit $$?; \
		done; \
	done

compare:
ifndef a
	$(error a=<plan>/<scenario> is required, e.g. make compare a=txtrs/baseline b=txtrs-av/baseline)
endif
ifndef b
	$(error b=<plan>/<scenario> is required, e.g. make compare a=txtrs/baseline b=txtrs-av/baseline)
endif
	$(PYTHON) scripts/diagnostic/compare_cells.py --a $(a) --b $(b)

compare-twin:
	$(PYTHON) scripts/diagnostic/compare_cells.py --a txtrs/baseline --b txtrs-av/baseline
	$(PYTHON) scripts/diagnostic/compare_cells.py --a txtrs/low_return --b txtrs-av/low_return
	$(PYTHON) scripts/diagnostic/compare_cells.py --a txtrs/high_discount --b txtrs-av/high_discount

compare-txtrs-av-to-av:
	$(PYTHON) scripts/diagnostic/compare_txtrs_av_to_av.py

all-checks: verify-cashflows r-match test
