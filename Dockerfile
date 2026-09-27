# Project overlay for the pinned Hermes runtime image.
# Build with HERMES_IMAGE pinned to a reviewed Hermes release or digest.
ARG HERMES_IMAGE=nousresearch/hermes-agent:latest@sha256:da20e13cc04fb7ade2a4725255870ebb5f367ec60e89d21707d35bc09a10a934

FROM alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce AS project
WORKDIR /src
COPY . .

FROM ${HERMES_IMAGE} AS runtime
USER root
RUN install -d -m 0755 /opt/personal-assistant
COPY --from=project --chown=hermes:hermes /src/.hermes /opt/personal-assistant/.hermes
COPY --from=project --chown=hermes:hermes /src/config /opt/personal-assistant/config
COPY --from=project --chown=hermes:hermes /src/scripts /opt/personal-assistant/scripts
COPY --from=project --chown=hermes:hermes /src/README.md /opt/personal-assistant/README.md
COPY --chmod=0755 --chown=hermes:hermes docker/container-entrypoint.sh /usr/local/bin/personal-assistant-entrypoint

# The pinned Hermes image currently links Python's _sqlite3 extension against
# SQLite 3.40.1. Build the reviewed SQLite 3.51.3 release into /usr/local so
# Hermes can safely use WAL mode and avoid the WAL-reset corruption bug.
ARG SQLITE_URL=https://www.sqlite.org/2026/sqlite-autoconf-3510300.tar.gz
ARG SQLITE_SHA256=81f5be397049b0cae1b167f2225af7646fc0f82e4a9b3c48c9ea3a533e21d77a
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gcc make libc6-dev \
    && curl -fsSL "$SQLITE_URL" -o /tmp/sqlite.tar.gz \
    && echo "$SQLITE_SHA256  /tmp/sqlite.tar.gz" | sha256sum -c - \
    && mkdir /tmp/sqlite-src \
    && tar -xzf /tmp/sqlite.tar.gz -C /tmp/sqlite-src --strip-components=1 \
    && cd /tmp/sqlite-src \
    && CFLAGS='-DSQLITE_ENABLE_FTS5' ./configure --prefix=/usr/local --disable-static --enable-threadsafe \
    && make -j2 \
    && make install \
    && ldconfig \
    && python3 -c 'import sqlite3; assert tuple(map(int, sqlite3.sqlite_version.split("."))) >= (3, 51, 3), sqlite3.sqlite_version' \
    && rm -rf /tmp/sqlite.tar.gz /tmp/sqlite-src /var/lib/apt/lists/*

# The daily report may contain multiple 25-message batches. Discord still
# enforces 2,000 characters per message, so permit the adapter to send all
# generated chunks successively instead of truncating after the base-image cap.
RUN python3 - <<'PY'
from pathlib import Path
path = Path('/opt/hermes/plugins/platforms/discord/adapter.py')
text = path.read_text(encoding='utf-8')
old = '    MAX_SPLIT_MESSAGES = 8'
new = '    MAX_SPLIT_MESSAGES = 1000'
if text.count(old) != 1:
    raise SystemExit('unexpected Hermes Discord adapter version')
text = text.replace(old, new)
needle = '        event = MessageEvent(\n            text=event_text, message_type=msg_type, source=source, raw_message=message,\n'
injection = r'''        # Personal Assistant approval replies are handled before the LLM so
        # reply-target, user, channel, and command validation cannot be bypassed
        # by prompt content or model interpretation.
        if isinstance(message.channel, discord.DMChannel) and reply_to_id:
            import re as _pda_re
            if _pda_re.fullmatch(r"(?i)(approve|deny)(?: all)? (?:new-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}|rec-[0-9a-f]{16})", event_text.strip()):
                try:
                    _proc = await asyncio.create_subprocess_exec(
                        sys.executable, "/opt/personal-assistant/scripts/handle-mail-approval.py",
                        event_text.strip(),
                        str(getattr(message.author, "id", "")),
                        str(getattr(message.channel, "id", "")),
                        str(message.id), str(reply_to_id),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    )
                    _stdout, _ = await asyncio.wait_for(_proc.communicate(), timeout=30)
                    _approval_result = _stdout.decode("utf-8", errors="replace").strip()[-1800:]
                except Exception:
                    _approval_result = '{"success": false, "error": "approval bridge failed"}'
                try:
                    _parsed_approval = json.loads(_approval_result)
                except (TypeError, ValueError):
                    _parsed_approval = {"success": False, "error": "The approval could not be processed."}
                if _parsed_approval.get("success"):
                    _results = _parsed_approval.get("results") or []
                    _applied = sum(1 for item in _results if item.get("status") == "applied")
                    _denied = sum(1 for item in _results if item.get("status") == "denied")
                    _failed = sum(1 for item in _results if item.get("status") == "failed")
                    _lines = ["✅ **Mail approval complete**"]
                    if _applied:
                        _lines.append(f"Applied: {_applied}")
                    if _denied:
                        _lines.append(f"Rejected: {_denied}")
                    if _failed:
                        _lines.append(f"Failed: {_failed}")
                    if not _failed:
                        _lines.append("No other messages were changed." if _denied == 0 else "")
                    _approval_message = "\n".join(line for line in _lines if line)
                else:
                    _error = str(_parsed_approval.get("error") or "The approval could not be processed.")
                    _approval_message = "⚠️ **Mail approval could not be completed**\n" + _error
                await self.send(str(message.channel.id), _approval_message)
                return True

'''
if text.count(needle) != 1:
    raise SystemExit('unexpected Hermes Discord message handler version')
path.write_text(text.replace(needle, injection + needle), encoding='utf-8')
PY

# The container is intentionally stateless except for /data. Docker's --user
# flag maps the host operator UID to the private bind mount at runtime.
ENV HERMES_HOME=/data \
    PERSONAL_ASSISTANT_DATA_DIR=/data \
    PDA_MAIL_SOURCES=gmail,microsoft \
    HERMES_ENABLE_PROJECT_PLUGINS=1 \
    HERMES_TIMEZONE=Asia/Kolkata \
    TMPDIR=/run/personal-assistant-tmp \
    TEMP=/run/personal-assistant-tmp \
    TMP=/run/personal-assistant-tmp \
    HOME=/run/personal-assistant-tmp/home \
    XDG_STATE_HOME=/run/personal-assistant-tmp/state \
    XDG_CACHE_HOME=/run/personal-assistant-tmp/cache
WORKDIR /opt/personal-assistant
USER 10000:10000
ENTRYPOINT ["/usr/local/bin/personal-assistant-entrypoint"]
CMD ["gateway", "run"]
