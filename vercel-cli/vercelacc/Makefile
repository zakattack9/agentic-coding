SCRIPTS = vercelacc.sh install.sh test/fake-vercel test/vercelacc-test.sh

.PHONY: test lint install uninstall
test:
	sh test/vercelacc-test.sh

lint:
	@bash -n vercelacc.sh && zsh -n vercelacc.sh
	@for script in install.sh test/fake-vercel test/vercelacc-test.sh; do sh -n "$$script" || exit; done
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck -s bash vercelacc.sh && shellcheck install.sh test/fake-vercel test/vercelacc-test.sh; else printf '%s\n' 'SKIP: ShellCheck is not installed (syntax checks passed)'; fi

install:
	sh install.sh

uninstall:
	sh install.sh --uninstall
