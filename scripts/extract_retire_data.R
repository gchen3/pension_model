#################################################################
##  Extract current retiree and projected benefit data          ##
#################################################################

r_model_dir <- file.path("R_model", "R_model_original")
setwd(r_model_dir)
cat(sprintf("Working directory: %s\n", getwd()))

library("readxl")
library(tidyverse)
library(zoo)
tryCatch(library(profvis), error = function(e) cat("profvis not available\n"))
library(data.table)
library(openxlsx)
library(janitor)
library(rio)
library(jsonlite)

source("utility_functions.R")
source("Florida FRS model input.R")
source("Florida FRS benefit model.R")

cat("Model loaded.\n")

classes <- c("regular", "special", "admin", "eco", "eso", "judges", "senior_management")

# Save retiree distribution (shared across classes)
write_csv(retiree_distribution, "../../baseline_outputs/retiree_distribution.csv")
cat("Saved retiree_distribution\n")

for (class_name in classes) {
  cat(sprintf("\nExtracting data for: %s\n", class_name))

  tryCatch({
    benefit_data <- get_benefit_data(class_name = class_name)

    # Save ann_factor_retire_table (used for current retiree liability)
    if (!is.null(benefit_data$ann_factor_retire_table)) {
      art <- benefit_data$ann_factor_retire_table
      cat(sprintf("  ann_factor_retire_table: %d rows, %d cols\n", nrow(art), ncol(art)))
      cat(sprintf("  Columns: %s\n", paste(names(art)[1:min(10,ncol(art))], collapse=", ")))

      # Save key columns only to keep size manageable
      art_save <- art %>%
        select(any_of(c(
          "base_age", "age", "year", "entry_year", "entry_age",
          "mort_final", "cola", "dr",
          "cum_mort", "cum_dr", "cum_cola",
          "cum_mort_dr", "cum_mort_dr_cola",
          "ann_factor_retire"
        )))

      write_csv(art_save, sprintf("../../baseline_outputs/%s_ann_factor_retire.csv", class_name))
      cat(sprintf("  Saved %d rows\n", nrow(art_save)))
    }

    # Save the final_benefit_table (used for projected retirees/terms)
    if (!is.null(benefit_data$final_benefit_table)) {
      fbt <- benefit_data$final_benefit_table
      cat(sprintf("  final_benefit_table: %d rows, %d cols\n", nrow(fbt), ncol(fbt)))

      fbt_save <- fbt %>%
        select(any_of(c(
          "entry_year", "entry_age", "yos", "term_age",
          "tier_at_term_age", "db_benefit", "ann_factor",
          "ann_factor_term", "pvfb_db_at_term_age",
          "separation_rate", "remaining_prob", "separation_prob",
          "sep_type", "ben_decision",
          "pvfb_db_wealth_at_term_age", "db_ee_balance"
        )))

      write_csv(fbt_save, sprintf("../../baseline_outputs/%s_final_benefit.csv", class_name))
      cat(sprintf("  Saved final_benefit_table: %d rows\n", nrow(fbt_save)))
    }

  }, error = function(e) {
    cat(sprintf("  ERROR: %s\n", e$message))
  })
}

cat("\nExtraction complete.\n")
