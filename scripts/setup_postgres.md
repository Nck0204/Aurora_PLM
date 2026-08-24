# Preparazione di PostgreSQL per Aurora

Istruzioni passo passo per Windows. Al termine esistono:

- un server PostgreSQL in ascolto sulla porta `5432`;
- un database chiamato `aurora`;
- un utente applicativo chiamato `aurora_app`, proprietario di quel database.

> **Situazione su questo computer (verificata il 24/08/2026)**
> PostgreSQL **18.6** risulta gia' installato e il servizio `postgresql-x64-18`
> e' in esecuzione. La **parte A** si puo' quindi saltare: si parte dalla
> **parte B**, che e' l'unica ancora da fare.
> La cartella dei programmi e' `C:\Program Files\PostgreSQL\18\bin`.

---

## Parte A — Installazione (solo su un server nuovo)

Da eseguire con un utente Windows che abbia i diritti di amministratore.

### A.1 Scaricare l'installatore

Aprire <https://www.enterprisedb.com/downloads/postgres-postgresql-downloads>
e scaricare l'installatore per **Windows x86-64** della versione **16** o
successiva. Il file si chiama qualcosa come
`postgresql-16.x-1-windows-x64.exe`.

### A.2 Eseguire l'installazione

Fare clic destro sul file scaricato e scegliere **Esegui come amministratore**.
Poi, schermata per schermata:

1. **Installation Directory** — lasciare il valore proposto
   (`C:\Program Files\PostgreSQL\16`).

2. **Select Components** — tenere selezionati:
   - `PostgreSQL Server` (obbligatorio)
   - `Command Line Tools` (obbligatorio: e' `psql`)
   - `pgAdmin 4` (facoltativo, interfaccia grafica; comodo)
   - `Stack Builder` (**togliere la spunta**, non serve)

3. **Data Directory** — lasciare il valore proposto. Su un server di
   produzione conviene invece indicare un disco dedicato, ad esempio
   `D:\PostgreSQL\data`, perche' e' la cartella che va nei backup.

4. **Password** — e' la password dell'utente amministratore `postgres`.
   Sceglierne una robusta e **annotarla subito** in un posto sicuro: senza
   quella password non si entra piu' nel database.

5. **Port** — lasciare `5432`.

6. **Advanced Options / Locale** — scegliere `Italian, Italy` oppure lasciare
   `[Default locale]`. Non ha effetto sul funzionamento di Aurora, solo
   sull'ordinamento alfabetico e sulla lingua dei messaggi del server.

7. Confermare e attendere la fine dell'installazione.

### A.3 Aggiungere psql al PATH (consigliato)

Serve per poter scrivere `psql` da qualunque cartella invece del percorso
completo.

1. Premere `Win`, scrivere `variabili d'ambiente` e aprire
   **Modifica le variabili di ambiente relative al sistema**.
2. Pulsante **Variabili d'ambiente...**
3. In **Variabili di sistema** selezionare `Path` e premere **Modifica...**
4. **Nuovo** e incollare: `C:\Program Files\PostgreSQL\16\bin`
   (su questo computer: `C:\Program Files\PostgreSQL\18\bin`)
5. Confermare con **OK** tutte le finestre.
6. **Chiudere e riaprire** PowerShell: le finestre gia' aperte non vedono la
   modifica.

Verifica:

```powershell
psql --version
```

Deve rispondere qualcosa come `psql (PostgreSQL) 16.4`.

### A.4 Controllare che il servizio sia avviato

```powershell
Get-Service -Name "postgresql*"
```

La colonna `Status` deve dire `Running`. Se dice `Stopped`:

```powershell
Start-Service -Name "postgresql-x64-16"
```

---

## Parte B — Creazione del database e dell'utente applicativo

**Questa e' la parte da eseguire su questo computer.**

Aurora non si collega mai come `postgres`. Usa un utente dedicato con i
permessi sul solo database `aurora`: se un giorno le credenziali di Aurora
finissero nelle mani sbagliate, il danno resterebbe circoscritto.

### B.1 Entrare in psql come amministratore

Aprire PowerShell e lanciare:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost
```

(se il PATH e' stato sistemato al punto A.3, basta `psql -U postgres -h localhost`)

Viene chiesta la password dell'utente `postgres`, quella scelta durante
l'installazione. **Mentre si scrive la password non compare nulla a schermo,
nemmeno gli asterischi: e' normale.** Premere Invio.

Quando compare il prompt `postgres=#` si e' dentro.

### B.2 Creare l'utente e il database

Incollare le tre istruzioni qui sotto, una alla volta, **compreso il punto e
virgola finale**. Sostituire `aurora_dev` con la password scelta.

```sql
CREATE ROLE aurora_app WITH LOGIN PASSWORD 'aurora_dev';
```

```sql
CREATE DATABASE aurora OWNER aurora_app;
```

```sql
GRANT ALL PRIVILEGES ON DATABASE aurora TO aurora_app;
```

Poi ci si sposta dentro il database appena creato e si concedono i permessi
sullo schema `public` (da PostgreSQL 15 non sono piu' automatici):

```sql
\c aurora
```

```sql
GRANT ALL ON SCHEMA public TO aurora_app;
```

Per uscire:

```sql
\q
```

> **Sulla password.** In sviluppo va bene `aurora_dev`. In produzione serve una
> password lunga e casuale. Se contiene i caratteri `@ : / # ?` questi vanno
> codificati in percentuale dentro `DATABASE_URL` nel file `.env`:
> `@` diventa `%40`, `#` diventa `%23`, `/` diventa `%2F`.
> Per cambiare la password in seguito:
> `ALTER ROLE aurora_app WITH PASSWORD 'nuova_password';`

### B.3 Allineare il file .env

Aprire il file `.env` nella radice del progetto e controllare che la riga
`DATABASE_URL` contenga esattamente l'utente, la password e il nome del
database appena creati:

```
DATABASE_URL=postgresql+psycopg://aurora_app:aurora_dev@localhost:5432/aurora
```

---

## Parte C — Verifica

### C.1 Il database risponde all'utente applicativo

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U aurora_app -h localhost -d aurora -c "SELECT version();"
```

Viene chiesta la password di `aurora_app`. La risposta attesa e' una riga
sola con la versione del server, ad esempio:

```
                          version
------------------------------------------------------------
 PostgreSQL 18.6 on x86_64-windows, compiled by msvc-19...
(1 riga)
```

Se invece compare `autenticazione con password fallita`, la password digitata
non corrisponde a quella impostata al punto B.2.

### C.2 Aurora si collega davvero

Dalla radice del progetto:

```powershell
.venv\Scripts\activate
uvicorn app.main:app --reload
```

Aprire nel browser <http://localhost:8000/salute>. La risposta attesa e':

```json
{
  "stato": "ok",
  "applicazione": "Aurora",
  "versione": "0.1.0",
  "ora": "...",
  "database": { "connesso": true, "errore": null }
}
```

Se `"stato"` vale `"degradato"`, il campo `"errore"` dice cosa non va.

### C.3 I test passano tutti

```powershell
pytest
```

Con il database preparato devono risultare **3 passed**, nessuno saltato.
Finche' il database non c'e', il test `test_health_check_reports_database_connected`
viene saltato: e' previsto.

---

## Appendice — Problemi frequenti

| Sintomo | Causa probabile | Rimedio |
|---|---|---|
| `psql non e' riconosciuto come comando` | PATH non aggiornato, oppure PowerShell aperto prima della modifica | Rifare il punto A.3 e riaprire PowerShell |
| `autenticazione con password fallita per l'utente "aurora_app"` | password diversa fra `.env` e database, oppure il ruolo non esiste | Rifare il punto B.2, o `ALTER ROLE aurora_app WITH PASSWORD '...';` |
| `connection refused` sulla porta 5432 | servizio fermo | `Start-Service -Name "postgresql-x64-18"` |
| `il database "aurora" non esiste` | saltato il punto B.2 | Rifare il punto B.2 |
| `permission denied for schema public` | mancato `GRANT ALL ON SCHEMA public` | Rifare l'ultima istruzione del punto B.2 |

## Appendice — Accesso da altri computer della rete

Serve solo quando Aurora verra' spostata sul server aziendale e dovra' essere
raggiungibile dalle altre postazioni. **In sviluppo non va fatto.**

1. In `C:\Program Files\PostgreSQL\18\data\postgresql.conf`:
   `listen_addresses = '*'`
2. In `C:\Program Files\PostgreSQL\18\data\pg_hba.conf`, aggiungere una riga
   per la sola sottorete aziendale, ad esempio:
   `host    aurora    aurora_app    192.168.1.0/24    scram-sha-256`
3. Aprire la porta 5432 nel firewall di Windows **solo** verso quella sottorete.
4. Riavviare il servizio: `Restart-Service -Name "postgresql-x64-18"`
