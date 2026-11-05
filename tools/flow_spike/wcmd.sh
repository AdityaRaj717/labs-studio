#!/bin/bash
# Feed win_driver one command from stdin and print its answer.
O=/d/Prog/labs-studio-dev/tools/flow_spike/out/win; rm -f $O/res.json; cat > $O/cmd.tmp; mv $O/cmd.tmp $O/cmd.py
for i in $(seq 1 ${1:-300}); do [ -f $O/res.json ] && { cat $O/res.json; echo; exit 0; }; sleep 0.2; done; echo TIMEOUT
