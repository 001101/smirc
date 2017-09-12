BIN=bin
FLAGS=
SRC=$(shell find . -type f -name "*.py" | grep -v "build\/" | grep -v "smirc-test.py")
.PHONY:

check: test analyze lib

clean:
	rm -rf $(BIN)
	mkdir -p $(BIN)

test:
	cd tests && ./run.sh

analyze:
	pep8 $(SRC)
	pep257 $(SRC)

lib: clean
	gcc -shared -Wall -o $(BIN)/libsmirc.so -fPIC src/smirc.c src/smirc.h
