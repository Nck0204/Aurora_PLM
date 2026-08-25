# Aurora

Gestione progetti e documentazione tecnica. Gira in rete locale, senza cloud.

## Avvio in sviluppo

1. Preparare il database seguendo `scripts/setup_postgres.md` (parte B).
2. Copiare `.env.example` in `.env` e adattare `DATABASE_URL`.
3. Creare l'ambiente virtuale: `python -m venv .venv`
4. Attivarlo: `.venv\Scripts\activate`
5. Installare le dipendenze: `pip install -r requirements.txt`
6. Applicare le migrazioni: `alembic upgrade head`
7. Creare i dati iniziali: `python scripts/seed.py`
   Stampa **una volta sola** la password dell'utente `admin`: annotarla.
8. Avviare il server: `uvicorn app.main:app --reload`
9. Controllare che sia vivo: <http://localhost:8000/salute> (attesa: `"stato": "ok"`)
10. Entrare: <http://localhost:8000/entra>, utente `admin` con la password del
    punto 7. Al primo accesso il programma obbliga a cambiarla.
11. Eseguire i test: `pytest`
12. In caso di problemi, leggere il registro: `Get-Content logs\aurora.log -Tail 50`

## Dove finiscono i file caricati

In `STORAGE_PATH` (di partenza `storage/`), depositati con il nome della loro
impronta SHA-256 e non con il loro:

```
storage/objects/3f/9a/3f9a2c11...   il file
storage/tmp/                        i file a meta' scrittura
```

Il nome originale, il tipo e tutti i metadati stanno nel database. Due
caricamenti dello stesso identico file occupano un file solo. La cartella
`tmp/` in condizioni normali e' vuota: quello che ci resta e' un caricamento
interrotto, e non lo riferisce nessuna riga del database.

**`STORAGE_PATH` va nei backup del server**: il database senza quella cartella
e' un elenco di documenti che non si aprono. In produzione conviene un disco
dedicato.

## Se nessuno riesce piu' a entrare

Le password non si recuperano: nel database c'e' solo l'impronta argon2. Se ne
assegna una nuova dalla riga di comando, sul server:

```powershell
python scripts/reimposta_password.py admin
```

Stampa una password nuova, obbliga a cambiarla al primo accesso e chiude tutte
le sessioni aperte di quell'utente. Funziona con qualunque nome utente, non
solo `admin`, e sa riattivare un utente disattivato.

## Da leggere prima di modificare il codice

- `CLAUDE.md` — convenzioni e regole permanenti del progetto
- `docs/STATO.md` — a che punto e' il lavoro
- `docs/DECISIONI.md` — le decisioni tecniche prese e il perche'
- `docs/GUIDA_STILE.md` — palette e componenti, prima di scrivere una pagina

I componenti dell'interfaccia si vedono tutti insieme, in tutte le varianti,
all'indirizzo <http://localhost:8000/stile> (serve il ruolo di creatore).
