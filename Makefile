PY=cd src && python
.PHONY: catalog pass1 verify sample grade site all serve
catalog:  ; $(PY) pass0_composio.py
pass1:    ; $(PY) pass1_research.py
verify:   ; $(PY) pass2_linkcheck.py && $(PY) pass2_oracle.py && $(PY) pass2_grounded.py && $(PY) pass2_rephrased.py && $(PY) merge.py && $(PY) pass2_oracle.py
sample:   ; $(PY) sample.py
grade:    ; $(PY) grade.py
site:     ; $(PY) merge.py && $(PY) cluster.py && $(PY) build_site.py
all: catalog pass1 verify sample
serve:    ; cd site && python -m http.server 8000
