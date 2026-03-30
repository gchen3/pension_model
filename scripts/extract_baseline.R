#################################################################
##                   R Baseline Extraction Script for Python Comparison     ##
#################################################################
# This script runs the Florida FRS R model and captures all intermediate
# outputs for comparison with the Python implementation.
#
# Outputs are saved to baseline_outputs/ directory as CSV and JSON files.
#################################################################

# Set working directory to R model location
# Get the script directory and set relative paths
script_dir <- tryCatch(
  {
    # Try to get script path if running via Rscript
    dirname(normalizePath(sys.frames()[[1]]$ofile))
  },
  error = function(e) {
    # Fallback to current working directory
    getwd()
  }
)

# Set working directory relative to script location
r_model_dir <- file.path(dirname(script_dir), "R_model", "R_model_original")
if (!dir.exists(r_model_dir)) {
  # Try alternate path
  r_model_dir <- file.path(getwd(), "R_model", "R_model_original")
}
setwd(r_model_dir)
cat(sprintf("Working directory: %s\n", getwd()))

# Create output directory
if (!dir.exists("../../baseline_outputs")) {
  dir.create("../../baseline_outputs")
  cat("Created baseline_outputs/ directory\n")
}

# Load required libraries
library("readxl")
library(tidyverse)
library(zoo)
tryCatch(library(profvis), error = function(e) cat("profvis not available, skipping\n"))
library(data.table)
library(openxlsx)
library(janitor)
library(rio)
library(parallel)
library(jsonlite)

# Get actuarial and financial functions
source("utility_functions.R")

# Get model inputs and assumptions
source("Florida FRS model input.R")

# Get benefit data and model
source("Florida FRS benefit model.R")

# Get workforce data (run this model only when workforce data is updated, otherwise use the rds files)
source("Florida FRS workforce model.R")
get_wf_data(class_name = "regular")
get_wf_data(class_name = "special")
get_wf_data(class_name = "admin")
get_wf_data(class_name = "eco")
get_wf_data(class_name = "eso")
get_wf_data(class_name = "judges")
get_wf_data(class_name = "senior_management")

# Get liability model
regular_wf_data <- readRDS("regular_wf_data.rds")
special_wf_data <- readRDS("special_wf_data.rds")
admin_wf_data <- readRDS("admin_wf_data.rds")
eco_wf_data <- readRDS("eco_wf_data.rds")
eso_wf_data <- readRDS("eso_wf_data.rds")
judges_wf_data <- readRDS("judges_wf_data.rds")
senior_management_wf_data <- readRDS("senior_management_wf_data.rds")
source("Florida FRS liability model.R")

# Get funding model
source("Florida FRS funding model.R")

#################################################################
##                   Capture Input Data                         ##
#################################################################

cat("Capturing input data...\n")

# Save input parameters as JSON
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
  retire_refund_ratio = retire_refund_ratio_,

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

write_json(
  input_params,
  "../../baseline_outputs/input_params.json",
  pretty = TRUE
)

#################################################################
##                   Capture Salary Growth Table                 ##
#################################################################

cat("Capturing salary growth table...\n")

# Salary growth table is already in salary_growth_table_ variable
# Save it as CSV
write_csv(
  salary_growth_table_,
  "../../baseline_outputs/salary_growth_table.csv"
)

cat("Salary growth table captured.\n")

#################################################################
##                   Capture Mortality Tables                 ##
#################################################################

cat("Capturing mortality tables...\n")

# Save mortality tables for each class
if (exists("regular_mort_table")) {
  write_csv(
    regular_mort_table,
    "../../baseline_outputs/regular_mortality_rates.csv"
  )
  cat("Saved regular mortality table\n")
}
if (exists("special_mort_table")) {
  write_csv(
    special_mort_table,
    "../../baseline_outputs/special_mortality_rates.csv"
  )
  cat("Saved special mortality table\n")
}
if (exists("admin_mort_table")) {
  write_csv(
    admin_mort_table,
    "../../baseline_outputs/admin_mortality_rates.csv"
  )
  cat("Saved admin mortality table\n")
}
if (exists("eco_mort_table")) {
  write_csv(eco_mort_table, "../../baseline_outputs/eco_mortality_rates.csv")
  cat("Saved eco mortality table\n")
}
if (exists("eso_mort_table")) {
  write_csv(eso_mort_table, "../../baseline_outputs/eso_mortality_rates.csv")
  cat("Saved eso mortality table\n")
}
if (exists("judges_mort_table")) {
  write_csv(
    judges_mort_table,
    "../../baseline_outputs/judges_mortality_rates.csv"
  )
  cat("Saved judges mortality table\n")
}
if (exists("senior_management_mort_table")) {
  write_csv(
    senior_management_mort_table,
    "../../baseline_outputs/senior_management_mortality_rates.csv"
  )
  cat("Saved senior_management mortality table\n")
}

cat("Mortality tables captured.\n")

#################################################################
##                   Capture Withdrawal Rate Tables                 ##
#################################################################

cat("Capturing withdrawal rate tables...\n")

# Save withdrawal rate tables for each class
if (exists("regular_withdrawal_rate_table")) {
  write_csv(
    regular_withdrawal_rate_table,
    "../../baseline_outputs/regular_withdrawal_rates.csv"
  )
  cat("Saved regular withdrawal rate table\n")
}
if (exists("special_withdrawal_rate_table")) {
  write_csv(
    special_withdrawal_rate_table,
    "../../baseline_outputs/special_withdrawal_rates.csv"
  )
  cat("Saved special withdrawal rate table\n")
}
if (exists("admin_withdrawal_rate_table")) {
  write_csv(
    admin_withdrawal_rate_table,
    "../../baseline_outputs/admin_withdrawal_rates.csv"
  )
  cat("Saved admin withdrawal rate table\n")
}
if (exists("eco_withdrawal_rate_table")) {
  write_csv(
    eco_withdrawal_rate_table,
    "../../baseline_outputs/eco_withdrawal_rates.csv"
  )
  cat("Saved eco withdrawal rate table\n")
}
if (exists("eso_withdrawal_rate_table")) {
  write_csv(
    eso_withdrawal_rate_table,
    "../../baseline_outputs/eso_withdrawal_rates.csv"
  )
  cat("Saved eso withdrawal rate table\n")
}
if (exists("judges_withdrawal_rate_table")) {
  write_csv(
    judges_withdrawal_rate_table,
    "../../baseline_outputs/judges_withdrawal_rates.csv"
  )
  cat("Saved judges withdrawal rate table\n")
}
if (exists("senior_management_withdrawal_rate_table")) {
  write_csv(
    senior_management_withdrawal_rate_table,
    "../../baseline_outputs/senior_management_withdrawal_rates.csv"
  )
  cat("Saved senior_management withdrawal rate table\n")
}

cat("Withdrawal rate tables captured.\n")

#################################################################
##                   Capture Retirement Eligibility Tables                 ##
#################################################################

cat("Capturing retirement eligibility tables...\n")

# Save retirement tables for each class
if (exists("normal_retirement_tier_1_table")) {
  write_csv(
    normal_retirement_tier_1_table,
    "../../baseline_outputs/regular_normal_retirement.csv"
  )
  cat("Saved regular_normal retirement table\n")
}
if (exists("early_retirement_tier_1_table")) {
  write_csv(
    early_retirement_tier_1_table,
    "../../baseline_outputs/regular_early_retirement.csv"
  )
  cat("Saved regular_early retirement table\n")
}
if (exists("normal_retirement_tier_2_table")) {
  write_csv(
    normal_retirement_tier_2_table,
    "../../baseline_outputs/special_normal_retirement.csv"
  )
  cat("Saved special_normal retirement table\n")
}
if (exists("early_retirement_tier_2_table")) {
  write_csv(
    early_retirement_tier_2_table,
    "../../baseline_outputs/special_early_retirement.csv"
  )
  cat("Saved special_early retirement table\n")
}
if (exists("normal_retirement_tier_3_table")) {
  write_csv(
    normal_retirement_tier_3_table,
    "../../baseline_outputs/admin_normal_retirement.csv"
  )
  cat("Saved admin_normal retirement table\n")
}
if (exists("early_retirement_tier_3_table")) {
  write_csv(
    early_retirement_tier_3_table,
    "../../baseline_outputs/admin_early_retirement.csv"
  )
  cat("Saved admin_early retirement table\n")
}

cat("Retirement eligibility tables captured.\n")

#################################################################
##                   Capture Salary and Headcount Tables                 ##
#################################################################

cat("Capturing salary and headcount tables...\n")

# Save salary and headcount tables for each class
if (exists("regular_salary_table")) {
  write_csv(regular_salary_table, "../../baseline_outputs/regular_salary.csv")
  cat("Saved regular_salary table\n")
}
if (exists("regular_headcount_table")) {
  write_csv(
    regular_headcount_table,
    "../../baseline_outputs/regular_headcount.csv"
  )
  cat("Saved regular_headcount table\n")
}
if (exists("special_salary_table")) {
  write_csv(special_salary_table, "../../baseline_outputs/special_salary.csv")
  cat("Saved special_salary table\n")
}
if (exists("special_headcount_table")) {
  write_csv(
    special_headcount_table,
    "../../baseline_outputs/special_headcount.csv"
  )
  cat("Saved special_headcount table\n")
}
if (exists("admin_salary_table")) {
  write_csv(admin_salary_table, "../../baseline_outputs/admin_salary.csv")
  cat("Saved admin_salary table\n")
}
if (exists("admin_headcount_table")) {
  write_csv(admin_headcount_table, "../../baseline_outputs/admin_headcount.csv")
  cat("Saved admin_headcount table\n")
}
if (exists("eco_salary_table")) {
  write_csv(eco_salary_table, "../../baseline_outputs/eco_salary.csv")
  cat("Saved eco_salary table\n")
}
if (exists("eco_headcount_table")) {
  write_csv(eco_headcount_table, "../../baseline_outputs/eco_headcount.csv")
  cat("Saved eco_headcount table\n")
}
if (exists("judges_salary_table")) {
  write_csv(judges_salary_table, "../../baseline_outputs/judges_salary.csv")
  cat("Saved judges_salary table\n")
}
if (exists("judges_headcount_table")) {
  write_csv(
    judges_headcount_table,
    "../../baseline_outputs/judges_headcount.csv"
  )
  cat("Saved judges_headcount table\n")
}
if (exists("senior_management_salary_table")) {
  write_csv(
    senior_management_salary_table,
    "../../baseline_outputs/senior_management_salary.csv"
  )
  cat("Saved senior_management_salary table\n")
}
if (exists("senior_management_headcount_table")) {
  write_csv(
    senior_management_headcount_table,
    "../../baseline_outputs/senior_management_headcount.csv"
  )
  cat("Saved senior_management_headcount table\n")
}

cat("Salary and headcount tables captured.\n")

#################################################################
##                   Capture Workforce Data                      ##
#################################################################

cat("Capturing workforce data...\n")

# Process each class's workforce data from RDS files
classes <- c(
  "regular",
  "special",
  "admin",
  "eco",
  "eso",
  "judges",
  "senior_management"
)

for (class_name in classes) {
  cat(sprintf("Processing class: %s\n", class_name))

  # Check if RDS file exists
  rds_file <- paste0(class_name, "_wf_data.rds")

  if (file.exists(rds_file)) {
    cat(sprintf("Loading %s workforce data from RDS...\n", class_name))
    wf_data <- readRDS(rds_file)

    # Save workforce data as CSV
    if (!is.null(wf_data$wf_active_df)) {
      write_csv(
        wf_data$wf_active_df,
        paste0(
          "../../baseline_outputs/",
          gsub(" ", "_", class_name),
          "_wf_active.csv"
        )
      )
    }
    if (!is.null(wf_data$wf_term_df)) {
      write_csv(
        wf_data$wf_term_df,
        paste0(
          "../../baseline_outputs/",
          gsub(" ", "_", class_name),
          "_wf_term.csv"
        )
      )
    }
    if (!is.null(wf_data$wf_refund_df)) {
      write_csv(
        wf_data$wf_refund_df,
        paste0(
          "../../baseline_outputs/",
          gsub(" ", "_", class_name),
          "_wf_refund.csv"
        )
      )
    }
    if (!is.null(wf_data$wf_retire_df)) {
      write_csv(
        wf_data$wf_retire_df,
        paste0(
          "../../baseline_outputs/",
          gsub(" ", "_", class_name),
          "_wf_retire.csv"
        )
      )
    }

    # Save summary statistics
    wf_summary <- list(
      total_active = if (!is.null(wf_data$wf_active_df)) {
        sum(wf_data$wf_active_df$n_active, na.rm = TRUE)
      } else {
        0
      },
      total_terminations = if (!is.null(wf_data$wf_term_df)) {
        sum(wf_data$wf_term_df$n_term, na.rm = TRUE)
      } else {
        0
      },
      total_refunds = if (!is.null(wf_data$wf_refund_df)) {
        sum(wf_data$wf_refund_df$n_refund, na.rm = TRUE)
      } else {
        0
      },
      total_retirements = if (!is.null(wf_data$wf_retire_df)) {
        sum(wf_data$wf_retire_df$n_retire, na.rm = TRUE)
      } else {
        0
      },
      years = if (!is.null(wf_data$wf_active_df)) {
        length(unique(wf_data$wf_active_df$year))
      } else {
        0
      },
      ages = if (!is.null(wf_data$wf_active_df)) {
        length(unique(wf_data$wf_active_df$age))
      } else {
        0
      },
      entry_ages = if (!is.null(wf_data$wf_active_df)) {
        length(unique(wf_data$wf_active_df$entry_age))
      } else {
        0
      }
    )

    write_json(
      wf_summary,
      paste0(
        "../../baseline_outputs/",
        gsub(" ", "_", class_name),
        "_wf_summary.json"
      ),
      pretty = TRUE
    )

    cat(sprintf("Captured %s workforce data\n", class_name))
  } else {
    cat(sprintf("RDS file not found for %s, skipping\n", class_name))
  }
}

cat("Workforce data captured.\n")

#################################################################
##                   Capture Liability Data                      ##
#################################################################

cat("Capturing liability data...\n")

# Run liability model for each class
for (class_name in classes) {
  cat(sprintf("Processing liability data for class: %s\n", class_name))

  # Get liability data
  liability_data <- get_liability_data(class_name = class_name)

  # Save liability data as CSV
  write_csv(
    liability_data,
    paste0(
      "../../baseline_outputs/",
      gsub(" ", "_", class_name),
      "_liability.csv"
    )
  )

  # Save liability summary
  liability_summary <- list(
    total_tal_legacy = if ("tal_legacy_est" %in% names(liability_data)) {
      sum(liability_data$tal_legacy_est, na.rm = TRUE)
    } else {
      0
    },
    total_tal_new = if ("tal_new_est" %in% names(liability_data)) {
      sum(liability_data$tal_new_est, na.rm = TRUE)
    } else {
      0
    },
    total_nc_legacy = if ("nc_legacy_est" %in% names(liability_data)) {
      sum(liability_data$nc_legacy_est, na.rm = TRUE)
    } else {
      0
    },
    total_nc_new = if ("nc_new_est" %in% names(liability_data)) {
      sum(liability_data$nc_new_est, na.rm = TRUE)
    } else {
      0
    },
    total_pvfb_legacy = if ("pvfb_legacy_est" %in% names(liability_data)) {
      sum(liability_data$pvfb_legacy_est, na.rm = TRUE)
    } else {
      0
    },
    total_pvfb_new = if ("pvfb_new_est" %in% names(liability_data)) {
      sum(liability_data$pvfb_new_est, na.rm = TRUE)
    } else {
      0
    },
    total_al_legacy = if ("al_legacy_est" %in% names(liability_data)) {
      sum(liability_data$al_legacy_est, na.rm = TRUE)
    } else {
      0
    },
    total_al_new = if ("al_new_est" %in% names(liability_data)) {
      sum(liability_data$al_new_est, na.rm = TRUE)
    } else {
      0
    }
  )

  write_json(
    liability_summary,
    paste0(
      "../../baseline_outputs/",
      gsub(" ", "_", class_name),
      "_liability_summary.json"
    ),
    pretty = TRUE
  )

  cat(sprintf("Captured %s liability data\n", class_name))
}

cat("Liability data captured.\n")

#################################################################
##                   Capture Benefit Data (Intermediate)          ##
#################################################################

cat("Capturing intermediate benefit data...\n")

# Extract the salary_benefit_table and ann_factor_table from the benefit model
# These contain per-cohort salary, PVFB, PVFS, NC rate, and AAL data
for (class_name in classes) {
  cat(sprintf("Extracting benefit data for class: %s\n", class_name))

  # Run get_benefit_data to get intermediate tables
  tryCatch({
    benefit_data <- get_benefit_data(class_name = class_name)

    # benefit_data should be a list with components
    # Save the main benefit table (salary, PVFB, PVFS, NC, etc.)
    if (!is.null(benefit_data)) {
      # Save a summary version with key columns per entry_year/entry_age/yos
      # (full table is too large - millions of rows)
      benefit_summary <- benefit_data %>%
        filter(yos == 0 | term_age == entry_age + yos) %>%
        select(any_of(c(
          "entry_year", "entry_age", "yos", "term_age",
          "tier_at_term_age", "salary", "fas", "ben_mult",
          "reduce_factor", "db_benefit", "ann_factor_term",
          "pvfb_db_at_term_age", "pvfb_db_wealth_at_term_age",
          "pvfb_db_wealth_at_current_age", "pvfs_at_current_age",
          "indv_norm_cost", "pvfnc_db",
          "separation_rate", "remaining_prob"
        ))) %>%
        # Keep only a representative sample per entry_year/entry_age
        filter(entry_year >= 2000)  # Recent cohorts only to keep file size manageable

      write_csv(
        benefit_summary,
        paste0("../../baseline_outputs/", gsub(" ", "_", class_name), "_benefit_data.csv")
      )
      cat(sprintf("Saved %s benefit data (%d rows)\n", class_name, nrow(benefit_summary)))
    }
  }, error = function(e) {
    cat(sprintf("Error extracting benefit data for %s: %s\n", class_name, e$message))
  })
}

cat("Benefit data captured.\n")

#################################################################
##                   Capture Funding Data                        ##
#################################################################

cat("Capturing funding data...\n")

# Run funding model
funding_data <- get_funding_data()

# Save funding data for each class
for (class_name in names(funding_data)) {
  cat(sprintf("Processing funding data for: %s\n", class_name))

  # Save funding data as CSV
  write_csv(
    funding_data[[class_name]],
    paste0(
      "../../baseline_outputs/",
      gsub(" ", "_", class_name),
      "_funding.csv"
    )
  )

  cat(sprintf("Captured %s funding data\n", class_name))
}

cat("Funding data captured.\n")

#################################################################
##                   Capture Salary/Headcount Distribution Files ##
#################################################################

cat("Capturing salary/headcount distribution files from extracted inputs...\n")

# Define the mapping of class names to file names
distribution_files <- list(
  admin = "salary and headcount distribution of admin.xlsx",
  eco = "salary and headcount distribution of eco.xlsx",
  eso = "salary and headcount distribution of eso.xlsx",
  judges = "salary and headcount distribution of judges.xlsx",
  senior_management = "salary and headcount distribution of senior management.xlsx"
)

# Function to parse distribution Excel file
parse_distribution_file <- function(file_path, class_name) {
  cat(sprintf("Processing distribution file for: %s\n", class_name))

  # Read the Excel file (col_names = FALSE means no header row)
  df <- read_excel(file_path, col_names = FALSE)

  # Find the header row (contains "Age" and "Years of Service" indicators)
  header_row <- which(grepl("Age", df[[1]], ignore.case = TRUE))[1]

  if (is.na(header_row)) {
    cat(sprintf("Warning: Could not find header row for %s\n", class_name))
    return(NULL)
  }

  # Extract count data (typically rows after header)
  count_start <- header_row + 1
  count_end <- count_start + 13 # Typically 13 age groups

  # Extract salary data (typically after count data)
  salary_start <- count_end + 3 # Skip blank rows and "Avg. Annual Salary" row
  salary_end <- salary_start + 13

  # Get YOS headers from header row
  yos_headers <- as.character(df[header_row, -1])
  yos_headers <- yos_headers[!is.na(yos_headers) & yos_headers != ""]

  # Extract count data
  count_data <- df[count_start:count_end, ]
  colnames(count_data) <- c("age_group", yos_headers, "all_years")

  # Clean age groups
  count_data$age_group <- as.character(count_data$age_group)
  count_data <- count_data[!is.na(count_data$age_group), ]

  # Add data type indicator
  count_data$data_type <- "count"

  # Extract salary data
  salary_data <- df[salary_start:salary_end, ]
  if (ncol(salary_data) == ncol(count_data) - 1) {
    colnames(salary_data) <- c("age_group", yos_headers, "all_years")
    salary_data$age_group <- as.character(salary_data$age_group)
    salary_data <- salary_data[!is.na(salary_data$age_group), ]
    salary_data$data_type <- "salary"
  } else {
    salary_data <- NULL
  }

  return(list(
    count = count_data,
    salary = salary_data
  ))
}

# Process each distribution file
for (class_name in names(distribution_files)) {
  file_name <- distribution_files[[class_name]]
  file_path <- file.path("Reports/extracted inputs", file_name)

  if (file.exists(file_path)) {
    cat(sprintf("Found distribution file for %s\n", class_name))

    dist_data <- parse_distribution_file(file_path, class_name)

    if (!is.null(dist_data)) {
      # Save count distribution
      if (!is.null(dist_data$count)) {
        write_csv(
          dist_data$count,
          paste0("../../baseline_outputs/", class_name, "_dist_count.csv")
        )
        cat(sprintf("Saved %s count distribution\n", class_name))
      }

      # Save salary distribution
      if (!is.null(dist_data$salary)) {
        write_csv(
          dist_data$salary,
          paste0("../../baseline_outputs/", class_name, "_dist_salary.csv")
        )
        cat(sprintf("Saved %s salary distribution\n", class_name))
      }
    }
  } else {
    cat(sprintf(
      "Distribution file not found for %s: %s\n",
      class_name,
      file_path
    ))
  }
}

cat("Salary/headcount distribution files captured.\n")

#################################################################
##                   Summary Report                              ##
#################################################################

cat("========================================\n")
cat("Baseline Extraction Complete\n")
cat("========================================\n")
cat(sprintf("Output directory: %s\n", getwd()))
cat(sprintf(
  "Total files created: %d\n",
  length(list.files("../../baseline_outputs"))
))
cat("\nNext steps:\n")
cat("1. Review captured data in baseline_outputs/\n")
cat("2. Use these files as test fixtures for Python implementation\n")
cat("3. Compare Python outputs against these baseline values\n")
