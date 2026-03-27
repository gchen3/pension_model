#################################################################
##      R Baseline Extraction Script for Python Comparison     ##
#################################################################
# This script runs the Florida FRS R model and captures all
# intermediate outputs for comparison with the Python implementation.
#
# Outputs are saved to baseline_outputs/ directory as CSV and JSON files.
#################################################################

# Set working directory to R model location
setwd("R_model/R_model_original")

# Create output directory
if (!dir.exists("../../baseline_outputs")) {
  dir.create("../../baseline_outputs")
}

# Load required libraries
library("readxl")
library(tidyverse)
library(zoo)
library(profvis)
library(data.table)
library(openxlsx)
library(janitor)
library(rio)
library(parallel)
library(jsonlite)

# Source R model components
source("utility_functions.R")
source("Florida FRS model input.R")
source("Florida FRS benefit model.R")

#################################################################
##                   Capture Input Data                         ##
#################################################################

cat("Capturing input data...\n")

# Save input parameters
input_params <- list(
  # Actuarial and economic assumptions
  dr_old = dr_old_,
  dr_current = dr_current_,
  dr_new = dr_new_,
  payroll_growth = payroll_growth_,
  pop_growth = pop_growth_,
  inflation = inflation_,

  # Benefit assumptions
  db_ee_interest_rate = db_ee_interest_rate_,
  cola_tier_1_active_constant = cola_tier_1_active_constant_,
  cola_tier_1_active = cola_tier_1_active_,
  cola_tier_2_active = cola_tier_2_active_,
  cola_tier_3_active = cola_tier_3_active_,
  cola_current_retire = cola_current_retire_,
  cola_current_retire_one = cola_current_retire_one_,
  one_time_cola = one_time_cola_,

  # DC Employer contributions
  regular_er_dc_cont_rate = regular_er_dc_cont_rate_,
  special_er_dc_cont_rate = special_er_dc_cont_rate_,
  admin_er_dc_cont_rate = admin_er_dc_cont_rate_,
  judges_er_dc_cont_rate = judges_er_dc_cont_rate_,
  eso_er_dc_cont_rate = eso_er_dc_cont_rate_,
  eco_er_dc_cont_rate = eco_er_dc_cont_rate_,
  senior_management_er_dc_cont_rate = senior_management_er_dc_cont_rate_,

  # Funding assumptions
  funding_policy = funding_policy_,
  db_ee_cont_rate = db_ee_cont_rate_,
  amo_pay_growth = amo_pay_growth_,
  amo_period_new = amo_period_new_,
  amo_method = amo_method_,
  funding_lag = funding_lag_,

  # Investment assumptions
  return_scen = return_scen_,
  model_return = model_return_,
  return_2023 = return_2023_,

  # Plan design assumptions
  special_db_legacy_before_2018_ratio = special_db_legacy_before_2018_ratio_,
  non_special_db_legacy_before_2018_ratio = non_special_db_legacy_before_2018_ratio_,
  special_db_legacy_after_2018_ratio = special_db_legacy_after_2018_ratio_,
  non_special_db_legacy_after_2018_ratio = non_special_db_legacy_after_2018_ratio_,
  special_db_new_ratio = special_db_new_ratio_,
  non_special_db_new_ratio = non_special_db_new_ratio_,

  # Model assumptions
  model_period = model_period_,
  min_age = min_age_,
  max_age = max_age_,
  start_year = start_year_,
  new_year = new_year_,
  min_year = min_year_,
  max_year = max_year_,

  # Retirement benefit assumptions
  pension_payment = pension_payment_,
  contribution_refunds = contribution_refunds_,
  disbursement_to_ip = disbursement_to_ip_,
  admin_expense = admin_expense_,
  ben_payment_ratio = ben_payment_ratio_,

  # Class outflows
  regular_outflow = regular_outflow_,
  special_outflow = special_outflow_,
  admin_outflow = admin_outflow_,
  judges_outflow = judges_outflow_,
  eso_outflow = eso_outflow_,
  eco_outflow = eco_outflow_,
  senior_management_outflow = senior_management_outflow_
)

write_json(input_params, "../../baseline_outputs/input_params.json", pretty = TRUE)

# Save salary growth table
write_csv(salary_growth_table_, "../../baseline_outputs/salary_growth_table.csv")

# Save mortality tables
write_csv(pub_2010_headcount_mort_rates_, "../../baseline_outputs/pub_2010_headcount_mort_rates.csv")
write_csv(mortality_improvement_scale_mp_2018_rates_, "../../baseline_outputs/mortality_improvement_scale_mp_2018_rates.csv")

# Save withdrawal rate tables
for (class in c("admin", "eco", "eso", "judges", "senior_management", "special")) {
  for (gender in c("male", "female")) {
    var_name <- paste0(class, "_withdrawal_rate_", gender, "_")
    if (exists(var_name)) {
      write_csv(get(var_name), paste0("../../baseline_outputs/", class, "_withdrawal_rate_", gender, ".csv"))
    }
  }
}

# Save retirement tables
for (tier in c(1, 2)) {
  write_csv(get(paste0("normal_retirement_tier_", tier, "_")),
             paste0("../../baseline_outputs/normal_retirement_tier_", tier, ".csv"))
  write_csv(get(paste0("early_retirement_tier_", tier, "_")),
             paste0("../../baseline_outputs/early_retirement_tier_", tier, ".csv"))
}

# Save salary and headcount tables
for (class in c("regular", "special", "admin", "eco", "eso", "judges", "senior_management")) {
  salary_var <- paste0(class, "_salary_table_")
  headcount_var <- paste0(class, "_headcount_table_")

  if (exists(salary_var)) {
    write_csv(get(salary_var), paste0("../../baseline_outputs/", class, "_salary_table.csv"))
  }
  if (exists(headcount_var)) {
    write_csv(get(headcount_var), paste0("../../baseline_outputs/", class, "_headcount_table.csv"))
  }
}

cat("Input data captured.\n\n")

#################################################################
##                   Capture Workforce Data                      ##
#################################################################

cat("Capturing workforce data...\n")

# Run workforce model for each class
classes <- c("regular", "special", "admin", "eco", "eso", "judges", "senior management")

for (class_name in classes) {
  cat(sprintf("  Processing class: %s\n", class_name))

  wf_data <- get_wf_data(class_name = class_name)

  # Save workforce data
  write_csv(wf_data$wf_active_df,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_wf_active.csv"))
  write_csv(wf_data$wf_term_df,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_wf_term.csv"))
  write_csv(wf_data$wf_retire_df,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_wf_retire.csv"))

  # Save summary statistics
  wf_summary <- list(
    total_active = sum(wf_data$wf_active_df, na.rm = TRUE),
    total_terminations = sum(wf_data$wf_term_df, na.rm = TRUE),
    total_retirements = sum(wf_data$wf_retire_df, na.rm = TRUE),
    years = length(unique(wf_data$wf_active_df$year)),
    ages = length(unique(wf_data$wf_active_df$age)),
    entry_ages = length(unique(wf_data$wf_active_df$entry_age))
  )
  write_json(wf_summary,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_wf_summary.json"),
             pretty = TRUE)
}

cat("Workforce data captured.\n\n")

#################################################################
##                   Capture Benefit Data                         ##
#################################################################

cat("Capturing benefit data...\n")

for (class_name in classes) {
  cat(sprintf("  Processing class: %s\n", class_name))

  benefit_data <- get_benefit_data(class_name = class_name)

  # Save benefit valuation table
  write_csv(benefit_data$benefit_val_table,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_benefit_val.csv"))

  # Save normal cost data
  write_csv(benefit_data$nc_agg,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_nc_agg.csv"))

  # Save benefit summary
  benefit_summary <- list(
    total_nc = sum(benefit_data$nc_agg$normal_cost_aggregate_DB, na.rm = TRUE),
    total_pvfb = sum(benefit_data$nc_agg$pvfb_aggregate_DB, na.rm = TRUE),
    total_pvfs = sum(benefit_data$nc_agg$pvfs_aggregate_DB, na.rm = TRUE),
    total_al = sum(benefit_data$nc_agg$al_aggregate_DB, na.rm = TRUE)
  )
  write_json(benefit_summary,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_benefit_summary.json"),
             pretty = TRUE)
}

cat("Benefit data captured.\n\n")

#################################################################
##                   Capture Liability Data                       ##
#################################################################

cat("Capturing liability data...\n")

source("Florida FRS liability model.R")

for (class_name in classes) {
  cat(sprintf("  Processing class: %s\n", class_name))

  liability_data <- get_liability_data(class_name = class_name)

  # Save liability data
  write_csv(liability_data$liability_agg,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_liability_agg.csv"))

  # Save liability summary
  liability_summary <- list(
    total_tal = sum(liability_data$liability_agg$tal_aggregate_DB, na.rm = TRUE),
    total_nc = sum(liability_data$liability_agg$nc_aggregate_DB, na.rm = TRUE),
    total_pvfb = sum(liability_data$liability_agg$pvfb_aggregate_DB, na.rm = TRUE),
    total_pvfs = sum(liability_data$liability_agg$pvfs_aggregate_DB, na.rm = TRUE),
    total_al = sum(liability_data$liability_agg$al_aggregate_DB, na.rm = TRUE)
  )
  write_json(liability_summary,
             paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_liability_summary.json"),
             pretty = TRUE)
}

cat("Liability data captured.\n\n")

#################################################################
##                   Capture Funding Data                         ##
#################################################################

cat("Capturing funding data...\n")

source("Florida FRS funding model.R")

# Run baseline funding scenario
funding_data <- get_funding_data()

# Save funding data for each class
for (class_name in c(classes, "drop", "frs")) {
  cat(sprintf("  Processing class: %s\n", class_name))

  if (class_name %in% names(funding_data)) {
    write_csv(funding_data[[class_name]],
               paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_funding.csv"))
  }
}

# Save FRS system summary
frs_summary <- list(
  total_ual_mva = funding_data$frs$total_ual_mva,
  total_ual_ava = funding_data$frs$total_ual_ava,
  total_nc_mva = funding_data$frs$total_nc_mva,
  total_nc_ava = funding_data$frs$total_nc_ava,
  fr_mva = funding_data$frs$fr_mva,
  fr_ava = funding_data$frs$fr_ava
)
write_json(frs_summary, "../../baseline_outputs/frs_summary.json", pretty = TRUE)

cat("Funding data captured.\n\n")

#################################################################
##                   Summary Report                              ##
#################################################################

cat("========================================\n")
cat("Baseline Extraction Complete\n")
cat("========================================\n")
cat(sprintf("Output directory: %s\n", getwd()))
cat(sprintf("Total files created: %d\n", length(list.files("../../baseline_outputs"))))
cat("\nAll baseline outputs saved to: baseline_outputs/\n")
cat("\nNext steps:\n")
cat("1. Review the captured data in baseline_outputs/\n")
cat("2. Use these files as test fixtures for Python implementation\n")
cat("3. Compare Python outputs against these baseline values\n")
