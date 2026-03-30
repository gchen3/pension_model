# Extract funding model input data from Excel
r_model_dir <- file.path("R_model", "R_model_original")
setwd(r_model_dir)
library("readxl")
library(tidyverse)
library(rio)

FileName <- "Florida FRS inputs.xlsx"
out_dir <- "../../baseline_outputs"

# Init funding data (year-1 values: total_payroll, AAL, AVA, MVA, etc.)
init_funding_data <- read_excel(FileName, sheet = "Funding Input")
write_csv(init_funding_data, file.path(out_dir, "init_funding_data.csv"))
cat(sprintf("init_funding_data: %d rows, %d cols\n", nrow(init_funding_data), ncol(init_funding_data)))
cat(sprintf("  Classes: %s\n", paste(init_funding_data$class, collapse=", ")))
cat(sprintf("  Columns: %s\n", paste(names(init_funding_data), collapse=", ")))

# Return scenarios
return_scenarios <- read_excel(FileName, sheet = "Return Scenarios")
write_csv(return_scenarios, file.path(out_dir, "return_scenarios.csv"))
cat(sprintf("return_scenarios: %d rows, %d cols\n", nrow(return_scenarios), ncol(return_scenarios)))

# Amortization layers
current_amort_layers <- read_excel(FileName, sheet = "Amort Input")
write_csv(current_amort_layers, file.path(out_dir, "current_amort_layers.csv"))
cat(sprintf("current_amort_layers: %d rows, %d cols\n", nrow(current_amort_layers), ncol(current_amort_layers)))
cat(sprintf("  Columns: %s\n", paste(names(current_amort_layers), collapse=", ")))

cat("Done.\n")
