PLIST = $(HOME)/Library/LaunchAgents/com.slackarchive.plist
VENV  = .venv/bin

.PHONY: restart stop start logs install

restart:
	launchctl unload $(PLIST)
	launchctl load $(PLIST)

stop:
	launchctl unload $(PLIST)

start:
	launchctl load $(PLIST)

logs:
	tail -f $(HOME)/Library/Logs/com.slackarchive.err.log

install:
	$(VENV)/pip install -r requirements.txt
