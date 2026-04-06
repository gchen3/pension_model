#!/usr/bin/env Rscript
# Run an R model scenario and export the truth table for Python comparison.
#
# Usage (from project root):
#   cd R_model/R_model_frs
#   Rscript ../../scripts/run_r_scenario.R high_discount
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
if (scenario_name == "high_discount") {
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

truth <- data.frame(
  plan = "frs",
  year = as.integer(f$year),
  n_active_boy = NA,
  n_retired_boy = NA,
  n_inactive_boy = NA,
  payroll_fy = f$total_payroll,
  benefits_fy = f$total_ben_payment,
  aal_boy = f$total_aal,
  er_cont_fy = f$total_er_cont,
  ee_cont_fy = f$total_ee_nc_cont,
  mva_boy = f$total_mva,
  invest_income_fy = f$exp_inv_earnings_ava_legacy + f$exp_inv_earnings_ava_new,
  ava_boy = f$total_ava,
  fr_mva_boy = f$fr_mva,
  fr_ava_boy = f$fr_ava
)

# Write output
out_dir <- file.path("../../plans/frs/baselines")
out_path <- file.path(out_dir, paste0("r_truth_table_", scenario_name, ".csv"))
write.csv(truth, out_path, row.names = FALSE)
cat("Wrote", out_path, "\n")
