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

# The container is intentionally stateless except for /data. Docker's --user
# flag maps the host operator UID to the private bind mount at runtime.
ENV HERMES_HOME=/data \
    PERSONAL_ASSISTANT_DATA_DIR=/data \
    PDA_MAIL_SOURCES=gmail \
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
