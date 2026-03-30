# Extract benefit decisions (ben_decision + dist_age) from R
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
  benefit_data <- get_benefit_data(class_name = class_name)

  bd <- benefit_data$benefit_val_table %>%
    select(entry_year, entry_age, yos, term_age, dist_age, ben_decision) %>%
    filter(!is.na(ben_decision))

  write_csv(bd, sprintf("%s/%s_ben_decisions.csv", out_dir, class_key))
  cat(sprintf("%s: %d rows\n", class_key, nrow(bd)))
}
cat("Done.\n")
