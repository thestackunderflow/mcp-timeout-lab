# MCP timeout lab: a tiny stdio MCP server whose tools are slow, silent or hung on purpose. Standard library only.
FROM python:3.12-slim
WORKDIR /work
COPY server/ /opt/slow/server/
COPY proxy/ /opt/slow/proxy/
