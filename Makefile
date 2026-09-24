.PHONY: check

check:
	python -m unittest discover -s tests -v
