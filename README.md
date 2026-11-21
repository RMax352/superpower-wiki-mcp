# Superpower Wiki MCP (`superpower_wiki_mcp`)

Servidor MCP (Model Context Protocol) especializado na **Superpower Wiki** (`https://powerlisting.fandom.com/api.php`), projetado para criação de personagens, balanceamento de sistemas de poder e *worldbuilding*.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/RMax352/superpower-wiki-mcp)

## Deploy Gratuito para o Gemini App (Sem Cartão)

### Opção 1 — FastMCP Cloud (Mais rápido, sem cold-start longo)
1. Acesse [fastmcp.cloud](https://fastmcp.cloud) e entre com sua conta GitHub.
2. Clique em **New Project**, selecione o repositório `RMax352/superpower-wiki-mcp` (o `fastmcp.json` já aponta para `superpower_wiki_mcp/server.py:mcp`).
3. Copie a URL gerada (`https://<seu-projeto>.fastmcp.app/mcp`) e cole nas configurações de apps conectados do **Gemini App**.

### Opção 2 — Render (1 clique via Blueprint `render.yaml`)
1. Clique no botão **Deploy to Render** acima (ou abra `https://render.com/deploy?repo=https://github.com/RMax352/superpower-wiki-mcp`).
2. Confirme o plano **Free** e aguarde o build do `Dockerfile`.
3. A URL do seu servidor será `https://superpower-wiki-mcp.onrender.com/mcp` (com health check em `/health`).

---

## Ferramentas Disponíveis (8 Tools)

- `superpower_search`: busca full-text com paginação e filtro de namespace (ignora `Fanon:` por padrão).
- `superpower_get_power`: ficha estruturada de um poder (resolve redirects como `Pyrokinesis` -> `Fire Manipulation` e omite `Known Users`/`Gallery` por padrão).
- `superpower_get_section`: leitura sob demanda de uma seção específica (`Known Users`, `Levels`, `Trivia`, etc.).
- `superpower_explore_tree`: extrai a árvore navegável de links internos em `Applications`, `Techniques`, `Variations`, `Combinations` e `Associations`.
- `superpower_get_limitations`: busca limitações e fraquezas de 1 a 5 poderes em paralelo.
- `superpower_browse_category`: navega categorias e subcategorias da wiki com cursor de paginação.
- `superpower_random_powers`: sorteia de 1 a 10 poderes canônicos (global ou por categoria) com resumo de `Capabilities`.
- `superpower_compare_powers`: compara 2 a 4 poderes em paralelo (capacidades, limitações, categorias e associações em comum).

## Modo Local (Antigravity CLI / Termux — `stdio`)

```bash
PYTHONPATH=~/.gemini/mcp/superpower-wiki-mcp SUPERPOWER_MCP_FORCE_IPV4=1 \
  python -u -m superpower_wiki_mcp.server
```

## Modo HTTP Local (`Streamable HTTP`)

```bash
PYTHONPATH=~/.gemini/mcp/superpower-wiki-mcp SUPERPOWER_MCP_FORCE_IPV4=1 \
  python -u -m superpower_wiki_mcp.server --transport http --host 127.0.0.1 --port 8765 --path /mcp
```
