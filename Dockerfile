FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOMIE_DATA=/data HOMIE_PORT=8090

# Eigener Benutzer ohne Rechte; der Datenordner gehört ihm (ein neues Volume übernimmt das).
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin homie \
 && mkdir /data && chown homie:homie /data && chmod 700 /data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY homie/ homie/
COPY config/ config/

USER homie
VOLUME /data
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/login' % os.environ.get('HOMIE_PORT','8090'), timeout=4)"]
CMD ["python", "-m", "homie"]
