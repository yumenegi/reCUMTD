LATEXMK ?= latexmk
LATEXMK_FLAGS = -lualatex -auxdir=build -outdir=. -synctex=1 \
	-interaction=nonstopmode -file-line-error

.PHONY: all watch clean

all:
	$(LATEXMK) $(LATEXMK_FLAGS) main.tex

watch:
	$(LATEXMK) $(LATEXMK_FLAGS) -pvc -view=none main.tex

clean:
	$(LATEXMK) $(LATEXMK_FLAGS) -c main.tex
