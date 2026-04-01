## Generate fresh baseline output for Python comparison
## Run from: R_model/R_model_txtrs/

rm(list = ls())

library(readxl)
library(dplyr)
library(tidyr)
library(stringr)
library(zoo)
library(data.table)
library(openxlsx)
library(Rcpp)
library(janitor)

# Get utility functions
sourceCpp("./Rcpp_functions.cpp")
source("utility_functions.R")

# Get model inputs
source("TxTRS_model_inputs.R")

# Get benefit model
source("TxTRS_R_BModel revised.R")

# Get workforce model
source("TxTRS_workforce.R")

# Get liability model
source("TxTRS_liability_model.R")

# Load pre-computed workforce data
wf_data_baseline <- readRDS("wf_data_baseline.rds")

# Get funding model
source("TxTRS_funding_model.R")

# Run baseline
cat("Running baseline liability model...\n")
liability_data <- get_liability_data()

cat("Running baseline funding model...\n")
funding_data <- get_funding_data()

# Write outputs
write.csv(liability_data, "baseline_fresh.csv", row.names = TRUE)
write.csv(funding_data, "funding_fresh.csv", row.names = TRUE)

cat("Done! Written baseline_fresh.csv and funding_fresh.csv\n")

# Print key year-1 values for comparison
cat("\nYear 1 summary:\n")
cat("  n.active:", liability_data$n.active[1], "\n")
cat("  payroll_est:", liability_data$payroll_est[1], "\n")
cat("  nc_rate_est:", liability_data$nc_rate_est[1], "\n")
cat("  AAL_est:", liability_data$AAL_est[1], "\n")
cat("  AAL_retire_current_est:", liability_data$AAL_retire_current_est[1], "\n")
