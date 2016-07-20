#!/bin/bash
python -m SimpleHTTPServer 8000 &>/dev/null &
python main.py -u $1 -p $2 -l "$3"
trap "killall Python" EXIT
