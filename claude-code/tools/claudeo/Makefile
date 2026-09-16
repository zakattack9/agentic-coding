PREFIX ?= $(HOME)/.local
SCRIPTS = bin/claudeo test/fake-claude test/claudeo-test.sh test/smoke.sh

.PHONY: test lint smoke install uninstall
test:
	sh test/claudeo-test.sh

smoke:
	sh test/smoke.sh

lint:
	@for script in $(SCRIPTS); do sh -n "$$script" || exit; done
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck $(SCRIPTS); else printf '%s\n' 'SKIP: ShellCheck is not installed (sh -n passed)'; fi

install:
	install -d "$(DESTDIR)$(PREFIX)/bin"
	install -m 755 bin/claudeo "$(DESTDIR)$(PREFIX)/bin/claudeo"

uninstall:
	rm -f "$(DESTDIR)$(PREFIX)/bin/claudeo"
