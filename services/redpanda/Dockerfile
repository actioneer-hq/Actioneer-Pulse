FROM redpandadata/redpanda:v24.3.11
COPY start.sh /start.sh
USER root
RUN chmod 755 /start.sh
ENTRYPOINT ["/start.sh"]
