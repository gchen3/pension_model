# Extract per-class retirement and withdrawal rate tables from R
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

out_dir <- "../../baseline_outputs/decrement_tables"
classes <- c("regular", "special", "admin", "eco", "eso", "judges", "senior_management")

for (class_name in classes) {
  class_key <- str_replace(class_name, " ", "_")

  # Normal retirement rates (tier 1 and 2) - final per-class versions
  nr1 <- get(paste0(class_key, "_normal_retire_rate_tier_1_table"))
  nr2 <- get(paste0(class_key, "_normal_retire_rate_tier_2_table"))
  er1 <- get(paste0(class_key, "_early_retire_rate_tier_1_table"))
  er2 <- get(paste0(class_key, "_early_retire_rate_tier_2_table"))

  write_csv(nr1, sprintf("%s/%s_normal_retire_rate_tier1.csv", out_dir, class_key))
  write_csv(nr2, sprintf("%s/%s_normal_retire_rate_tier2.csv", out_dir, class_key))
  write_csv(er1, sprintf("%s/%s_early_retire_rate_tier1.csv", out_dir, class_key))
  write_csv(er2, sprintf("%s/%s_early_retire_rate_tier2.csv", out_dir, class_key))

  # Withdrawal rates (gender-averaged, extended)
  term_male <- get(paste0(class_key, "_term_rate_male_table_"))
  term_female <- get(paste0(class_key, "_term_rate_female_table_"))
  term_avg <- ((term_male + term_female) / 2) %>%
    add_row(yos = (max(term_male$yos) + 1):max(yos_range_)) %>%
    fill(everything(), .direction="down")

  write_csv(term_avg, sprintf("%s/%s_term_rate_avg.csv", out_dir, class_key))

  cat(sprintf("%s: nr1=%d nr2=%d er1=%d er2=%d term=%d\n",
              class_key, nrow(nr1), nrow(nr2), nrow(er1), nrow(er2), nrow(term_avg)))
}
cat("Done.\n")
