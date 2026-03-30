#################################################################
##  Extract intermediate benefit data from R model              ##
#################################################################

# Set working directory to R model
r_model_dir <- file.path("R_model", "R_model_original")
setwd(r_model_dir)
cat(sprintf("Working directory: %s\n", getwd()))

# Load libraries
library("readxl")
library(tidyverse)
library(zoo)
tryCatch(library(profvis), error = function(e) cat("profvis not available\n"))
library(data.table)
library(openxlsx)
library(janitor)
library(rio)
library(jsonlite)

# Source model code
source("utility_functions.R")
source("Florida FRS model input.R")
source("Florida FRS benefit model.R")

cat("Model loaded. Extracting benefit data...\n")

classes <- c("regular", "special", "admin", "eco", "eso", "judges", "senior_management")

for (class_name in classes) {
  cat(sprintf("\nExtracting benefit data for: %s\n", class_name))

  tryCatch({
    benefit_data <- get_benefit_data(class_name = class_name)

    # Save benefit_val_table (has PVFB, PVFS, NC per cohort)
    if (!is.null(benefit_data$benefit_val_table)) {
      bvt <- benefit_data$benefit_val_table
      cat(sprintf("  benefit_val_table: %d rows, %d cols\n", nrow(bvt), ncol(bvt)))
      cat(sprintf("  Columns: %s\n", paste(names(bvt), collapse=", ")))

      # Save a filtered version (recent entry years, key columns)
      bvt_save <- bvt %>%
        select(any_of(c(
          "entry_year", "entry_age", "yos", "term_age",
          "tier_at_term_age", "salary", "fas", "ben_mult",
          "reduce_factor", "db_benefit",
          "pvfb_db_wealth_at_term_age", "pvfb_db_wealth_at_current_age",
          "pvfs_at_current_age", "indv_norm_cost", "pvfnc_db",
          "separation_rate", "remaining_prob", "count"
        )))

      write_csv(bvt_save, sprintf("../../baseline_outputs/%s_benefit_data.csv", class_name))
      cat(sprintf("  Saved %d rows to %s_benefit_data.csv\n", nrow(bvt_save), class_name))
    }

    # Save aggregate normal cost table
    if (!is.null(benefit_data$agg_norm_cost_table)) {
      anc <- benefit_data$agg_norm_cost_table
      cat(sprintf("  Aggregate NC: %s\n", paste(anc$agg_normal_cost, collapse=", ")))
      write_csv(anc, sprintf("../../baseline_outputs/%s_agg_norm_cost.csv", class_name))
    }

    # Save individual normal cost table
    if (!is.null(benefit_data$indv_norm_cost_table)) {
      inc <- benefit_data$indv_norm_cost_table
      cat(sprintf("  indv_norm_cost_table: %d rows\n", nrow(inc)))
      inc_save <- inc
      write_csv(inc_save, sprintf("../../baseline_outputs/%s_indv_norm_cost.csv", class_name))
    }

  }, error = function(e) {
    cat(sprintf("  ERROR: %s\n", e$message))
  })
}

cat("\nBenefit data extraction complete.\n")
