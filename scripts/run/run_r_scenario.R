#!/usr/bin/env Rscript
# Run an R model scenario and export the truth table for Python comparison.
#
# Usage (from project root):
#   cd R_model/R_model_frs
#   Rscript ../../scripts/run/run_r_scenario.R baseline
#   Rscript ../../scripts/run/run_r_scenario.R high_discount
#
# This sources the R model, runs get_funding_data() with overridden
# parameters, and writes a truth table CSV to plans/frs/baselines/.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("Usage: Rscript run_r_scenario.R <scenario_name>")
}
scenario_name <- args[1]

cat("Loading R model...\n")

# Source the full model (must run from R_model/R_model_frs/)
library(readxl)
library(tidyverse)
library(zoo)
library(data.table)
library(openxlsx)
library(janitor)
library(rio)
library(parallel)

source("utility_functions.R")
source("Florida FRS model input.R")
source("Florida FRS benefit model.R")

# Load pre-built workforce data (skip the slow get_wf_data step)
regular_wf_data <- readRDS("regular_wf_data.rds")
special_wf_data <- readRDS("special_wf_data.rds")
admin_wf_data <- readRDS("admin_wf_data.rds")
eco_wf_data <- readRDS("eco_wf_data.rds")
eso_wf_data <- readRDS("eso_wf_data.rds")
judges_wf_data <- readRDS("judges_wf_data.rds")
senior_management_wf_data <- readRDS("senior_management_wf_data.rds")

source("Florida FRS liability model.R")
source("Florida FRS funding model.R")

# Define scenario overrides
if (scenario_name == "baseline") {
  cat("Running baseline scenario: no overrides\n")
  funding <- get_funding_data()
} else if (scenario_name == "high_discount") {
  cat("Running high_discount scenario: dr=0.075, model_return=0.075\n")
  funding <- get_funding_data(
    dr_current = 0.075,
    dr_new = 0.075,
    model_return = 0.075
  )
} else if (scenario_name == "low_return") {
  cat("Running low_return scenario: model_return=0.05\n")
  funding <- get_funding_data(
    return_scen = "model",
    model_return = 0.05
  )
} else if (scenario_name == "asset_shock") {
  cat("Running asset_shock scenario: returns current plan investment return, 3%, -24%, 12%, 12%, 12%, then current plan investment return\n")
  first_proj_year <- start_year_ + 1
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
  inflation_ <- inflation_ + 0.03
  funding <- get_funding_data()
} else if (scenario_name == "high_inflation_linked") {
  cat("Running high_inflation_linked scenario: inflation, payroll growth, discount rates, model return, and amortization growth = baseline + 0.03\n")
  inflation_ <- inflation_ + 0.03
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
    cola_tier_1_active = 0.0,
    cola_tier_2_active = 0.0,
    cola_tier_3_active = 0.0,
    cola_current_retire = 0.0,
    cola_current_retire_one = 0.0,
    one_time_cola = FALSE
  )
} else {
  stop(paste("Unknown scenario:", scenario_name))
}

# Build truth table from funding results
f <- funding$frs

net_cf <- f$net_cf_legacy + f$net_cf_new
mva <- f$total_mva
invest_income <- c(
  mva[2:length(mva)] - mva[1:(length(mva) - 1)] - net_cf[1:(length(net_cf) - 1)],
  0
)
ee <- f$ee_nc_cont_legacy + f$ee_nc_cont_new
er_db <- f$total_er_db_cont
benefits <- f$total_ben_payment
refunds <- f$total_refund
admin <- f$admin_exp_legacy + f$admin_exp_new

baseline_ref_path <- "../../plans/frs/baselines/r_truth_table.csv"
n_active <- rep(NA, length(mva))
if (file.exists(baseline_ref_path)) {
  baseline_ref <- read.csv(baseline_ref_path)
  if ("n_active_boy" %in% names(baseline_ref) && nrow(baseline_ref) == length(mva)) {
    n_active <- baseline_ref$n_active_boy
  }
}

truth <- data.frame(
  plan = "frs",
  year = as.integer(f$year),
  mva_boy = mva,
  er_db_cont = er_db,
  ee_cont = ee,
  invest_income = invest_income,
  benefits = benefits,
  refunds = refunds,
  admin_exp = admin,
  mva_eoy = mva + net_cf + invest_income,
  aal_boy = f$total_aal,
  ava_boy = f$total_ava,
  fr_mva_boy = f$fr_mva,
  fr_ava_boy = f$fr_ava,
  n_active_boy = n_active,
  payroll = f$total_payroll,
  er_cont_total = f$total_er_cont
)

# Write output
out_dir <- file.path("../../plans/frs/baselines")
out_file <- if (scenario_name == "baseline") {
  "r_truth_table.csv"
} else {
  paste0("r_truth_table_", scenario_name, ".csv")
}
out_path <- file.path(out_dir, out_file)
write.csv(truth, out_path, row.names = FALSE)
cat("Wrote", out_path, "\n")
