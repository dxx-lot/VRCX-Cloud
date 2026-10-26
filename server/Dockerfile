FROM python:3.13.17-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
WORKDIR /app
COPY requirements-frozen.txt ./
RUN pip install --no-cache-dir "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70" \
    && pip install --no-cache-dir -r requirements-frozen.txt \
    && groupadd --gid 10001 vrcx \
    && useradd --uid 10001 --gid 10001 --no-create-home vrcx \
    && mkdir /state && chown 10001:10001 /state && chmod 700 /state
COPY run.py ./
COPY src/application ./src/application
COPY src/webui ./src/webui
COPY backend ./backend
COPY scripts/check-runtime.py ./check-runtime.py
COPY LICENSE LICENSING.md ./
COPY LICENSES ./LICENSES
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "run.py", "--data-dir", "/state", "--host", "0.0.0.0"]
