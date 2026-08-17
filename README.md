# Escala semanal de rotas

Sistema em Python + Streamlit para transformar a planilha `ROTAS_2026.xlsx` em uma escala semanal persistente. A regra central é sempre:

`escala → rota → todas as cidades/localidades → município oficial → feriados`

## Recursos

- grade compacta de segunda a sexta, com navegação entre semanas;
- importação inicial das abas `CARREGAMENTOS ATUALIZADOS` e `CIDADES X ROTAS ATUALIZADAS`;
- parser tolerante a variações como `(R.40)` e `( R. 40 )`;
- normalização sem perda do texto original e identificação exata por município/código IBGE;
- PostgreSQL/Neon por `DATABASE_URL`, com SQLite local como fallback de desenvolvimento;
- edição da escala e cadastro de rotas/cidades;
- feriados nacionais, estaduais e municipais, com timeout, cache em memória e cache persistente;
- cadastro manual para contingência e vínculo explícito de distritos/localidades;
- exportação da semana para Excel com cabeçalhos e rotas afetadas em vermelho.

## Preparação

Requer Python 3.11 ou mais recente.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Crie `.streamlit/secrets.toml` (o arquivo já está ignorado pelo Git):

```toml
DATABASE_URL = "postgresql://usuario:senha@host/neondb?sslmode=require"
FERIADOS_API_KEY = "sua_chave"
```

`DATABASE_URL` é opcional no desenvolvimento: sem ela, a aplicação cria `data/rotas.db`. A chave municipal é necessária para consultar cidades do interior pelo provedor configurado. Sem a chave, a aplicação continua disponível com feriados gerais, valores já armazenados e cadastros manuais, e informa que a cobertura municipal é parcial.

## Importação inicial

A planilha inicial já acompanha o projeto como `ROTAS_2026.xlsx`. A aplicação procura primeiro em:

```text
data/ROTAS_2026.xlsx
ROTAS_2026.xlsx
```

Quando o banco ainda não contém rotas, a primeira abertura importa automaticamente o primeiro arquivo encontrado. Também é possível enviar outra versão pela página **Configurações**.

Para validar somente o parser e imprimir abas, contagens e exemplos de `rota → cidades`:

```powershell
python -m scripts.analyze_excel data/ROTAS_2026.xlsx
```

O parser não associa um distrito ao município por aproximação. Uma localidade que não corresponda exatamente à lista oficial do IBGE fica como **pendente**, para vínculo manual em **Configurações**.

## Execução

```powershell
streamlit run app.py
```

## Testes

```powershell
pytest -q
```

O teste principal cria a rota R.40 com Itaúna, Mateus Leme e Juatuba e confirma que um feriado apenas em Mateus Leme afeta a rota inteira no dia correspondente.

## Serviços externos e fallback

- municípios e códigos oficiais: API de Localidades do IBGE;
- feriados nacionais online: BrasilAPI;
- feriados municipais: Feriados API por código IBGE (`FERIADOS_API_KEY`);
- fallback nacional/estadual offline: pacote `holidays`;
- fallback municipal operacional: cache PostgreSQL e cadastro manual.

O provedor municipal implementa `HolidayProvider`, portanto pode ser trocado sem alterar a lógica de associação das rotas.

## Deploy no Streamlit Community Cloud

1. Publique o repositório sem `.streamlit/secrets.toml` e sem a planilha real, caso ela seja confidencial.
2. Cadastre `DATABASE_URL` e `FERIADOS_API_KEY` na área de segredos do aplicativo.
3. Defina `app.py` como arquivo principal.
4. Faça a primeira importação na página **Configurações**.
