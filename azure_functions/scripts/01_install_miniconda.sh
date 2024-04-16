#!/bin/bash 
set -e

mkdir -p ~/miniconda3
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm -rf ~/miniconda3/miniconda.sh

# Initialise bash and zsh shells**
~/miniconda3/bin/conda init bash
~/miniconda3/bin/conda init zsh

# Close and open new bash Terminal to see conda e.g. conda env list
