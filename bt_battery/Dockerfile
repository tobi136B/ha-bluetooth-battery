ARG BUILD_FROM
FROM ${BUILD_FROM}

COPY requirements.txt /tmp/requirements.txt
# Compiler nur für den Fall, dass für die Architektur kein fertiges Wheel existiert
RUN apk add --no-cache --virtual .build-deps gcc musl-dev \
    && pip3 install --no-cache-dir -r /tmp/requirements.txt \
    && apk del .build-deps

COPY bt_battery /app/bt_battery
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /app
CMD ["/run.sh"]
