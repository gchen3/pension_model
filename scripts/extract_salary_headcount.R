# Extract salary_headcount_table from R for validation
r_model_dir <- file.path("R_model", "R_model_original")
setwd(r_model_dir)

library("readxl")
library(tidyverse)
library(zoo)
library(data.table)
library(openxlsx)
library(janitor)
library(rio)
library(jsonlite)

source("utility_functions.R")
source("Florida FRS model input.R")
source("Florida FRS benefit model.R")

out_dir <- "../../baseline_outputs"

classes <- c("regular", "special", "admin", "eco", "eso", "judges", "senior_management")

for (class_name in classes) {
  class_key <- str_replace(class_name, " ", "_")
  tbl <- get(paste0(class_key, "_salary_headcount_table"))
  write_csv(tbl, sprintf("%s/%s_salary_headcount.csv", out_dir, class_key))
  cat(sprintf("%s: %d rows\n", class_key, nrow(tbl)))
}

cat("Done.\n")
