#!/bin/bash 
set -e

# exec bash # New shell
conda init bash

# Conda environment
conda create --name batch-prompt-processor-function python==3.10 --yes
conda activate batch-prompt-processor-function
conda install notebook ipykernel --yes
ipython kernel install --name batch-prompt-processor-function --display-name "Python 3.10 (batch-prompt-processor-function)" --user

pip install -r ../requirements.txt