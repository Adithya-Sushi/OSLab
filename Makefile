CC = cc
CFLAGS = -O2 -std=c11 -Wall -Wextra -Wpedantic
PROGRAMS = donor foreground reclaim_worker
BUILD = build/$(shell uname -s)
all: $(PROGRAMS:%=$(BUILD)/%)
$(BUILD)/%: src/%.c src/common.h
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) $< -o $@
test: all
	python3 -m unittest discover -s tests -v
clean:
	rm -f $(PROGRAMS:%=$(BUILD)/%)
.PHONY: all test clean
