# Re-extract Senior Management headcount from Excel
r_model_dir <- file.path("R_model", "R_model_original")
setwd(r_model_dir)
library("readxl")
library(tidyverse)
library(rio)

source("Florida FRS model input.R")

# Extract the actual headcount table
cat("SM headcount table:\n")
print(senior_management_headcount_table_)
write.csv(senior_management_headcount_table_, "../../baseline_outputs/senior_management_headcount.csv", row.names = FALSE)

cat("\nSM salary table:\n")
print(senior_management_salary_table_)
write.csv(senior_management_salary_table_, "../../baseline_outputs/senior_management_salary.csv", row.names = FALSE)
cat("Done.\n")
