#################################################################
##                   Extract Entrant Profile Tables             ##
#################################################################
# This script extracts entrant profile tables from the R model
# for use in the Python implementation.
#
# Outputs: baseline_outputs/entrant_profiles/{class}_entrant_profile.csv
#################################################################

# Store original working directory
original_wd <- getwd()

# Set working directory to R model location
r_model_dir <- file.path(original_wd, "R_model", "R_model_original")
if (!dir.exists(r_model_dir)) {
  stop(sprintf(
    "R model directory not found: %s\nCurrent WD: %s",
    r_model_dir,
    original_wd
  ))
}
setwd(r_model_dir)
cat(sprintf("R model working directory: %s\n", getwd()))

# Create output directory (relative to original working directory)
output_dir <- file.path(original_wd, "baseline_outputs", "entrant_profiles")
if (!dir.exists(output_dir)) {
  dir.create(output_dir, recursive = TRUE)
  cat(sprintf("Created output directory: %s\n", output_dir))
}

# Load required libraries
library(readxl)
library(tidyverse)
library(zoo)
library(data.table)
library(openxlsx)
library(janitor)
library(rio)

# Get utility functions
source("utility_functions.R")

# Get model inputs and assumptions
source("Florida FRS model input.R")

# Get benefit model which creates entrant profiles
source("Florida FRS benefit model.R")

#################################################################
##                   Extract Entrant Profiles                   ##
#################################################################

cat("\n=== Extracting Entrant Profile Tables ===\n")

# List of classes to extract
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
  # Get the entrant profile table
  table_name <- paste0(class_name, "_entrant_profile_table")

  if (exists(table_name)) {
    entrant_table <- get(table_name)

    # Save to CSV
    output_file <- file.path(
      output_dir,
      paste0(class_name, "_entrant_profile.csv")
    )
    write.csv(entrant_table, output_file, row.names = FALSE)

    cat(sprintf(
      "[OK] %s: %d entry ages, saved to %s\n",
      class_name,
      nrow(entrant_table),
      output_file
    ))
    cat(sprintf(
      "     Columns: %s\n",
      paste(names(entrant_table), collapse = ", ")
    ))
    cat(sprintf(
      "     Entry ages: %s\n",
      paste(entrant_table$entry_age, collapse = ", ")
    ))
    cat(sprintf(
      "     Distribution sum: %.4f\n\n",
      sum(entrant_table$entrant_dist)
    ))
  } else {
    cat(sprintf("[ERROR] %s: Table not found\n", class_name))
  }
}

cat("\n=== Extraction Complete ===\n")
cat(sprintf("Output directory: %s\n", normalizePath(output_dir)))
