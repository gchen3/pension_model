#################################################################
##  Extract intermediate liability data from R model            ##
##  Produces: benefit_table subset, ann_factor subset           ##
##  For term/retire/refund liability validation                 ##
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
source("Florida FRS workforce model.R")
source("Florida FRS liability model.R")

# Load pre-computed workforce data from RDS
regular_wf_data <- readRDS("regular_wf_data.rds")
special_wf_data <- readRDS("special_wf_data.rds")
admin_wf_data <- readRDS("admin_wf_data.rds")
eco_wf_data <- readRDS("eco_wf_data.rds")
eso_wf_data <- readRDS("eso_wf_data.rds")
judges_wf_data <- readRDS("judges_wf_data.rds")
senior_management_wf_data <- readRDS("senior_management_wf_data.rds")

cat("Model loaded. Extracting liability intermediate data...\n")

classes <- c("regular", "special", "admin", "eco", "eso", "judges", "senior_management")
out_dir <- "../../baseline_outputs"

for (class_name in classes) {
  cat(sprintf("\n========== %s ==========\n", toupper(class_name)))

  tryCatch({
    # Run benefit model
    benefit_data <- get_benefit_data(class_name = class_name)

    # Get workforce data
    class_key <- str_replace(class_name, " ", "_")
    wf_data <- get(paste0(class_key, "_wf_data"))

    # ---- Extract benefit_table subset for TERM joins ----
    # R liability code joins wf_term with benefit_table on:
    #   (entry_age, age=dist_age, year=dist_year, term_year, entry_year)
    # to get cum_mort_dr
    # We only need rows matching the workforce term data

    wf_term_keys <- wf_data$wf_term_df %>%
      filter(year <= start_year_ + model_period_, n_term > 0) %>%
      mutate(entry_year = year - (age - entry_age)) %>%
      select(entry_age, age, year, term_year, entry_year) %>%
      distinct()

    cat(sprintf("  wf_term keys: %d unique rows\n", nrow(wf_term_keys)))

    # Extract benefit_table rows matching term keys
    bt_for_term <- benefit_data$benefit_table %>%
      select(entry_age, entry_year, dist_age, dist_year, term_year, yos, cum_mort_dr) %>%
      inner_join(wf_term_keys, by = c("entry_age", "dist_age" = "age", "dist_year" = "year",
                                       "term_year", "entry_year"))

    cat(sprintf("  benefit_table rows for term: %d\n", nrow(bt_for_term)))
    write_csv(bt_for_term, sprintf("%s/%s_bt_term.csv", out_dir, class_key))

    # Also extract pvfb_db_at_term_age from benefit_val_table for term joins
    # R joins on (entry_age, term_year, entry_year)
    bvt_for_term <- benefit_data$benefit_val_table %>%
      select(entry_year, entry_age, yos, term_age, pvfb_db_wealth_at_term_age,
             pvfb_db_at_term_age = pvfb_db_wealth_at_term_age) %>%
      mutate(term_year = entry_year + yos)

    # Actually, looking more carefully at the R code:
    # left_join(benefit_data$benefit_val_table, by = c("entry_age", "term_year", "entry_year"))
    # So benefit_val_table must have term_year. Let's check and extract properly.
    bvt_cols <- names(benefit_data$benefit_val_table)
    cat(sprintf("  benefit_val_table columns: %s\n", paste(bvt_cols, collapse=", ")))

    # Extract the columns used in the term join
    bvt_for_term2 <- benefit_data$benefit_val_table %>%
      mutate(term_year = entry_year + yos) %>%
      select(entry_age, entry_year, term_year, yos, term_age, pvfb_db_at_term_age) %>%
      filter(!is.na(pvfb_db_at_term_age))

    # Only keep rows that match wf_term keys
    bvt_term_matched <- bvt_for_term2 %>%
      semi_join(wf_term_keys, by = c("entry_age", "term_year", "entry_year"))

    cat(sprintf("  benefit_val_table rows for term: %d\n", nrow(bvt_term_matched)))
    write_csv(bvt_term_matched, sprintf("%s/%s_bvt_term.csv", out_dir, class_key))

    # ---- Extract benefit_table subset for REFUND joins ----
    # R joins on (entry_age, age=dist_age, year=dist_year, term_year, entry_year)
    # Gets db_ee_balance
    wf_refund_keys <- wf_data$wf_refund_df %>%
      filter(year <= start_year_ + model_period_, n_refund > 0) %>%
      mutate(entry_year = year - (age - entry_age)) %>%
      select(entry_age, age, year, term_year, entry_year) %>%
      distinct()

    cat(sprintf("  wf_refund keys: %d unique rows\n", nrow(wf_refund_keys)))

    bt_for_refund <- benefit_data$benefit_table %>%
      select(entry_age, entry_year, dist_age, dist_year, term_year, yos, db_ee_balance) %>%
      inner_join(wf_refund_keys, by = c("entry_age", "dist_age" = "age", "dist_year" = "year",
                                         "term_year", "entry_year"))

    cat(sprintf("  benefit_table rows for refund: %d\n", nrow(bt_for_refund)))
    write_csv(bt_for_refund, sprintf("%s/%s_bt_refund.csv", out_dir, class_key))

    # ---- Extract benefit_table + ann_factor_table for RETIRE joins ----
    # First join: benefit_table by (entry_age, entry_year, term_year, retire_year=dist_year)
    #   Gets db_benefit, cola
    # Second join: ann_factor_table by (entry_age, entry_year, term_year, year=dist_year)
    #   Gets ann_factor

    wf_retire_keys <- wf_data$wf_retire_df %>%
      filter(year <= start_year_ + model_period_) %>%
      mutate(entry_year = year - (age - entry_age)) %>%
      select(entry_age, age, year, term_year, retire_year, entry_year) %>%
      distinct()

    cat(sprintf("  wf_retire keys: %d unique rows\n", nrow(wf_retire_keys)))

    # Get db_benefit and cola at retirement year
    bt_for_retire <- benefit_data$benefit_table %>%
      select(entry_age, entry_year, dist_age, dist_year, term_year, yos, db_benefit, cola) %>%
      inner_join(wf_retire_keys %>% select(entry_age, entry_year, term_year, retire_year) %>% distinct(),
                 by = c("entry_age", "entry_year", "term_year", "dist_year" = "retire_year"))

    cat(sprintf("  benefit_table rows for retire: %d\n", nrow(bt_for_retire)))
    write_csv(bt_for_retire, sprintf("%s/%s_bt_retire.csv", out_dir, class_key))

    # Get ann_factor at current year
    af_for_retire <- benefit_data$ann_factor_table %>%
      select(entry_age, entry_year, dist_age, dist_year, yos, term_year, ann_factor) %>%
      mutate(term_year = as.numeric(term_year)) %>%
      inner_join(wf_retire_keys %>% select(entry_age, entry_year, term_year, year) %>% distinct(),
                 by = c("entry_age", "entry_year", "term_year", "dist_year" = "year"))

    cat(sprintf("  ann_factor_table rows for retire: %d\n", nrow(af_for_retire)))
    write_csv(af_for_retire, sprintf("%s/%s_af_retire.csv", out_dir, class_key))

    # ---- Also save the full per-year aggregated results for comparison ----
    # Run liability model to get funding_df
    funding_df <- get_liability_data(class_name = class_name)

    # Save just the projected components
    proj_components <- funding_df %>%
      select(year, aal_term_db_legacy_est, aal_term_db_new_est,
             refund_db_legacy_est, refund_db_new_est,
             retire_ben_db_legacy_est, retire_ben_db_new_est,
             aal_retire_db_legacy_est, aal_retire_db_new_est,
             aal_legacy_est, aal_new_est, total_aal_est)

    write_csv(proj_components, sprintf("%s/%s_proj_components.csv", out_dir, class_key))
    cat(sprintf("  Saved projected liability components: %d years\n", nrow(proj_components)))

  }, error = function(e) {
    cat(sprintf("  ERROR: %s\n", e$message))
    cat(sprintf("  %s\n", paste(capture.output(traceback()), collapse="\n  ")))
  })
}

cat("\nLiability data extraction complete.\n")
