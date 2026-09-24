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
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "troque-por-uma-senha-forte"
AUTH_SECRET = "troque-por-uma-chave-aleatoria-longa"
```

`DATABASE_URL` é opcional no desenvolvimento: sem ela, a aplicação cria `data/rotas.db`. `ADMIN_USERNAME` e `ADMIN_PASSWORD` habilitam o acesso administrativo; sem essas duas configurações, o sistema continua disponível apenas no modo visitante. `AUTH_SECRET` assina a opção **Lembrar meu acesso**; use uma chave longa e privada. Se ela não for configurada, a assinatura é derivada das credenciais administrativas. O provedor municipal padrão usa o dataset aberto `joaopbini/feriados-brasil` e não exige conta, token ou plano pago.

## Importação inicial

A planilha inicial já acompanha o projeto como `ROTAS_2026.xlsx`. A aplicação procura primeiro em:

```text
data/ROTAS_2026.xlsx
ROTAS_2026.xlsx
```

Ao publicar uma nova versão de `ROTAS_2026.xlsx`, a aplicação identifica a alteração e substitui uma única vez a base operacional anterior por essa planilha. Depois da sincronização, as alterações feitas no sistema continuam no banco e não são reimportadas a cada recarga. Também é possível enviar outra versão pela página **Configurações**; essa ação também substitui integralmente a base atual.

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
- feriados municipais: dataset aberto [feriados-brasil](https://github.com/joaopbini/feriados-brasil), por código IBGE, incluído localmente para 2026 e com cache anual;
- fallback nacional/estadual offline: pacote `holidays`;
- fallback municipal operacional: cache PostgreSQL e cadastro manual.

O dataset aberto é distribuído sob licença MIT, mas pode conter nomes genéricos ou lacunas. O cadastro manual permite corrigir exceções. O provedor implementa `HolidayProvider`, portanto pode ser trocado sem alterar a lógica de associação das rotas.

Para atualizar ou incluir outro ano no repositório:

```powershell
python -m scripts.sync_holiday_dataset 2027
```

Os avisos de licença estão em `THIRD_PARTY_NOTICES.md`.

## Deploy no Streamlit Community Cloud

1. Publique o repositório sem `.streamlit/secrets.toml` e sem a planilha real, caso ela seja confidencial.
2. Cadastre `DATABASE_URL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` e `AUTH_SECRET` na área de segredos do aplicativo.
3. Defina `app.py` como arquivo principal.
4. Faça a primeira importação na página **Configurações**.
