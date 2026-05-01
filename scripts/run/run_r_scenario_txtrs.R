#!/usr/bin/env Rscript
# Run a TXTRS R model scenario and export the truth table for Python comparison.
#
# Usage (from project root):
#   cd R_model/R_model_txtrs
#   Rscript ../../scripts/run/run_r_scenario_txtrs.R baseline
#   Rscript ../../scripts/run/run_r_scenario_txtrs.R <scenario_name>
#
# Mirrors scripts/run/run_r_scenario.R (FRS) but drives the TxTRS R model.
# Writes plans/txtrs/baselines/r_truth_table_<scenario>.csv with the same
# column schema as the FRS truth tables so the Python regression test
# (tests/test_pension_model/test_truth_table_scenarios.py) can include it.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("Usage: Rscript run_r_scenario_txtrs.R <scenario_name>")
}
scenario_name <- args[1]

cat("Loading TxTRS R model...\n")

library(readxl)
library(dplyr)
library(tidyr)
library(stringr)
library(zoo)
library(data.table)
library(openxlsx)
library(Rcpp)
library(janitor)
library(rio)

sourceCpp("./Rcpp_functions.cpp")
source("utility_functions.R")
source("TxTRS_model_inputs.R")
source("TxTRS_R_BModel revised.R")
source("TxTRS_workforce.R")

# Pre-built workforce data (skip the slow get_wf_data step)
wf_data_baseline <- readRDS("wf_data_baseline.rds")
wf_data_reduced  <- readRDS("wf_data_reduced.rds")

source("TxTRS_liability_model.R")
source("TxTRS_funding_model.R")

# Define scenario overrides
if (scenario_name == "baseline") {
  cat("Running baseline scenario: no overrides\n")
  funding <- get_funding_data()
} else if (scenario_name == "high_discount") {
  cat("Running high_discount scenario: dr_current=dr_new=model_return=0.075\n")
  funding <- get_funding_data(
    dr_current = 0.075,
    dr_new = 0.075,
    model_return = 0.075
  )
} else if (scenario_name == "low_return") {
  cat("Running low_return scenario: model_return=0.05, return_scen='model'\n")
  funding <- get_funding_data(
    return_scen = "model",
    model_return = 0.05
  )
} else if (scenario_name == "asset_shock") {
  cat("Running asset_shock scenario: returns current plan investment return, 3%, -24%, 12%, 12%, 12%, then current plan investment return\n")
  first_proj_year <- YearStart + 1
  return_path <- c(model_return_, 0.03, -0.24, 0.12, 0.12, 0.12)
  shock_mask <- return_scenarios$year >= first_proj_year &
    return_scenarios$year < first_proj_year + length(return_path)
  return_scenarios$asset_shock <- model_return_
  return_scenarios$asset_shock[shock_mask] <-
    return_path[return_scenarios$year[shock_mask] - first_proj_year + 1]
  funding <- get_funding_data(
    return_scen = "asset_shock"
  )
} else if (scenario_name == "high_inflation") {
  cat("Running high_inflation scenario: inflation = baseline inflation + 0.03\n")
  inf_rate <- inf_rate + 0.03
  funding <- get_funding_data()
} else if (scenario_name == "high_inflation_linked") {
  cat("Running high_inflation_linked scenario: inflation, payroll growth, discount rates, model return, and amortization growth = baseline + 0.03\n")
  inf_rate <- inf_rate + 0.03
  payroll_growth_ <- payroll_growth_ + 0.03
  funding <- get_funding_data(
    dr_current = dr_current_ + 0.03,
    dr_new = dr_new_ + 0.03,
    model_return = model_return_ + 0.03,
    amo_pay_growth = amo_pay_growth_ + 0.03
  )
} else if (scenario_name == "no_cola") {
  cat("Running no_cola scenario: all COLA = 0\n")
  funding <- get_funding_data(
    cola_current_retire = 0.0,
    cola_current_retire_one = 0.0,
    one_time_cola = FALSE,
    cola_current_active = 0.0,
    cola_new_active = 0.0
  )
} else {
  stop(paste("Unknown scenario:", scenario_name))
}

# Build truth table from funding results.
# TXTRS funding_data is a flat data.frame (not nested like FRS).
f <- funding

# Helper that errors clearly (with available columns) when no candidate matches.
get_col <- function(df, candidates) {
  for (name in candidates) {
    if (name %in% colnames(df)) return(df[[name]])
  }
  stop(sprintf(
    "None of %s found in funding output. Available: %s",
    paste(candidates, collapse = ", "),
    paste(colnames(df), collapse = ", ")
  ))
}

mva       <- get_col(f, c("MVA", "mva", "total_mva"))
aal       <- get_col(f, c("AAL", "aal", "total_aal"))
ava       <- get_col(f, c("AVA", "ava", "total_ava"))
fr_mva    <- get_col(f, c("FR_MVA", "fr_mva"))
fr_ava    <- get_col(f, c("FR_AVA", "fr_ava"))
payroll   <- get_col(f, c("payroll", "total_payroll"))
er_cont   <- get_col(f, c("er_cont", "total_er_cont"))
yr        <- get_col(f, c("fy", "year", "Year"))

ee        <- get_col(f, c("ee_nc_cont_legacy")) +
             get_col(f, c("ee_nc_cont_new"))
er_db     <- get_col(f, c("er_nc_cont_legacy")) +
             get_col(f, c("er_nc_cont_new")) +
             get_col(f, c("er_amo_cont_legacy")) +
             get_col(f, c("er_amo_cont_new"))
benefits  <- get_col(f, c("ben_payment_legacy")) +
             get_col(f, c("ben_payment_new"))
refunds   <- get_col(f, c("refund_legacy")) +
             get_col(f, c("refund_new"))
admin     <- get_col(f, c("admin_exp_legacy")) +
             get_col(f, c("admin_exp_new"))
net_cf    <- get_col(f, c("net_cf_legacy")) +
             get_col(f, c("net_cf_new"))

invest_income <- c(
  mva[2:length(mva)] - mva[1:(length(mva) - 1)] - net_cf[1:(length(net_cf) - 1)],
  0
)

# n_active and some year-0 contribution components are not fully populated in
# funding_data; pull reviewed values from the existing TXTRS baseline when
# available so the comparison surface stays complete.
baseline_ref_path <- "../../plans/txtrs/baselines/r_truth_table.csv"
n_active <- rep(NA, length(mva))
if (file.exists(baseline_ref_path)) {
  baseline_ref <- read.csv(baseline_ref_path)
  if ("n_active_boy" %in% names(baseline_ref) && nrow(baseline_ref) == length(mva)) {
    n_active <- baseline_ref$n_active_boy
  }
  if ("ee_cont" %in% names(baseline_ref) && nrow(baseline_ref) == length(ee)) {
    ee[is.na(ee)] <- baseline_ref$ee_cont[is.na(ee)]
  }
  if ("er_db_cont" %in% names(baseline_ref) && nrow(baseline_ref) == length(er_db)) {
    er_db[is.na(er_db)] <- baseline_ref$er_db_cont[is.na(er_db)]
  }
}

truth <- data.frame(
  plan = "txtrs",
  year = as.integer(yr),
  mva_boy = mva,
  er_db_cont = er_db,
  ee_cont = ee,
  invest_income = invest_income,
  benefits = benefits,
  refunds = refunds,
  admin_exp = admin,
  mva_eoy = mva + net_cf + invest_income,
  aal_boy = aal,
  ava_boy = ava,
  fr_mva_boy = fr_mva,
  fr_ava_boy = fr_ava,
  n_active_boy = n_active,
  payroll = payroll,
  er_cont_total = er_cont
)

out_dir <- file.path("../../plans/txtrs/baselines")
out_file <- if (scenario_name == "baseline") {
  "r_truth_table.csv"
} else {
  paste0("r_truth_table_", scenario_name, ".csv")
}
out_path <- file.path(out_dir, out_file)
write.csv(truth, out_path, row.names = FALSE)
cat("Wrote", out_path, "\n")
