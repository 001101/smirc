SRC=$(shell find . -type f -name "*.py" | grep -v "smirc-test.py")
.PHONY:

check: test analyze

test:
	cd tests && ./run.sh

analyze:
	pep8 $(SRC)
	pep257 $(SRC)
