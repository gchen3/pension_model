This repo contains a first-cut at a python version of a pension simulation model. It was based initially on the Reason Foundation's R model of the Florida Retirement System, generalized for more plans, and optimized to reduce looping through classes.

To install the model, open a terminal, cd to the folder that you like to "own" the python pension_model project, then execute the following one-time commands:

```
python3 --version                                          # make sure you have python 3.11+ on your system
# install python 3.11+ if needed
git clone https://github.com/donboyd5/pension_model.git    # download the model
cd pension_model                                           # cd into the folder just created
python3 -m venv .venv                                      # create a virtual environment for the project
source .venv/bin/activate                                  # activate the environment
pip install -e .                                           # install packages needed to run the model
```

Execute one or more of the commands below to run the model and/or its tests:

```
python scripts/run_model.py                                # run the model and tests

python scripts/run_model.py --no-test —                    # model + validation only, skip unit tests

python scripts/run_model.py --                             # unit tests only
```
